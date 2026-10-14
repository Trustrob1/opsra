-- SITE-OPTIONS OPT-1: several design options per client, one link, the client picks.
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the OPT-1 code.
-- New tables + new columns with defaults only; existing sites, orders and forms behave exactly as before.

-- 1) A group of sites made for one client. The token is the private link (like a payment link or My-leads link).
create table if not exists public.site_option_sets (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null references public.organisations(id),
  builder_id      uuid not null,
  client_name     text,
  token           text not null unique,
  status          text not null default 'open' check (status in ('open', 'chosen', 'closed', 'expired')),
  chosen_site_id  uuid,
  chosen_at       timestamptz,
  release_after   timestamptz,          -- 14 days after the latest pick: unchosen options are cleaned up then (if not paid, the pick can still change before this)
  expires_at      timestamptz not null, -- never picked by this time: the sites go back to being ordinary sites
  created_by      text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists site_option_sets_org_builder_idx on public.site_option_sets (org_id, builder_id, status);
create index if not exists site_option_sets_due_idx on public.site_option_sets (status, expires_at);
alter table public.site_option_sets enable row level security;

-- 2) The sites in a set (max 5, enforced in code).
create table if not exists public.site_option_items (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organisations(id),
  set_id      uuid not null references public.site_option_sets(id) on delete cascade,
  site_id     uuid not null references public.sites(id) on delete cascade,
  label       text not null,
  sort_order  integer not null default 0,
  status      text not null default 'offered' check (status in ('offered', 'chosen', 'released')),
  created_at  timestamptz not null default now(),
  unique (set_id, site_id)
);
create index if not exists site_option_items_site_idx on public.site_option_items (site_id);
alter table public.site_option_items enable row level security;

-- 3) Marks on the site itself. option_offered = "still only an option": not counted in the builder's free-sites
--    limit and cannot be checked out. It turns false when the client picks it.
alter table public.sites add column if not exists option_set_id uuid;
alter table public.sites add column if not exists option_offered boolean not null default false;
create index if not exists sites_option_set_idx on public.sites (option_set_id) where option_set_id is not null;

-- 4) A brief-form link created for a set makes its new site an option (so it is not blocked by the free-sites limit).
alter table public.site_brief_forms add column if not exists option_set_id uuid;
