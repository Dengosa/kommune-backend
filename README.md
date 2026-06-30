# Kommune Backend (Rebuilt)

Full rebuild merging the working Nemo/handoff/memory agent system with the
`/app/core/` architecture, now fully implemented (no stubs).

## Structure
```
backend/
  app/
    main.py                  # FastAPI entrypoint (create_app)
    core/
      config.py              # env-driven settings
      state.py               # KommuneState schema (gate_status, emergency, vault, etc.)
      agent_graph.py          # LangGraph orchestration: Nemo -> specialists,
                               #   handoffs, emergency-lock, Vault audit logging
      agents/
        nemo.py               # router
        legal.py              # Lex — + emergency detection (detention/deportation)
        credit.py             # Rex
        health.py             # Vita — + emergency detection (health crisis)
        opportunity.py        # education agent
        journey.py            # Journey Engine
        _shared.py            # Anthropic client, handoff/emergency tag parsing
      security/
        cors.py               # env-driven CORS (KOMMUNE_CORS_ALLOW_ORIGINS or FRONTEND_URL)
      vault/
        ledger.py             # hash-chained audit ledger, persisted to Supabase
    api/v1/
      api.py                  # router registration
      endpoints/
        chat.py               # POST /chat/stream (SSE)
        waitlist.py           # POST /waitlist, GET /waitlist/count
        activation.py         # Zapper QR manual activation flow
        vault.py              # GET /vault/{session_id}/ledger
  db/
    supabase_client.py
    migrations/
      001_waitlist.sql
      002_pending_activations.sql
      003_vault_entries.sql    # NEW — run this too
  notifications/
    resend_client.py
  requirements.txt
  Dockerfile                  # CMD: uvicorn app.main:app
  fly.toml
  .env.example
```

## New features vs previous version

### 1. Emergency lock (circuit breaker)
Lex and Vita can detect active emergencies (detention, imminent deportation,
health crisis with no care access) via an `[[EMERGENCY: reason]]` tag in
their response. When triggered:
- The graph short-circuits — skips further handoffs
- `gate_status` becomes `LOCKED`
- Returns a `rights_checklist` (basic rights + "we're escalating to <NGO>")
- Logs an `EMERGENCY_LOCK` entry to the Vault

Chat stream sends an `event: emergency` SSE event instead of `event: routing`
when this happens.

### 2. Vault audit ledger
Every Nemo routing decision, agent response, and handoff is written to
`vault_entries` (Supabase) as a SHA-256 hash-chained entry — tamper-evident
audit trail per session. View via:
```
GET /vault/{session_id}/ledger
```

### 3. Unified state schema
`app/core/state.py` now includes `gate_status` (UNVERIFIED/PENDING/ACTIVE/LOCKED)
— ready to wire to the activation flow (when a user's `payment_status`
becomes true, set `gate_status: ACTIVE`).

## Setup
1. Run all 3 migrations in Supabase SQL editor (001, 002, 003)
2. Set Fly secrets: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   `RESEND_API_KEY`, `FRONTEND_URL`, `ADMIN_SECRET`, `ZAPPER_QR_URL`
3. Deploy: `fly deploy` (Dockerfile already points to `app.main:app`)

## Still TODO
- Wire `gate_status`/`payment_status` from the activation flow into the
  chat graph (e.g. gate `/chat/stream` behind `gate_status == "ACTIVE"`)
- WhatsApp webhook (Meta Cloud API) — Priority 4 from build doc
- Persist `vault_entries` with proper RLS policies once auth is added
