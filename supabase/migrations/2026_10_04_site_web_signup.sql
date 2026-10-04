-- SITE-WEB-1 - web sign-up for builders (and owners who build their own site).
-- Additive and safe to re-run. Run in Supabase BEFORE deploying the SITE-WEB-1 code.

-- 1) Who the account is for. 'owner' = a business owner building their own site; 'builder' = building for clients.
ALTER TABLE site_builders ADD COLUMN IF NOT EXISTS account_type text NOT NULL DEFAULT 'builder';
ALTER TABLE site_builders DROP CONSTRAINT IF EXISTS site_builders_account_type_check;
ALTER TABLE site_builders ADD CONSTRAINT site_builders_account_type_check CHECK (account_type IN ('builder', 'owner'));

-- 2) Where the account came from. The WhatsApp bot already writes 'whatsapp' and 'whatsapp_self_serve', which the
--    old check rejected (so a bot sign-up in open mode would have failed). Add those and 'web_signup'.
ALTER TABLE site_builders DROP CONSTRAINT IF EXISTS site_builders_source_check;
ALTER TABLE site_builders ADD CONSTRAINT site_builders_source_check CHECK (source IN
  ('webinar_oct_2026', 'manual', 'csv_import', 'self_signup', 'whatsapp', 'whatsapp_self_serve', 'web_signup'));

-- 3) Email-code sign-up requests. The code is stored only as a hash. Rows double as the durable rate-limit log.
CREATE TABLE IF NOT EXISTS site_signup_requests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organisations(id),
  full_name     text NOT NULL,
  email         text NOT NULL,
  phone_number  text NOT NULL,
  account_type  text NOT NULL DEFAULT 'builder' CHECK (account_type IN ('builder', 'owner')),
  code_hash     text NOT NULL,
  attempts      integer NOT NULL DEFAULT 0,
  status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'blocked')),
  ip_hash       text,
  expires_at    timestamptz NOT NULL,
  verified_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS site_signup_requests_ip_idx    ON site_signup_requests (ip_hash, created_at);
CREATE INDEX IF NOT EXISTS site_signup_requests_email_idx ON site_signup_requests (email, created_at);
CREATE INDEX IF NOT EXISTS site_signup_requests_phone_idx ON site_signup_requests (phone_number, created_at);
CREATE INDEX IF NOT EXISTS site_signup_requests_org_idx   ON site_signup_requests (org_id, created_at);

ALTER TABLE site_signup_requests ENABLE ROW LEVEL SECURITY;
