from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from db.supabase_client import get_supabase
from notifications.resend_client import send_waitlist_confirmation

router = APIRouter()


class WaitlistRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    city: Optional[str] = None
    source: Optional[str] = None


@router.post("/waitlist")
def join_waitlist(payload: WaitlistRequest):
    supabase = get_supabase()

    try:
        result = (
            supabase.table("waitlist")
            .insert(
                {
                    "email": payload.email,
                    "name": payload.name,
                    "city": payload.city,
                    "source": payload.source,
                }
            )
            .execute()
        )
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email already on waitlist")
        raise HTTPException(status_code=500, detail=f"Failed to join waitlist: {e}")

    try:
        send_waitlist_confirmation(payload.email, payload.name)
    except Exception:
        pass

    return {"status": "ok", "data": result.data}


_count_cache = {"value": 0, "ts": 0.0}
COUNT_CACHE_TTL = 60


@router.get("/waitlist/count")
def waitlist_count():
    now = time.time()
    if now - _count_cache["ts"] < COUNT_CACHE_TTL:
        return {"count": _count_cache["value"]}

    supabase = get_supabase()
    try:
        result = supabase.table("waitlist").select("id", count="exact").execute()
        count = result.count or 0
    except Exception:
        count = _count_cache["value"]

    _count_cache["value"] = count
    _count_cache["ts"] = now
    return {"count": count}
