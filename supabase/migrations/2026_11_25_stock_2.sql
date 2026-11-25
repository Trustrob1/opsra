-- STOCK-2: invoices hold stock. Safe to run more than once. Run AFTER the STOCK-1 migration.
-- An issued invoice holds its product lines' stock at its location; fully paid moves it to "to deliver"; delivered
-- takes it out of on hand; void (or a receipt voided) puts it back. Only invoices issued while stock is on are tracked.

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS location_id uuid REFERENCES stock_locations(id) ON DELETE SET NULL;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stock_tracked boolean NOT NULL DEFAULT false;
ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_held integer NOT NULL DEFAULT 0;
ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_sold integer NOT NULL DEFAULT 0;
ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_delivered integer NOT NULL DEFAULT 0;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'invoice_items_stock_counts') THEN
    ALTER TABLE invoice_items ADD CONSTRAINT invoice_items_stock_counts
      CHECK (stock_held >= 0 AND stock_sold >= 0 AND stock_delivered >= 0);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS invoices_stock_tracked ON invoices (org_id, status) WHERE stock_tracked;

-- stock_apply: same as STOCK-1, plus the invoice line counters (STOCK_BAD_INVOICE_ITEM if the line isn't this business's).
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

  -- STOCK-2: an invoice line's own counters move in the same step (held / to deliver / delivered).
  IF p_invoice_item IS NOT NULL THEN
    UPDATE invoice_items SET
      stock_held = stock_held + coalesce(p_held, 0),
      stock_sold = stock_sold + coalesce(p_sold, 0),
      stock_delivered = stock_delivered + CASE WHEN p_kind = 'deliver' THEN -v_d_on ELSE 0 END
    WHERE id = p_invoice_item AND org_id = p_org AND (p_invoice IS NULL OR invoice_id = p_invoice);
    IF NOT FOUND THEN RAISE EXCEPTION 'STOCK_BAD_INVOICE_ITEM'; END IF;
  END IF;

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


-- Check (should be 5 and true):
-- SELECT count(*) FROM information_schema.columns WHERE (table_name='invoices' AND column_name IN ('location_id','stock_tracked'))
--   OR (table_name='invoice_items' AND column_name IN ('stock_held','stock_sold','stock_delivered'));
-- SELECT prosrc LIKE '%STOCK_BAD_INVOICE_ITEM%' FROM pg_proc WHERE proname = 'stock_apply';
