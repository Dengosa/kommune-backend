from __future__ import annotations

import asyncio
import json
import os
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.agents._shared import call_agent_with_tools_stream, extract_emergency, extract_priority, extract_handoff
from app.core.agents.legal import SYSTEM_PROMPT as LEGAL_SYSTEM_PROMPT
from app.core.tools.registry import get_tools_for_agent

router = APIRouter()
logger = logging.getLogger("voice")

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
FISH_API_KEY = os.environ.get("FISH_API_KEY", "")
FISH_VOICE_ID = os.environ.get("FISH_VOICE_ID", "")

# Using Deepgram's raw WebSocket protocol directly (not the SDK) so this
# endpoint doesn't break every time Deepgram ships a new SDK major version -
# the underlying wire protocol is far more stable than the Python client.
DEEPGRAM_WS_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&language=en"
    "&smart_format=true"
    "&interim_results=true"
    "&endpointing=500"          # stop waiting after 500ms of silence - marks end of utterance
    "&encoding=linear16"
    "&sample_rate=16000"
)

async def _speak_sentence(text: str, websocket: WebSocket):
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
        logger.exception("Fish Audio TTS call failed")


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket):
    """
    Real-time voice pipeline: browser mic -> Deepgram (live STT) -> streaming
    Gemini agent (Lex, with real tools) -> ElevenLabs (streaming TTS) -> browser.

    Messages sent to the browser:
        {"type": "transcript", "text": "...", "is_final": bool}
        {"type": "agent_delta", "text": "..."}       - streamed response text
        {"type": "agent_done", "emergency": str|None, "priority": str|None}
        {"type": "audio_start"} / raw audio bytes / {"type": "audio_end"}
        {"type": "error", "message": "..."}

    If FISH_API_KEY isn't set yet, everything above still works except
    audio playback - text still streams so this is testable today.
    """
    await websocket.accept()

    if not DEEPGRAM_API_KEY:
        await websocket.send_json({"type": "error", "message": "Voice is not configured on the server yet (missing DEEPGRAM_API_KEY)."})
        await websocket.close()
        return

    conversation_history: list[dict] = []

    try:
        logger.info("Connecting to Deepgram...")
        async with websockets.connect(
            DEEPGRAM_WS_URL,
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        ) as dg_socket:
            logger.info("Connected to Deepgram successfully")

            async def relay_browser_audio_to_deepgram():
                first_chunk_logged = False
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        if not first_chunk_logged:
                            logger.info(f"Received first audio chunk from browser ({len(data)} bytes)")
                            first_chunk_logged = True
                        await dg_socket.send(data)
                except WebSocketDisconnect:
                    logger.info("Browser disconnected, closing Deepgram stream")
                    await dg_socket.send(json.dumps({"type": "CloseStream"}))

            async def handle_final_transcript(user_text: str):
                """A complete utterance came in - run it through the real
                streaming agent and speak the response back."""
                logger.info(f"Final transcript received: {user_text!r} - calling agent")
                await websocket.send_json({"type": "transcript", "text": user_text, "is_final": True})

                conversation_history.append({"role": "user", "content": user_text})
                tools = get_tools_for_agent("legal", preview_mode=False)

                full_text = ""
                sentence_buffer = ""
                first_event_logged = False

                async for event in call_agent_with_tools_stream(
                    LEGAL_SYSTEM_PROMPT, conversation_history, tools
                ):
                    if not first_event_logged:
                        logger.info(f"First agent stream event received: {event['type']}")
                        first_event_logged = True

                    if event["type"] == "delta":
                        full_text += event["text"]
                        sentence_buffer += event["text"]
                        await websocket.send_json({"type": "agent_delta", "text": event["text"]})

                        # Speak as soon as we have a full sentence, rather than
                        # waiting for the entire response - this is what
                        # actually removes the "long silence" problem.
                        for terminator in (". ", "! ", "? ", "\n"):
                            if terminator in sentence_buffer:
                                idx = sentence_buffer.rindex(terminator) + len(terminator)
                                to_speak, sentence_buffer = sentence_buffer[:idx], sentence_buffer[idx:]
                                asyncio.create_task(_speak_sentence(to_speak, websocket))
                                break

                    elif event["type"] == "done":
                        logger.info(f"Agent stream done. Full text length: {len(full_text)}")
                        if sentence_buffer.strip():
                            asyncio.create_task(_speak_sentence(sentence_buffer, websocket))

                clean_text, emergency_reason = extract_emergency(full_text)
                clean_text, priority_reason = extract_priority(clean_text)
                clean_text, _handoff = extract_handoff(clean_text)

                conversation_history.append({"role": "assistant", "content": clean_text})
                await websocket.send_json({
                    "type": "agent_done",
                    "emergency": emergency_reason,
                    "priority": priority_reason,
                })
                logger.info("agent_done sent to browser")

            async def relay_deepgram_transcripts_to_browser():
                first_message_logged = False
                async for message in dg_socket:
                    if not first_message_logged:
                        logger.info(f"First message received from Deepgram: {str(message)[:200]}")
                        first_message_logged = True

                    try:
                        result = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    channel = result.get("channel")
                    if not channel:
                        continue
                    alternatives = channel.get("alternatives", [])
                    if not alternatives:
                        continue
                    transcript = alternatives[0].get("transcript", "")
                    if not transcript:
                        continue

                    is_final = result.get("is_final", False)
                    if is_final:
                        await handle_final_transcript(transcript)
                    else:
                        await websocket.send_json({"type": "transcript", "text": transcript, "is_final": False})

            await asyncio.gather(
                relay_browser_audio_to_deepgram(),
                relay_deepgram_transcripts_to_browser(),
            )

    except websockets.exceptions.InvalidStatusCode as e:
        logger.exception("Deepgram rejected the connection")
        await websocket.send_json({"type": "error", "message": f"Deepgram connection failed: {e}"})
    except Exception:
        logger.exception("Voice stream crashed")
        try:
            await websocket.send_json({"type": "error", "message": "Voice connection failed unexpectedly."})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
