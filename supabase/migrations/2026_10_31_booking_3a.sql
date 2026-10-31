-- BOOKING-3A: optional deposits at booking. Idempotent, additive. Services default to NO deposit.
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS deposit_amount numeric(12,2) NOT NULL DEFAULT 0;
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS deposit_currency text NOT NULL DEFAULT 'NGN';
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS deposit_method text NOT NULL DEFAULT 'paystack';
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS deposit_external_url text;
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS deposit_hold_minutes integer NOT NULL DEFAULT 30;
ALTER TABLE booking_services ADD COLUMN IF NOT EXISTS deposit_refund_rule text NOT NULL DEFAULT 'before_cutoff';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'booking_services_deposit_method_chk') THEN
    ALTER TABLE booking_services ADD CONSTRAINT booking_services_deposit_method_chk CHECK (deposit_method IN ('paystack','external'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'booking_services_deposit_rule_chk') THEN
    ALTER TABLE booking_services ADD CONSTRAINT booking_services_deposit_rule_chk CHECK (deposit_refund_rule IN ('before_cutoff','always','never'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'booking_services_deposit_amount_chk') THEN
    ALTER TABLE booking_services ADD CONSTRAINT booking_services_deposit_amount_chk CHECK (deposit_amount >= 0);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS booking_payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  demo_id uuid NOT NULL REFERENCES lead_demos(id) ON DELETE CASCADE,
  lead_id uuid,
  method text NOT NULL,                       -- paystack | external
  reference text,                             -- Paystack reference (null for external)
  pay_url text,                               -- checkout or external payment link
  amount numeric(12,2) NOT NULL,
  currency text NOT NULL DEFAULT 'NGN',
  status text NOT NULL DEFAULT 'pending',     -- pending | paid | expired | cancelled | refunded | refund_due | waived
  refund_rule text NOT NULL DEFAULT 'before_cutoff',
  hold_expires_at timestamptz NOT NULL,
  paid_at timestamptz,
  refunded_at timestamptz,
  marked_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS booking_payments_reference_uq ON booking_payments(reference) WHERE reference IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS booking_payments_one_open_per_demo ON booking_payments(demo_id) WHERE status IN ('pending','paid','refund_due');
CREATE INDEX IF NOT EXISTS booking_payments_pending_idx ON booking_payments(hold_expires_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS booking_payments_org_demo_idx ON booking_payments(org_id, demo_id);
ALTER TABLE booking_payments ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = 'booking_payments'::regclass AND polname = 'service_role_bypass') THEN
    CREATE POLICY service_role_bypass ON booking_payments FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
