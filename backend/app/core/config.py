from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

    RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL: str = os.environ.get(
        "RESEND_FROM_EMAIL", "Kommune <hello@kommune.app>"
    )

    FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "*")

    ADMIN_SECRET: str = os.environ.get("ADMIN_SECRET", "")
    ZAPPER_QR_URL: str = os.environ.get(
        "ZAPPER_QR_URL", "https://placehold.co/300x300?text=Zapper+QR"
    )

    MAX_HANDOFFS: int = int(os.environ.get("MAX_HANDOFFS", "3"))
    WAITLIST_COUNT_CACHE_TTL: int = int(os.environ.get("WAITLIST_COUNT_CACHE_TTL", "60"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
