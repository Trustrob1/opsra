-- INV-SALES-2: the size (variant) picked on an invoice line. Safe to run more than once. Additive only.
ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS variant text;

-- Check (should be true):
-- SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invoice_items' AND column_name='variant');
