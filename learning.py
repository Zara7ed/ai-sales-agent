"""Conversation learning: heuristic win/loss analysis + lesson storage.

``analyze_conversation`` uses keyword heuristics (Persian + English) with an
optional LLM hook for refinement. ``save_lesson`` appends to the
``kb_data['lessons']`` JSON section (persisting to disk when a KB object or
path is given) and optionally stores a note via ConversationStore/MiniCRM.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

WON_KEYWORDS = (
    # English
    "booked", "booking confirmed", "paid", "payment done", "confirmed",
    "deal", "agree", "yes let's", "sounds good", "thank you, i'll take",
    # Persian
    "رزرو", "پرداخت کردم", "پرداخت شد", "باشه", "حتماً", "حتما",
    "عالیه", "ممنون", "قبول", "تأیید", "تایید", "میام", "می‌آیم",
    "ثبت کن", "نهایی کن",
)

LOST_KEYWORDS = (
    # English
    "too expensive", "too costly", "i'll think", "need to think",
    "later", "not now", "cancel", "refund", "not interested", "no thanks",
    "found another", "competitor",
    # Persian
    "گرون", "گران", "فکر", "بعداً", "بعدا", "فعلاً", "فعلا",
    "لغو", "کنسل", "نمی‌خوام", "نمیخوام", "نه ممنون", "انصراف",
    "پشیمون", "پشیمان", "نمی‌تونم", "نمی‌صرفه", "نمیصرفه",
)

WON_LESSONS = (
    "پاسخ سریع و پیشنهاد ساعت مشخص، نرخ تبدیل را بالا می‌برد.",
    "جمع‌بندی شفاف قیمت + قدم بعدی، تردید را کم می‌کند.",
)
LOST_LESSONS = (
    "اعتراض قیمت را با طرح پرداخت/ارزش‌گذاری مجدد پیگیری کن.",
    "برای «فکر می‌کنم» یک ساعت رزرو موقت نگه دار و فردا پیگیری کن.",
)


def _as_text(transcript: Any) -> str:
    if isinstance(transcript, str):
        return transcript
    if isinstance(transcript, (list, tuple)):
        parts: list[str] = []
        for m in transcript:
            if isinstance(m, dict):
                parts.append(str(m.get("content", m)))
            else:
                parts.append(str(m))
        return "\n".join(parts)
    return str(transcript)


def _hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [k for k in keywords if k.lower() in low]


def analyze_conversation(
    transcript: Any,
    outcome: Optional[str] = None,
    llm_hook: Optional[Callable[[str], Optional[dict]]] = None,
) -> dict[str, Any]:
    """Return {'verdict': 'won'|'lost', 'reasons': [...], 'lessons': [...]}.

    ``outcome`` (if given) forces the verdict. ``llm_hook`` receives the
    transcript text and may return a dict to override/extend the result.
    """
    text = _as_text(transcript)
    won_hits = _hits(text, WON_KEYWORDS)
    lost_hits = _hits(text, LOST_KEYWORDS)

    if outcome is not None:
        o = str(outcome).strip().lower()
        if o in ("won", "win", "success", "برد", "موفق"):
            verdict = "won"
        elif o in ("lost", "lose", "fail", "باخت", "ناموفق"):
            verdict = "lost"
        else:
            verdict = "won" if len(won_hits) >= len(lost_hits) else "lost"
    else:
        if won_hits or lost_hits:
            verdict = "won" if len(won_hits) >= len(lost_hits) else "lost"
        else:
            verdict = "lost"  # no buying signal -> treat as not converted

    reasons: list[str] = []
    for k in won_hits:
        reasons.append(f"نشانه خرید: «{k}»")
    for k in lost_hits:
        reasons.append(f"نشانه ریزش: «{k}»")
    if not reasons:
        reasons.append("سیگنال مشخصی در متن یافت نشد؛ بر اساس نبود نشانه خرید، ناموفق ثبت شد.")

    lessons = list(WON_LESSONS if verdict == "won" else LOST_LESSONS)

    result = {"verdict": verdict, "reasons": reasons, "lessons": lessons}

    if llm_hook is not None:
        try:
            refined = llm_hook(text)
        except Exception:
            refined = None
        if isinstance(refined, dict):
            if refined.get("verdict") in ("won", "lost"):
                result["verdict"] = refined["verdict"]
            for key in ("reasons", "lessons"):
                extra = refined.get(key)
                if isinstance(extra, list) and extra:
                    merged = list(result[key])
                    for item in extra:
                        s = str(item)
                        if s not in merged:
                            merged.append(s)
                    result[key] = merged
    return result


def save_lesson(
    kb_data: Any,
    lesson: Any,
    kb_path: Optional[str] = None,
    kb: Any = None,
    store: Any = None,
    user_id: Optional[str] = None,
    channel: str = "default",
) -> dict[str, Any]:
    """Append ``lesson`` to the ``lessons`` JSON section; persist + note.

    - ``kb_data``: plain dict (or BusinessKB; its ``.data`` is used).
    - ``lesson``: str or dict (str -> {'text': ...}).
    - Persists to disk when ``kb`` (BusinessKB with .path) or ``kb_path`` given.
    - Stores a note when ``store`` (ConversationStore/MiniCRM) + ``user_id`` given.
    Returns the stored entry.
    """
    target: Optional[dict] = None
    if isinstance(kb_data, dict):
        target = kb_data
    else:
        data = getattr(kb_data, "data", None)
        if isinstance(data, dict):
            target = data
            kb = kb or kb_data
    if target is None:
        raise TypeError("kb_data must be a dict or a BusinessKB-like object")

    entry = {"text": lesson} if isinstance(lesson, str) else dict(lesson)
    entry.setdefault("ts", time.strftime("%Y-%m-%d %H:%M"))

    lessons = target.get("lessons")
    if not isinstance(lessons, list):
        lessons = []
        target["lessons"] = lessons
    lessons.append(entry)

    path = kb_path or getattr(kb, "path", None)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                disk = json.load(f)
            if not isinstance(disk, dict):
                disk = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            disk = {}
        disk_lessons = disk.get("lessons")
        if not isinstance(disk_lessons, list):
            disk_lessons = []
            disk["lessons"] = disk_lessons
        if entry not in disk_lessons:
            disk_lessons.append(entry)
        # Merge other in-memory sections so we don't clobber the file.
        for k, v in target.items():
            if k != "lessons":
                disk.setdefault(k, v)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(disk, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        # Refresh KB object if it manages mtime.
        try:
            if kb is not None and hasattr(kb, "load"):
                kb.load()
        except Exception:
            pass

    if store is not None and user_id is not None:
        note = entry.get("text", str(entry))
        try:
            if hasattr(store, "append_note"):
                store.append_note(user_id, f"درس آموخته: {note}", channel)
            elif hasattr(store, "add_note"):
                store.add_note(user_id, f"درس آموخته: {note}", channel)
        except Exception:
            pass

    return entry
