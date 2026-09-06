"""Telegram owner/admin bot handlers as pure functions over engine pieces.

handle_owner_command(text, owner_id) -> str parses an owner command and
returns a Persian reply string. answer_admin_question(question, owner_id)
chats with the sales agent in 'owner-advisory' mode and returns advice.

Commands:
  /stats              user/message counts (crm.db when present, else bot DB)
  /takeover <user>    silence the bot for <user>; owner replies manually
  /release <user>     hand <user> back to the bot
  /watch <user>       forward <user>'s exchanges to the owner live-feed
  /reminders          due reminders (learning.py/crm.py when present)
  /kb get <section>   show a knowledge-base section
"""
from __future__ import annotations

import os
import sqlite3

_HELP = (
    "دستورات مالک:\n"
    "/stats — آمار کاربران و پیام‌ها\n"
    "/takeover <user> — تحویل گفتگو به شما (بات ساکت می‌شود)\n"
    "/release <user> — بازگرداندن گفتگو به بات\n"
    "/watch <user> — پخش زنده گفتگو\n"
    "/reminders — یادآوری‌های سررسیده\n"
    "/kb get <section> — نمایش بخش دانش (services, faqs, ...)"
)


def _owner_ids() -> set[str]:
    raw = os.getenv("OWNER_TELEGRAM_ID", "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def _is_owner(owner_id: object) -> bool:
    allowed = _owner_ids()
    if not allowed:
        return True  # dev-open, same convention as admin/panel.py
    return str(owner_id) in allowed


def _db_path() -> str:
    return os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "conversations.db"))


def _crm_db_path() -> str:
    return os.getenv("CRM_DB_PATH", "crm.db")


def _count(db_path: str, table: str) -> int | None:
    """Row count for table, or None if DB/table is missing."""
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _cmd_stats() -> str:
    crm_db = _crm_db_path()
    contacts = _count(crm_db, "contacts")
    deals = _count(crm_db, "deals")
    reminders = _count(crm_db, "reminders")
    if contacts is None and deals is None and reminders is None:
        users = _count(_db_path(), "users") or 0
        messages = _count(_db_path(), "messages") or 0
        return f"📊 آمار بات:\n👥 کاربران: {users}\n💬 پیام‌ها: {messages}"
    lines = ["📊 آمار CRM:"]
    if contacts is not None:
        lines.append(f"👥 مخاطبان: {contacts}")
    if deals is not None:
        lines.append(f"🤝 معامله‌ها: {deals}")
    if reminders is not None:
        lines.append(f"⏰ یادآوری‌ها: {reminders}")
    return "\n".join(lines)


def _cmd_takeover(user: str) -> str:
    if not user:
        return "کاربر را مشخص کنید: /takeover <user>"
    try:
        from memory import ConversationStore

        from owner import OwnerMode

        store = ConversationStore(db_path=_db_path())
        try:
            OwnerMode(store).takeover(user, True)
        finally:
            store.close()
    except Exception:
        return "خطا در فعال‌سازی تحویل گفتگو. دوباره تلاش کنید."
    return f"✅ گفتگوی {user} به شما تحویل داده شد. بات برای این کاربر ساکت می‌ماند."


def _cmd_release(user: str) -> str:
    if not user:
        return "کاربر را مشخص کنید: /release <user>"
    try:
        from memory import ConversationStore

        from owner import OwnerMode

        store = ConversationStore(db_path=_db_path())
        try:
            OwnerMode(store).takeover(user, False)
        finally:
            store.close()
    except Exception:
        return "خطا در بازگرداندن گفتگو. دوباره تلاش کنید."
    return f"✅ گفتگوی {user} به بات بازگردانده شد."


def _cmd_watch(user: str) -> str:
    if not user:
        return "کاربر را مشخص کنید: /watch <user>"
    try:
        from memory import ConversationStore

        from owner import OwnerMode

        store = ConversationStore(db_path=_db_path())
        try:
            OwnerMode(store).enable_live(user)
        finally:
            store.close()
    except Exception:
        return "خطا در فعال‌سازی پخش زنده. دوباره تلاش کنید."
    return f"🔴 پخش زنده {user} فعال شد. پیام‌های جدید برای شما ارسال می‌شود."


def _cmd_reminders() -> str:
    for mod_name in ("learning", "crm"):
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue
        for fn_name in ("list_due_reminders", "get_due_reminders", "due_reminders"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    items = fn()
                except Exception:
                    return "خطا در خواندن یادآوری‌ها. دوباره تلاش کنید."
                if not items:
                    return "⏰ یادآوری سررسیده‌ای نیست."
                lines = ["⏰ یادآوری‌های سررسیده:"]
                for it in items if isinstance(items, list) else []:
                    if isinstance(it, dict):
                        who = it.get("user_id") or it.get("contact_id") or ""
                        text = it.get("text") or it.get("note") or ""
                        lines.append(f"• {who}: {text}".strip())
                    else:
                        lines.append(f"• {it}")
                return "\n".join(lines)
    return "⏰ یادآوری فعالی ثبت نشده است."


def _cmd_kb_get(section: str) -> str:
    if not section:
        return "بخش را مشخص کنید: /kb get <section>"
    try:
        from config import load as load_settings

        from knowledge import BusinessKB

        kb = BusinessKB(path=load_settings().kb_path)
        data = kb.get_section(section)
    except Exception:
        return "خطا در خواندن دانش. دوباره تلاش کنید."
    if isinstance(data, dict):
        items = [f"{k}: {v}" for k, v in data.items()]
    elif isinstance(data, list):
        items = [str(x) for x in data]
    else:
        items = [str(data)]
    if not items:
        return f"بخش «{section}» خالی است."
    preview = "\n".join(f"• {x}" for x in items[:10])
    more = f"\n…و {len(items) - 10} مورد دیگر." if len(items) > 10 else ""
    return f"📚 بخش «{section}» ({len(items)} مورد):\n{preview}{more}"


def handle_owner_command(text: str, owner_id: object) -> str:
    """Parse one owner command; always returns a Persian reply string."""
    if not _is_owner(owner_id):
        return "⛔️ دسترسی ندارید."
    parts = (text or "").strip().split()
    if not parts:
        return _HELP
    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]
    if cmd in ("start", "help", "کمک"):
        return _HELP
    if cmd == "stats":
        return _cmd_stats()
    if cmd == "takeover":
        return _cmd_takeover(args[0] if args else "")
    if cmd == "release":
        return _cmd_release(args[0] if args else "")
    if cmd == "watch":
        return _cmd_watch(args[0] if args else "")
    if cmd == "reminders":
        return _cmd_reminders()
    if cmd == "kb" and len(args) >= 2 and args[0].lower() == "get":
        return _cmd_kb_get(args[1])
    return "دستور نامشخص است.\n" + _HELP


def answer_admin_question(question: str, owner_id: object) -> str:
    """Chat with the agent in 'owner-advisory' mode; returns Persian advice."""
    if not _is_owner(owner_id):
        return "⛔️ دسترسی ندارید."
    if not (question or "").strip():
        return "سؤالتان را بنویسید تا راهنمایی‌تان کنم."
    try:
        from engine import build_engine

        parts = build_engine()
        agent = parts["agent"]
        result = agent.handle(
            f"owner:{owner_id}",
            f"[owner-advisory] {question.strip()}",
            channel="owner-advisory",
        )
        return str(getattr(result, "reply", "") or "پاسخی نداشتم.")
    except Exception:
        return "خطا در مشاوره. دوباره تلاش کنید."
