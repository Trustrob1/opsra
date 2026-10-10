-- SITE-ADDONS A0-1: tiers and add-ons per site (entitlements), plus monthly usage counters.
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the A0-1 code.
-- Nothing here changes existing tables, so it cannot affect sites, orders or builders that exist today.
-- (The 'site_addon' order kind is added later, with the A0-2 billing migration, from the live constraint list.)

-- 1) What each site has bought or been granted: one tier row (capture / convert / grow) plus optional add-ons.
create table if not exists public.site_addons (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null,
  site_id          uuid not null references public.sites(id) on delete cascade,
  kind             text not null check (kind in ('tier', 'addon')),
  key              text not null,
  status           text not null default 'pending'
                     check (status in ('pending', 'active', 'grace', 'paused', 'cancelled')),
  source           text not null default 'paid' check (source in ('paid', 'staff')),
  billing_mode     text not null default 'link' check (billing_mode in ('link', 'auto')),
  price_ngn        numeric not null default 0 check (price_ngn >= 0),
  paid_until       timestamptz,
  grace_until      timestamptz,
  next_reminder_at timestamptz,
  payer_name       text,
  payer_phone      text,
  payer_email      text,
  payer_token_hash text,
  config           jsonb not null default '{}'::jsonb,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- One live tier per site (cancelled rows are history and may repeat).
create unique index if not exists site_addons_one_tier_per_site
  on public.site_addons (site_id) where kind = 'tier' and status <> 'cancelled';
-- One live row per add-on key per site.
create unique index if not exists site_addons_one_addon_key_per_site
  on public.site_addons (site_id, key) where kind = 'addon' and status <> 'cancelled';
create index if not exists site_addons_org_site_idx on public.site_addons (org_id, site_id);
create index if not exists site_addons_due_idx on public.site_addons (status, paid_until);
create unique index if not exists site_addons_payer_token_uq
  on public.site_addons (payer_token_hash) where payer_token_hash is not null;

-- 2) Monthly usage against capped features (AI messages, bulk recipients). One row per site, cap and month.
create table if not exists public.site_usage_counters (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null,
  site_id       uuid not null references public.sites(id) on delete cascade,
  cap_key       text not null,
  period_start  date not null,
  used          integer not null default 0 check (used >= 0),
  updated_at    timestamptz not null default now(),
  unique (site_id, cap_key, period_start)
);
create index if not exists site_usage_counters_org_idx on public.site_usage_counters (org_id, site_id);

-- The backend uses the service role; row level security stays on so nothing is readable through the public API.
alter table public.site_addons enable row level security;
alter table public.site_usage_counters enable row level security;
