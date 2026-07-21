from __future__ import annotations

import os
import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from google.genai import types

from app.core.tools.whatsapp_tool import send_whatsapp_messages_chunked
from app.core.agents._shared import client, MODEL

router = APIRouter()
logger = logging.getLogger("demo")

DEMO_WHATSAPP_FALLBACK = os.environ.get("DEMO_WHATSAPP_NUMBER", "")

Topic = Literal["asylum_permit", "citizenship"]

CHECKLISTS: dict[Topic, str] = {
    "asylum_permit": (
        "Kommune \u2014 Section 22 Permit Renewal Checklist\n\n"
        "1. Current (or most recently expired) Section 22 asylum permit\n"
        "2. Proof of address (utility bill, affidavit, or letter from host)\n"
        "3. Your Home Affairs reference/file number, if you have it\n"
        "4. Any prior Refugee Reception Office appointment confirmation\n"
        "5. Passport or ID from your country of origin, if available\n\n"
        "Reply here and I'll help you book the next available renewal appointment."
    ),
    "citizenship": (
        "Kommune \u2014 Section 4(3) Citizenship Application Checklist\n\n"
        "(For a child born in South Africa to foreign national parents, "
        "applying for citizenship on reaching majority \u2014 Citizenship "
        "Amendment Act)\n\n"
        "1. Unabridged South African birth certificate\n"
        "2. Proof of continuous residence in South Africa since birth\n"
        "3. Parents' identity/passport documents\n"
        "4. School records covering the full residence period\n"
        "5. Proof of registration of birth in the population register\n\n"
        "Reply here and I'll help you prepare the application."
    ),
}


# ---------------------------------------------------------------------------
# Step 1: real WhatsApp checklist send
# ---------------------------------------------------------------------------
class SendChecklistPayload(BaseModel):
    phone_number: str | None = None  # E.164 without '+', e.g. "27821234567"
    topic: Topic = "asylum_permit"


@router.post("/demo/send-checklist")
async def send_checklist(payload: SendChecklistPayload):
    """Sends a REAL WhatsApp message using the same tool that powers
    production WhatsApp - not a simulation. Topic is chosen explicitly by
    the presenter (not auto-detected) to match whatever was actually
    discussed in the live conversation."""
    to_number = payload.phone_number or DEMO_WHATSAPP_FALLBACK
    if not to_number:
        return {"status": "error", "error": "No phone number provided and DEMO_WHATSAPP_NUMBER not set."}

    message = CHECKLISTS[payload.topic]

    try:
        result = await send_whatsapp_messages_chunked(to_number, message)
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
    topic: Topic = "asylum_permit"


EMAIL_PROMPTS: dict[Topic, str] = {
    "asylum_permit": (
        "Draft a short, professional email to a Refugee Reception Office "
        "requesting a Section 22 asylum permit renewal appointment (under 120 words)."
    ),
    "citizenship": (
        "Draft a short, professional email to Home Affairs requesting guidance "
        "on a Section 4(3) citizenship application for a person born in South "
        "Africa to foreign national parents, now reaching majority (under 120 words)."
    ),
}

FALLBACK_DRAFTS: dict[Topic, dict[str, str]] = {
    "asylum_permit": {
        "subject": "Request for Section 22 Permit Renewal Appointment",
        "body": (
            "To the Refugee Reception Office,\n\n"
            "My Section 22 asylum seeker permit has expired and I would like to "
            "request an appointment to renew it as soon as possible. Please "
            "advise which documents I should bring and whether any appointment "
            "slots are currently available.\n\n"
            "Thank you for your assistance.\n\n"
            "Kind regards"
        ),
    },
    "citizenship": {
        "subject": "Inquiry \u2014 Section 4(3) Citizenship Application",
        "body": (
            "To Whom It May Concern,\n\n"
            "I was born in South Africa to foreign national parents and have "
            "lived here continuously since birth. Having now reached the age "
            "of majority, I would like guidance on applying for citizenship "
            "under Section 4(3) of the Citizenship Amendment Act, including "
            "which documents are required.\n\n"
            "Thank you for your assistance.\n\n"
            "Kind regards"
        ),
    },
}


@router.post("/demo/draft-email")
async def draft_email(payload: DraftEmailPayload):
    """Generates a real drafted email using the same model/client as the
    live agents. Displayed on screen only - not sent - so a slow or failed
    generation never breaks the live demo (falls back to a solid static
    draft instead of erroring). Topic chosen explicitly by the presenter."""
    prompt = (
        EMAIL_PROMPTS[payload.topic]
        + "\n\nRespond ONLY as JSON: {\"subject\": \"...\", \"body\": \"...\"}. "
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
        return {"status": "ok", **FALLBACK_DRAFTS[payload.topic]}
