from __future__ import annotations

from typing import Optional, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from db.supabase_client import get_supabase
from app.core.config import settings

router = APIRouter()


class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: Literal["solo", "spotme"]
    spot_email: Optional[str] = None
    spot_message: Optional[str] = None
    pay_method: Literal["payfast", "zapper"]


@router.post("/checkout")
def create_checkout(payload: CheckoutRequest):
    """Save a checkout attempt (email, plan, chosen payment method) to
    Supabase before the person is sent to PayFast or shown the Zapper QR.
    This is the record of intent - actual payment confirmation is handled
    separately once PayFast/Zapper webhooks are wired in."""
    supabase = get_supabase()
    try:
        result = (
            supabase.table("checkout")
            .insert(
                {
                    "email": payload.email,
                    "plan": payload.plan,
                    "spot_email": payload.spot_email,
                    "spot_message": payload.spot_message,
                    "pay_method": payload.pay_method,
                    "status": "pending",
                }
            )
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save checkout: {e}")

    return {"status": "ok", "data": result.data}


@router.get("/checkout/payment-options")
def payment_options():
    """Frontend calls this to know whether Zapper has a real QR configured
    yet, so it can show the QR image or an honest 'coming soon' state."""
    zapper_configured = "placehold.co" not in settings.ZAPPER_QR_URL
    return {
        "zapper": {
            "configured": zapper_configured,
            "qr_url": settings.ZAPPER_QR_URL if zapper_configured else None,
        },
    }
