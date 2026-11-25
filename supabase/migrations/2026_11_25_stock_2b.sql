-- STOCK-2b (25 Nov 2026): sell from another location with an admin's approval.
-- Run AFTER 2026_11_25_stock_2.sql. Safe to run twice.
--  * invoice_items.stock_location_id: where this line's stock is held when it is not the invoice's own location
--  * invoices.stock_approval: 'pending' while a rep's request waits for an owner / ops manager / admin,
--    then 'approved' or 'rejected' (null = no request). Who asked, who decided, when, and the note are kept.

ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_location_id uuid REFERENCES stock_locations(id) ON DELETE SET NULL;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_approval text;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_requested_by uuid;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_requested_at timestamptz;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_request_note text;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_decided_by uuid;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_decided_at timestamptz;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_decision_note text;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'invoices_stock_approval_check') THEN
    ALTER TABLE invoices ADD CONSTRAINT invoices_stock_approval_check
      CHECK (stock_approval IS NULL OR stock_approval IN ('pending', 'approved', 'rejected'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS invoices_stock_pending ON invoices (org_id, stock_requested_at) WHERE stock_approval = 'pending';
