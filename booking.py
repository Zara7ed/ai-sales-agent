"""Appointment booking on top of crm.db (stdlib only).

Rules come from ``kb_data['booking']`` (a plain dict, or a BusinessKB whose
``.data`` holds it), e.g.::

    {"days": [0, 1, 2, 3, 4, 5], "start_hour": 9, "end_hour": 19,
     "duration_min": 30, "capacity": 1}

Accepted variants: day names (mon/sat/شنبه...), ``hours`` pair, ``days``
as ISO weekday numbers (Mon=0..Sun=6). Missing config -> sensible defaults.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'default',
    slot TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'reserved',
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_slot_active ON bookings (slot) WHERE status = 'reserved';
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings (user_id, channel);
"""

_DAY_NAMES = {
    "mon": 0, "monday": 0, "دوشنبه": 0,
    "tue": 1, "tuesday": 1, "سه": 1, "سه‌شنبه": 1, "سه شنبه": 1,
    "wed": 2, "wednesday": 2, "چهارشنبه": 2, "چهار": 2,
    "thu": 3, "thursday": 3, "پنجشنبه": 3, "پنج": 3,
    "fri": 4, "friday": 4, "جمعه": 4,
    "sat": 5, "saturday": 5, "شنبه": 5,
    "sun": 6, "sunday": 6, "یکشنبه": 6, "يکشنبه": 6,
}

DEFAULTS = {
    "days": [0, 1, 2, 3, 4, 5],
    "start_hour": 9,
    "end_hour": 19,
    "duration_min": 30,
}


def _kb_dict(kb_data: Any) -> dict[str, Any]:
    if kb_data is None:
        return {}
    if isinstance(kb_data, dict) and "booking" in kb_data:
        cfg = kb_data.get("booking") or {}
        return cfg if isinstance(cfg, dict) else {}
    if isinstance(kb_data, dict):
        return kb_data
    data = getattr(kb_data, "data", None)  # BusinessKB instance
    if isinstance(data, dict):
        cfg = data.get("booking") or {}
        return cfg if isinstance(cfg, dict) else {}
    return {}


def _norm_days(raw: Any) -> set[int]:
    if not raw:
        return set(DEFAULTS["days"])
    out: set[int] = set()
    items = raw if isinstance(raw, (list, tuple, set)) else [raw]
    for d in items:
        if isinstance(d, int) and 0 <= d <= 6:
            out.add(d)
        elif isinstance(d, str):
            key = d.strip().lower()
            if key in _DAY_NAMES:
                out.add(_DAY_NAMES[key])
            elif key.isdigit() and 0 <= int(key) <= 6:
                out.add(int(key))
    return out or set(DEFAULTS["days"])


class BookingManager:
    """Generate free slots from KB rules; persist reservations in crm.db."""

    def __init__(
        self,
        db_path: str = "crm.db",
        kb_data: Any = None,
        **kwargs: Any,
    ):
        if kb_data is None and "kb" in kwargs:
            kb_data = kwargs["kb"]
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            # Migrate pre-fix schema (unique index without partial WHERE).
            self._conn.execute("DROP INDEX IF EXISTS idx_bookings_slot_active")
            self._conn.executescript(_SCHEMA)
        self.reload(kb_data)

    def reload(self, kb_data: Any = None) -> dict[str, Any]:
        cfg = _kb_dict(kb_data) if kb_data is not None else getattr(self, "config", {})
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        hours = cfg.get("hours") if isinstance(cfg, dict) else None
        if isinstance(hours, (list, tuple)) and len(hours) >= 2:
            try:
                merged["start_hour"] = int(hours[0])
                merged["end_hour"] = int(hours[1])
            except (TypeError, ValueError):
                pass
        for key in ("start", "start_hour", "from"):
            if key in cfg and key != "start_hour":
                try:
                    merged["start_hour"] = int(cfg[key])
                except (TypeError, ValueError):
                    pass
        for key in ("end", "end_hour", "to"):
            if key in cfg and key != "end_hour":
                try:
                    merged["end_hour"] = int(cfg[key])
                except (TypeError, ValueError):
                    pass
        if "duration" in cfg and "duration_min" not in cfg:
            try:
                merged["duration_min"] = int(cfg["duration"])
            except (TypeError, ValueError):
                pass
        if "slot_minutes" in cfg and "duration_min" not in cfg:
            try:
                merged["duration_min"] = int(cfg["slot_minutes"])
            except (TypeError, ValueError):
                pass
        self.config = merged
        self.days = _norm_days(merged.get("days"))
        return merged

    # -- slot generation ------------------------------------------------
    def _taken_slots(self) -> set[str]:
        cur = self._conn.execute(
            "SELECT slot FROM bookings WHERE status = 'reserved'"
        )
        return {r["slot"] for r in cur.fetchall()}

    @staticmethod
    def _fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M")

    def list_free_slots(
        self,
        days_ahead: int = 7,
        limit: int = 20,
        now: Optional[datetime] = None,
    ) -> list[str]:
        """Free 'YYYY-MM-DD HH:MM' slots for the next ``days_ahead`` days."""
        now = now or datetime.now()
        taken = self._taken_slots()
        step = timedelta(minutes=int(self.config.get("duration_min", 30) or 30))
        start_h = int(self.config.get("start_hour", 9))
        end_h = int(self.config.get("end_hour", 19))
        free: list[str] = []
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(max(1, days_ahead)):
            cur_day = day + timedelta(days=i)
            if cur_day.weekday() not in self.days:
                continue
            t = cur_day.replace(hour=start_h, minute=0)
            end = cur_day.replace(hour=end_h, minute=0)
            while t < end and len(free) < max(0, limit):
                if t > now and self._fmt(t) not in taken:
                    free.append(self._fmt(t))
                t += step
        return free

    # -- reservations ----------------------------------------------------
    @staticmethod
    def _norm_slot(slot: Any) -> str:
        if isinstance(slot, datetime):
            return slot.strftime("%Y-%m-%d %H:%M")
        s = str(slot).strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(s[:16] if len(s) > 16 else s, fmt[:16] if len(s) <= 16 else fmt).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
        # Fall back: keep first 16 chars if it looks like a datetime.
        if len(s) >= 16 and s[4] in "-/" and s[10] == " ":
            return s[:16].replace("/", "-")
        raise ValueError(f"bad slot format {slot!r}; expected 'YYYY-MM-DD HH:MM'")

    def reserve(
        self, user_id: str, slot: Any, channel: str = "default"
    ) -> int:
        """Reserve ``slot``; returns booking id. Raises ValueError if taken/past."""
        norm = self._norm_slot(slot)
        try:
            dt = datetime.strptime(norm, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError(f"bad slot format {slot!r}")
        if dt <= datetime.now():
            raise ValueError("slot is in the past")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT id FROM bookings WHERE slot = ? AND status = 'reserved'",
                (norm,),
            )
            if cur.fetchone():
                raise ValueError("این ساعت قبلاً رزرو شده است 🙏 لطفاً ساعت دیگری انتخاب کنید")
            cur = self._conn.execute(
                "INSERT INTO bookings (user_id, channel, slot, status, created_at)"
                " VALUES (?, ?, ?, 'reserved', ?)",
                (user_id, channel, norm, time.time()),
            )
            return int(cur.lastrowid)

    def cancel(
        self,
        booking_id: Optional[int] = None,
        user_id: Optional[str] = None,
        slot: Optional[Any] = None,
        channel: str = "default",
    ) -> bool:
        """Cancel by id, or by (user_id + slot). Returns True if cancelled."""
        with self._lock, self._conn:
            if booking_id is not None:
                cur = self._conn.execute(
                    "UPDATE bookings SET status = 'cancelled'"
                    " WHERE id = ? AND status = 'reserved'",
                    (booking_id,),
                )
                return cur.rowcount > 0
            if user_id is not None and slot is not None:
                norm = self._norm_slot(slot)
                cur = self._conn.execute(
                    "UPDATE bookings SET status = 'cancelled'"
                    " WHERE user_id = ? AND channel = ? AND slot = ?"
                    " AND status = 'reserved'",
                    (user_id, channel, norm),
                )
                return cur.rowcount > 0
            raise ValueError("cancel() needs booking_id or (user_id + slot)")

    def list_bookings(self, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        if user_id:
            cur = self._conn.execute(
                "SELECT id, user_id, channel, slot, status FROM bookings"
                " WHERE user_id = ? ORDER BY slot",
                (user_id,),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, channel, slot, status FROM bookings ORDER BY slot"
            )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
