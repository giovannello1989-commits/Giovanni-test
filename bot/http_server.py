from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from bot.storage import Storage
from bot.web import create_web_app


def create_http_app(store: Storage | None = None) -> FastAPI:
    """
    Minimal HTTP server for Railway (prevents 502 by listening on $PORT).

    Routes:
      - GET /        -> 200
      - GET /health  -> 200 JSON {"ok": true}

    Optional:
      - if ENABLE_WEB_SETUP=1 and store is provided, mounts the existing setup UI under /setup
        (protected by SETUP_ADMIN_TOKEN inside bot/web.py).
    """
    app = FastAPI(docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        return HTMLResponse("<h3>ok</h3>")

    @app.get("/health", response_class=JSONResponse)
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    if os.getenv("ENABLE_WEB_SETUP", "0") == "1" and store is not None:
        # Mount the existing setup wizard at /setup (so "/" can stay a simple 200).
        setup_app = create_web_app(store)
        app.mount("/setup", setup_app)

    # Small debug endpoint (optional, no secrets)
    @app.get("/info", response_class=JSONResponse)
    async def info() -> JSONResponse:
        payload: dict[str, Any] = {
            "ok": True,
            "service": "revolutx-bot",
            "enable_web_setup": os.getenv("ENABLE_WEB_SETUP", "0"),
        }
        return JSONResponse(payload)

    return app

