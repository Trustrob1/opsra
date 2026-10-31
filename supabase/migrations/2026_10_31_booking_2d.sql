-- BOOKING-2D: template buttons, leads choose a person, pipeline-stage auto-send. Idempotent, additive.
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS template_buttons boolean NOT NULL DEFAULT false;
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS let_leads_choose_person boolean NOT NULL DEFAULT false;
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS auto_send_trigger text NOT NULL DEFAULT 'qualified';
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS auto_send_stage text;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'booking_settings_auto_send_trigger_chk') THEN
    ALTER TABLE booking_settings ADD CONSTRAINT booking_settings_auto_send_trigger_chk CHECK (auto_send_trigger IN ('qualified','stage'));
  END IF;
END $$;
