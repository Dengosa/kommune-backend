from __future__ import annotations

import os
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from google.genai import types

from app.core.tools.whatsapp_tool import send_whatsapp_messages_chunked
from app.core.agents._shared import client, MODEL

router = APIRouter()
logger = logging.getLogger("demo")

DEMO_WHATSAPP_FALLBACK = os.environ.get("DEMO_WHATSAPP_NUMBER", "")


# ---------------------------------------------------------------------------
# Step 1: real WhatsApp checklist send
# ---------------------------------------------------------------------------
class SendChecklistPayload(BaseModel):
    phone_number: str | None = None  # E.164 without '+', e.g. "27821234567"


CHECKLIST_MESSAGE = (
    "Kommune Journey Checklist \u2014 Getting Started\n\n"
    "1. ID document or asylum permit\n"
    "2. Proof of residence (any recent utility bill or affidavit)\n"
    "3. Highest school certificate you have\n"
    "4. Any existing bank or mobile money account details\n\n"
    "Reply here anytime and I'll walk you through the next step."
)


@router.post("/demo/send-checklist")
async def send_checklist(payload: SendChecklistPayload):
    """Sends a REAL WhatsApp message using the same tool that powers
    production WhatsApp - not a simulation. Used as the scripted action
    beat in the live lawyer demo."""
    to_number = payload.phone_number or DEMO_WHATSAPP_FALLBACK
    if not to_number:
        return {"status": "error", "error": "No phone number provided and DEMO_WHATSAPP_NUMBER not set."}

    try:
        result = await send_whatsapp_messages_chunked(to_number, CHECKLIST_MESSAGE)
        return {"status": "sent", "to": to_number, "result": result}
    except Exception as e:
        logger.exception("Demo WhatsApp send failed")
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Step 2: drafted email (displayed only, not sent - matches "showing a
# document" without the risk of a live send failing or going to the wrong
# inbox in front of an audience)
# ---------------------------------------------------------------------------
class DraftEmailPayload(BaseModel):
    student_context: str = (
        "An 18-year-old who just finished school, asking about bursary "
        "and further education options in South Africa."
    )


FALLBACK_DRAFT = {
    "subject": "Bursary Application Inquiry \u2014 Getting Started",
    "body": (
        "To Whom It May Concern,\n\n"
        "I recently completed my schooling and am seeking information about "
        "bursary opportunities available to me. I would appreciate guidance "
        "on the application process, required documents, and any upcoming "
        "deadlines.\n\n"
        "Thank you for your time and assistance.\n\n"
        "Kind regards"
    ),
}


@router.post("/demo/draft-email")
async def draft_email(payload: DraftEmailPayload):
    """Generates a real drafted email using the same model/client as the
    live agents. Displayed on screen only - not sent - so a slow or failed
    generation never breaks the live demo (falls back to a solid static
    draft instead of erroring)."""
    prompt = (
        "Draft a short, professional bursary inquiry email (under 120 words) "
        f"for this situation: {payload.student_context}\n\n"
        "Respond ONLY as JSON: {\"subject\": \"...\", \"body\": \"...\"}. "
        "No markdown, no code fences, no extra text."
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(max_output_tokens=300),
        )
        raw = (response.text or "").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        import json
        parsed = json.loads(raw)
        if "subject" in parsed and "body" in parsed:
            return {"status": "ok", **parsed}
        raise ValueError("Missing subject/body in model response")

    except Exception as e:
        logger.warning(f"Draft email generation failed, using fallback: {e}")
        return {"status": "ok", **FALLBACK_DRAFT}
