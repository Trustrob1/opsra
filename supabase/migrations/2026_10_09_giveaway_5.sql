-- GIVEAWAY-5: a winner who doesn't pay the giveaway fee in time keeps their site at the normal rate for a few more days,
-- and only then is it taken down. Safe to re-run.
alter table public.site_giveaways add column if not exists full_price_ngn  integer not null default 65000 check (full_price_ngn >= 1000);
alter table public.site_giveaways add column if not exists full_price_days integer not null default 4 check (full_price_days between 1 and 30);

alter table public.site_giveaway_entries add column if not exists lapsed_at timestamptz;
alter table public.site_giveaway_entries add column if not exists takedown_reminder_at timestamptz;

-- a new state: 'lapsed' = the slot was given back, the site and the winner link stay until the takedown
alter table public.site_giveaway_entries drop constraint if exists site_giveaway_entries_status_check;
alter table public.site_giveaway_entries add constraint site_giveaway_entries_status_check
  check (status in ('opened','winner','lapsed','voided'));
