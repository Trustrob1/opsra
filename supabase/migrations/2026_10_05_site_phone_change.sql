-- SITE-WEB-2 - a builder changes their own WhatsApp number from the portal.
-- Additive and safe to re-run. Run in Supabase BEFORE deploying the SITE-WEB-2 code.
-- The confirmation code is emailed to the address already on the account and is stored only as a hash.
-- Rows double as the durable rate-limit log (3 requests per builder per hour).

CREATE TABLE IF NOT EXISTS site_phone_changes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES organisations(id),
  builder_id   uuid NOT NULL REFERENCES site_builders(id) ON DELETE CASCADE,
  new_phone    text NOT NULL,
  code_hash    text NOT NULL,
  attempts     integer NOT NULL DEFAULT 0,
  status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'blocked')),
  expires_at   timestamptz NOT NULL,
  verified_at  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS site_phone_changes_builder_idx ON site_phone_changes (builder_id, created_at);

ALTER TABLE site_phone_changes ENABLE ROW LEVEL SECURITY;
