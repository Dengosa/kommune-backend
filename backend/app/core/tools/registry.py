from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from app.core.tools.email_tool import send_agent_email
from app.core.tools.calendar_tool import send_calendar_invite

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

SCHEDULE_APPOINTMENT_TOOL = {
    "name": "schedule_appointment",
    "description": (
        "Send the user a calendar invite (.ics file via email) for an "
        "appointment — e.g. a legal aid consultation, DHA appointment, or "
        "follow-up reminder. Only use this when the user has provided their "
        "email and confirmed they want a calendar reminder."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to_email": {"type": "string", "description": "User's email address"},
            "title": {"type": "string", "description": "Short event title"},
            "description": {"type": "string", "description": "Event details/notes"},
            "location": {"type": "string", "description": "Location or 'Online'/'Phone call'"},
            "start_iso": {
                "type": "string",
                "description": "Start date/time in ISO 8601 format, e.g. 2026-06-20T10:00:00",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Duration in minutes (default 30)",
            },
        },
        "required": ["to_email", "title", "description", "location", "start_iso"],
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
        return [WEB_SEARCH_TOOL, SEND_EMAIL_TOOL, SCHEDULE_APPOINTMENT_TOOL]
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

    return {"status": "error", "error": f"Unknown tool: {tool_name}"}
