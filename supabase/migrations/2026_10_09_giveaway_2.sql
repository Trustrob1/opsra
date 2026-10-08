-- GIVEAWAY-2: pay-by deadline, bigger-catalog pack. Safe to re-run.

-- 1) pay-by deadline
alter table public.site_giveaways add column if not exists pay_by_days integer not null default 3;
alter table public.site_giveaways drop constraint if exists site_giveaways_pay_by_days_check;
alter table public.site_giveaways add constraint site_giveaways_pay_by_days_check check (pay_by_days between 1 and 30);
alter table public.site_giveaway_entries add column if not exists preview_ready_at timestamptz;
alter table public.site_giveaway_entries add column if not exists deadline_reminder_at timestamptz;
alter table public.site_giveaway_entries add column if not exists void_reason text;

-- 2) bigger-catalog pack (pack size and price live in site_builder_settings.pricing.catalog_pack; defaults +30 items for 5000)
alter table public.sites add column if not exists extra_items integer not null default 0;
alter table public.site_orders drop constraint if exists site_orders_kind_check;
alter table public.site_orders add constraint site_orders_kind_check
  check (kind = any (array['initial','renewal','care_plan','edit_pack','premium_design','premium_redesign','builder_access','catalog_pack']::text[]));
