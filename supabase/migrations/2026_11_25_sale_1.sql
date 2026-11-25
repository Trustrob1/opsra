-- SALE-1: Make a sale, reps see only their own invoices and receipts, optional admin confirmation of payments.
-- Run AFTER 2026_11_25_stock_3.sql. Safe to run twice.

-- whose receipt this is (the invoice's maker, or whoever recorded a receipt with no invoice)
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS approved_by uuid REFERENCES users(id) ON DELETE SET NULL;
UPDATE receipts r SET owner_id = coalesce(i.created_by, r.recorded_by)
  FROM invoices i WHERE r.owner_id IS NULL AND r.invoice_id = i.id;
UPDATE receipts SET owner_id = recorded_by WHERE owner_id IS NULL AND invoice_id IS NULL;
CREATE INDEX IF NOT EXISTS receipts_owner ON receipts (org_id, owner_id);
CREATE INDEX IF NOT EXISTS invoices_created_by ON invoices (org_id, created_by);

-- the owner's switch: payments recorded by staff wait for an admin's OK
ALTER TABLE invoice_settings ADD COLUMN IF NOT EXISTS payments_need_approval boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS payment_approvals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  invoice_id    uuid REFERENCES invoices(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('invoice', 'standalone')),
  amount        numeric(14,2) NOT NULL CHECK (amount > 0),
  payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
  deliver       boolean NOT NULL DEFAULT false,
  status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
  owner_id      uuid REFERENCES users(id) ON DELETE SET NULL,
  requested_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  requested_at  timestamptz NOT NULL DEFAULT now(),
  decided_by    uuid REFERENCES users(id) ON DELETE SET NULL,
  decided_at    timestamptz,
  decision_note text CHECK (decision_note IS NULL OR char_length(decision_note) <= 500),
  receipt_id    uuid REFERENCES receipts(id) ON DELETE SET NULL,
  CONSTRAINT payment_approvals_invoice CHECK ((kind = 'invoice') = (invoice_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS payment_approvals_pending ON payment_approvals (org_id, requested_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS payment_approvals_invoice ON payment_approvals (invoice_id) WHERE invoice_id IS NOT NULL;

ALTER TABLE payment_approvals ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'payment_approvals' AND policyname = 'service_role_bypass') THEN
    CREATE POLICY service_role_bypass ON payment_approvals FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
