-- SITE-ACCESS-1 - builder access (3 free sites, then a monthly subscription).
-- Additive and safe to re-run. Run in Supabase BEFORE deploying the SITE-ACCESS-1 code.
-- 1) A builder subscription order belongs to a builder, not to a site, so site_orders.site_id may be empty.
-- 2) The order kind check gains 'builder_access'.

ALTER TABLE site_orders ALTER COLUMN site_id DROP NOT NULL;

ALTER TABLE site_orders DROP CONSTRAINT IF EXISTS site_orders_kind_check;
ALTER TABLE site_orders ADD CONSTRAINT site_orders_kind_check
  CHECK (kind = ANY (ARRAY['initial'::text, 'renewal'::text, 'care_plan'::text, 'edit_pack'::text,
                           'premium_design'::text, 'premium_redesign'::text, 'builder_access'::text]));
