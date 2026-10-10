-- SITE-ADDONS A0-2: a new order kind for tier / add-on payments.
-- Safe to re-run. Run in the Supabase SQL editor BEFORE deploying the A0-2 code.
-- The list below is the LIVE list read from Supabase on 10 Oct 2026 (8 kinds) plus 'site_addon'.
-- If you add another kind in a later migration, start from this list so none is dropped.

alter table public.site_orders drop constraint if exists site_orders_kind_check;
alter table public.site_orders add constraint site_orders_kind_check
  check (kind::text = any (array['initial','renewal','care_plan','edit_pack','premium_design','premium_redesign','builder_access','catalog_pack','site_addon']::text[]));
