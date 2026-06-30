from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.state import new_state
from app.core.agent_graph import run_agent_graph
from app.core.preview_limit import is_activated

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    user_id: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    """
    SSE streaming endpoint. Runs the Kommune agent graph (Nemo router ->
    specialist agent(s) with inter-agent handoffs, emergency-lock circuit
    breaker, and Vault-audited actions), then streams the result back.

    Conversation memory: the graph is checkpointed per `thread_id`
    (session_id, falling back to user_id, falling back to "anonymous").

    Event sequence:
      event: routing   -> {"agent", "escalate_ngo", "ngo", "agents_involved", "preview_mode"}
      event: emergency -> {"event_id", "reason", "checklist", "ngo"}  (only if locked)
      event: message   -> {"delta": "<chunk of text>"}   (repeated)
      event: done      -> {}

    Preview mode: unactivated users (is_activated() == False for their
    user_id) get `preview_mode=True` on state. Agents still give full
    informational answers, but action tools (send_email,
    schedule_appointment) are disabled — see app/core/agents/legal.py and
    app/core/tools/registry.py. The `routing` event includes
    `preview_mode` so the frontend can show an "Activate to unlock actions"
    prompt without blocking the conversation.
    """
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    thread_id = payload.session_id or payload.user_id or "anonymous"

    activated = is_activated(payload.user_id)

    state = new_state(session_id=thread_id, user_id=payload.user_id or "anonymous")
    state["messages"] = history
    state["user_message"] = payload.message
    state["preview_mode"] = not activated

    async def event_stream():
        result = await run_agent_graph(state)

        if result.status == "EMERGENCY_LOCKED":
            payload_data = result.payload
            yield f"event: emergency\ndata: {json.dumps({k: v for k, v in payload_data.items() if k != 'response'})}\n\n"
            response_text = payload_data.get("response", "")
        else:
            routing = {
                "agent": result.payload.get("agent"),
                "escalate_ngo": result.payload.get("escalate_ngo", False),
                "ngo": result.payload.get("ngo"),
                "agents_involved": result.payload.get("agents_involved", []),
                "priority_flagged": result.payload.get("state", {}).get("priority_flagged", False),
                "priority_reason": result.payload.get("state", {}).get("priority_reason"),
                "preview_mode": state.get("preview_mode", False),
            }
            yield f"event: routing\ndata: {json.dumps(routing)}\n\n"
            response_text = result.payload.get("response", "")

        chunk_size = 20
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i : i + chunk_size]
            yield f"event: message\ndata: {json.dumps({'delta': chunk})}\n\n"

        yield f"event: done\ndata: {{}}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
