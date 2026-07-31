"""
Activation endpoints for the manual/direct-payment flow (Zapper QR).

Flow:
1. User submits email/whatsapp via POST /activate/request
   -> backend generates a short reference code, stores a "pending"
      activation row, returns the reference + Zapper QR info to the
      frontend so it can be displayed for scanning.
2. User pays R300 via Zapper (out of band).
3. Founder checks Zapper app, matches the payment (amount + timing),
   then calls POST /admin/activate-user with the reference (or email)
   and an admin secret to confirm activation.
4. Confirmed users get a row in `users` with activated_at set, and
   pending_activations.status -> 'confirmed'.

This is intentionally manual for the first cohort of users (no business
account / payment processor yet). It can be swapped for an automated
Paystack/Yoco webhook later without changing the `users` table schema.
"""

import os
import secrets
import string
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr

from db.supabase_client import get_supabase
from notifications.resend_client import send_waitlist_confirmation

router = APIRouter()

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

# Set this to your real Zapper QR code image URL once created
ZAPPER_QR_URL = os.environ.get(
    "ZAPPER_QR_URL", "https://placehold.co/300x300?text=Zapper+QR"
)
ZAPPER_AMOUNT_ZAR = 300


def _generate_reference() -> str:
    """Generate a short, human-friendly reference code, e.g. KOM-7F3K9P."""
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"KOM-{code}"


# ---------------------------------------------------------------------------
# User-facing: request activation
# ---------------------------------------------------------------------------
class ActivationRequest(BaseModel):
    email: Optional[EmailStr] = None
    whatsapp_number: Optional[str] = None
    plan: str = "solo"  # "solo" | "spotme"
    spot_email: Optional[str] = None
    spot_message: Optional[str] = None


class ActivationRequestResponse(BaseModel):
    reference: str
    amount_zar: int
    qr_code_url: str
    instructions: str


@router.post("/activate/request", response_model=ActivationRequestResponse)
def request_activation(payload: ActivationRequest):
    if not payload.email and not payload.whatsapp_number:
        raise HTTPException(
            status_code=400,
            detail="Provide at least an email or WhatsApp number",
        )

    supabase = get_supabase()
    reference = _generate_reference()

    try:
        supabase.table("pending_activations").insert(
            {
                "email": payload.email,
                "whatsapp_number": payload.whatsapp_number,
                "reference": reference,
                "status": "pending",
                "plan": payload.plan,
                "spot_email": payload.spot_email,
                "spot_message": payload.spot_message,
            }
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log request: {e}")

    return ActivationRequestResponse(
        reference=reference,
        amount_zar=ZAPPER_AMOUNT_ZAR,
        qr_code_url=ZAPPER_QR_URL,
        instructions=(
            f"Scan the QR code and pay R{ZAPPER_AMOUNT_ZAR}. "
            f"Your reference is {reference} — please keep it. "
            "We'll activate your account within 24 hours of payment."
        ),
    )


# ---------------------------------------------------------------------------
# Admin: confirm activation manually
# ---------------------------------------------------------------------------
class AdminActivateRequest(BaseModel):
    reference: Optional[str] = None
    email: Optional[EmailStr] = None


class AdminActivateResponse(BaseModel):
    status: str
    email: Optional[str] = None
    reference: Optional[str] = None


@router.post("/admin/activate-user", response_model=AdminActivateResponse)
def admin_activate_user(
    payload: AdminActivateRequest,
    x_admin_secret: str = Header(default=""),
):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not payload.reference and not payload.email:
        raise HTTPException(
            status_code=400, detail="Provide a reference or email to activate"
        )

    supabase = get_supabase()

    # Find the pending activation
    query = supabase.table("pending_activations").select("*")
    if payload.reference:
        query = query.eq("reference", payload.reference)
    else:
        query = query.eq("email", payload.email)

    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No matching activation request found")

    record = result.data[0]
    email = record.get("email")
    reference = record.get("reference")

    # Mark pending activation as confirmed
    supabase.table("pending_activations").update(
        {"status": "confirmed", "confirmed_at": "now()"}
    ).eq("reference", reference).execute()

    # Upsert into users table with activated_at set
    if email:
        try:
            existing = supabase.table("users").select("id").eq("email", email).execute()
            if existing.data:
                supabase.table("users").update(
                    {"activated_at": "now()", "payment_reference": reference}
                ).eq("email", email).execute()
            else:
                supabase.table("users").insert(
                    {
                        "email": email,
                        "activated_at": "now()",
                        "payment_reference": reference,
                    }
                ).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to activate user: {e}")

        # Send confirmation email
        try:
            send_waitlist_confirmation(email, name=None)
        except Exception:
            pass

    return AdminActivateResponse(status="activated", email=email, reference=reference)


# ---------------------------------------------------------------------------
# Public: check activation status (for frontend polling)
# ---------------------------------------------------------------------------
class ActivationStatusResponse(BaseModel):
    status: str  # pending | confirmed | not_found


@router.get("/activate/status/{reference}", response_model=ActivationStatusResponse)
def activation_status(reference: str):
    supabase = get_supabase()
    result = (
        supabase.table("pending_activations")
        .select("status")
        .eq("reference", reference)
        .execute()
    )
    if not result.data:
        return ActivationStatusResponse(status="not_found")
    return ActivationStatusResponse(status=result.data[0]["status"])

# ---------------------------------------------------------------------------
# Admin: list all activations
# ---------------------------------------------------------------------------
@router.get("/admin/activations")
def admin_list_activations(
    x_admin_secret: str = Header(default=""),
):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase = get_supabase()
    result = (
        supabase.table("pending_activations")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# Admin: list all activations
# ---------------------------------------------------------------------------
@router.get("/admin/activations")
def admin_list_activations(
    x_admin_secret: str = Header(default=""),
):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase = get_supabase()
    result = (
        supabase.table("pending_activations")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []
