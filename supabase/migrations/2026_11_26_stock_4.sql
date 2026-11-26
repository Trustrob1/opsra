-- STOCK-4 (26 Nov 2026): owner approval before stock leaves a warehouse, the Inventory Manager role, movement records.
-- Run AFTER 2026_11_25_stock_3.sql. Safe to run twice.

-- 1. Each location is a warehouse or a showroom. Names with "warehouse", "depot" or "store room" become warehouses.
ALTER TABLE stock_locations ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'showroom';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'stock_locations_kind_check') THEN
    ALTER TABLE stock_locations ADD CONSTRAINT stock_locations_kind_check CHECK (kind IN ('warehouse', 'showroom'));
    UPDATE stock_locations SET kind = 'warehouse'
     WHERE name ~* '(warehouse|depot|store ?room)';
  END IF;
END $$;

-- 2. Requests to move stock (warehouse -> another location) or deliver an invoice's goods from a warehouse.
--    pending -> approved (by the owner) -> done (sent / delivered); or rejected / cancelled.
--    lines: transfer  [{product_id, variant, quantity}]
--           delivery  [{item_id, quantity, used}]
CREATE TABLE IF NOT EXISTS stock_move_requests (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  kind             text NOT NULL CHECK (kind IN ('transfer', 'delivery')),
  status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'done')),
  from_location_id uuid NOT NULL REFERENCES stock_locations(id),
  to_location_id   uuid REFERENCES stock_locations(id),
  invoice_id       uuid REFERENCES invoices(id) ON DELETE CASCADE,
  lines            jsonb NOT NULL DEFAULT '[]'::jsonb,
  units            integer NOT NULL DEFAULT 0,
  note             text CHECK (note IS NULL OR char_length(note) <= 300),
  requested_by     uuid,
  requested_at     timestamptz NOT NULL DEFAULT now(),
  decided_by       uuid,
  decided_at       timestamptz,
  decision_note    text CHECK (decision_note IS NULL OR char_length(decision_note) <= 300),
  done_by          uuid,
  done_at          timestamptz,
  transfer_id      uuid REFERENCES stock_transfers(id) ON DELETE SET NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT stock_move_requests_shape CHECK (
    (kind = 'transfer' AND to_location_id IS NOT NULL AND to_location_id <> from_location_id)
    OR (kind = 'delivery' AND invoice_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS stock_move_requests_org ON stock_move_requests (org_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS stock_move_requests_decided ON stock_move_requests (org_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS stock_move_requests_invoice ON stock_move_requests (invoice_id) WHERE invoice_id IS NOT NULL;

ALTER TABLE stock_move_requests ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stock_move_requests' AND policyname = 'service_role_bypass') THEN
    CREATE POLICY service_role_bypass ON stock_move_requests FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;

-- 3. Stock held for a move request uses the hold / release move kinds (no invoice); nothing else changes.
