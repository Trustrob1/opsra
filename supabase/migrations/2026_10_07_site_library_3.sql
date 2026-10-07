-- SITE-IMPORT 3 (library designs) - additive and idempotent. Run BEFORE deploying the IMPORT-3 code.
-- Spec: website-business/SITE-IMPORT_Spec.md sections 16 and 21.
-- Needs the IMPORT-1a migration (tier 'imported', design kind 'library', import columns) to be applied first.

CREATE TABLE IF NOT EXISTS site_library_designs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organisations(id),
  name             varchar(80)  NOT NULL,
  niche            varchar(80)  NOT NULL,            -- a site_presets.key
  note             text         NOT NULL DEFAULT '',
  source_kind      varchar(20)  NOT NULL CHECK (source_kind IN ('import', 'premium')),
  source_design_id uuid,                              -- informational only: a library design is a copy, not a link
  skeleton_html    text         NOT NULL DEFAULT '',  -- import: the page as uploaded; premium: the marked body markup
  skeleton_css     text         NOT NULL DEFAULT '',
  slot_skeleton    text,                              -- import only: the page with the slot markers written in
  slot_manifest    jsonb        NOT NULL DEFAULT '{}'::jsonb,
  tokens           jsonb        NOT NULL DEFAULT '{}'::jsonb,
  art_direction    jsonb        NOT NULL DEFAULT '{}'::jsonb,
  fingerprint      jsonb        NOT NULL DEFAULT '{}'::jsonb,
  sample_content   jsonb        NOT NULL DEFAULT '{}'::jsonb,   -- preview only, never copied to a site
  import_meta      jsonb        NOT NULL DEFAULT '{}'::jsonb,   -- import only: scan report and the library's own file list
  files_prefix     text,                              -- import only: folder in bucket site-import-files ('library/<org>/<id>')
  has_scripts      boolean      NOT NULL DEFAULT false,
  fit              jsonb        NOT NULL DEFAULT '{}'::jsonb,   -- warnings and the fixed-text list from the save-time checks
  status           varchar(20)  NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'retired')),
  uses_count       integer      NOT NULL DEFAULT 0,
  created_by       varchar(80),
  created_at       timestamptz  NOT NULL DEFAULT now(),
  updated_at       timestamptz  NOT NULL DEFAULT now(),
  UNIQUE (org_id, niche, name)
);

CREATE INDEX IF NOT EXISTS site_library_designs_niche_idx ON site_library_designs (org_id, niche, status);

-- Backend-only table (service role). RLS on with no policies = no direct client access.
ALTER TABLE site_library_designs ENABLE ROW LEVEL SECURITY;

ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS site_library_enabled boolean NOT NULL DEFAULT false;

-- To switch the library on for Trust's org (replace the id):
--   update site_builder_settings set site_library_enabled = true where org_id = '<trust org id>';
