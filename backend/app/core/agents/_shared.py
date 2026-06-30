from __future__ import annotations

import os
import re
import json
from typing import Optional

from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

MAX_HANDOFFS = int(os.environ.get("MAX_HANDOFFS", "3"))

NGO_MAP = {
    "legal_detention": "LHR (Lawyers for Human Rights)",
    "asylum": "Scalabrini Centre",
    "refugee_urgent": "UNHCR South Africa",
    "health_crisis": "SIHMA",
}

VALID_AGENTS = {"legal", "credit", "health", "education", "journey"}

AGENT_DISPLAY_NAMES = {
    "legal": "Lex",
    "credit": "Rex",
    "health": "Vita",
    "education": "Opportunity",
    "journey": "Journey Engine",
}

HANDOFF_INSTRUCTIONS = """

INTER-AGENT HANDOFF PROTOCOL:
You are one of several specialist agents working together within Kommune
(Lex/legal, Rex/credit, Vita/health, education, journey). If, while helping
the user, you identify that part of their issue falls clearly into another
agent's domain and would benefit from that agent's expertise in THIS SAME
reply, end your response with a handoff tag on its own line:

[[HANDOFF: <agent_name>]]

where <agent_name> is one of: legal, credit, health, education, journey.

Only do this if it genuinely adds value. Do NOT hand off for issues you can
fully answer yourself. Do NOT hand off back to an agent that has already
responded in this conversation turn. If no handoff is needed, simply do not
include the tag.
"""

EMERGENCY_INSTRUCTIONS = """

EMERGENCY DETECTION PROTOCOL:
If the user's message describes an ACTIVE emergency — they are currently
detained, about to be deported imminently (e.g. "they're putting me on a
plane", "I'm at the airport being deported now"), in immediate danger of
violence, or facing an urgent health crisis with no access to care RIGHT
NOW — begin your response with a tag on its own line, BEFORE any other
text:

[[EMERGENCY: <reason>]]

where <reason> is a short (2-6 word) description, e.g. "active detention"
or "imminent deportation". Only use this for genuinely urgent, time-critical
situations happening now — not for general questions about rights,
processes, or past events. Most messages should NOT trigger this.
"""

PRIORITY_INSTRUCTIONS = """

PRIORITY CASE FLAGGING PROTOCOL:
Some situations aren't an active emergency (nothing is happening RIGHT NOW)
but put the person at serious ongoing legal risk and warrant proactive NGO
referral. This includes:
- Expired permits/passports, especially where a renewal application is
  stuck, overdue, or the person's home country embassy won't reissue a
  passport
- Final asylum rejection (appeal exhausted) where the person has overstayed
  and remains in South Africa
- Any situation where the person is currently undocumented/out of status
  through no clear fault of their own (e.g. DHA processing delays)

For these, AFTER your normal helpful response (do not skip giving real
guidance), add a tag on its own line at the END of your response:

[[PRIORITY: <reason>]]

where <reason> is a short (2-6 word) description, e.g. "overstayed after
final rejection" or "expired permit, stuck renewal". This does NOT lock the
conversation — continue normally. It flags the case for proactive referral
to LHR/Scalabrini so a human can follow up, even if the user doesn't
explicitly ask for escalation. Do not use this for routine questions about
people who currently have valid status.
"""

HANDOFF_PATTERN = re.compile(r"\[\[HANDOFF:\s*(\w+)\s*\]\]", re.IGNORECASE)
EMERGENCY_PATTERN = re.compile(r"\[\[EMERGENCY:\s*([^\]]+)\]\]", re.IGNORECASE)
PRIORITY_PATTERN = re.compile(r"\[\[PRIORITY:\s*([^\]]+)\]\]", re.IGNORECASE)


def extract_handoff(text: str) -> tuple[str, Optional[str]]:
    """Strip the handoff tag from response text. Returns
    (clean_text, handoff_agent_or_None)."""
    match = HANDOFF_PATTERN.search(text)
    if not match:
        return text.strip(), None

    agent = match.group(1).lower()
    clean_text = HANDOFF_PATTERN.sub("", text).strip()

    if agent not in VALID_AGENTS:
        return clean_text, None

    return clean_text, agent


def extract_emergency(text: str) -> tuple[str, Optional[str]]:
    """Strip an emergency tag from response text. Returns
    (clean_text, reason_or_None)."""
    match = EMERGENCY_PATTERN.search(text)
    if not match:
        return text, None

    reason = match.group(1).strip()
    clean_text = EMERGENCY_PATTERN.sub("", text, count=1).strip()
    return clean_text, reason


def extract_priority(text: str) -> tuple[str, Optional[str]]:
    """Strip a priority-case tag from response text. Returns
    (clean_text, reason_or_None)."""
    match = PRIORITY_PATTERN.search(text)
    if not match:
        return text, None

    reason = match.group(1).strip()
    clean_text = PRIORITY_PATTERN.sub("", text, count=1).strip()
    return clean_text, reason


def _to_gemini_contents(messages: list[dict]) -> list[types.Content]:
    """Convert our internal [{"role": "user"|"assistant", "content": str}]
    message list into Gemini's Content format. Gemini uses "model" instead
    of "assistant" for the AI role."""
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    return contents


def call_agent(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 1024,
) -> str:
    """Call the Gemini API and return the response text."""
    contents = _to_gemini_contents(messages)

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


# ---------------------------------------------------------------------------
# Tool-calling loop (Gemini function calling + Google Search grounding)
# ---------------------------------------------------------------------------
def call_agent_with_tools(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 1536,
    max_iterations: int = 5,
) -> tuple[str, list[dict]]:
    """Run an agentic tool-use loop with Gemini.

    `tools` is our internal tool-spec format (see app.core.tools.registry).
    A special entry {"type": "web_search"} requests Gemini's built-in
    Google Search grounding tool. Other entries are converted to Gemini
    function declarations and dispatched via
    app.core.tools.registry.execute_tool when Gemini calls them.

    Returns (final_text, tool_calls_log) where tool_calls_log is a list of
    {"tool": str, "input": dict, "result": dict} for non-search tools,
    used for Vault audit logging.
    """
    from app.core.tools.registry import execute_tool

    contents = _to_gemini_contents(messages)
    tool_calls_log: list[dict] = []

    # Split out web_search (Gemini's built-in grounding) from custom
    # function-calling tools (send_email, schedule_appointment, etc.)
    gemini_tools = []
    has_search = any(t.get("type") == "web_search_20250305" or t.get("name") == "web_search" for t in tools)
    function_tools = [t for t in tools if t.get("name") not in (None, "web_search") and "input_schema" in t]

    if has_search:
        gemini_tools.append(types.Tool(google_search=types.GoogleSearch()))

    if function_tools:
        declarations = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=_to_gemini_schema(t["input_schema"]),
            )
            for t in function_tools
        ]
        gemini_tools.append(types.Tool(function_declarations=declarations))

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=max_tokens,
        tools=gemini_tools if gemini_tools else None,
    )

    final_text = ""

    for _ in range(max_iterations):
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0] if response.candidates else None
        if not candidate:
            return final_text, tool_calls_log

        function_calls = []
        text_parts = []

        for part in candidate.content.parts:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            if getattr(part, "function_call", None):
                function_calls.append(part.function_call)

        final_text = "".join(text_parts) if text_parts else final_text

        if not function_calls:
            return final_text, tool_calls_log

        # Append the model's turn (including function call parts) to history
        contents.append(candidate.content)

        # Execute each function call and append results
        response_parts = []
        for fc in function_calls:
            tool_input = dict(fc.args) if fc.args else {}
            result = execute_tool(fc.name, tool_input)
            tool_calls_log.append({"tool": fc.name, "input": tool_input, "result": result})
            response_parts.append(
                types.Part.from_function_response(
                    name=fc.name,
                    response={"result": result},
                )
            )

        contents.append(types.Content(role="user", parts=response_parts))

    return final_text, tool_calls_log


def _to_gemini_schema(input_schema: dict) -> types.Schema:
    """Convert our internal JSON-schema-style tool input_schema into a
    Gemini types.Schema object."""
    properties = {}
    for key, prop in input_schema.get("properties", {}).items():
        properties[key] = types.Schema(
            type=prop.get("type", "string").upper(),
            description=prop.get("description", ""),
        )

    return types.Schema(
        type="OBJECT",
        properties=properties,
        required=input_schema.get("required", []),
    )
