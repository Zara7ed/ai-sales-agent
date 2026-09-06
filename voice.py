"""Voice transcription via an OpenAI-compatible audio API (stdlib only)."""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

# Signals that mean quota / credit / token-out: caller should ask user to type.
_QUOTA_MARKERS = (
    "insufficient_quota",
    "quota",
    "billing",
    "credit",
    "tokens exhausted",
    "token exhausted",
    "out of tokens",
    "rate_limit_exceeded",
    "usage limit",
)


def _cfg_get(cfg: Any, name: str, default: Any = None) -> Any:
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(name, default)
    return getattr(cfg, name, default)


def _is_quota_error(status: Optional[int], body: str) -> bool:
    if status in (402, 429):
        return True
    low = (body or "").lower()
    return any(m in low for m in _QUOTA_MARKERS)


def _encode_multipart(fields: dict[str, str], filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body without third-party deps."""
    boundary = "----hermesvoiceboundary7f3a1c"
    buf = io.BytesIO()
    for key, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        buf.write(f"{value}\r\n".encode())
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    buf.write(b"Content-Type: audio/ogg\r\n\r\n")
    buf.write(file_bytes)
    buf.write(f"\r\n--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def transcribe(ogg_bytes: Optional[bytes], cfg: Any = None) -> Optional[str]:
    """Transcribe OGG voice bytes -> text.

    Uses POST {base_url}/audio/transcriptions (OpenAI-compatible).
    Returns None on quota/token-out (or any failure) so the caller
    can ask the user to type instead. Never raises.
    """
    try:
        if not ogg_bytes:
            return None
        base_url = _cfg_get(cfg, "base_url", None) or os.getenv(
            "VOICE_BASE_URL", os.getenv("PRIMARY_BASE_URL", "https://api.openai.com/v1")
        )
        api_key = _cfg_get(cfg, "api_key", None) or os.getenv(
            "VOICE_API_KEY", os.getenv("PRIMARY_API_KEY", "")
        )
        model = _cfg_get(cfg, "model", None) or os.getenv("VOICE_MODEL", "whisper-1")
        language = _cfg_get(cfg, "language", None) or os.getenv("VOICE_LANG", "fa")
        timeout = float(_cfg_get(cfg, "timeout", 30.0) or 30.0)

        url = base_url.rstrip("/") + "/audio/transcriptions"
        fields: dict[str, str] = {"model": str(model)}
        if language:
            fields["language"] = str(language)
        body, content_type = _encode_multipart(fields, "voice.ogg", bytes(ogg_bytes))

        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", content_type)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", "replace")
            except Exception:
                err_body = ""
            # Quota / token-out AND any HTTP error -> graceful None.
            _ = _is_quota_error(getattr(e, "code", None), err_body)
            return None
        text = str(payload.get("text", "") or "").strip()
        return text or None
    except Exception:
        return None
