-- INV-SALES-1: paid invoices go into Sales Record (direct_sales). Safe to run more than once. Additive only.

-- Region on invoices / quotes and on receipts (names from Data Sources, checked by the app).
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS region text;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS region text;

-- Per business: add paid invoices to Sales Record (off until turned on) and when it was turned on.
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS sales_record_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS sales_record_since timestamptz;

-- Each Sales Record row knows the invoice or receipt it came from.
ALTER TABLE direct_sales ADD COLUMN IF NOT EXISTS invoice_id uuid REFERENCES invoices(id) ON DELETE SET NULL;
ALTER TABLE direct_sales ADD COLUMN IF NOT EXISTS receipt_id uuid REFERENCES receipts(id) ON DELETE SET NULL;
-- 'inv:<invoice line id>' or 'rct:<receipt id>': the same sale can never be written twice.
ALTER TABLE direct_sales ADD COLUMN IF NOT EXISTS source_ref text;
CREATE UNIQUE INDEX IF NOT EXISTS direct_sales_org_source_ref ON direct_sales (org_id, source_ref)
  WHERE source_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS direct_sales_invoice ON direct_sales (invoice_id) WHERE invoice_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS direct_sales_receipt ON direct_sales (receipt_id) WHERE receipt_id IS NOT NULL;

-- The Sales Record card looks up part-paid invoices.
CREATE INDEX IF NOT EXISTS invoices_part_paid ON invoices (org_id, issue_date) WHERE status = 'part_paid';

-- Check (all should be true):
-- SELECT
--   EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invoices' AND column_name='region') AS inv_region,
--   EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='receipts' AND column_name='region') AS rct_region,
--   EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invoice_settings' AND column_name='sales_record_since') AS settings_ok,
--   EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='direct_sales_org_source_ref') AS unique_ok;
