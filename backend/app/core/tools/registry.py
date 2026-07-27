from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from app.core.tools.email_tool import send_agent_email
from app.core.tools.calendar_tool import send_calendar_invite
from app.core.tools.sms_tool import send_sms_sync
from app.core.tools.whatsapp_tool import send_whatsapp_message_sync
from app.core.tools.letter_tool import draft_letter

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic tool-use schema)
# ---------------------------------------------------------------------------

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

SEND_EMAIL_TOOL = {
    "name": "send_email",
    "description": (
        "Draft and send an email on the user's behalf to an official body, "
        "NGO, employer, school, or other recipient (e.g. DHA, LHR, "
        "Scalabrini Centre, a bank's dispute department). Use this when the "
        "user has confirmed they want this email sent — do not send without "
        "the user's explicit go-ahead in the conversation. Always show the "
        "user the drafted email content in your text response BEFORE or "
        "alongside calling this tool, so they know what was sent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to_email": {
                "type": "string",
                "description": "Recipient email address",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Full email body text, professionally written",
            },
            "reply_to": {
                "type": "string",
                "description": "Optional reply-to address (the user's own email, so replies go to them)",
            },
        },
        "required": ["to_email", "subject", "body"],
    },
}

SEND_SMS_TOOL = {
    "name": "send_sms",
    "description": (
        "Send a follow-up SMS to the user's phone number with a summary, "
        "checklist, or next-step reminder. Use this only when the user has "
        "provided their phone number and confirmed they want an SMS "
        "follow-up - do not send without their explicit go-ahead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to_number": {
                "type": "string",
                "description": "Recipient phone number in E.164 format, e.g. +27821234567",
            },
            "body": {
                "type": "string",
                "description": "SMS message text, concise (SMS has a length limit)",
            },
        },
        "required": ["to_number", "body"],
    },
}

SEND_WHATSAPP_TOOL = {
    "name": "send_whatsapp",
    "description": (
        "Send a follow-up WhatsApp message to the user with a summary, "
        "checklist, or next-step reminder. Use this only when the user has "
        "provided their WhatsApp number and confirmed they want a WhatsApp "
        "follow-up - do not send without their explicit go-ahead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to_number": {
                "type": "string",
                "description": "Recipient WhatsApp number, international format without '+', e.g. 27821234567",
            },
            "body": {
                "type": "string",
                "description": "WhatsApp message text",
            },
        },
        "required": ["to_number", "body"],
    },
}

DRAFT_LETTER_TOOL = {
    "name": "draft_letter",
    "description": (
        "Draft a formal letter document (e.g. to Home Affairs, an employer, "
        "or a school) that the user can print, attach to an email, or bring "
        "in person. This only formats the letter text - it does not send or "
        "mail anything. Always show the user the drafted letter in your "
        "response after calling this tool."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "recipient_name": {"type": "string", "description": "Who the letter is addressed to"},
            "recipient_address": {"type": "string", "description": "Recipient's address or department"},
            "subject": {"type": "string", "description": "Subject line / RE: line"},
            "body": {"type": "string", "description": "The letter's main content, professionally written"},
            "sender_name": {"type": "string", "description": "The user's name, for the sign-off (optional)"},
        },
        "required": ["recipient_name", "recipient_address", "subject", "body"],
    },
}


def get_tools_for_agent(agent_name: str, preview_mode: bool = False) -> list[dict]:
    """Return the tool set available to a given specialist agent.

    Legal (Lex) gets the full action toolkit: web search, email, calendar.
    Other agents currently get web search only; can be extended similarly.

    `preview_mode=True` (unactivated users in their free preview) disables
    action tools (send_email, schedule_appointment) — agents can still give
    full informational answers and web search, but cannot execute actions
    until the user activates their account.
    """
    if agent_name == "legal":
        if preview_mode:
            return [WEB_SEARCH_TOOL]
        return [
            WEB_SEARCH_TOOL,
            SEND_EMAIL_TOOL,
            SCHEDULE_APPOINTMENT_TOOL,
            SEND_SMS_TOOL,
            SEND_WHATSAPP_TOOL,
            DRAFT_LETTER_TOOL,
        ]
    return [WEB_SEARCH_TOOL]


# ---------------------------------------------------------------------------
# Tool execution dispatch
# ---------------------------------------------------------------------------
def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool call (other than web_search, which Anthropic executes
    server-side) and return a result dict. Used by the agent tool-loop to
    build tool_result blocks, and also returned to the caller for Vault
    logging.
    """
    if tool_name == "send_email":
        result = send_agent_email(
            to_email=tool_input["to_email"],
            subject=tool_input["subject"],
            body=tool_input["body"],
            reply_to=tool_input.get("reply_to"),
        )
        return result

    if tool_name == "schedule_appointment":
        try:
            start = datetime.fromisoformat(tool_input["start_iso"])
        except ValueError:
            return {"status": "error", "error": "Invalid start_iso format"}

        result = send_calendar_invite(
            to_email=tool_input["to_email"],
            title=tool_input["title"],
            description=tool_input["description"],
            location=tool_input["location"],
            start=start,
            duration_minutes=tool_input.get("duration_minutes", 30),
        )
        return result

    if tool_name == "send_sms":
        return send_sms_sync(
            to=tool_input["to_number"],
            body=tool_input["body"],
        )

    if tool_name == "send_whatsapp":
        return send_whatsapp_message_sync(
            to=tool_input["to_number"],
            text=tool_input["body"],
        )

    if tool_name == "draft_letter":
        return draft_letter(
            recipient_name=tool_input["recipient_name"],
            recipient_address=tool_input["recipient_address"],
            subject=tool_input["subject"],
            body=tool_input["body"],
            sender_name=tool_input.get("sender_name"),
        )

    return {"status": "error", "error": f"Unknown tool: {tool_name}"}
