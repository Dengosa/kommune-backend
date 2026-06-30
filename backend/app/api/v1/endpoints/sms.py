from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, BackgroundTasks

from app.core.state import new_state
from app.core.agent_graph import run_agent_graph
from app.core.tools.sms_tool import send_sms_chunked

router = APIRouter()
logger = logging.getLogger("sms")


@router.post("/sms/webhook")
async def receive_sms_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming SMS via Twilio's webhook (application/x-www-form-
    urlencoded). Twilio expects a fast response (empty TwiML is fine);
    actual processing + reply happens in a background task, mirroring the
    WhatsApp webhook pattern.

    The sender's phone number (`From`) is used as both `session_id` and
    `user_id`, giving each user a persistent conversation thread shared
    with their WhatsApp/web sessions if the same number/id is used
    consistently.
    """
    form = await request.form()
    from_number = form.get("From")
    body = form.get("Body", "")

    if from_number and body:
        background_tasks.add_task(_process_and_reply, from_number, body)

    # Empty TwiML response - acknowledges receipt without sending an
    # immediate auto-reply (the agent's reply is sent async via the API).
    return Response(content="<Response></Response>", media_type="application/xml")


async def _process_and_reply(from_number: str, text: str) -> None:
    """Run the agent graph for an incoming SMS and send the response back
    via Twilio's Messages API."""
    try:
        # SMS session id prefixed to distinguish from WhatsApp sessions
        # using the same phone number, if cross-channel continuity isn't
        # desired. Change to `from_number` directly for shared memory
        # across WhatsApp and SMS.
        session_id = f"sms:{from_number}"

        state = new_state(session_id=session_id, user_id=from_number)
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

        await send_sms_chunked(from_number, response_text)

    except Exception as e:
        logger.exception(f"Error processing SMS from {from_number}: {e}")
        await send_sms_chunked(
            from_number,
            "Sorry, something went wrong on our end. Please try again shortly.",
        )
