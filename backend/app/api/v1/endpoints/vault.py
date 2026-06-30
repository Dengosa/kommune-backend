from __future__ import annotations

from fastapi import APIRouter

from app.core.vault import ledger

router = APIRouter()


@router.get("/vault/{session_id}/ledger")
def get_ledger(session_id: str):
    """Return the immutable, hash-chained audit trail for a session —
    every routing decision, agent response, handoff, and escalation."""
    entries = ledger.get_session_ledger(session_id)
    return {"session_id": session_id, "entries": entries}
