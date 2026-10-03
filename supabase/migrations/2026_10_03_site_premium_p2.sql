-- SITE-PREMIUM P2 (generation). Additive only. Checked against the live schema on 3 Oct 2026:
-- site_designs already has model, prompt_version, input_tokens, output_tokens, cost_usd, status, checks.
ALTER TABLE site_builder_settings
  ADD COLUMN IF NOT EXISTS site_premium_model text NOT NULL DEFAULT 'claude-sonnet-5-5',
  ADD COLUMN IF NOT EXISTS site_premium_daily_cost_cap numeric(8,2) NOT NULL DEFAULT 20,
  ADD COLUMN IF NOT EXISTS site_premium_daily_per_builder integer NOT NULL DEFAULT 3;

ALTER TABLE site_presets
  ADD COLUMN IF NOT EXISTS premium_design_notes text NOT NULL DEFAULT '';

ALTER TABLE site_designs
  ADD COLUMN IF NOT EXISTS duration_ms integer NOT NULL DEFAULT 0;

-- One generation in flight per site, enforced by the database (spec section 8).
CREATE UNIQUE INDEX IF NOT EXISTS site_designs_one_inflight
  ON site_designs (site_id) WHERE status IN ('generating', 'checking');

CREATE INDEX IF NOT EXISTS site_designs_org_created_idx ON site_designs (org_id, created_at DESC);
