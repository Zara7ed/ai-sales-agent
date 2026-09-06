"""Token budgeting: history compression + per-day usage tracker (stdlib only)."""
from __future__ import annotations

import time
from datetime import date
from typing import Any, Optional


def estimate_tokens(text: str, chars_per_token: int = 4) -> int:
    """Rough token estimate from character count (esp. for non-English text)."""
    if not text:
        return 0
    return max(1, (len(text) + chars_per_token - 1) // chars_per_token)


def _is_system(msg: dict[str, Any]) -> bool:
    return msg.get("role") == "system"


def compress_history(
    messages: list[dict[str, Any]], budget: int = 20
) -> list[dict[str, Any]]:
    """Trim history to fit `budget` messages.

    Keeps all system messages + the first turn + the last N turns,
    dropping old middle turns first. Never reorders. Returns a new list.
    """
    msgs = list(messages or [])
    budget = max(0, int(budget))
    if budget == 0:
        return []
    if len(msgs) <= budget:
        return msgs
    system = [m for m in msgs if _is_system(m)]
    rest = [m for m in msgs if not _is_system(m)]
    room = budget - len(system)
    if room <= 0:
        return msgs[:budget]
    if len(rest) <= room:
        return system + rest
    # Keep first turn (1 msg) + last (room - 1) turns.
    first = rest[:1]
    tail = rest[-(room - 1):] if room > 1 else []
    return system + first + tail


class BudgetTracker:
    """Count chars->approx tokens with a per-day cap."""

    def __init__(
        self,
        daily_cap: int = 100_000,
        chars_per_token: int = 4,
        day: Optional[str] = None,
    ) -> None:
        self.daily_cap = int(daily_cap)
        self.chars_per_token = int(chars_per_token)
        self._day = day or date.today().isoformat()
        self._tokens = 0

    def _rollover(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day = today
            self._tokens = 0

    @property
    def tokens_used(self) -> int:
        self._rollover()
        return self._tokens

    @property
    def remaining(self) -> int:
        return max(0, self.daily_cap - self.tokens_used)

    @property
    def exceeded(self) -> bool:
        return self.tokens_used >= self.daily_cap

    def estimate(self, text: str) -> int:
        return estimate_tokens(text or "", self.chars_per_token)

    def add(self, text: str) -> bool:
        """Charge `text` against the cap. Returns False if it would exceed."""
        self._rollover()
        cost = self.estimate(text)
        if self._tokens + cost > self.daily_cap:
            return False
        self._tokens += cost
        return True

    def reset(self) -> None:
        self._day = date.today().isoformat()
        self._tokens = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "day": self._day,
            "tokens_used": self.tokens_used,
            "daily_cap": self.daily_cap,
            "remaining": self.remaining,
            "exceeded": self.exceeded,
            "ts": time.time(),
        }
