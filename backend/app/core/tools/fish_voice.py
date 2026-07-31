import os
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
