"""
One-time setup: adds WhatsApp voice-note support (Fish Audio STT + TTS).

Run from the backend root (where app/ lives):
    python fix_whatsapp_voice.py

What it does:
  1. Creates app/core/tools/fish_voice.py (Fish Audio STT/TTS helpers)
  2. Appends WhatsApp media download/upload/send-audio helpers to
     app/core/tools/whatsapp_tool.py
  3. Patches app/api/v1/endpoints/whatsapp.py to handle incoming
     voice notes: download -> transcribe -> run agent -> synthesize
     reply -> upload -> send back as a voice note
"""

import os

# ---------------------------------------------------------------------
# 1. New file: app/core/tools/fish_voice.py
# ---------------------------------------------------------------------
fish_voice_path = "app/core/tools/fish_voice.py"
fish_voice_content = '''import os
from functools import lru_cache
from fishaudio import AsyncFishAudio
from fishaudio.types import TTSConfig

FISH_API_KEY = os.environ.get("FISH_API_KEY", "")
FISH_VOICE_ID = os.environ.get("FISH_VOICE_ID", "")


@lru_cache
def get_fish_client() -> AsyncFishAudio:
    return AsyncFishAudio(api_key=FISH_API_KEY)


async def synthesize_reply(text: str) -> bytes:
    """Agent reply text -> mp3 bytes, for a WhatsApp voice note reply."""
    client = get_fish_client()
    config = TTSConfig(reference_id=FISH_VOICE_ID, format="mp3") if FISH_VOICE_ID else None
    chunks = []
    async for chunk in client.tts.stream(text=text, config=config):
        chunks.append(chunk)
    return b"".join(chunks)


async def transcribe_voice_note(audio_bytes: bytes, language: str | None = None) -> str:
    """Incoming WhatsApp voice note bytes -> text, fed into run_agent_graph()."""
    client = get_fish_client()
    result = await client.asr.transcribe(audio=audio_bytes, language=language)
    return result.text
'''

os.makedirs(os.path.dirname(fish_voice_path), exist_ok=True)
if os.path.exists(fish_voice_path):
    print(f"SKIP: {fish_voice_path} already exists - not overwriting")
else:
    with open(fish_voice_path, "w", encoding="utf-8") as f:
        f.write(fish_voice_content)
    print(f"CREATED: {fish_voice_path}")


# ---------------------------------------------------------------------
# 2. Append media helpers to app/core/tools/whatsapp_tool.py
# ---------------------------------------------------------------------
whatsapp_tool_path = "app/core/tools/whatsapp_tool.py"
whatsapp_tool_addition = '''

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
'''

with open(whatsapp_tool_path, encoding="utf-8") as f:
    tool_src = f.read()

if "download_whatsapp_media" in tool_src:
    print(f"SKIP: {whatsapp_tool_path} already has media helpers")
else:
    with open(whatsapp_tool_path, "a", encoding="utf-8") as f:
        f.write(whatsapp_tool_addition)
    print(f"UPDATED: {whatsapp_tool_path} (added media helpers)")


# ---------------------------------------------------------------------
# 3. Patch app/api/v1/endpoints/whatsapp.py to handle voice notes
# ---------------------------------------------------------------------
whatsapp_ep_path = "app/api/v1/endpoints/whatsapp.py"
with open(whatsapp_ep_path, encoding="utf-8") as f:
    ep_src = f.read()

old_import = "from app.core.tools.whatsapp_tool import send_whatsapp_messages_chunked"
new_import = (
    "from app.core.tools.whatsapp_tool import (\n"
    "    send_whatsapp_messages_chunked,\n"
    "    download_whatsapp_media,\n"
    "    upload_whatsapp_audio,\n"
    "    send_whatsapp_audio_message,\n"
    ")\n"
    "from app.core.tools.fish_voice import synthesize_reply, transcribe_voice_note"
)

old_dispatch = '''        if msg_type != "text":
            background_tasks.add_task(
                send_whatsapp_messages_chunked,
                from_number,
                "Sorry, I can currently only read text messages. Please send your question as text.",
            )
            return {"status": "ok"}

        text = message.get("text", {}).get("body", "")

        background_tasks.add_task(_process_and_reply, from_number, text)'''

new_dispatch = '''        if msg_type == "audio":
            media_id = message.get("audio", {}).get("id")
            if media_id:
                background_tasks.add_task(_process_and_reply_voice, from_number, media_id)
            return {"status": "ok"}

        if msg_type != "text":
            background_tasks.add_task(
                send_whatsapp_messages_chunked,
                from_number,
                "Sorry, I can currently only read text and voice messages. Please send your question as text or a voice note.",
            )
            return {"status": "ok"}

        text = message.get("text", {}).get("body", "")

        background_tasks.add_task(_process_and_reply, from_number, text)'''

new_voice_handler = '''


async def _process_and_reply_voice(from_number: str, media_id: str) -> None:
    """Handle an incoming WhatsApp voice note: download it, transcribe
    with Fish Audio, run the agent graph, then speak the reply back as
    a voice note using Fish Audio TTS."""
    try:
        audio_bytes = await download_whatsapp_media(media_id)
        user_text = await transcribe_voice_note(audio_bytes)

        if not user_text.strip():
            await send_whatsapp_messages_chunked(
                from_number,
                "Sorry, I couldn't make out that voice note. Could you try again or send it as text?",
            )
            return

        state = new_state(session_id=from_number, user_id=from_number)
        state["user_message"] = user_text

        result = await run_agent_graph(state)

        if result.status == "EMERGENCY_LOCKED":
            response_text = result.payload.get("response", "")
            checklist = result.payload.get("checklist", {})
            items = checklist.get("items", [])
            if items:
                response_text += "\\n\\n" + "\\n".join(f"- {item}" for item in items)
        else:
            response_text = result.payload.get("response", "")

        if not response_text:
            response_text = (
                "Sorry, something went wrong on our end. Please try again "
                "in a moment, or rephrase your question."
            )

        reply_audio = await synthesize_reply(response_text)
        reply_media_id = await upload_whatsapp_audio(reply_audio)
        await send_whatsapp_audio_message(from_number, reply_media_id)

    except Exception as e:
        logger.exception(f"Error processing WhatsApp voice note from {from_number}: {e}")
        await send_whatsapp_messages_chunked(
            from_number,
            "Sorry, something went wrong processing your voice note. Please try again shortly.",
        )
'''

changed = False

if old_import in ep_src:
    ep_src = ep_src.replace(old_import, new_import)
    changed = True
else:
    print("WARNING: expected import line not found - skipping import patch")

if old_dispatch in ep_src:
    ep_src = ep_src.replace(old_dispatch, new_dispatch)
    changed = True
else:
    print("WARNING: expected dispatch block not found - skipping dispatch patch")

if "_process_and_reply_voice" not in ep_src:
    ep_src = ep_src.rstrip("\n") + "\n" + new_voice_handler
    changed = True

if changed:
    with open(whatsapp_ep_path, "w", encoding="utf-8") as f:
        f.write(ep_src)
    print(f"UPDATED: {whatsapp_ep_path}")
else:
    print(f"SKIP: {whatsapp_ep_path} - nothing to change (already patched?)")

print("\\nDone. Remember: FISH_API_KEY and FISH_VOICE_ID must be set in .env and on Render.")
