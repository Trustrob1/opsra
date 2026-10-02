-- SITE-BACKUP — nightly offsite backup of published client sites (R2 -> a separate backup bucket).
-- Additive and idempotent. Run BEFORE deploying the SITE-BACKUP code.
-- One row per nightly run, and one row per site per run, so there is a record of when
-- each site was last backed up and whether the copy was verified.
-- Platform-level tables (the R2 bucket is shared by all orgs), so there is no org_id.

CREATE TABLE IF NOT EXISTS site_backup_runs (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger            text NOT NULL DEFAULT 'scheduled' CHECK (trigger IN ('scheduled', 'manual')),
  status             text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'partial', 'failed')),
  started_at         timestamptz NOT NULL DEFAULT now(),
  finished_at        timestamptz,
  domains_total      integer NOT NULL DEFAULT 0,
  domains_backed_up  integer NOT NULL DEFAULT 0,
  domains_unchanged  integer NOT NULL DEFAULT 0,
  domains_failed     integer NOT NULL DEFAULT 0,
  files_copied       integer NOT NULL DEFAULT 0,
  bytes_copied       bigint  NOT NULL DEFAULT 0,
  snapshots_pruned   integer NOT NULL DEFAULT 0,
  error              text
);

CREATE INDEX IF NOT EXISTS site_backup_runs_started_idx ON site_backup_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS site_backup_items (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id         uuid NOT NULL REFERENCES site_backup_runs(id) ON DELETE CASCADE,
  domain         text NOT NULL,
  status         text NOT NULL CHECK (status IN ('backed_up', 'unchanged', 'failed')),
  snapshot_date  date,                 -- the snapshot that holds this site's files (for 'unchanged', the earlier one)
  manifest_hash  text,                 -- hash of the site's file list (path, ETag, size) at backup time
  files          integer NOT NULL DEFAULT 0,
  bytes          bigint  NOT NULL DEFAULT 0,
  verified       boolean NOT NULL DEFAULT false,   -- true once the copy was listed back and matched
  error          text,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS site_backup_items_domain_idx ON site_backup_items (domain, created_at DESC);
CREATE INDEX IF NOT EXISTS site_backup_items_run_idx ON site_backup_items (run_id);

-- Backend-only tables (service role). RLS on with no policies = no direct client access.
ALTER TABLE site_backup_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_backup_items ENABLE ROW LEVEL SECURITY;
