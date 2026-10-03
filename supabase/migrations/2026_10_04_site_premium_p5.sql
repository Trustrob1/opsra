-- SITE-PREMIUM P5: two new order kinds for the Premium design fee and a paid extra new design.
-- Run once in the Supabase SQL editor. Safe to run twice.
ALTER TABLE public.site_orders DROP CONSTRAINT IF EXISTS site_orders_kind_check;
ALTER TABLE public.site_orders ADD CONSTRAINT site_orders_kind_check
  CHECK (kind::text = ANY (ARRAY['initial','renewal','care_plan','edit_pack','premium_design','premium_redesign']::text[]));
