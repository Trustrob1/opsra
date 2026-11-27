-- REVISE-1 (27 Nov 2026): sales reps revise their own unpaid invoices; each rep can have a home region.
-- Safe to run twice.

-- 1. A revised document points back to the one it replaced (the old one is voided).
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS revised_from_id uuid REFERENCES invoices(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS invoices_revised_from ON invoices (revised_from_id) WHERE revised_from_id IS NOT NULL;

-- 2. A sales rep's home region (one of the business's region names). Their invoices use it and they pick only
--    from that region's bank accounts. NULL = no home region.
ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_region text CHECK (sales_region IS NULL OR char_length(sales_region) <= 255);
