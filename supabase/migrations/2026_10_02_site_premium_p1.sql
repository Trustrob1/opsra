-- SITE-PREMIUM P1 (Foundation) - additive and idempotent. Run BEFORE deploying the P1 code.
-- Adds: sites.tier, sites.current_design_id, site_designs (versioned bespoke skeletons),
--       site_builder_settings.premium_enabled (Premium stays off except in the test org).
-- Spec: website-business/SITE-PREMIUM_Spec.md section 3. Schema checked live on 2 Oct 2026:
-- sites had no tier column and site_designs did not exist.

ALTER TABLE sites ADD COLUMN IF NOT EXISTS tier varchar(20) NOT NULL DEFAULT 'standard';
ALTER TABLE sites DROP CONSTRAINT IF EXISTS sites_tier_check;
ALTER TABLE sites ADD CONSTRAINT sites_tier_check CHECK (tier IN ('standard', 'premium'));
ALTER TABLE sites ADD COLUMN IF NOT EXISTS current_design_id uuid;

ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS premium_enabled boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS site_designs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organisations(id),
  site_id         uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  version         integer NOT NULL,
  kind            varchar(20) NOT NULL DEFAULT 'generate'
                  CHECK (kind IN ('generate', 'redesign', 'patch', 'import')),
  parent_id       uuid REFERENCES site_designs(id) ON DELETE SET NULL,
  skeleton_html   text NOT NULL,                 -- sanitised body markup with slot markers (no <style>, no scripts)
  skeleton_css    text NOT NULL DEFAULT '',      -- validated CSS, written as its own field
  slot_manifest   jsonb NOT NULL DEFAULT '{}'::jsonb,
  art_direction   jsonb NOT NULL DEFAULT '{}'::jsonb,
  tokens          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- the CSS variable values (--accent, --bg ...)
  model           text,
  prompt_version  text,
  input_tokens    integer NOT NULL DEFAULT 0,
  output_tokens   integer NOT NULL DEFAULT 0,
  cost_usd        numeric(10,4) NOT NULL DEFAULT 0,
  status          varchar(20) NOT NULL DEFAULT 'ready'
                  CHECK (status IN ('generating', 'checking', 'ready', 'failed')),
  checks          jsonb NOT NULL DEFAULT '{}'::jsonb,
  staged          boolean NOT NULL DEFAULT false,  -- DP-5: a design kept next to the live one (not used in v1)
  created_by      varchar(80),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (site_id, version)
);

CREATE INDEX IF NOT EXISTS site_designs_site_idx ON site_designs (site_id, version DESC);
CREATE INDEX IF NOT EXISTS site_designs_org_idx ON site_designs (org_id);

-- sites.current_design_id points at the live version (added after the table exists).
ALTER TABLE sites DROP CONSTRAINT IF EXISTS sites_current_design_id_fkey;
ALTER TABLE sites ADD CONSTRAINT sites_current_design_id_fkey
  FOREIGN KEY (current_design_id) REFERENCES site_designs(id) ON DELETE SET NULL;

-- Backend-only table (service role). RLS on with no policies = no direct client access.
ALTER TABLE site_designs ENABLE ROW LEVEL SECURITY;
