from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, TypedDict

AgentName = Literal["legal", "credit", "health", "education", "journey"]


class AgentExchange(TypedDict):
    agent: AgentName
    response: str


class KommuneState(TypedDict, total=False):
    """Shared state schema for the Kommune multi-agent LangGraph workflow.

    This combines the original production-oriented schema (identity,
    gatekeeper/access control, emergency protocol, Vault audit trail)
    with the fields needed by the working Nemo router + specialist
    agent graph (routing, inter-agent handoffs, conversation memory).
    """

    # Identity / correlation
    session_id: str
    user_id: str  # phone number, email, or internal user id

    # Gatekeeper / access control
    payment_status: bool
    gate_status: Literal["UNVERIFIED", "PENDING", "ACTIVE", "LOCKED"]

    # True if this user is unactivated and within their free preview -
    # agents give full informational answers but action tools (send_email,
    # schedule_appointment) are disabled. Set by chat.py before invoking
    # the graph.
    preview_mode: bool

    # Emergency protocol — circuit breaker for detention/crisis situations.
    # When emergency_triggered=True, the graph short-circuits: it skips
    # normal agent routing/handoffs and returns a rights checklist +
    # NGO escalation immediately.
    emergency_triggered: bool
    emergency_reason: Optional[str]
    emergency_event_id: Optional[str]
    emergency_metadata: Optional[Dict[str, Any]]
    emergency_locked_at: Optional[float]

    # Priority case flag — does NOT lock the session, but flags the case
    # for proactive NGO referral (e.g. expired permits with stuck renewals,
    # overstayed after final asylum rejection).
    priority_flagged: bool
    priority_reason: Optional[str]

    # Conversation
    messages: List[dict]  # [{"role": "user"|"assistant", "content": str}]
    user_message: str

    # Agent routing / orchestration (Nemo's decision)
    agent: Optional[AgentName]
    next_agent: Optional[str]
    escalate_ngo: bool
    ngo: Optional[str]

    # Inter-agent handoff
    handoff_to: Optional[AgentName]
    visited_agents: List[AgentName]
    exchanges: List[AgentExchange]

    # Output
    response: str

    # Progress & results
    progress: Dict[str, Any]

    # Audit/Vault integration (immutable ledger).
    # Each agent action is translated into Vault entries with SHA-256
    # hashes (see app/core/vault/ledger.py).
    vault_entries: List[Dict[str, Any]]

    # Accumulated agent output for downstream UI/API responses
    artifacts: Dict[str, Any]

    # Housekeeping
    created_at: float
    updated_at: float
    locale: Optional[str]


def now_ts() -> float:
    return time.time()


def new_state(*, session_id: str, user_id: str) -> KommuneState:
    """Create a minimal initial state instance."""

    t = now_ts()
    return {
        "session_id": session_id,
        "user_id": user_id,
        "payment_status": False,
        "gate_status": "UNVERIFIED",
        "preview_mode": False,
        "emergency_triggered": False,
        "emergency_reason": None,
        "emergency_event_id": None,
        "emergency_metadata": None,
        "emergency_locked_at": None,
        "priority_flagged": False,
        "priority_reason": None,
        "messages": [],
        "agent": None,
        "next_agent": "router",
        "escalate_ngo": False,
        "ngo": None,
        "handoff_to": None,
        "visited_agents": [],
        "exchanges": [],
        "response": "",
        "progress": {"phase": "INIT", "steps": []},
        "vault_entries": [],
        "artifacts": {},
        "created_at": t,
        "updated_at": t,
        "locale": None,
    }
