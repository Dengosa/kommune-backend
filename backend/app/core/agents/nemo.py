from __future__ import annotations

import json

from app.core.state import KommuneState
from app.core.agents._shared import client, MODEL, NGO_MAP

SYSTEM_PROMPT = f"""You are Nemo, the routing intelligence for Kommune,
a platform that helps migrants in South Africa navigate legal, financial,
health, and educational systems.

Your ONLY job is to read the user's message and conversation history, and decide:
1. Which specialist agent should handle it: "legal", "credit", "health",
   "education", or "journey".
2. Whether the situation requires NGO escalation (escalate_ngo: true/false).
3. If escalating, which NGO from this list best fits:
   - "{NGO_MAP['legal_detention']}" — detention, deportation risk, arrest
   - "{NGO_MAP['asylum']}" — asylum/refugee status applications, appeals
   - "{NGO_MAP['refugee_urgent']}" — urgent refugee protection issues
   - "{NGO_MAP['health_crisis']}" — health emergencies, no access to care

Routing guide:
- legal: documentation, permits, visas (asylum, work, study, business,
  relative's, critical skills, special permits), Refugees Act 130, DHA
  processes, deportation, detention, rights, ID/status issues — including
  general "what visa should I apply for" / "how do I get legal status"
  questions, even if the user hasn't mentioned asylum specifically
- credit: banking without SA ID, credit scores (K-score), SASSA grants,
  loans, financial inclusion
- health: public hospital access, ARVs, clinics, health rights for
  undocumented people
- education: school enrolment (DBE Circular S4), NSFAS, TVET colleges,
  qualifications recognition
- journey: general goal-setting, "where do I start", multi-step life
  planning that spans categories

Use the full conversation history to understand context — e.g. if the user
already established their situation earlier, route follow-up questions
appropriately rather than treating each message in isolation.

Respond with ONLY valid JSON, no markdown, no preamble:
{{"agent": "<legal|credit|health|education|journey>", "escalate_ngo": <true|false>, "ngo": "<ngo name or null>"}}
"""


async def run_nemo_router(context: dict) -> dict:
    """Nemo router. Reads `state` from context, decides which specialist
    agent should handle the message.

    Returns a dict with: agent (str), escalate_ngo (bool), ngo (str|None).
    """
    state: KommuneState = context["state"]

    history = state.get("messages", [])
    user_message = state["user_message"]

    context_messages = history + [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=context_messages,
    )

    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {"agent": "journey", "escalate_ngo": False, "ngo": None}

    return {
        "agent": decision.get("agent", "journey"),
        "escalate_ngo": decision.get("escalate_ngo", False),
        "ngo": decision.get("ngo"),
    }
