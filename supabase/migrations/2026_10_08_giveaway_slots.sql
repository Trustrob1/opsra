-- GIVEAWAY-1: group giveaways with a slot counter (first N complete submissions win)
create table if not exists public.site_giveaways (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organisations(id) on delete cascade,
  partner_id   uuid not null references public.site_partners(id) on delete cascade,
  title        text not null,
  total_slots  integer not null default 5 check (total_slots > 0 and total_slots <= 100),
  fee_ngn      integer not null default 24500 check (fee_ngn >= 1000),     -- domain + hosting fee the winner pays after the preview
  renewal_ngn  integer not null default 25000 check (renewal_ngn >= 1000),  -- yearly renewal from year two (shown in the terms)
  slug         text not null,
  status       text not null default 'active' check (status in ('active','closed')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create unique index if not exists site_giveaways_slug_uq on public.site_giveaways (slug);
create index if not exists site_giveaways_org_idx on public.site_giveaways (org_id, created_at desc);

create table if not exists public.site_giveaway_entries (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organisations(id) on delete cascade,
  giveaway_id  uuid not null references public.site_giveaways(id) on delete cascade,
  form_id      uuid references public.site_brief_forms(id) on delete set null,
  site_id      uuid references public.sites(id) on delete set null,
  position     integer,
  status       text not null default 'opened' check (status in ('opened','winner','voided')),
  contact_name  text,
  contact_phone text,            -- digits only, one spelling per number
  contact_email text,
  winner_token_hash text,        -- sha256 of the private /w/{token} link; the raw token is never stored
  consent_at   timestamptz,
  claimed_at   timestamptz,
  created_at   timestamptz not null default now(),
  constraint site_giveaway_entries_pos_uq unique (giveaway_id, position)
);
create unique index if not exists site_giveaway_entries_form_uq on public.site_giveaway_entries (form_id);
create index if not exists site_giveaway_entries_gw_idx on public.site_giveaway_entries (giveaway_id, status);
alter table public.site_giveaways enable row level security;
alter table public.site_giveaway_entries enable row level security;
-- one slot per WhatsApp number per giveaway (a voided slot frees the number)
create unique index if not exists site_giveaway_entries_phone_uq on public.site_giveaway_entries (giveaway_id, contact_phone) where status = 'winner';
create unique index if not exists site_giveaway_entries_token_uq on public.site_giveaway_entries (winner_token_hash) where winner_token_hash is not null;

-- edit counting: items changed so far inside the current 30-minute editing session (one edit covers up to 10 items)
alter table public.site_care_plans add column if not exists session_items_changed integer not null default 0;
