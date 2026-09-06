"""SQLite-backed conversation memory (stdlib sqlite3 only)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Optional


class ConversationStore:
    """Per-user, per-channel message history + profile facts + lead stage."""

    def __init__(self, db_path: str = "conversations.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_user_channel
                    ON messages (user_id, channel, id);
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    profile TEXT NOT NULL DEFAULT '{}',
                    stage TEXT NOT NULL DEFAULT 'new',
                    notes TEXT NOT NULL DEFAULT ''
                );
                """
            )

    # -- messages ---------------------------------------------------------
    def save_message(
        self, user_id: str, role: str, content: str, channel: str = "default"
    ) -> None:
        """Append one message to the user's history on a channel."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (user_id, channel, role, content, ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, channel, role, content, time.time()),
            )
            self._ensure_user(user_id)

    def get_history(
        self, user_id: str, channel: str = "default", limit: int = 20
    ) -> list[dict[str, str]]:
        """Return the last N messages (oldest first) for user+channel."""
        cur = self._conn.execute(
            "SELECT role, content FROM messages"
            " WHERE user_id = ? AND channel = ? ORDER BY id DESC LIMIT ?",
            (user_id, channel, max(0, limit)),
        )
        rows = cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_history(self, user_id: str, channel: str = "default") -> None:
        """Delete message history for a user on a channel."""
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM messages WHERE user_id = ? AND channel = ?",
                (user_id, channel),
            )

    # -- user profile / stage / notes --------------------------------------
    def _ensure_user(self, user_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
        )

    def get_profile(self, user_id: str) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT profile FROM users WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        if row is None:
            return {}
        try:
            return json.loads(row["profile"] or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    def update_profile(self, user_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        """Merge facts into the stored profile and return the full profile."""
        with self._lock, self._conn:
            self._ensure_user(user_id)
            profile = self.get_profile(user_id)
            profile.update(facts)
            self._conn.execute(
                "UPDATE users SET profile = ? WHERE user_id = ?",
                (json.dumps(profile, ensure_ascii=False), user_id),
            )
            return profile

    def get_stage(self, user_id: str) -> str:
        cur = self._conn.execute(
            "SELECT stage FROM users WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        return row["stage"] if row else "new"

    def set_stage(self, user_id: str, stage: str) -> None:
        with self._lock, self._conn:
            self._ensure_user(user_id)
            self._conn.execute(
                "UPDATE users SET stage = ? WHERE user_id = ?", (stage, user_id)
            )

    def get_notes(self, user_id: str) -> str:
        cur = self._conn.execute(
            "SELECT notes FROM users WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        return row["notes"] if row and row["notes"] else ""

    def append_note(self, user_id: str, note: str) -> str:
        """Append a timestamped note; returns the full notes text."""
        with self._lock, self._conn:
            self._ensure_user(user_id)
            current = self.get_notes(user_id)
            entry = f"[{time.strftime('%Y-%m-%d %H:%M')}] {note}"
            updated = (current + "\n" + entry).strip() if current else entry
            self._conn.execute(
                "UPDATE users SET notes = ? WHERE user_id = ?", (updated, user_id)
            )
            return updated

    def close(self) -> None:
        with self._lock:
            self._conn.close()
