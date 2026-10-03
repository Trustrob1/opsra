-- SITE-PREMIUM P4-4 (design history and "Try another design"). Additive only.
-- site_designs already has kind ('generate','redesign','patch','import'), staged and status from P1/P2.
-- Redesigns used are counted from site_events (event 'premium_redesign_used'), so no counter column is needed.
ALTER TABLE site_builder_settings
  ADD COLUMN IF NOT EXISTS site_premium_redesigns_included integer NOT NULL DEFAULT 2,
  ADD COLUMN IF NOT EXISTS site_premium_post_live_redesign boolean NOT NULL DEFAULT false;
