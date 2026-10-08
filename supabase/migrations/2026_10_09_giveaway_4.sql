-- GIVEAWAY-4: a campaign name (flier headline) and an optional closing time per giveaway. Safe to re-run.
alter table public.site_giveaways add column if not exists campaign_name text;
alter table public.site_giveaways add column if not exists ends_at timestamptz;
