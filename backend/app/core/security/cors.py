from __future__ import annotations

import os
from typing import Dict, List


def _split_csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def build_cors_settings() -> Dict[str, object]:
    """CORS configuration.

    Security posture: explicit allowlist via env. Falls back to
    FRONTEND_URL (single origin) if KOMMUNE_CORS_ALLOW_ORIGINS is unset,
    so a minimal deployment with just FRONTEND_URL set still works.

    Env:
      KOMMUNE_CORS_ALLOW_ORIGINS = "https://example.com,https://app.example.com"
      KOMMUNE_CORS_ALLOW_CREDENTIALS = "true" | "false"
      FRONTEND_URL = "https://your-frontend.vercel.app"  (fallback)
    """

    allow_origins = _split_csv(os.getenv("KOMMUNE_CORS_ALLOW_ORIGINS"))

    if not allow_origins:
        frontend_url = os.getenv("FRONTEND_URL")
        if frontend_url and frontend_url != "*":
            allow_origins = [frontend_url]
        elif frontend_url == "*":
            allow_origins = ["*"]

    allow_credentials = os.getenv("KOMMUNE_CORS_ALLOW_CREDENTIALS", "false").lower() == "true"

    # Credentials cannot be used with wildcard origins
    if "*" in allow_origins:
        allow_credentials = False

    return {
        "allow_origins": allow_origins,
        "allow_credentials": allow_credentials,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "X-Session-Id",
            "X-Admin-Secret",
        ],
    }
