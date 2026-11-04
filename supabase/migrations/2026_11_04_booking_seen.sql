-- BOOKINGS-BADGE-1: per-user "last looked at Upcoming Bookings" marker, used for the new-bookings badge.
create table if not exists public.user_booking_seen (
  user_id      uuid primary key,
  org_id       uuid not null,
  last_seen_at timestamptz not null default now()
);
alter table public.user_booking_seen enable row level security;
