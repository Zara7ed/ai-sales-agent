"""Owner control: human takeover + live-feed flags over ConversationStore.

The bot normally answers every customer message. With OwnerMode the human
owner can:

  - watch a customer live (enable_live) -> each exchange is forwarded to
    the owner chat as Persian live-feed text (see forward_payload);
  - take over a conversation (takeover) -> the bot stays silent for that
    user until released, so the owner can reply manually.

Flags live in a small ``owner_flags`` table inside the same sqlite file
used by ConversationStore, so no extra database is needed.
"""
from __future__ import annotations

from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_flags (
    user_id TEXT PRIMARY KEY,
    takeover INTEGER NOT NULL DEFAULT 0,
    live INTEGER NOT NULL DEFAULT 0
);
"""


class OwnerMode:
    """Takeover/live flags layered on top of an existing ConversationStore."""

    def __init__(self, store: Any) -> None:
        self.store = store
        with store._lock, store._conn:
            store._conn.executescript(_SCHEMA)

    # -- internals ------------------------------------------------------
    def _flags(self, user_id: str) -> tuple[bool, bool]:
        cur = self.store._conn.execute(
            "SELECT takeover, live FROM owner_flags WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False, False
        return bool(row["takeover"]), bool(row["live"])

    def _set(
        self,
        user_id: str,
        *,
        takeover: bool | None = None,
        live: bool | None = None,
    ) -> None:
        with self.store._lock, self.store._conn:
            cur_takeover, cur_live = self._flags(user_id)
            new_takeover = cur_takeover if takeover is None else takeover
            new_live = cur_live if live is None else live
            self.store._conn.execute(
                "INSERT INTO owner_flags (user_id, takeover, live)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " takeover = excluded.takeover, live = excluded.live",
                (user_id, int(new_takeover), int(new_live)),
            )

    # -- public API -----------------------------------------------------
    def enable_live(self, user_id: str) -> None:
        """Start forwarding this user's exchanges to the owner (live-feed)."""
        self._set(user_id, live=True)

    def disable_live(self, user_id: str) -> None:
        """Stop forwarding this user's exchanges to the owner."""
        self._set(user_id, live=False)

    def is_live(self, user_id: str) -> bool:
        """Check whether live-feed forwarding is on for this user."""
        return self._flags(user_id)[1]

    def takeover(self, user_id: str, active: bool = True) -> None:
        """Take over (True) or release (False) a conversation."""
        self._set(user_id, takeover=active)
        try:
            action = "takeover by owner" if active else "released back to bot"
            self.store.append_note(user_id, action)
        except Exception:
            pass

    def is_takeover(self, user_id: str) -> bool:
        """Check whether the bot must stay silent for this user."""
        return self._flags(user_id)[0]

    # -- live-feed formatting -------------------------------------------
    def forward_payload(
        self,
        user_id: str,
        channel: str,
        customer_text: str,
        agent_reply: str = "",
        stage: str = "",
    ) -> str:
        """Format one customer exchange as Persian live-feed text for the owner."""
        lines = [
            f"🔴 پخش زنده | {user_id} ({channel})",
            f"👤 مشتری: {customer_text}",
        ]
        if agent_reply:
            lines.append(f"🤖 بات: {agent_reply}")
        if stage:
            lines.append(f"📊 مرحله: {stage}")
        return "\n".join(lines)
