"""Humanize LLM replies: plain flowing Persian, no AI-ish formatting."""
from __future__ import annotations

import re

# Emoji / pictograph ranges (covers common emoji blocks).
_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"
    "\u2600-\u27bf"
    "\u2b00-\u2bff"
    "\u2300-\u23ff"
    "\ufe00-\ufe0f"
    "\u200d"
    "\u2190-\u21ff"
    "\u2200-\u22ff"
    "]+"
)

_ARROWS_RE = re.compile(r"\s*(?:-{1,2}>|={1,2}>|->|=>|→|←|↔|»|«)\s*")
_MD_CHARS_RE = re.compile(r"[*_`~#>|]")
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*+•○▪◦▪︎–—]+\s+|\d+[.)\]}:]\s+|\(?\d+\)\s+)")
_HEADER_LINE_RE = re.compile(r"^\s*#{1,6}\s*")
_FA_NUM_LINE_RE = re.compile(r"^\s*[۰-۹]+[.)\]}:ـ\-–—\s]+\s*")
_HR_LINE_RE = re.compile(r"^\s*(?:---|\*\*\*|___|─{3,}|═{3,})\s*$")
_BLANK_RE = re.compile(r"\n\s*\n+")


def _strip_line(line: str) -> str:
    """Remove bullets, numbers, headers and markdown from one line."""
    line = _HEADER_LINE_RE.sub("", line)
    line = _BULLET_LINE_RE.sub("", line)
    line = _FA_NUM_LINE_RE.sub("", line)
    line = _ARROWS_RE.sub("، ", line)
    line = _MD_CHARS_RE.sub("", line)
    line = _EMOJI_RE.sub("", line)
    return " ".join(line.split()).strip(" ،؛:").strip()


def strip_formatting(text: str) -> str:
    """Turn AI-ish formatted text into plain flowing sentences."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _EMOJI_RE.sub("", text)
    sentences: list[str] = []
    for raw in text.split("\n"):
        if not raw.strip() or _HR_LINE_RE.match(raw):
            continue
        cleaned = _strip_line(raw)
        if cleaned:
            sentences.append(cleaned)
    out = " ".join(sentences)
    out = re.sub(r"\s*،\s*،\s*", "، ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def enforce_max_words(text: str, max_words: int = 80) -> str:
    """Trim to max_words, preferring a sentence boundary."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    cut = " ".join(words[:max_words]).rstrip(" ,;:")
    sentences = re.split(r"(?<=[.!?؟…])\s+", cut)
    if len(sentences) > 1 and len(sentences[-1].split()) < 5:
        cut = " ".join(sentences[:-1])
    return cut.rstrip() + "…"


def humanize(text: str, max_words: int = 80) -> str:
    """Strip AI formatting and enforce max words -> plain Persian reply."""
    return enforce_max_words(strip_formatting(text), max_words)


def typing_delay(text: str) -> float:
    """Pretend-human typing pause: 4s for 2-5 words, scaling to 20s max."""
    n = len((text or "").split())
    if n <= 5:
        return 4.0
    # Linear ramp: 5 words -> 4s, 80+ words -> 20s.
    delay = 4.0 + (n - 5) * (16.0 / 75.0)
    return round(min(20.0, delay), 2)
