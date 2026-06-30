from __future__ import annotations

from app.core.state import KommuneState
from app.core.agents._shared import (
    call_agent,
    extract_handoff,
    AGENT_DISPLAY_NAMES,
    HANDOFF_INSTRUCTIONS,
    MAX_HANDOFFS,
)

SYSTEM_PROMPT = """You are Rex, the credit and financial inclusion
specialist agent within Kommune.

You help migrants in South Africa with:
- Opening bank accounts without a South African ID (using passports,
  asylum seeker permits, Section 22/24 documents — explain which banks
  currently accept these, noting policies vary and change)
- Understanding and building a "K-score" (Kommune's credit-building score
  for people excluded from traditional credit bureaus)
- SASSA grants: eligibility basics, application process, required documents
- Remittances, mobile money, and avoiding predatory lenders / loan sharks

Tone: practical, empowering, numbers-literate but plain-language. Always
flag scams and predatory lending red flags (e.g. upfront fees, unregistered
lenders, "guaranteed approval").

If a request involves a financial emergency tied to documentation status,
note that Lex (legal agent) may also help and that escalation to Scalabrini
Centre can assist with both.
""" + HANDOFF_INSTRUCTIONS


async def run_credit_agent(context: dict) -> dict:
    """Credit agent (Rex). Reads `state` from context, calls Claude with
    the credit system prompt, detects handoffs.

    Returns a dict with: response (str), handoff_to (str|None), agent="credit".
    """
    state: KommuneState = context["state"]

    history = state.get("messages", [])
    exchanges = state.get("exchanges", [])
    visited = state.get("visited_agents", [])

    prior_context = ""
    if exchanges:
        parts = [
            f"[{AGENT_DISPLAY_NAMES.get(ex['agent'], ex['agent'])} already said]: {ex['response']}"
            for ex in exchanges
        ]
        prior_context = (
            "\n\nContext from other Kommune agents who already responded "
            "to this user message (do not repeat this, build on it if relevant):\n"
            + "\n\n".join(parts)
        )

    user_turn = state["user_message"] + prior_context
    messages = history + [{"role": "user", "content": user_turn}]

    raw_text = call_agent(SYSTEM_PROMPT, messages)
    clean_text, handoff_agent = extract_handoff(raw_text)

    new_visited = visited + ["credit"]
    if handoff_agent and (handoff_agent in new_visited or len(new_visited) >= MAX_HANDOFFS):
        handoff_agent = None

    return {
        "agent": "credit",
        "response": clean_text,
        "handoff_to": handoff_agent,
        "visited_agents": new_visited,
    }
