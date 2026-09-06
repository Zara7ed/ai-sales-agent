"""Entry point: runs the web server (site widget + IG webhooks + admin)
and, if TELEGRAM_BOT_TOKEN is set, the Telegram long-polling bot."""
from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sales-agent")

try:
    from admin.panel import router as admin_router
except Exception:  # admin optional
    admin_router = None

try:
    from admin.ops import router as ops_router
except Exception:  # ops/CRM optional
    ops_router = None

from channels.telegram import TelegramAdapter
from config import load as load_settings
from engine import build_engine
from web.app import create_app


def main() -> None:
    import uvicorn

    settings = load_settings()
    parts = build_engine(settings)
    agent = parts["agent"]

    app = create_app(agent=agent, settings=settings)
    if admin_router is not None:
        app.include_router(admin_router)
        log.info("Admin panel mounted at /api/admin")
    if ops_router is not None:
        app.include_router(ops_router)
        log.info("Ops/CRM API mounted at /api/ops")

    async def _serve() -> None:
        config = uvicorn.Config(
            app,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            log_level="warning",
        )
        server = uvicorn.Server(config)
        tasks = [asyncio.create_task(server.serve())]
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if token:
            tg = TelegramAdapter(agent=agent, settings=settings, token=token)
            tasks.append(asyncio.create_task(tg.run()))
            log.info("Telegram polling started")
        else:
            log.info("TELEGRAM_BOT_TOKEN not set — web-only mode")
        await asyncio.gather(*tasks)

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
