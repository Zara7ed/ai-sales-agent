"""Shared engine builder: wires Settings -> KB -> Store -> Router -> Agent."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from agent import SalesAgent
from config import Settings, load as load_settings
from knowledge import BusinessKB
from llm_router import LLMRouter
from memory import ConversationStore


def _seed_kb_if_missing(kb_path: str) -> None:
    """Copy the bundled seed business file on first run."""
    if os.path.exists(kb_path):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    seed = os.path.join(here, "data", "seed_business.json")
    if os.path.exists(seed):
        import shutil

        shutil.copy(seed, kb_path)


def build_engine(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    _seed_kb_if_missing(settings.kb_path)
    kb = BusinessKB(path=settings.kb_path)
    store = ConversationStore(db_path=settings.db_path)
    providers = [p.__dict__ for p in settings.ordered_providers() if p.api_key or "localhost" in (p.base_url or "") or "127.0.0.1" in (p.base_url or "")]
    router = LLMRouter(providers=providers) if providers else None
    agent = SalesAgent(
        kb=kb,
        store=store,
        router=router,
        company_name=settings.company_name,
        tone=settings.company_tone,
        max_words=settings.max_reply_words,
    )
    return {"settings": settings, "kb": kb, "store": store, "router": router, "agent": agent}


async def handle_message(agent: SalesAgent, user_id: str, channel: str, text: str) -> tuple[str, str]:
    """Run the sync agent in a thread; return (reply, stage)."""
    result = await asyncio.to_thread(agent.handle, user_id, text, channel)
    reply = getattr(result, "reply", "") or ""
    stage = getattr(result, "stage", "unknown") or "unknown"
    return str(reply), str(stage)
