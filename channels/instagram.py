"""Meta Graph API webhook adapter for Instagram messaging."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agent import SalesAgent
from channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage
from config import Settings
from engine import handle_message

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v19.0"

router = APIRouter(prefix="/webhooks/instagram", tags=["instagram"])

_agent: Optional[SalesAgent] = None
_settings: Optional[Settings] = None
_client: Optional[httpx.AsyncClient] = None


def configure(agent: SalesAgent, settings: Optional[Settings] = None) -> APIRouter:
    """Bind a SalesAgent instance to the webhook router."""
    global _agent, _settings
    _agent = agent
    _settings = settings
    return router


def _verify_token() -> str:
    if _settings is not None and getattr(_settings, "instagram_verify_token", None):
        return str(_settings.instagram_verify_token)
    return os.getenv("IG_VERIFY_TOKEN", "verify-token")


def _page_token() -> str:
    if _settings is not None and getattr(_settings, "instagram_page_token", None):
        return str(_settings.instagram_page_token)
    return os.getenv("IG_PAGE_ACCESS_TOKEN", "")


def _client_or_new() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client


async def send_text(recipient_id: str, text: str) -> Any:
    """Send a text reply via the Graph send API."""
    token = _page_token()
    if not token:
        raise RuntimeError("IG_PAGE_ACCESS_TOKEN is not configured")
    client = _client_or_new()
    resp = await client.post(
        f"{GRAPH_BASE}/me/messages",
        params={"access_token": token},
        json={"recipient": {"id": recipient_id}, "message": {"text": text}},
    )
    resp.raise_for_status()
    return resp.json()


def extract_messages(payload: dict) -> list[IncomingMessage]:
    """Map a webhook payload to normalized incoming messages."""
    out: list[IncomingMessage] = []
    for entry in payload.get("entry", []) or []:
        for item in entry.get("messaging", []) or []:
            sender = (item.get("sender") or {}).get("id")
            text = ((item.get("message") or {}).get("text")) or ""
            if not sender or not text:
                continue
            out.append(
                IncomingMessage(
                    user_id=f"instagram:{sender}",
                    channel="instagram",
                    text=str(text),
                    raw=item,
                )
            )
    return out


@router.get("")
async def verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == _verify_token():
        return PlainTextResponse(hub_challenge or "")
    return JSONResponse({"error": "verification failed"}, status_code=403)


@router.post("")
async def events(request: Request):
    payload = await request.json()
    if _agent is None:
        return JSONResponse({"error": "adapter not configured"}, status_code=503)
    for incoming in extract_messages(payload):
        try:
            reply, _stage = await handle_message(
                _agent,
                incoming.user_id,
                "instagram",
                incoming.text,
            )
        except Exception:
            log.exception("SalesAgent.handle failed for instagram event")
            reply = "Sorry, something went wrong. Please try again."
        sender_id = incoming.user_id.removeprefix("instagram:")
        try:
            await send_text(sender_id, reply)
        except Exception:
            log.exception("Instagram Graph send failed")
    return {"status": "ok"}


class InstagramAdapter(ChannelAdapter):
    """Programmatic adapter wrapper around the Graph send API."""

    name = "instagram"

    def __init__(self, agent: SalesAgent, settings: Optional[Settings] = None) -> None:
        self.agent = agent
        self.settings = settings
        configure(agent, settings)

    def normalize(self, raw: dict) -> Optional[IncomingMessage]:
        msgs = extract_messages({"entry": [{"messaging": [raw]}]})
        return msgs[0] if msgs else None

    async def send(self, message: OutgoingMessage) -> Any:
        recipient = str(message.user_id).removeprefix("instagram:")
        return await send_text(recipient, message.text)

    async def run(self) -> None:
        # Webhook-driven: nothing to poll. Kept for the ChannelAdapter contract.
        return None
