from __future__ import annotations

from db.supabase_client import get_supabase


def is_activated(user_id: str | None) -> bool:
    """Check if a user (by email, used as user_id) has an activated
    account. Fails open (returns True) on DB error so a transient issue
    doesn't lock out paying users from action tools.

    Used by /chat/stream to set `preview_mode` on session state:
    - Activated users: preview_mode=False, full access to action tools
      (send_email, schedule_appointment)
    - Unactivated users: preview_mode=True, agents give full informational
      answers via web search, but action tools are disabled (see
      app/core/tools/registry.py get_tools_for_agent)
    """
    if not user_id:
        return False
    try:
        supabase = get_supabase()
        result = (
            supabase.table("users")
            .select("activated_at")
            .eq("email", user_id)
            .execute()
        )
        if result.data and result.data[0].get("activated_at"):
            return True
    except Exception:
        return True
    return False
