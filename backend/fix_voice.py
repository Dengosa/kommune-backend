"""
One-time fixer: swaps ElevenLabs TTS for Fish Audio TTS in
app/api/v1/endpoints/voice.py

Run from the backend root (where app/ lives):
    python fix_voice.py
"""

path = "app/api/v1/endpoints/voice.py"
src = open(path, encoding="utf-8").read()

old_block = '''ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # "Rachel" - a natural default voice'''

new_block = '''FISH_API_KEY = os.environ.get("FISH_API_KEY", "")
FISH_VOICE_ID = os.environ.get("FISH_VOICE_ID", "")'''

assert old_block in src, "old_block not found - file may already be edited"
src = src.replace(old_block, new_block)

old_url = 'ELEVENLABS_STREAM_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"\n\n\n'
src = src.replace(old_url, "")

old_fn = '''async def _speak_sentence(text: str, websocket: WebSocket):
    """Send one sentence to ElevenLabs and stream the resulting audio bytes
    straight back to the browser. Silently does nothing if no API key is
    set yet - the moment ELEVENLABS_API_KEY is added to the environment,
    this activates with no code change needed."""
    if not ELEVENLABS_API_KEY or not text.strip():
        return

    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            async with http_client.stream(
                "POST",
                ELEVENLABS_STREAM_URL,
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.warning(f"ElevenLabs TTS failed ({response.status_code}): {body[:200]}")
                    return
                await websocket.send_json({"type": "audio_start"})
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    await websocket.send_bytes(chunk)
                await websocket.send_json({"type": "audio_end"})
    except Exception:
        logger.exception("ElevenLabs TTS call failed")'''

new_fn = '''async def _speak_sentence(text: str, websocket: WebSocket):
    """Send one sentence to Fish Audio and stream the resulting audio bytes
    straight back to the browser. Silently does nothing if no API key is
    set yet - the moment FISH_API_KEY is added to the environment, this
    activates with no code change needed."""
    if not FISH_API_KEY or not text.strip():
        return

    from fishaudio import AsyncFishAudio
    from fishaudio.types import TTSConfig

    try:
        client = AsyncFishAudio(api_key=FISH_API_KEY)
        config = TTSConfig(reference_id=FISH_VOICE_ID, format="mp3") if FISH_VOICE_ID else None
        await websocket.send_json({"type": "audio_start"})
        async for chunk in client.tts.stream(text=text, config=config):
            await websocket.send_bytes(chunk)
        await websocket.send_json({"type": "audio_end"})
    except Exception:
        logger.exception("Fish Audio TTS call failed")'''

assert old_fn in src, "old_fn not found - file may already be edited"
src = src.replace(old_fn, new_fn)

src = src.replace(
    "If ELEVENLABS_API_KEY isn't set yet, everything above still works except",
    "If FISH_API_KEY isn't set yet, everything above still works except",
)

open(path, "w", encoding="utf-8").write(src)
print("voice.py updated: ElevenLabs -> Fish Audio")
