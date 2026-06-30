from __future__ import annotations

from app.core.state import KommuneState
from app.core.agents._shared import (
    call_agent,
    extract_handoff,
    extract_emergency,
    AGENT_DISPLAY_NAMES,
    HANDOFF_INSTRUCTIONS,
    EMERGENCY_INSTRUCTIONS,
    MAX_HANDOFFS,
    NGO_MAP,
)

SYSTEM_PROMPT = """You are Vita, the health specialist agent within
Kommune.

You help migrants in South Africa with:
- Accessing public hospitals and clinics regardless of documentation status
  (Constitutional right to emergency care; explain Uniform Patient Fee
  Schedule classifications for non-citizens)
- ARV (antiretroviral) treatment access — South Africa provides ARVs
  regardless of nationality at public facilities
- Maternal health, child immunisation, and chronic medication access
- Mental health support resources

Tone: warm, non-judgmental, medically accurate but not a diagnosis tool.
Always include a disclaimer that you provide informational guidance, not
medical advice, and to seek in-person care for symptoms.

For health crises where someone has been denied care or is in danger,
recommend SIHMA (Scalabrini Institute for Human Mobility in Africa) and
note Kommune can help escalate.
""" + EMERGENCY_INSTRUCTIONS + HANDOFF_INSTRUCTIONS


async def run_health_agent(context: dict) -> dict:
    """Health agent (Vita). Reads `state` from context, calls Claude with
    the health system prompt, detects health-crisis emergencies and handoffs.

    Returns a dict with: response (str), handoff_to (str|None),
    emergency_reason (str|None), agent="health".
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

    clean_text, emergency_reason = extract_emergency(raw_text)
    clean_text, handoff_agent = extract_handoff(clean_text)

    new_visited = visited + ["health"]
    if handoff_agent and (handoff_agent in new_visited or len(new_visited) >= MAX_HANDOFFS):
        handoff_agent = None

    return {
        "agent": "health",
        "response": clean_text,
        "handoff_to": handoff_agent,
        "emergency_reason": emergency_reason,
        "visited_agents": new_visited,
        "escalate_ngo": emergency_reason is not None,
        "ngo": NGO_MAP["health_crisis"] if emergency_reason else state.get("ngo"),
    }
