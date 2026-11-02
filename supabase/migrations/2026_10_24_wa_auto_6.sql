-- WA-AUTO-6: where "help me connect WhatsApp" requests are emailed, and a way to mark a request as done.
-- Safe to run more than once.
ALTER TABLE wa_signup_settings ADD COLUMN IF NOT EXISTS alert_email text DEFAULT 'trustrobert34@gmail.com';
UPDATE wa_signup_settings SET alert_email = 'trustrobert34@gmail.com' WHERE alert_email IS NULL;
ALTER TABLE wa_onboarding ADD COLUMN IF NOT EXISTS setup_done_at timestamptz;
