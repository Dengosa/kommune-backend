from __future__ import annotations

import os
import httpx
import base64

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


async def send_sms(to: str, body: str) -> dict:
    """Send an SMS via Twilio. `to` should be in E.164 format
    (e.g. "+27821234567"). Returns a status dict."""
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        return {"status": "error", "error": "Twilio not configured"}

    url = f"{TWILIO_API_BASE}/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"

    auth = base64.b64encode(
        f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "From": TWILIO_FROM_NUMBER,
        "To": to,
        "Body": body,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, data=data)
            resp.raise_for_status()
            return {"status": "sent", "result": resp.json()}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": str(e), "response": e.response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def send_sms_chunked(to: str, body: str, max_len: int = 1500) -> list[dict]:
    """SMS has a 1600-char practical limit per message (concatenated
    segments). Split long agent responses and send as multiple messages."""
    if len(body) <= max_len:
        return [await send_sms(to, body)]

    chunks = []
    remaining = body
    while remaining:
        chunks.append(remaining[:max_len])
        remaining = remaining[max_len:]

    results = []
    for chunk in chunks:
        results.append(await send_sms(to, chunk))
    return results
