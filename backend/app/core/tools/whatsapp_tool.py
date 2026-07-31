from __future__ import annotations

import os
import httpx

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v21.0")

GRAPH_API_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


async def send_whatsapp_message(to: str, text: str) -> dict:
    """Send a text message via the Meta WhatsApp Cloud API.

    `to` is the recipient's phone number in international format without
    '+' (e.g. "27821234567"). Returns the API response dict, or an error
    dict if not configured / the request fails.
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"status": "error", "error": "WhatsApp not configured"}

    url = f"{GRAPH_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "sent", "result": resp.json()}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": str(e), "response": e.response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def send_whatsapp_messages_chunked(to: str, text: str, max_len: int = 4000) -> list[dict]:
    """WhatsApp text messages have a length limit (~4096 chars). Split long
    agent responses into multiple messages, sent in order."""
    if len(text) <= max_len:
        return [await send_whatsapp_message(to, text)]

    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:max_len])
        remaining = remaining[max_len:]

    results = []
    for chunk in chunks:
        results.append(await send_whatsapp_message(to, chunk))
    return results


def send_whatsapp_message_sync(to: str, text: str) -> dict:
    """Sync-safe sibling of send_whatsapp_message, for use inside the
    synchronous execute_tool dispatch (agent tool-calling loop). Uses a
    blocking httpx.Client rather than AsyncClient - kept separate from the
    async version above so the existing async callers (webhook, voice
    pipeline) are completely untouched."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"status": "error", "error": "WhatsApp not configured"}

    url = f"{GRAPH_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "sent", "result": resp.json()}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": str(e), "response": e.response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def download_whatsapp_media(media_id: str) -> bytes:
    """Fetch the raw bytes of an incoming WhatsApp media attachment
    (e.g. a voice note) given its media id from the webhook payload."""
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WhatsApp not configured")
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=30) as client:
        meta_resp = await client.get(f"{GRAPH_API_BASE}/{media_id}", headers=headers)
        meta_resp.raise_for_status()
        media_url = meta_resp.json()["url"]
        media_resp = await client.get(media_url, headers=headers)
        media_resp.raise_for_status()
        return media_resp.content


async def upload_whatsapp_audio(audio_bytes: bytes, mime_type: str = "audio/mpeg") -> str:
    """Upload generated audio (e.g. a Fish Audio TTS reply) to WhatsApp's
    media store and return the media id, needed before it can be sent."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp not configured")
    url = f"{GRAPH_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    files = {"file": ("reply.mp3", audio_bytes, mime_type)}
    data = {"messaging_product": "whatsapp", "type": mime_type}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, files=files, data=data)
        resp.raise_for_status()
        return resp.json()["id"]


async def send_whatsapp_audio_message(to: str, media_id: str) -> dict:
    """Send a previously-uploaded audio file as a WhatsApp voice note."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"status": "error", "error": "WhatsApp not configured"}
    url = f"{GRAPH_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "sent", "result": resp.json()}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": str(e), "response": e.response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}
