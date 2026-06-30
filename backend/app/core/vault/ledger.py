from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, asdict
from typing import Optional, List

from db.supabase_client import get_supabase


@dataclass(frozen=True)
class VaultEntry:
    """An append-only audit ledger entry.

    Each entry is hash-chained to the previous entry for the same session
    (previous_sha256), giving a tamper-evident trail of every agent action.
    """

    id: str
    session_id: str
    actor: str  # e.g. "nemo", "legal", "credit", "system"
    action: str  # e.g. "ROUTE", "RESPOND", "HANDOFF", "ESCALATE", "EMERGENCY_LOCK"
    resource: str  # e.g. "chat_turn", "ngo_escalation"
    metadata: dict
    sha256: str
    previous_sha256: Optional[str] = None


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_entry_hash(
    *,
    actor: str,
    action: str,
    resource: str,
    metadata: dict,
    previous_sha256: Optional[str],
) -> str:
    canonical = (
        f"actor={actor};action={action};resource={resource};"
        f"metadata={str(sorted(metadata.items()))};prev={previous_sha256 or ''}"
    ).encode("utf-8")
    return sha256_of_bytes(canonical)


def get_latest_hash(session_id: str) -> Optional[str]:
    """Fetch the most recent vault entry's hash for this session, to chain
    the next entry. Returns None if no entries exist yet (or on error,
    fails open so logging never blocks the main request)."""
    try:
        supabase = get_supabase()
        result = (
            supabase.table("vault_entries")
            .select("sha256")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["sha256"]
    except Exception:
        pass
    return None


def write_entry(
    *,
    session_id: str,
    actor: str,
    action: str,
    resource: str,
    metadata: dict,
) -> VaultEntry:
    """Create and persist a new hash-chained vault entry.

    Fails open: if Supabase is unreachable, the entry is still constructed
    and returned (so callers can append it to in-memory state), but
    persistence is best-effort and won't raise.
    """

    previous_sha256 = get_latest_hash(session_id)
    entry_id = str(uuid.uuid4())
    entry_hash = compute_entry_hash(
        actor=actor,
        action=action,
        resource=resource,
        metadata=metadata,
        previous_sha256=previous_sha256,
    )

    entry = VaultEntry(
        id=entry_id,
        session_id=session_id,
        actor=actor,
        action=action,
        resource=resource,
        metadata=metadata,
        sha256=entry_hash,
        previous_sha256=previous_sha256,
    )

    try:
        supabase = get_supabase()
        supabase.table("vault_entries").insert(
            {
                "id": entry.id,
                "session_id": entry.session_id,
                "actor": entry.actor,
                "action": entry.action,
                "resource": entry.resource,
                "metadata": entry.metadata,
                "sha256": entry.sha256,
                "previous_sha256": entry.previous_sha256,
            }
        ).execute()
    except Exception:
        # Persistence is best-effort; don't break the request flow.
        pass

    return entry


def get_session_ledger(session_id: str) -> List[dict]:
    """Return the full ordered audit trail for a session."""
    try:
        supabase = get_supabase()
        result = (
            supabase.table("vault_entries")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def entry_to_dict(entry: VaultEntry) -> dict:
    return asdict(entry)
