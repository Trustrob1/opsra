-- STOCK-3 (25 Nov 2026): moving stock between locations, the website / web chat / AI use Opsra's numbers at one
-- online location, web checkouts hold stock for 2 hours and become paid invoices, daily low-stock alerts.
-- Run AFTER 2026_11_25_stock_2b.sql. Safe to run twice.

-- 1. Settings: where website orders come from, and the low-stock alert switch
ALTER TABLE stock_settings ADD COLUMN IF NOT EXISTS online_location_id uuid REFERENCES stock_locations(id) ON DELETE SET NULL;
ALTER TABLE stock_settings ADD COLUMN IF NOT EXISTS low_stock_alerts boolean NOT NULL DEFAULT true;
ALTER TABLE stock_settings ADD COLUMN IF NOT EXISTS low_stock_alerted_at timestamptz;

-- 2. Moves between locations (send -> in transit -> received, part receive allowed, the rest can be cancelled back)
CREATE TABLE IF NOT EXISTS stock_transfers (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  from_location_id uuid NOT NULL REFERENCES stock_locations(id),
  to_location_id   uuid NOT NULL REFERENCES stock_locations(id),
  status           text NOT NULL DEFAULT 'in_transit' CHECK (status IN ('in_transit', 'done', 'cancelled')),
  note             text,
  sent_by          uuid,
  sent_at          timestamptz NOT NULL DEFAULT now(),
  closed_by        uuid,
  closed_at        timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT stock_transfers_two_places CHECK (from_location_id <> to_location_id)
);
CREATE INDEX IF NOT EXISTS stock_transfers_org ON stock_transfers (org_id, status, sent_at DESC);

CREATE TABLE IF NOT EXISTS stock_transfer_lines (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  transfer_id uuid NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
  product_id  uuid NOT NULL REFERENCES products(id),
  variant     text NOT NULL DEFAULT '',
  quantity    integer NOT NULL CHECK (quantity > 0),
  received    integer NOT NULL DEFAULT 0 CHECK (received >= 0),
  cancelled   integer NOT NULL DEFAULT 0 CHECK (cancelled >= 0),
  CONSTRAINT stock_transfer_lines_fit CHECK (received + cancelled <= quantity)
);
CREATE INDEX IF NOT EXISTS stock_transfer_lines_transfer ON stock_transfer_lines (transfer_id);

ALTER TABLE stock_transfers ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfer_lines ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stock_transfers' AND policyname = 'service_role_bypass') THEN
    CREATE POLICY service_role_bypass ON stock_transfers FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stock_transfer_lines' AND policyname = 'service_role_bypass') THEN
    CREATE POLICY service_role_bypass ON stock_transfer_lines FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;

-- 3. Web checkouts: a hidden draft invoice holds the cart for 2 hours; paid -> issued + paid; unpaid -> released
--    web_state: holding (goods held) -> releasing (worker is giving them back) -> released ; or -> paid
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS origin text;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS web_state text;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS web_hold_until timestamptz;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS web_reference text;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS web_hidden boolean NOT NULL DEFAULT false;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'invoices_web_state_check') THEN
    ALTER TABLE invoices ADD CONSTRAINT invoices_web_state_check
      CHECK (web_state IS NULL OR web_state IN ('holding', 'releasing', 'released', 'paid'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS invoices_web_holding ON invoices (web_hold_until) WHERE web_state = 'holding';
CREATE INDEX IF NOT EXISTS invoices_web_reference ON invoices (org_id, web_reference) WHERE web_reference IS NOT NULL;
