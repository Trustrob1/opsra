-- GIVEAWAY-3: resend a lost winner link (stops people asking for a new one every minute). Safe to re-run.
alter table public.site_giveaway_entries add column if not exists link_sent_at timestamptz;
