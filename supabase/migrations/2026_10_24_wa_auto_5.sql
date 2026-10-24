-- WA-AUTO-5: public sign-up for WhatsApp-automation-only businesses (/start/whatsapp).
-- Safe to run more than once.

-- A free trial of the Automate plan is stored as a plan row whose source is 'trial'.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'public.org_plans'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) ILIKE '%source%'
  LOOP
    EXECUTE format('ALTER TABLE public.org_plans DROP CONSTRAINT %I', c.conname);
  END LOOP;
  ALTER TABLE public.org_plans ADD CONSTRAINT org_plans_source_check CHECK (source IN ('paid', 'staff', 'grandfathered', 'trial'));
END $$;

-- Switches Trust sets in Superadmin. One row. Sign-up is CLOSED until Trust opens it.
CREATE TABLE IF NOT EXISTS wa_signup_settings (
  id                 integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  is_open            boolean NOT NULL DEFAULT false,
  trial_days         integer NOT NULL DEFAULT 7  CHECK (trial_days BETWEEN 1 AND 30),
  starter_credit_ngn integer NOT NULL DEFAULT 0  CHECK (starter_credit_ngn BETWEEN 0 AND 5000),
  daily_cap          integer NOT NULL DEFAULT 50 CHECK (daily_cap BETWEEN 0 AND 1000),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
INSERT INTO wa_signup_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
ALTER TABLE wa_signup_settings ENABLE ROW LEVEL SECURITY;

-- Every sign-up attempt (rate limits are counted from here). The emailed code is stored only as a hash.
CREATE TABLE IF NOT EXISTS wa_signup_requests (
  id            uuid PRIMARY KEY,
  business_name text NOT NULL,
  full_name     text NOT NULL,
  email         text NOT NULL,
  phone_number  text NOT NULL,
  ip_hash       text NOT NULL,
  code_hash     text NOT NULL,
  attempts      integer NOT NULL DEFAULT 0,
  status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'blocked')),
  org_id        uuid REFERENCES organisations(id) ON DELETE SET NULL,
  expires_at    timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  verified_at   timestamptz
);
CREATE INDEX IF NOT EXISTS wa_signup_requests_ip_idx    ON wa_signup_requests (ip_hash, created_at);
CREATE INDEX IF NOT EXISTS wa_signup_requests_email_idx ON wa_signup_requests (email, created_at);
ALTER TABLE wa_signup_requests ENABLE ROW LEVEL SECURITY;
