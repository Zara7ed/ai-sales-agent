"""Telegram Bot API long-polling adapter (direct HTTPS, no aiogram)."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from agent import SalesAgent
from channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage
from config import Settings
from engine import handle_message

log = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """Long-polling Telegram adapter wiring text into SalesAgent.handle."""

    name = "telegram"

    def __init__(
        self,
        agent: SalesAgent,
        settings: Optional[Settings] = None,
        token: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        poll_timeout: int = 30,
    ) -> None:
        self.agent = agent
        self.settings = settings
        self.token = token or (getattr(settings, "telegram_bot_token", None) if settings else None) or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._base = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self._client = client
        self._owns_client = client is None
        self.poll_timeout = poll_timeout
        self._offset: int = 0
        self._running = False

    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.poll_timeout + 15.0))
            self._owns_client = True
        return self._client

    def normalize(self, raw: dict) -> Optional[IncomingMessage]:
        try:
            msg = raw.get("message") or raw.get("edited_message") or {}
            text = msg.get("text", "")
            chat = msg.get("chat", {}) or {}
            chat_id = chat.get("id")
            if chat_id is None or not text:
                return None
            return IncomingMessage(
                user_id=f"telegram:{chat_id}",
                channel="telegram",
                text=str(text),
                raw=raw,
            )
        except Exception:
            return None

    async def send(self, message: OutgoingMessage) -> Any:
        client = self._client_or_new()
        chat_id = str(message.user_id).removeprefix("telegram:")
        resp = await client.post(
            f"{self._base}/sendMessage",
            json={"chat_id": chat_id, "text": message.text},
        )
        resp.raise_for_status()
        return resp.json()

    async def _poll_once(self) -> None:
        client = self._client_or_new()
        resp = await client.get(
            f"{self._base}/getUpdates",
            params={"offset": self._offset, "timeout": self.poll_timeout},
        )
        resp.raise_for_status()
        data = resp.json()
        for update in data.get("result", []):
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            incoming = self.normalize(update)
            if incoming is None:
                continue
            try:
                reply, _stage = await handle_message(
                    self.agent,
                    incoming.user_id,
                    "telegram",
                    incoming.text,
                )
            except Exception:
                log.exception("SalesAgent.handle failed for telegram update")
                reply = "Sorry, something went wrong. Please try again."
            try:
                await self.send(OutgoingMessage(user_id=incoming.user_id, channel="telegram", text=reply))
            except Exception:
                log.exception("Telegram sendMessage failed")

    async def run(self) -> None:
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        self._client_or_new()
        self._running = True
        log.info("Telegram long-polling started")
        try:
            while self._running:
                try:
                    await self._poll_once()
                except Exception:
                    log.exception("Telegram poll error; retrying in 2s")
                    await asyncio.sleep(2)
        finally:
            if self._owns_client and self._client is not None:
                await self._client.aclose()
                self._client = None

    async def stop(self) -> None:
        self._running = False
