"""Abstract channel adapter contract."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IncomingMessage:
    """Normalized incoming message from any channel."""

    user_id: str
    channel: str
    text: str
    raw: dict = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """Normalized outgoing message to any channel."""

    user_id: str
    channel: str
    text: str
    extra: dict = field(default_factory=dict)


class ChannelAdapter(abc.ABC):
    """Abstract send/recv contract every channel must implement."""

    name: str = "base"

    @abc.abstractmethod
    async def send(self, message: OutgoingMessage) -> Any:
        """Send a message to a user on this channel."""
        raise NotImplementedError

    @abc.abstractmethod
    async def run(self) -> None:
        """Start receiving (e.g. polling loop). Webhook channels may no-op."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Stop receiving. Default is a no-op."""
        return None

    def normalize(self, raw: dict) -> Optional[IncomingMessage]:
        """Convert a channel-native payload into an IncomingMessage."""
        raise NotImplementedError
