-- SITE-DISCOUNT — discount codes for site-hosting orders (initial orders only).
-- Additive and idempotent. Run BEFORE deploying the SITE-DISCOUNT code.
-- A code takes a percentage or a fixed naira amount off the WHOLE order total.
-- Uses are counted from PAID orders (site_discount_redemptions), not from abandoned checkouts.

CREATE TABLE IF NOT EXISTS site_discount_codes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL,
  code            text NOT NULL,                       -- stored upper-case
  kind            text NOT NULL CHECK (kind IN ('percent', 'fixed')),
  value           numeric(12,2) NOT NULL CHECK (value > 0),
  note            text,
  active          boolean NOT NULL DEFAULT true,
  expires_at      timestamptz,
  max_uses        integer CHECK (max_uses IS NULL OR max_uses > 0),
  one_per_builder boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT site_discount_percent_range CHECK (kind <> 'percent' OR value <= 100)
);

CREATE UNIQUE INDEX IF NOT EXISTS site_discount_codes_org_code_uq
  ON site_discount_codes (org_id, code);

CREATE TABLE IF NOT EXISTS site_discount_redemptions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL,
  code_id      uuid NOT NULL REFERENCES site_discount_codes(id) ON DELETE CASCADE,
  builder_id   uuid,
  order_id     uuid,
  amount_ngn   numeric(12,2) NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- One redemption per order, so a repeated payment webhook can never count twice.
CREATE UNIQUE INDEX IF NOT EXISTS site_discount_redemptions_order_uq
  ON site_discount_redemptions (order_id) WHERE order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS site_discount_redemptions_code_idx
  ON site_discount_redemptions (code_id, builder_id);

-- Backend-only tables (service role). RLS on with no policies = no direct client access.
ALTER TABLE site_discount_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_discount_redemptions ENABLE ROW LEVEL SECURITY;
