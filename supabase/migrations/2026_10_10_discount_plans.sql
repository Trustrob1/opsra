-- SITE-ADDONS: discount codes can apply to plans and add-ons.
-- Additive and idempotent. Run BEFORE deploying the code.
-- applies_to: 'websites' (the first website order - how every existing code works), 'plans' (the first payment of a
-- plan or add-on) or 'both'. Existing codes keep working exactly as before because the default is 'websites'.
ALTER TABLE site_discount_codes
  ADD COLUMN IF NOT EXISTS applies_to text NOT NULL DEFAULT 'websites';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'site_discount_codes_applies_to_chk') THEN
    ALTER TABLE site_discount_codes
      ADD CONSTRAINT site_discount_codes_applies_to_chk CHECK (applies_to IN ('websites', 'plans', 'both'));
  END IF;
END $$;
