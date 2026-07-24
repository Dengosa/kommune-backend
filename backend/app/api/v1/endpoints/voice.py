from __future__ import annotations

import asyncio
import json
import os
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger("voice")

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")

# Using Deepgram's raw WebSocket protocol directly (not the SDK) so this
# endpoint doesn't break every time Deepgram ships a new SDK major version -
# the underlying wire protocol is far more stable than the Python client.
DEEPGRAM_WS_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&language=en"
    "&smart_format=true"
    "&interim_results=true"
    "&encoding=linear16"
    "&sample_rate=16000"
)


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket):
    """
    PHASE 1 ONLY: live speech-to-text, nothing else.

    Browser sends raw 16-bit PCM audio chunks (16kHz, mono) over this
    WebSocket. We forward them to Deepgram's live transcription API and
    relay transcripts back to the browser as JSON:

        {"type": "transcript", "text": "...", "is_final": true|false}
        {"type": "error", "message": "..."}

    This does NOT yet call the Kommune agent graph or any TTS - that's
    Phase 2 (agent streaming) and Phase 3 (text-to-speech), built and
    tested separately once this phase is confirmed working end to end.
    """
    await websocket.accept()

    if not DEEPGRAM_API_KEY:
        await websocket.send_json({"type": "error", "message": "Voice is not configured on the server yet (missing DEEPGRAM_API_KEY)."})
        await websocket.close()
        return

    try:
        async with websockets.connect(
            DEEPGRAM_WS_URL,
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        ) as dg_socket:

            async def relay_browser_audio_to_deepgram():
                """Forward raw audio bytes from the browser straight to Deepgram."""
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await dg_socket.send(data)
                except WebSocketDisconnect:
                    # Browser closed the mic / left the page - tell Deepgram
                    # we're done sending audio so it flushes any final result.
                    await dg_socket.send(json.dumps({"type": "CloseStream"}))

            async def relay_deepgram_transcripts_to_browser():
                """Forward Deepgram's transcript messages back to the browser."""
                async for message in dg_socket:
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

                    await websocket.send_json({
                        "type": "transcript",
                        "text": transcript,
                        "is_final": result.get("is_final", False),
                    })

            # Run both directions concurrently until either side closes.
            await asyncio.gather(
                relay_browser_audio_to_deepgram(),
                relay_deepgram_transcripts_to_browser(),
            )

    except websockets.exceptions.InvalidStatusCode as e:
        logger.exception("Deepgram rejected the connection")
        await websocket.send_json({"type": "error", "message": f"Deepgram connection failed: {e}"})
    except Exception as e:
        logger.exception("Voice stream crashed")
        try:
            await websocket.send_json({"type": "error", "message": "Voice connection failed unexpectedly."})
        except Exception:
            pass  # socket may already be closed
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
