-- SITE-1C-2 — allowed section layouts per template (spec website-business/SITE-1C_Spec.md §7)
-- Additive and idempotent. Run BEFORE deploying the SITE-1C-2 code.
-- Empty {} (the default) means every layout is allowed, so existing templates behave as before.
ALTER TABLE site_presets ADD COLUMN IF NOT EXISTS allowed_variants jsonb NOT NULL DEFAULT '{}'::jsonb;
