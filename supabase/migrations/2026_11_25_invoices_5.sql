-- INV-5: overdue reminders and quote expiry follow-up. Safe to run more than once. Additive only.

-- Per business: send customers a reminder when an invoice is overdue (off until the business turns it on).
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS reminders_enabled boolean NOT NULL DEFAULT false;

-- Per invoice: how many overdue reminders went out and when (the worker sends at most 3: 1, 7 and 14 days late).
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS reminder_count integer NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS last_reminder_at timestamptz;
-- Per quote: when the team was told it expired (so it is told once).
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS expiry_notified_at timestamptz;

-- The worker looks for open invoices and quotes past their date.
CREATE INDEX IF NOT EXISTS invoices_open_due ON invoices (due_date)
  WHERE status IN ('issued', 'part_paid');

-- Check (all should be true):
-- SELECT
--   EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invoice_settings' AND column_name='reminders_enabled') AS settings_ok,
--   EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invoices' AND column_name='reminder_count') AS count_ok,
--   EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invoices' AND column_name='expiry_notified_at') AS expiry_ok;
