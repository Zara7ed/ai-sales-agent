"""Mini CRM over sqlite3 (stdlib only).

Compact schema in ``crm.db``: contacts + notes + reminders + deals.
Thread-safe, indexed, Persian user-facing strings where shown to users.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Optional

STAGES = ("lead", "qualified", "proposal", "won", "lost")
TERMINAL_STAGES = ("won", "lost")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'default',
    fields TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, channel)
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'default',
    note TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes (user_id, channel, id);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'default',
    text TEXT NOT NULL,
    remind_at REAL NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (done, remind_at);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders (user_id, channel);
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'default',
    stage TEXT NOT NULL DEFAULT 'lead',
    title TEXT NOT NULL DEFAULT '',
    value REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_user ON deals (user_id, channel, stage);
"""


def _now() -> float:
    return time.time()


class MiniCRM:
    """Tiny per-(user, channel) CRM backed by a single sqlite file."""

    def __init__(self, db_path: str = "crm.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    # -- contacts ------------------------------------------------------
    def upsert_contact(
        self, user_id: str, channel: str = "default", fields: Optional[dict] = None
    ) -> dict[str, Any]:
        """Merge ``fields`` into the contact record; return full fields dict."""
        fields = fields or {}
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT fields FROM contacts WHERE user_id = ? AND channel = ?",
                (user_id, channel),
            )
            row = cur.fetchone()
            current: dict[str, Any] = {}
            if row:
                try:
                    current = json.loads(row["fields"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    current = {}
            current.update(fields)
            now = _now()
            self._conn.execute(
                "INSERT INTO contacts (user_id, channel, fields, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (user_id, channel) DO UPDATE SET"
                " fields = excluded.fields, updated_at = excluded.updated_at",
                (user_id, channel, json.dumps(current, ensure_ascii=False), now, now),
            )
            return current

    def get_contact(
        self, user_id: str, channel: str = "default"
    ) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT fields FROM contacts WHERE user_id = ? AND channel = ?",
            (user_id, channel),
        )
        row = cur.fetchone()
        if row is None:
            return {}
        try:
            return json.loads(row["fields"] or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    # -- notes ---------------------------------------------------------
    def add_note(
        self, user_id: str, note: str, channel: str = "default"
    ) -> int:
        """Append a note; returns the note row id."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO notes (user_id, channel, note, ts) VALUES (?, ?, ?, ?)",
                (user_id, channel, note, _now()),
            )
            return int(cur.lastrowid)

    def get_notes(
        self, user_id: str, channel: str = "default", limit: int = 50
    ) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT id, note, ts FROM notes WHERE user_id = ? AND channel = ?"
            " ORDER BY id DESC LIMIT ?",
            (user_id, channel, max(0, limit)),
        )
        return [
            {"id": r["id"], "note": r["note"], "ts": r["ts"]} for r in cur.fetchall()
        ]

    # -- reminders -----------------------------------------------------
    def set_reminder(
        self,
        user_id: str,
        remind_at: float,
        text: str,
        channel: str = "default",
    ) -> int:
        """Schedule a reminder at unix-ts ``remind_at``; returns reminder id."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO reminders (user_id, channel, text, remind_at, done, created_at)"
                " VALUES (?, ?, ?, ?, 0, ?)",
                (user_id, channel, text, float(remind_at), _now()),
            )
            return int(cur.lastrowid)

    def due_reminders(
        self, now: Optional[float] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return undone reminders with remind_at <= now (oldest first)."""
        now = _now() if now is None else float(now)
        cur = self._conn.execute(
            "SELECT id, user_id, channel, text, remind_at FROM reminders"
            " WHERE done = 0 AND remind_at <= ? ORDER BY remind_at ASC LIMIT ?",
            (now, max(0, limit)),
        )
        return [dict(r) for r in cur.fetchall()]

    def done_reminder(self, reminder_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,)
            )
            return cur.rowcount > 0

    # -- deals ---------------------------------------------------------
    @staticmethod
    def _check_stage(stage: str) -> str:
        s = (stage or "").strip().lower()
        if s not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")
        return s

    def move_deal(
        self,
        user_id: str,
        stage: str,
        channel: str = "default",
        title: str = "",
        value: float = 0.0,
    ) -> dict[str, Any]:
        """Move the latest open deal to ``stage`` (creating one if needed)."""
        stage = self._check_stage(stage)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT id, stage, title, value FROM deals"
                " WHERE user_id = ? AND channel = ? AND stage NOT IN ('won', 'lost')"
                " ORDER BY id DESC LIMIT 1",
                (user_id, channel),
            )
            row = cur.fetchone()
            now = _now()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO deals (user_id, channel, stage, title, value, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, channel, stage, title, float(value), now),
                )
                deal_id = int(cur.lastrowid)
            else:
                deal_id = int(row["id"])
                self._conn.execute(
                    "UPDATE deals SET stage = ?, title = COALESCE(NULLIF(?, ''), title),"
                    " value = CASE WHEN ? != 0 THEN ? ELSE value END,"
                    " updated_at = ? WHERE id = ?",
                    (stage, title, float(value), float(value), now, deal_id),
                )
            cur = self._conn.execute(
                "SELECT id, user_id, channel, stage, title, value FROM deals WHERE id = ?",
                (deal_id,),
            )
            return dict(cur.fetchone())

    def get_deal(
        self, user_id: str, channel: str = "default"
    ) -> Optional[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT id, user_id, channel, stage, title, value FROM deals"
            " WHERE user_id = ? AND channel = ? ORDER BY id DESC LIMIT 1",
            (user_id, channel),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def pipeline(self, channel: Optional[str] = None) -> dict[str, int]:
        """Count deals per stage (optionally filtered by channel)."""
        if channel:
            cur = self._conn.execute(
                "SELECT stage, COUNT(*) c FROM deals WHERE channel = ? GROUP BY stage",
                (channel,),
            )
        else:
            cur = self._conn.execute(
                "SELECT stage, COUNT(*) c FROM deals GROUP BY stage"
            )
        counts = {s: 0 for s in STAGES}
        for r in cur.fetchall():
            if r["stage"] in counts:
                counts[r["stage"]] = int(r["c"])
        return counts

    # -- summary -------------------------------------------------------
    def contact_card(
        self, user_id: str, channel: str = "default"
    ) -> dict[str, Any]:
        """Compact summary: fields + recent notes + pending reminders + deal."""
        fields = self.get_contact(user_id, channel)
        notes = self.get_notes(user_id, channel, limit=5)
        cur = self._conn.execute(
            "SELECT COUNT(*) c FROM reminders"
            " WHERE user_id = ? AND channel = ? AND done = 0",
            (user_id, channel),
        )
        pending = int(cur.fetchone()["c"])
        deal = self.get_deal(user_id, channel)
        name = fields.get("name") or fields.get("phone") or user_id
        lines = [
            f"👤 {name}",
            f"مرحله معامله: {deal['stage'] if deal else '—'}",
            f"یادداشت‌ها: {len(notes)} | یادآورهای باز: {pending}",
        ]
        if fields.get("phone"):
            lines.append(f"📞 {fields['phone']}")
        return {
            "user_id": user_id,
            "channel": channel,
            "fields": fields,
            "recent_notes": notes,
            "pending_reminders": pending,
            "deal": deal,
            "card_fa": "\n".join(lines),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
