-- SITE-OPTIONS OPT-3: share several VERSIONS of one client's Premium site behind one link; the client picks one.
-- Additive and safe to re-run. Run in the Supabase SQL editor BEFORE deploying the OPT-3 code.
-- Two new tables only; nothing existing changes.

-- 1) One share = one site + the versions chosen for the client to compare. The token is the private link.
create table if not exists public.site_version_shares (
  id                uuid primary key default gen_random_uuid(),
  org_id            uuid not null references public.organisations(id),
  site_id           uuid not null references public.sites(id) on delete cascade,
  builder_id        uuid not null,
  client_name       text,
  token             text not null unique,
  status            text not null default 'open' check (status in ('open', 'chosen', 'closed', 'expired')),
  chosen_design_id  uuid,
  chosen_at         timestamptz,
  expires_at        timestamptz not null,
  created_by        text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists site_version_shares_org_builder_idx on public.site_version_shares (org_id, builder_id, status);
create index if not exists site_version_shares_site_idx on public.site_version_shares (site_id, status);
create index if not exists site_version_shares_due_idx on public.site_version_shares (status, expires_at);
alter table public.site_version_shares enable row level security;

-- 2) The versions included (max 5, enforced in code). Deleting a design version removes it from the share.
create table if not exists public.site_version_items (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organisations(id),
  share_id    uuid not null references public.site_version_shares(id) on delete cascade,
  design_id   uuid not null references public.site_designs(id) on delete cascade,
  label       text not null,
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now(),
  unique (share_id, design_id)
);
create index if not exists site_version_items_design_idx on public.site_version_items (design_id);
alter table public.site_version_items enable row level security;
