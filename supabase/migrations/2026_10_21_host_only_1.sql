-- HOST-1: "Host with Opsra" entry point for sites built outside Opsra.
-- Run once in the Supabase SQL editor. Safe to run twice.
-- The feature is OFF until you switch it on for the Opsra organisation (see the last lines).
ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS host_only_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE site_builder_settings ADD COLUMN IF NOT EXISTS host_only_max_sites integer NOT NULL DEFAULT 25;

-- To switch on (also needs site_import_enabled = true, which is how Trust's own imports are allowed):
--   update site_builder_settings set site_import_enabled = true, host_only_enabled = true where org_id = '<opsra org id>';
-- To switch off again:
--   update site_builder_settings set host_only_enabled = false where org_id = '<opsra org id>';
