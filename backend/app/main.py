from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.security.cors import build_cors_settings
from app.api.v1.api import api_router


def create_app() -> FastAPI:
    """Kommune backend app entrypoint.

    Wires together:
    - Nemo router + 5 specialist agents (Lex/legal, Rex/credit, Vita/health,
      Opportunity/education, Journey Engine), with real Claude API calls,
      inter-agent handoffs, and LangGraph conversation memory
    - Emergency-lock circuit breaker (detention/health crisis detection)
    - Vault: immutable, hash-chained audit ledger of every agent action
    - Waitlist (Supabase + Resend)
    - Activation flow (Zapper QR manual payment, admin confirmation)
    """

    app = FastAPI(title="Kommune", version=os.getenv("KOMMUNE_VERSION", "0.2.0"))

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "kommune-backend"}

    app.include_router(api_router)

    cors_settings = build_cors_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_settings["allow_origins"],
        allow_credentials=cors_settings["allow_credentials"],
        allow_methods=cors_settings["allow_methods"],
        allow_headers=cors_settings["allow_headers"],
    )

    return app


app = create_app()
