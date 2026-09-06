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
            if chat_id is None:
                return None
            # Voice notes: keep file_id in raw for transcription downstream.
            if not text and isinstance(msg.get("voice"), dict):
                text = ""
            if not text and not isinstance(msg.get("voice"), dict):
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

    async def _download_voice(self, file_id: str) -> Optional[bytes]:
        """Download a voice note file via getFile; None on any failure."""
        try:
            client = self._client_or_new()
            r = await client.get(f"{self._base}/getFile", params={"file_id": file_id})
            r.raise_for_status()
            path = (r.json().get("result") or {}).get("file_path", "")
            if not path:
                return None
            d = await client.get(f"https://api.telegram.org/file/bot{self.token}/{path}")
            d.raise_for_status()
            return d.content
        except Exception:
            log.exception("Voice download failed")
            return None

    async def _poll_once(self) -> None:
        from humanize import typing_delay

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
            customer_text = incoming.text
            # Voice note -> transcribe; on quota/token-out ask to type.
            msg = (incoming.raw.get("message") or {}) if isinstance(incoming.raw, dict) else {}
            if not customer_text and isinstance(msg.get("voice"), dict):
                audio = await self._download_voice(str(msg["voice"].get("file_id", "")))
                customer_text = ""
                if audio:
                    try:
                        from voice import transcribe

                        customer_text = transcribe(audio, None) or ""
                    except Exception:
                        customer_text = ""
                if not customer_text:
                    await self.send(OutgoingMessage(
                        user_id=incoming.user_id, channel="telegram",
                        text="ببخشید، الان نمی‌تونم ویس گوش بدم، میشه تایپ کنی؟",
                    ))
                    continue
            # Owner takeover: stay silent, forward to owner only.
            owner_mode, owner_id = self._owner()
            if owner_mode is not None and owner_mode.is_takeover(incoming.user_id):
                if owner_id:
                    try:
                        await self.send(OutgoingMessage(
                            user_id=f"telegram:{owner_id}", channel="telegram",
                            text=owner_mode.forward_payload(
                                incoming.user_id, "telegram", customer_text),
                        ))
                    except Exception:
                        log.exception("Owner forward failed")
                continue
            try:
                reply, stage = await handle_message(
                    self.agent,
                    incoming.user_id,
                    "telegram",
                    customer_text,
                )
            except Exception:
                log.exception("SalesAgent.handle failed for telegram update")
                reply, stage = "ببخشید، یه مشکل پیش اومد. دوباره بگو.", "new"
            try:
                await asyncio.sleep(typing_delay(reply))
            except Exception:
                pass
            try:
                await self.send(OutgoingMessage(user_id=incoming.user_id, channel="telegram", text=reply))
            except Exception:
                log.exception("Telegram sendMessage failed")
            # Live-feed to owner.
            if owner_mode is not None and owner_id and owner_mode.is_live(incoming.user_id):
                try:
                    await self.send(OutgoingMessage(
                        user_id=f"telegram:{owner_id}", channel="telegram",
                        text=owner_mode.forward_payload(
                            incoming.user_id, "telegram", customer_text, reply, stage),
                    ))
                except Exception:
                    log.exception("Owner live-feed failed")

    def _owner(self):
        """Return (OwnerMode|None, owner_chat_id|None)."""
        owner_id = os.getenv("OWNER_TELEGRAM_ID", "")
        if not owner_id:
            return None, None
        try:
            from owner import OwnerMode

            store = getattr(self.agent, "store", None)
            if store is None:
                return None, owner_id
            return OwnerMode(store), owner_id
        except Exception:
            return None, owner_id

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
