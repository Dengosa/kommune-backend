-- Run after 001_waitlist.sql and 002_pending_activations.sql

create table if not exists vault_entries (
    id uuid primary key,
    session_id text not null,
    actor text not null,
    action text not null,
    resource text not null,
    metadata jsonb not null default '{}'::jsonb,
    sha256 text not null,
    previous_sha256 text,
    created_at timestamptz not null default now()
);

create index if not exists vault_entries_session_idx on vault_entries (session_id, created_at);
