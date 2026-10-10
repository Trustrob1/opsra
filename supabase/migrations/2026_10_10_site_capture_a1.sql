-- SITE-ADDONS A1-1: lead capture from client sites (Capture tier).
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the A1-1 code.
-- Adds new tables and new NULLABLE columns only; nothing existing changes behaviour.

-- 1) Mark an organisation as a client workspace (holds one client's website leads; never a real customer account).
alter table public.organisations add column if not exists is_site_workspace boolean not null default false;

-- 2) The public identifier a site's form and WhatsApp links use. It is public by design (it sits in the page);
--    it never reveals an org or site id, can be rotated, and one site has one live key at a time.
create table if not exists public.site_keys (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null,
  site_id     uuid not null references public.sites(id) on delete cascade,
  key         text not null unique,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  rotated_at  timestamptz
);
create unique index if not exists site_keys_one_active_per_site on public.site_keys (site_id) where active;
alter table public.site_keys enable row level security;

-- 3) Which workspace holds a site's leads, and the hidden system user those leads are assigned to.
create table if not exists public.site_workspaces (
  site_id          uuid primary key references public.sites(id) on delete cascade,
  org_id           uuid not null,
  workspace_org_id uuid not null unique references public.organisations(id) on delete cascade,
  system_user_id   uuid not null,
  created_at       timestamptz not null default now()
);
alter table public.site_workspaces enable row level security;

-- 4) What happened on the site: form sends, rejected sends, WhatsApp clicks, the owner tapping "answer now".
create table if not exists public.site_lead_events (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null,
  site_id     uuid not null references public.sites(id) on delete cascade,
  key_id      uuid references public.site_keys(id) on delete set null,
  kind        text not null check (kind in ('wa_click', 'form_submit', 'form_rejected', 'answer_tap')),
  source      text,
  lead_id     uuid,
  ip_hash     text,
  created_at  timestamptz not null default now()
);
create index if not exists site_lead_events_site_idx on public.site_lead_events (site_id, created_at desc);
alter table public.site_lead_events enable row level security;

-- 5) Leads that came from a site: which site, where on it, consent, and the owner-alert bookkeeping.
alter table public.leads add column if not exists site_id uuid;
alter table public.leads add column if not exists source_detail text;
alter table public.leads add column if not exists consent_at timestamptz;
alter table public.leads add column if not exists consent_version text;
alter table public.leads add column if not exists answered_at timestamptz;
alter table public.leads add column if not exists alert_reminder_at timestamptz;
create index if not exists leads_site_idx on public.leads (site_id) where site_id is not null;
create index if not exists leads_alert_reminder_idx on public.leads (alert_reminder_at) where alert_reminder_at is not null;
