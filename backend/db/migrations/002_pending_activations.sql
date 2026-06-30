-- Run this in the Supabase SQL editor (after 001_waitlist.sql)

create table if not exists pending_activations (
    id uuid primary key default gen_random_uuid(),
    email text,
    whatsapp_number text,
    reference text not null unique,  -- shown to user, used to match Zapper payment
    status text not null default 'pending',  -- pending | confirmed | rejected
    created_at timestamptz not null default now(),
    confirmed_at timestamptz
);

create index if not exists pending_activations_status_idx on pending_activations (status);
create index if not exists pending_activations_reference_idx on pending_activations (reference);
