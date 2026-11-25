-- STOCK-1: inventory - locations, stock per product + size + location, history, and one locked function that makes
-- every stock change. Safe to run more than once. Additive only (no existing column changes).
-- Buckets: on_hand (physically there), held (on an issued invoice not yet paid - STOCK-2), sold_pending (paid, not yet
-- delivered - STOCK-2), in_transit_in (being moved here - STOCK-3). Available = on_hand - held - sold_pending.

CREATE TABLE IF NOT EXISTS stock_settings (
  org_id uuid PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
  enabled boolean NOT NULL DEFAULT false,
  enabled_at timestamptz,
  imported_at timestamptz,
  default_reorder_level integer NOT NULL DEFAULT 5 CHECK (default_reorder_level BETWEEN 0 AND 1000000),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_locations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 100),
  region text CHECK (region IS NULL OR char_length(region) <= 255),
  is_default boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_locations_org_name ON stock_locations (org_id, lower(btrim(name)));
CREATE UNIQUE INDEX IF NOT EXISTS stock_locations_one_default ON stock_locations (org_id) WHERE is_default;

CREATE TABLE IF NOT EXISTS stock_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  variant text NOT NULL DEFAULT '' CHECK (char_length(variant) <= 100),   -- size title; '' = product has no sizes
  sku text CHECK (sku IS NULL OR char_length(sku) <= 100),
  cost_price numeric(14,2) CHECK (cost_price IS NULL OR cost_price >= 0),
  reorder_level integer CHECK (reorder_level IS NULL OR reorder_level BETWEEN 0 AND 1000000),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, product_id, variant)
);

CREATE TABLE IF NOT EXISTS stock_levels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  item_id uuid NOT NULL REFERENCES stock_items(id) ON DELETE CASCADE,
  location_id uuid NOT NULL REFERENCES stock_locations(id) ON DELETE RESTRICT,
  on_hand integer NOT NULL DEFAULT 0 CHECK (on_hand >= 0),
  held integer NOT NULL DEFAULT 0 CHECK (held >= 0),
  sold_pending integer NOT NULL DEFAULT 0 CHECK (sold_pending >= 0),
  in_transit_in integer NOT NULL DEFAULT 0 CHECK (in_transit_in >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (item_id, location_id),
  CHECK (held + sold_pending <= on_hand)
);
CREATE INDEX IF NOT EXISTS stock_levels_org ON stock_levels (org_id);
CREATE INDEX IF NOT EXISTS stock_levels_location ON stock_levels (location_id);

CREATE TABLE IF NOT EXISTS stock_moves (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  item_id uuid NOT NULL REFERENCES stock_items(id) ON DELETE CASCADE,
  location_id uuid NOT NULL REFERENCES stock_locations(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK (kind IN ('import','receive','adjust','return','hold','release','paid','deliver',
                                     'transfer_out','transfer_in','transfer_cancel')),
  d_on_hand integer NOT NULL DEFAULT 0,
  d_held integer NOT NULL DEFAULT 0,
  d_sold integer NOT NULL DEFAULT 0,
  d_transit integer NOT NULL DEFAULT 0,
  on_hand_after integer NOT NULL,
  held_after integer NOT NULL,
  sold_after integer NOT NULL,
  transit_after integer NOT NULL,
  unit_cost numeric(14,2) CHECK (unit_cost IS NULL OR unit_cost >= 0),
  reason text CHECK (reason IS NULL OR char_length(reason) <= 500),
  ref text CHECK (ref IS NULL OR char_length(ref) <= 200),
  invoice_id uuid REFERENCES invoices(id) ON DELETE SET NULL,
  invoice_item_id uuid REFERENCES invoice_items(id) ON DELETE SET NULL,
  transfer_id uuid,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stock_moves_org_time ON stock_moves (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS stock_moves_item_time ON stock_moves (item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS stock_moves_invoice ON stock_moves (invoice_id) WHERE invoice_id IS NOT NULL;

-- Every stock change goes through here: one row lock, the check, the new numbers and the history row together, so two
-- people can never take the same last unit. Errors: STOCK_BAD_LOCATION, STOCK_BAD_PRODUCT, STOCK_NEGATIVE|<bucket>,
-- STOCK_SHORT|<available before>. p_set_on_hand sets on_hand to a counted number (the change is worked out under the lock).
CREATE OR REPLACE FUNCTION stock_apply(
  p_org uuid, p_product uuid, p_variant text, p_location uuid, p_kind text,
  p_on_hand integer DEFAULT 0, p_held integer DEFAULT 0, p_sold integer DEFAULT 0, p_transit integer DEFAULT 0,
  p_set_on_hand integer DEFAULT NULL, p_user uuid DEFAULT NULL, p_reason text DEFAULT NULL, p_unit_cost numeric DEFAULT NULL,
  p_invoice uuid DEFAULT NULL, p_invoice_item uuid DEFAULT NULL, p_transfer uuid DEFAULT NULL, p_ref text DEFAULT NULL,
  p_sku text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_variant text := coalesce(btrim(p_variant), '');
  v_item uuid;
  v_lvl stock_levels%ROWTYPE;
  v_on integer; v_held integer; v_sold integer; v_tr integer; v_d_on integer;
  v_move uuid;
BEGIN
  PERFORM 1 FROM stock_locations WHERE id = p_location AND org_id = p_org AND is_active;
  IF NOT FOUND THEN RAISE EXCEPTION 'STOCK_BAD_LOCATION'; END IF;
  PERFORM 1 FROM products WHERE id = p_product AND org_id = p_org;
  IF NOT FOUND THEN RAISE EXCEPTION 'STOCK_BAD_PRODUCT'; END IF;

  INSERT INTO stock_items (org_id, product_id, variant, sku) VALUES (p_org, p_product, v_variant, p_sku)
  ON CONFLICT (org_id, product_id, variant) DO NOTHING;
  SELECT id INTO v_item FROM stock_items WHERE org_id = p_org AND product_id = p_product AND variant = v_variant;

  INSERT INTO stock_levels (org_id, item_id, location_id) VALUES (p_org, v_item, p_location)
  ON CONFLICT (item_id, location_id) DO NOTHING;
  SELECT * INTO v_lvl FROM stock_levels WHERE item_id = v_item AND location_id = p_location FOR UPDATE;

  v_d_on := CASE WHEN p_set_on_hand IS NOT NULL THEN p_set_on_hand - v_lvl.on_hand ELSE coalesce(p_on_hand, 0) END;
  v_on   := v_lvl.on_hand + v_d_on;
  v_held := v_lvl.held + coalesce(p_held, 0);
  v_sold := v_lvl.sold_pending + coalesce(p_sold, 0);
  v_tr   := v_lvl.in_transit_in + coalesce(p_transit, 0);

  IF v_on < 0 THEN RAISE EXCEPTION 'STOCK_NEGATIVE|on_hand|%', v_lvl.on_hand - v_lvl.held - v_lvl.sold_pending; END IF;
  IF v_held < 0 THEN RAISE EXCEPTION 'STOCK_NEGATIVE|held|%', v_lvl.held; END IF;
  IF v_sold < 0 THEN RAISE EXCEPTION 'STOCK_NEGATIVE|sold_pending|%', v_lvl.sold_pending; END IF;
  IF v_tr < 0 THEN RAISE EXCEPTION 'STOCK_NEGATIVE|in_transit_in|%', v_lvl.in_transit_in; END IF;
  IF v_held + v_sold > v_on THEN
    RAISE EXCEPTION 'STOCK_SHORT|%', v_lvl.on_hand - v_lvl.held - v_lvl.sold_pending;
  END IF;

  UPDATE stock_levels SET on_hand = v_on, held = v_held, sold_pending = v_sold, in_transit_in = v_tr, updated_at = now()
  WHERE id = v_lvl.id;

  IF p_unit_cost IS NOT NULL OR (p_sku IS NOT NULL AND btrim(p_sku) <> '') THEN
    UPDATE stock_items SET cost_price = coalesce(p_unit_cost, cost_price),
                           sku = coalesce(nullif(btrim(p_sku), ''), sku), updated_at = now()
    WHERE id = v_item;
  END IF;

  INSERT INTO stock_moves (org_id, item_id, location_id, kind, d_on_hand, d_held, d_sold, d_transit,
                           on_hand_after, held_after, sold_after, transit_after, unit_cost, reason, ref,
                           invoice_id, invoice_item_id, transfer_id, created_by)
  VALUES (p_org, v_item, p_location, p_kind, v_d_on, coalesce(p_held, 0), coalesce(p_sold, 0), coalesce(p_transit, 0),
          v_on, v_held, v_sold, v_tr, p_unit_cost, left(p_reason, 500), left(p_ref, 200),
          p_invoice, p_invoice_item, p_transfer, p_user)
  RETURNING id INTO v_move;

  -- Catalogue total for the product = what can still be sold, across every location (Shopify sync stops writing it).
  UPDATE products SET inventory_count = (
    SELECT coalesce(sum(l.on_hand - l.held - l.sold_pending), 0)
    FROM stock_levels l JOIN stock_items i ON i.id = l.item_id
    WHERE i.org_id = p_org AND i.product_id = p_product)
  WHERE id = p_product AND org_id = p_org;

  RETURN jsonb_build_object('item_id', v_item, 'location_id', p_location, 'move_id', v_move,
    'on_hand', v_on, 'held', v_held, 'sold_pending', v_sold, 'in_transit_in', v_tr,
    'available', v_on - v_held - v_sold, 'change', v_d_on);
END;
$$;
REVOKE ALL ON FUNCTION stock_apply(uuid, uuid, text, uuid, text, integer, integer, integer, integer, integer, uuid, text,
  numeric, uuid, uuid, uuid, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION stock_apply(uuid, uuid, text, uuid, text, integer, integer, integer, integer, integer, uuid, text,
  numeric, uuid, uuid, uuid, text, text) TO service_role;

-- RLS: same posture as the other server-only tables (backend uses the service role).
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['stock_settings','stock_locations','stock_items','stock_levels','stock_moves'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = t::regclass AND polname = 'service_role_bypass') THEN
      EXECUTE format('CREATE POLICY service_role_bypass ON %I TO service_role USING (true) WITH CHECK (true)', t);
    END IF;
  END LOOP;
END $$;

-- Check (should list 5 tables and 1 function):
-- SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'stock\_%' ORDER BY 1;
-- SELECT proname FROM pg_proc WHERE proname = 'stock_apply';
