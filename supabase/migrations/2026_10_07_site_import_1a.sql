-- SITE-IMPORT 1a (import of finished HTML/CSS/JS sites made outside Opsra) - additive and idempotent.
-- Run BEFORE deploying the IMPORT-1a code. Spec: website-business/SITE-IMPORT_Spec.md (sections 10, 17).
-- Read the live constraints first (Supabase SQL editor):
--   select conname, pg_get_constraintdef(oid) from pg_constraint where conrelid in ('sites'::regclass,'site_designs'::regclass) and contype='c';
-- The statements below replace sites_tier_check and site_designs_kind_check, so make sure any value a later
-- migration added is listed here too.

-- 1. A site can now be an imported site.
ALTER TABLE sites DROP CONSTRAINT IF EXISTS sites_tier_check;
ALTER TABLE sites ADD CONSTRAINT sites_tier_check CHECK (tier IN ('standard', 'premium', 'imported'));

-- 2. New design kinds ('import' already exists; 'import_slot' = the Level 2 Claude pass, 'library' = a copy of a library design).
ALTER TABLE site_designs DROP CONSTRAINT IF EXISTS site_designs_kind_check;
ALTER TABLE site_designs ADD CONSTRAINT site_designs_kind_check
  CHECK (kind IN ('generate', 'redesign', 'patch', 'import', 'import_slot', 'library'));

-- 3. What an imported design needs on top of the Premium columns.
ALTER TABLE site_designs ADD COLUMN IF NOT EXISTS import_meta   jsonb   NOT NULL DEFAULT '{}'::jsonb;  -- file list, warnings, scan, external hosts
ALTER TABLE site_designs ADD COLUMN IF NOT EXISTS editable      boolean NOT NULL DEFAULT false;         -- true once Level 2 has run
ALTER TABLE site_designs ADD COLUMN IF NOT EXISTS source_path   text;                                   -- private raw upload in bucket site-imports
ALTER TABLE site_designs ADD COLUMN IF NOT EXISTS files_prefix  text;                                   -- folder of the extracted files in bucket site-import-files

-- 4. Settings (all off / default; switch on for the test org only).
ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS site_import_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS site_import_allowed_hosts text[] NOT NULL
  DEFAULT ARRAY['fonts.googleapis.com','fonts.gstatic.com','cdnjs.cloudflare.com','cdn.jsdelivr.net','unpkg.com']::text[];
ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS site_import_max_zip_mb integer NOT NULL DEFAULT 25;

-- 5. Storage. site-imports = private (the raw upload, kept for audit and re-import).
--    site-import-files = public (the extracted CSS/JS/fonts/images; the published site is public anyway,
--    and every path carries a random token). site-assets stays images-only.
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('site-imports', 'site-imports', false, 26214400)
ON CONFLICT (id) DO NOTHING;
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('site-import-files', 'site-import-files', true, 10485760)
ON CONFLICT (id) DO NOTHING;

-- To switch import on for Trust's org (replace the id):
--   update site_builder_settings set site_import_enabled = true where org_id = '<trust org id>';
