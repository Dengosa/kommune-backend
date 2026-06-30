from __future__ import annotations

import os
import logging

from fastapi import APIRouter, Request, Response, Query, BackgroundTasks

from app.core.state import new_state
from app.core.agent_graph import run_agent_graph
from app.core.tools.whatsapp_tool import send_whatsapp_messages_chunked

router = APIRouter()
logger = logging.getLogger("whatsapp")

WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")


@router.get("/whatsapp/webhook")
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification handshake. Called once when configuring
    the webhook URL in the Meta App dashboard."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("/whatsapp/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages. Meta requires a fast 200
    response, so message processing happens in a background task.

    Each WhatsApp number (the user's phone number) is used as both
    `session_id` and `user_id` for the agent graph — giving each user a
    persistent conversation thread via LangGraph's checkpointer, matching
    the web chat's memory behavior.
    """
    payload = await request.json()

    try:
        entry = payload.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Status updates (delivered/read receipts) etc - ignore
            return {"status": "ignored"}

        message = messages[0]
        from_number = message.get("from")  # e.g. "27821234567"
        msg_type = message.get("type")

        if msg_type != "text":
            background_tasks.add_task(
                send_whatsapp_messages_chunked,
                from_number,
                "Sorry, I can currently only read text messages. Please send your question as text.",
            )
            return {"status": "ok"}

        text = message.get("text", {}).get("body", "")

        background_tasks.add_task(_process_and_reply, from_number, text)

    except (IndexError, KeyError, TypeError) as e:
        logger.warning(f"Unexpected WhatsApp webhook payload shape: {e}")
        return {"status": "ignored"}

    return {"status": "ok"}


async def _process_and_reply(from_number: str, text: str) -> None:
    """Run the agent graph for an incoming WhatsApp message and send the
    response back via WhatsApp. Designed to run as a background task so the
    webhook can return 200 immediately (Meta requirement)."""
    try:
        state = new_state(session_id=from_number, user_id=from_number)
        state["user_message"] = text

        result = await run_agent_graph(state)

        if result.status == "EMERGENCY_LOCKED":
            response_text = result.payload.get("response", "")
            checklist = result.payload.get("checklist", {})
            items = checklist.get("items", [])
            if items:
                response_text += "\n\n" + "\n".join(f"- {item}" for item in items)
        else:
            response_text = result.payload.get("response", "")

        if not response_text:
            response_text = (
                "Sorry, something went wrong on our end. Please try again "
                "in a moment, or rephrase your question."
            )

        await send_whatsapp_messages_chunked(from_number, response_text)

    except Exception as e:
        logger.exception(f"Error processing WhatsApp message from {from_number}: {e}")
        await send_whatsapp_messages_chunked(
            from_number,
            "Sorry, something went wrong on our end. Please try again shortly.",
        )
