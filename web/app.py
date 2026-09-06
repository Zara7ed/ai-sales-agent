"""FastAPI factory mounting channel routers + website chat endpoint."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import SalesAgent
from channels import instagram as instagram_channel
from config import Settings, load as load_settings
from engine import build_engine, handle_message

STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    user_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    stage: str


def create_app(agent: Optional[SalesAgent] = None, settings: Optional[Settings] = None) -> FastAPI:
    """Build the FastAPI application."""
    settings = settings or load_settings()
    if agent is None:
        agent = build_engine(settings)["agent"]

    app = FastAPI(title="AI Sales Agent")

    instagram_channel.configure(agent, settings)
    app.include_router(instagram_channel.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest):
        reply, stage = await handle_message(agent, body.user_id, "web", body.message)
        return ChatResponse(reply=reply, stage=stage)

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    @app.exception_handler(Exception)
    async def unhandled(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse({"error": "internal error"}, status_code=500)

    return app


def _load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:
        return Settings.__new__(Settings)  # fallback if env-driven init fails


app = None
if os.getenv("SALES_AGENT_AUTOCREATE_APP", "").lower() in ("1", "true", "yes"):
    app = create_app()
