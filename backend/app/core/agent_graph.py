from __future__ import annotations

import time
from dataclasses import dataclass

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.core.state import KommuneState, now_ts
from app.core.vault import ledger
from app.core.agents.nemo import run_nemo_router
from app.core.agents.legal import run_legal_agent
from app.core.agents.credit import run_credit_agent
from app.core.agents.health import run_health_agent
from app.core.agents.opportunity import run_opportunity_agent
from app.core.agents.journey import run_journey_agent
from app.core.agents._shared import AGENT_DISPLAY_NAMES, VALID_AGENTS

SPECIALIST_AGENTS = ["legal", "credit", "health", "education", "journey"]

SPECIALIST_RUNNERS = {
    "legal": run_legal_agent,
    "credit": run_credit_agent,
    "health": run_health_agent,
    "education": run_opportunity_agent,
    "journey": run_journey_agent,
}


@dataclass
class AgentGraphResult:
    status: str
    payload: dict


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
async def _emergency_check_node(state: KommuneState) -> KommuneState:
    """Entry node. If emergency was already triggered (e.g. by a previous
    turn locking this session), short-circuit immediately."""
    if state.get("emergency_triggered"):
        return state
    return state


async def _nemo_node(state: KommuneState) -> KommuneState:
    decision = await run_nemo_router({"state": state})

    ledger.write_entry(
        session_id=state["session_id"],
        actor="nemo",
        action="ROUTE",
        resource="chat_turn",
        metadata={"agent": decision["agent"], "escalate_ngo": decision["escalate_ngo"]},
    )

    return {
        **state,
        "agent": decision["agent"],
        "next_agent": decision["agent"],
        "escalate_ngo": decision["escalate_ngo"],
        "ngo": decision["ngo"],
        "visited_agents": [],
        "exchanges": [],
        "handoff_to": None,
    }


def _make_specialist_node(agent_name: str):
    runner = SPECIALIST_RUNNERS[agent_name]

    async def node(state: KommuneState) -> KommuneState:
        result = await runner({"state": state})

        # Emergency lock: a specialist (legal/health) flagged an active
        # emergency. Short-circuit the rest of the graph.
        emergency_reason = result.get("emergency_reason")
        if emergency_reason:
            event_id = f"emrg-{int(time.time())}"
            ledger.write_entry(
                session_id=state["session_id"],
                actor=agent_name,
                action="EMERGENCY_LOCK",
                resource="session",
                metadata={"reason": emergency_reason, "event_id": event_id},
            )

            rights_checklist = _build_rights_checklist(agent_name, result.get("ngo"))

            return {
                **state,
                "emergency_triggered": True,
                "emergency_reason": emergency_reason,
                "emergency_event_id": event_id,
                "emergency_locked_at": now_ts(),
                "gate_status": "LOCKED",
                "escalate_ngo": True,
                "ngo": result.get("ngo"),
                "response": result["response"],
                "agent": agent_name,
                "artifacts": {
                    **state.get("artifacts", {}),
                    "rights_checklist": rights_checklist,
                },
            }

        exchanges = state.get("exchanges", []) + [
            {"agent": agent_name, "response": result["response"]}
        ]

        if len(exchanges) == 1:
            combined_response = result["response"]
        else:
            combined_response = "\n\n---\n\n".join(
                f"**{AGENT_DISPLAY_NAMES.get(ex['agent'], ex['agent'])}:** {ex['response']}"
                for ex in exchanges
            )

        # Priority case flag (e.g. expired permit with stuck renewal,
        # overstayed after final asylum rejection). Does not lock the
        # session, but logs for proactive NGO follow-up.
        priority_reason = result.get("priority_reason")
        if priority_reason:
            ledger.write_entry(
                session_id=state["session_id"],
                actor=agent_name,
                action="PRIORITY_FLAG",
                resource="session",
                metadata={"reason": priority_reason, "ngo": result.get("ngo")},
            )

        ledger.write_entry(
            session_id=state["session_id"],
            actor=agent_name,
            action="RESPOND",
            resource="chat_turn",
            metadata={
                "handoff_to": result.get("handoff_to"),
                "response_length": len(result["response"]),
            },
        )

        # Log any executed actions (emails sent, appointments scheduled)
        for call in result.get("tool_calls", []):
            ledger.write_entry(
                session_id=state["session_id"],
                actor=agent_name,
                action=f"TOOL:{call['tool'].upper()}",
                resource=call["tool"],
                metadata={
                    "input": {k: v for k, v in call["input"].items() if k != "body"},
                    "status": call["result"].get("status"),
                },
            )

        if result.get("handoff_to"):
            ledger.write_entry(
                session_id=state["session_id"],
                actor=agent_name,
                action="HANDOFF",
                resource="chat_turn",
                metadata={"to": result["handoff_to"]},
            )

        return {
            **state,
            "visited_agents": result["visited_agents"],
            "exchanges": exchanges,
            "handoff_to": result.get("handoff_to"),
            "response": combined_response,
            "agent": agent_name if not result.get("handoff_to") else state.get("agent"),
            "escalate_ngo": result.get("escalate_ngo", state.get("escalate_ngo", False)),
            "ngo": result.get("ngo", state.get("ngo")),
            "priority_flagged": priority_reason is not None or state.get("priority_flagged", False),
            "priority_reason": priority_reason or state.get("priority_reason"),
        }

    return node


def _build_rights_checklist(agent_name: str, ngo: str | None) -> dict:
    """Construct a short rights/next-steps checklist returned immediately
    when an emergency lock is triggered."""
    base = {
        "title": "Immediate rights & next steps",
        "items": [
            "You have the right to remain silent and to request a lawyer.",
            "You have the right to contact a person of your choice (family, NGO).",
            "Do not sign any documents you do not understand.",
            f"Kommune is escalating this to {ngo or 'a partner NGO'} now.",
        ],
        "agent": agent_name,
        "ngo": ngo,
    }
    return base


async def _finalize_node(state: KommuneState) -> KommuneState:
    """Append this turn's user message and final response to `messages`
    so checkpointed history accumulates across turns."""
    history = state.get("messages", [])
    updated = history + [
        {"role": "user", "content": state["user_message"]},
        {"role": "assistant", "content": state.get("response", "")},
    ]
    return {**state, "messages": updated, "updated_at": now_ts()}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------
def _route_entry(state: KommuneState) -> str:
    if state.get("emergency_triggered"):
        return "finalize"
    return "nemo"


def _route_from_nemo(state: KommuneState) -> str:
    return state.get("agent", "journey")


def _route_handoff(state: KommuneState) -> str:
    if state.get("emergency_triggered"):
        return "finalize"
    handoff = state.get("handoff_to")
    if handoff and handoff in VALID_AGENTS:
        return handoff
    return "finalize"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------
def build_graph(checkpointer=None):
    graph = StateGraph(KommuneState)

    graph.add_node("entry", _emergency_check_node)
    graph.add_node("nemo", _nemo_node)
    for name in SPECIALIST_AGENTS:
        graph.add_node(name, _make_specialist_node(name))
    graph.add_node("finalize", _finalize_node)

    graph.set_entry_point("entry")

    graph.add_conditional_edges(
        "entry",
        _route_entry,
        {"nemo": "nemo", "finalize": "finalize"},
    )

    graph.add_conditional_edges(
        "nemo",
        _route_from_nemo,
        {agent: agent for agent in SPECIALIST_AGENTS},
    )

    for agent in SPECIALIST_AGENTS:
        graph.add_conditional_edges(
            agent,
            _route_handoff,
            {**{a: a for a in SPECIALIST_AGENTS}, "finalize": "finalize"},
        )

    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


_checkpointer = MemorySaver()
kommune_graph = build_graph(checkpointer=_checkpointer)


async def run_agent_graph(state: KommuneState) -> AgentGraphResult:
    """Run the Kommune multi-agent routing workflow.

    Thin async wrapper around the compiled LangGraph, matching the
    original skeleton's interface (AgentGraphResult with status/payload)
    while delegating to the real Nemo + specialist + handoff + emergency
    + Vault-audited graph.
    """
    thread_id = state.get("session_id", "anonymous")

    result = await kommune_graph.ainvoke(
        state,
        config={"configurable": {"thread_id": thread_id}},
    )

    if result.get("emergency_triggered"):
        return AgentGraphResult(
            status="EMERGENCY_LOCKED",
            payload={
                "locked": True,
                "event_id": result.get("emergency_event_id"),
                "reason": result.get("emergency_reason"),
                "response": result.get("response"),
                "checklist": result.get("artifacts", {}).get("rights_checklist"),
                "ngo": result.get("ngo"),
            },
        )

    return AgentGraphResult(
        status="OK",
        payload={
            "agent": result.get("agent"),
            "response": result.get("response"),
            "escalate_ngo": result.get("escalate_ngo", False),
            "ngo": result.get("ngo"),
            "agents_involved": result.get("visited_agents", []),
            "state": result,
        },
    )
