-- BOOKING-2C: WhatsApp slot picker. Safe to run more than once. Additive only.

-- One short-lived conversation state per lead while they pick a time inside WhatsApp.
CREATE TABLE IF NOT EXISTS booking_wa_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  service_id uuid REFERENCES booking_services(id) ON DELETE SET NULL,
  demo_id uuid REFERENCES lead_demos(id) ON DELETE SET NULL,   -- set when this is a reschedule
  step text NOT NULL DEFAULT 'day' CHECK (step IN ('day','time','confirm')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','expired')),
  offered jsonb NOT NULL DEFAULT '{}'::jsonb,                   -- what was shown; replies only point into this
  chosen_start timestamptz,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- At most one live conversation per lead.
CREATE UNIQUE INDEX IF NOT EXISTS booking_wa_sessions_one_active ON booking_wa_sessions(lead_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS booking_wa_sessions_lead_created ON booking_wa_sessions(lead_id, created_at);

-- Auto-send after qualification: send the link (default) or start the WhatsApp picker.
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS auto_send_mode text NOT NULL DEFAULT 'link';
DO $$ BEGIN
  ALTER TABLE booking_settings ADD CONSTRAINT booking_settings_auto_send_mode_chk CHECK (auto_send_mode IN ('link','picker'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE booking_wa_sessions ENABLE ROW LEVEL SECURITY;
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = 'booking_wa_sessions'::regclass AND polname = 'service_role_bypass') THEN
    CREATE POLICY service_role_bypass ON booking_wa_sessions TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
