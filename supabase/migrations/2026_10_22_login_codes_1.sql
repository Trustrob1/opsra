-- LOGIN-1: sign in with an emailed 6-digit code (and link). One row per code sent; only a hash of the code is stored.
-- Safe to run twice.
CREATE TABLE IF NOT EXISTS site_login_codes (
  id          uuid PRIMARY KEY,
  org_id      uuid NOT NULL,
  builder_id  uuid NOT NULL,
  code_hash   text NOT NULL,
  attempts    integer NOT NULL DEFAULT 0,
  status      text NOT NULL DEFAULT 'pending',   -- pending | used | locked | replaced
  expires_at  timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS site_login_codes_builder_idx ON site_login_codes (builder_id, created_at DESC);
ALTER TABLE site_login_codes ENABLE ROW LEVEL SECURITY;
