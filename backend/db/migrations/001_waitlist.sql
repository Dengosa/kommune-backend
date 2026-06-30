-- Run this in the Supabase SQL editor

create table if not exists waitlist (
    id uuid primary key default gen_random_uuid(),
    email text not null unique,
    name text,
    city text,
    source text,
    created_at timestamptz not null default now()
);

create index if not exists waitlist_created_at_idx on waitlist (created_at);

-- Separate table for activated (paying) users, used in Priority 3
create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    email text not null unique,
    name text,
    activated_at timestamptz,
    payment_reference text,
    created_at timestamptz not null default now()
);
