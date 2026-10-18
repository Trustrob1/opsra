-- WEBCHAT-1 + WEBCHAT-2 — Opsra's own chat page, and the WhatsApp redirect to it.
-- Additive and idempotent: safe to run twice. Nothing changes for any org until
-- organisations.webchat_config.enabled is set true for that org (default: not set).
-- Service-role only (RLS on, no policies), like the credit tables.

-- ── The public chat key (the part of the link: /c/{key}) ──────────────────
create table if not exists webchat_keys (
    key          text primary key,
    org_id       uuid not null references organisations(id) on delete cascade,
    active       boolean not null default true,
    created_at   timestamptz not null default now()
);
create unique index if not exists webchat_keys_one_active_per_org
    on webchat_keys (org_id) where active;

-- ── One row per visitor chat ──────────────────────────────────────────────
create table if not exists webchat_sessions (
    id                 uuid primary key default gen_random_uuid(),
    org_id             uuid not null references organisations(id) on delete cascade,
    token_hash         text not null unique,          -- sha256 of the session token; the token is never stored
    handoff_hash       text unique,                   -- sha256 of a one-time WhatsApp hand-off token
    handoff_expires_at timestamptz,
    handoff_used_at    timestamptz,
    lead_id            uuid references leads(id) on delete set null,
    contact_name       text,
    contact_phone      text,
    phone_verified     boolean not null default false, -- true only when the number came from WhatsApp itself
    contact_email      text,
    consent_at         timestamptz,
    consent_version    text,
    source             text,                          -- instagram | qr | site | whatsapp | link
    source_detail      text,
    history            jsonb not null default '[]'::jsonb,  -- messages before a lead exists
    state              jsonb not null default '{}'::jsonb,  -- where the visitor is in the scripted flow
    status             text not null default 'active' check (status in ('active','closed','expired')),
    ip_hash            text,
    turn_count         integer not null default 0,
    last_activity_at   timestamptz not null default now(),
    expires_at         timestamptz not null default (now() + interval '30 days'),
    created_at         timestamptz not null default now()
);
create index if not exists webchat_sessions_org_idx on webchat_sessions (org_id, last_activity_at desc);
create index if not exists webchat_sessions_lead_idx on webchat_sessions (lead_id) where lead_id is not null;
create index if not exists webchat_sessions_expiry_idx on webchat_sessions (expires_at) where status = 'active';

-- ── Funnel counts: visit → started → contact → booked ─────────────────────
create table if not exists webchat_events (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references organisations(id) on delete cascade,
    session_id  uuid references webchat_sessions(id) on delete set null,
    kind        text not null check (kind in ('visit','started','contact','booked','handoff_sent','redirect_sent')),
    source      text,
    created_at  timestamptz not null default now()
);
create index if not exists webchat_events_org_idx on webchat_events (org_id, created_at desc);

-- ── WhatsApp redirect: at most one automatic reply per phone per 24 h ─────
create table if not exists webchat_redirects (
    org_id       uuid not null references organisations(id) on delete cascade,
    phone        text not null,
    last_sent_at timestamptz not null default now(),
    sent_count   integer not null default 1,
    last_notified_at timestamptz,
    primary key (org_id, phone)
);

-- ── Org settings (greeting, menu, answers, redirect text; enabled defaults off) ─
alter table organisations add column if not exists webchat_config jsonb not null default '{}'::jsonb;

-- ── Messages: new channel + link to the session ───────────────────────────
alter table whatsapp_messages add column if not exists webchat_session_id uuid
    references webchat_sessions(id) on delete set null;
alter table whatsapp_messages drop constraint if exists whatsapp_messages_channel_check;
alter table whatsapp_messages add constraint whatsapp_messages_channel_check
    check (channel = any (array['whatsapp'::text, 'instagram'::text, 'messenger'::text, 'webchat'::text]));
create index if not exists whatsapp_messages_webchat_idx
    on whatsapp_messages (webchat_session_id, created_at) where webchat_session_id is not null;

-- ── New number mode for the WhatsApp redirect ─────────────────────────────
alter table whatsapp_numbers drop constraint if exists whatsapp_numbers_wa_sales_mode_check;
alter table whatsapp_numbers add constraint whatsapp_numbers_wa_sales_mode_check
    check ((wa_sales_mode)::text = any (array[
        'human'::varchar, 'bot'::varchar, 'ai_agent'::varchar, 'event_funnel'::varchar,
        'site_builder'::varchar, 'webchat_redirect'::varchar
    ]::text[]));

-- ── RLS: service role only ────────────────────────────────────────────────
alter table webchat_keys      enable row level security;
alter table webchat_sessions  enable row level security;
alter table webchat_events    enable row level security;
alter table webchat_redirects enable row level security;
