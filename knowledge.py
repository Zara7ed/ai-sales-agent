"""Business knowledge base: JSON-loaded, hot-reloadable, keyword retrieval."""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Optional


SECTIONS = (
    "services",
    "products",
    "pricing",
    "faqs",
    "policies",
    "objection_handlers",
    "sales_scenarios",
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


class BusinessKB:
    """Loads business knowledge from a JSON file with keyword search.

    Expected JSON shape (all keys optional):
      {
        "services": [...], "products": [...], "pricing": [...],
        "faqs": [...], "policies": [...],
        "objection_handlers": {...} | [...], "sales_scenarios": [...] | {...},
        ...any extra keys are indexed too...
      }
    Items may be strings or dicts (dicts with q/a, question/answer,
    name/description, keyword/text, etc. are rendered readably).
    """

    def __init__(self, path: str = "kb.json", auto_reload: bool = True):
        self.path = path
        self.auto_reload = auto_reload
        self._lock = threading.Lock()
        self._mtime: Optional[float] = None
        self.data: dict[str, Any] = {}
        self.load()

    # -- loading ----------------------------------------------------------
    def load(self) -> dict[str, Any]:
        """(Re)load the JSON file; missing file yields an empty KB."""
        with self._lock:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
                    if not isinstance(self.data, dict):
                        self.data = {"content": self.data}
            except FileNotFoundError:
                self.data = {}
            except json.JSONDecodeError:
                # Keep last good data on corrupt reload.
                pass
            try:
                self._mtime = os.path.getmtime(self.path)
            except OSError:
                self._mtime = None
            return self.data

    def maybe_reload(self) -> bool:
        """Reload if the file changed on disk. Returns True if reloaded."""
        if not self.auto_reload:
            return False
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return False
        if self._mtime is None or mtime > self._mtime:
            self.load()
            return True
        return False

    # -- chunk access ------------------------------------------------------
    def _render_item(self, section: str, item: Any) -> str:
        if isinstance(item, str):
            return f"[{section}] {item}"
        if isinstance(item, dict):
            for qk, ak in (
                ("q", "a"),
                ("question", "answer"),
                ("title", "body"),
                ("name", "description"),
                ("keyword", "response"),
                ("objection", "response"),
                ("scenario", "response"),
            ):
                if qk in item and ak in item:
                    return f"[{section}] {item[qk]} -> {item[ak]}"
            parts = " | ".join(f"{k}: {v}" for k, v in item.items())
            return f"[{section}] {parts}"
        return f"[{section}] {_stringify(item)}"

    def chunks(self) -> list[str]:
        """Flatten the whole KB into labelled text chunks."""
        out: list[str] = []
        for section, value in self.data.items():
            items = value if isinstance(value, list) else [value]
            for item in items:
                out.append(self._render_item(str(section), item))
        return out

    # -- retrieval ----------------------------------------------------------
    def search(self, query: str, top_k: int = 3) -> list[str]:
        """Return up to top_k chunks ranked by keyword overlap with query."""
        self.maybe_reload()
        qwords = _words(query)
        if not qwords:
            return []
        scored: list[tuple[int, str]] = []
        for chunk in self.chunks():
            overlap = len(qwords & _words(chunk))
            if overlap > 0:
                scored.append((overlap, chunk))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [c for _, c in scored[: max(0, top_k)]]

    def get_section(self, name: str) -> Any:
        """Return a raw KB section (default [] for lists, {} for handlers)."""
        self.maybe_reload()
        return self.data.get(name, [] if name not in ("objection_handlers",) else {})
