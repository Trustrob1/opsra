-- HOST-4: stay signed in for 30 days. One row per browser a builder has signed in on; only a hash of the cookie value is stored.
-- Safe to run twice.
CREATE TABLE IF NOT EXISTS site_builder_sessions (
  id           uuid PRIMARY KEY,
  org_id       uuid NOT NULL,
  builder_id   uuid NOT NULL,
  token_hash   text NOT NULL UNIQUE,
  user_agent   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz
);
CREATE INDEX IF NOT EXISTS site_builder_sessions_builder_idx ON site_builder_sessions (builder_id);
ALTER TABLE site_builder_sessions ENABLE ROW LEVEL SECURITY;
