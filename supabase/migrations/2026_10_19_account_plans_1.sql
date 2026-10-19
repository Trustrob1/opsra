-- ACCOUNT-PLANS AP-1: account-level plans (Capture / Convert / Grow for a whole organisation).
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the AP-1 code.
-- Nothing here changes an existing business: organisations.plans_enforced defaults to false, so every business
-- behaves exactly as today until a superadmin switches it on for that business.

-- 1) The plan an organisation HAS: one tier row plus optional add-on rows (same shape as site_addons, keyed by org).
create table if not exists public.org_plans (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null references public.organisations(id) on delete cascade,
  kind             text not null check (kind in ('tier', 'addon')),
  key              text not null,
  status           text not null default 'pending'
                     check (status in ('pending', 'active', 'grace', 'paused', 'cancelled')),
  source           text not null default 'paid' check (source in ('paid', 'staff', 'grandfathered')),
  price_ngn        numeric not null default 0 check (price_ngn >= 0),
  paid_until       timestamptz,
  grace_until      timestamptz,
  next_reminder_at timestamptz,
  config           jsonb not null default '{}'::jsonb,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
-- One live tier per organisation (cancelled rows are history and may repeat).
create unique index if not exists org_plans_one_tier_per_org
  on public.org_plans (org_id) where kind = 'tier' and status <> 'cancelled';
create unique index if not exists org_plans_one_addon_key_per_org
  on public.org_plans (org_id, key) where kind = 'addon' and status <> 'cancelled';
create index if not exists org_plans_due_idx on public.org_plans (status, paid_until);

-- 2) Monthly usage against capped features (AI replies, bulk recipients). One row per organisation, cap and month.
create table if not exists public.org_usage_counters (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null references public.organisations(id) on delete cascade,
  cap_key       text not null,
  period_start  date not null,
  used          integer not null default 0 check (used >= 0),
  updated_at    timestamptz not null default now(),
  unique (org_id, cap_key, period_start)
);

-- 3) Audit trail of every change to a plan or to enforcement.
create table if not exists public.org_plan_events (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organisations(id) on delete cascade,
  actor       text not null,
  event       text not null,
  detail      jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists org_plan_events_org_idx on public.org_plan_events (org_id, created_at desc);

-- 4) The per-business switch. false = the business behaves as it always has.
alter table public.organisations add column if not exists plans_enforced boolean not null default false;

-- The backend uses the service role; row level security stays on so nothing is readable through the public API.
alter table public.org_plans enable row level security;
alter table public.org_usage_counters enable row level security;
alter table public.org_plan_events enable row level security;
