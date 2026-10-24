-- WA-AUTO-3: where a WhatsApp-automation-only business is in the first-login wizard.
-- One row per organisation. Safe to run more than once.
CREATE TABLE IF NOT EXISTS wa_onboarding (
  org_id               uuid PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
  basics               jsonb NOT NULL DEFAULT '{}'::jsonb,   -- what_you_sell, hours, language
  setup_requested_at   timestamptz,                          -- the owner asked Opsra to connect the number
  setup_phone          text,
  setup_note           text,
  completed_at         timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE wa_onboarding ENABLE ROW LEVEL SECURITY;
