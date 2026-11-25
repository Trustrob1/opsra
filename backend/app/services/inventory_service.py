"""
app/services/inventory_service.py
---------------------------------
STOCK-1 - inventory: Opsra holds the true stock number, per product + size + location.

Buckets per product + size + location (table stock_levels):
  on_hand        physically in that location
  held           on an issued invoice that is not fully paid yet (STOCK-2)
  sold_pending   paid but not delivered yet; can't be sold again (STOCK-2)
  in_transit_in  being moved into this location (STOCK-3)
  available      on_hand - held - sold_pending  <- the only number a new sale can use

Every change goes through the Postgres function stock_apply() (one row lock, the checks, the new numbers and the
history row in one step), so two people can never take the same last unit. This module never reads-then-writes a level.

  get_settings / save_settings   the switch (turning it on the first time makes a default location and copies today's
                                 numbers in once: Shopify per-size quantities, else products.inventory_count)
  stock_on                       is stock switched on (Shopify sync stops writing inventory_count when it is)
  list_locations / create_location / update_location
  overview                       one row per product + size: totals and per-location numbers, low-stock flag
  history                        stock_moves, newest first
  receive / adjust / update_item managers only (owner, ops_manager, or a role with is_admin)

STOCK-3 - the website, web chat shop and AI keep reading each product's size fields (variants[].inventory_quantity /
available, products.available), but while stock is on Opsra writes them: what is available at the ONLINE location
(settings.online_location_id, else the main location). refresh_product() runs after every stock change; refresh_all()
after the switch or the online location changes. So every channel follows Opsra without its own stock rule.

S1/S2: org_id always comes from the caller's token; every id is checked against the org (in here and in stock_apply).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.services import invoice_sales_service as sales
from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

StockError = inv.InvoiceError
MANAGER_TEMPLATES = ("owner", "ops_manager")
MAX_QTY = 1_000_000
ADJUST_REASONS = {
    "recount": "Stock count",
    "damaged": "Damaged",
    "lost": "Lost or stolen",
    "found": "Found",
    "returned": "Returned by customer",
    "other": "Other",
}
KIND_LABEL = {
    "import": "Starting stock", "receive": "Received", "adjust": "Adjusted", "return": "Returned",
    "hold": "Held for invoice", "release": "Hold released", "paid": "Paid, to deliver", "deliver": "Delivered",
    "transfer_out": "Sent to another location", "transfer_in": "Received from another location",
    "transfer_cancel": "Move cancelled",
}
_ERR = re.compile(r"(STOCK_[A-Z_]+)(?:\|([a-z_]+))?(?:\|(-?\d+))?")


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_manager(org_ctx: Optional[dict]) -> bool:
    role = (org_ctx or {}).get("roles") or {}
    return role.get("template") in MANAGER_TEMPLATES or (role.get("permissions") or {}).get("is_admin") is True


def _qty(value: Any, field: str = "quantity", allow_zero: bool = False) -> int:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise StockError("VALIDATION_ERROR", "Enter a whole number.", 422, field)
    if d != d.to_integral_value():
        raise StockError("VALIDATION_ERROR", "Stock is counted in whole units.", 422, field)
    n = int(d)
    if n < 0 or (n == 0 and not allow_zero) or n > MAX_QTY:
        raise StockError("VALIDATION_ERROR", "Enter a number from 1 to 1,000,000." if not allow_zero
                         else "Enter a number from 0 to 1,000,000.", 422, field)
    return n


def _money(value: Any, field: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise StockError("VALIDATION_ERROR", "Enter an amount.", 422, field)
    if d < 0 or d > Decimal("100000000000") or d != d.quantize(Decimal("0.01")):
        raise StockError("VALIDATION_ERROR", "Enter an amount with at most 2 decimal places.", 422, field)
    return d


# ───────────────────────────── settings ─────────────────────────────

DEFAULTS = {"enabled": False, "enabled_at": None, "imported_at": None, "default_reorder_level": 5,
            "online_location_id": None, "low_stock_alerts": True, "low_stock_alerted_at": None}   # STOCK-3


def get_settings(db, org_id: str) -> dict:
    rows = _rows(db.table("stock_settings").select("*").eq("org_id", org_id).limit(1).execute())
    s = {**DEFAULTS, **{k: v for k, v in (rows[0] if rows else {}).items() if k in DEFAULTS}}
    s["enabled"] = bool(s["enabled"])
    s["low_stock_alerts"] = s["low_stock_alerts"] is not False
    return s


def stock_on(db, org_id: str) -> bool:
    """Used by Shopify sync. If the check itself fails, say 'off' so sync behaves as before."""
    try:
        return bool(get_settings(db, org_id)["enabled"])
    except Exception as exc:
        logger.warning("inventory: stock_on check failed org=%s: %s", org_id, exc)
        return False


def save_settings(db, org_id: str, user_id: Optional[str], body: dict) -> dict:
    current = get_settings(db, org_id)
    patch: dict = {"updated_at": _now()}
    if "default_reorder_level" in body and body["default_reorder_level"] is not None:
        patch["default_reorder_level"] = _qty(body["default_reorder_level"], "default_reorder_level", allow_zero=True)
    turning_on = body.get("enabled") is True and not current["enabled"]
    if "online_location_id" in body:   # STOCK-3: where website orders come from (None = the main location)
        loc_id = body.get("online_location_id")
        if loc_id:
            try:
                loc = _location(db, org_id, loc_id)
            except StockError as e:
                raise StockError(e.code, e.message, e.status, "online_location_id")
            if not loc.get("is_active"):
                raise StockError("VALIDATION_ERROR", "Choose a location that is turned on.", 422, "online_location_id")
            loc_id = loc["id"]
        patch["online_location_id"] = loc_id or None
    if "low_stock_alerts" in body and body["low_stock_alerts"] is not None:
        patch["low_stock_alerts"] = bool(body["low_stock_alerts"])
    if "enabled" in body and body["enabled"] is not None:
        patch["enabled"] = bool(body["enabled"])
        if turning_on:
            patch["enabled_at"] = _now()
    exists = bool(_rows(db.table("stock_settings").select("org_id").eq("org_id", org_id).limit(1).execute()))
    if exists:
        db.table("stock_settings").update(patch).eq("org_id", org_id).execute()
    else:
        db.table("stock_settings").insert({"org_id": org_id, **DEFAULTS, **patch}).execute()

    out = get_settings(db, org_id)
    if turning_on and not current["imported_at"]:
        loc = _default_location(db, org_id) or create_location(db, org_id, {"name": "Main store", "is_default": True})
        out["import"] = import_initial(db, org_id, user_id, loc["id"])
        db.table("stock_settings").update({"imported_at": _now()}).eq("org_id", org_id).execute()
        out["imported_at"] = get_settings(db, org_id)["imported_at"]
    if out["enabled"] and (turning_on or ("online_location_id" in patch
                                          and patch["online_location_id"] != current.get("online_location_id"))):
        out["refreshed"] = refresh_all(db, org_id)   # STOCK-3: the website now shows Opsra's numbers
    return out


# ───────────────────────────── STOCK-3: what the website / web chat / AI see ─────────────────────────────

def online_location(db, org_id: str, settings: Optional[dict] = None) -> Optional[dict]:
    """The location website orders come from: the chosen one if still on, else the main one."""
    settings = settings or get_settings(db, org_id)
    locs = [l for l in list_locations(db, org_id) if l.get("is_active")]
    if settings.get("online_location_id"):
        hit = next((l for l in locs if l["id"] == settings["online_location_id"]), None)
        if hit:
            return hit
    return next((l for l in locs if l.get("is_default")), None) or (locs[0] if locs else None)


def _online_available(db, org_id: str, location_id: Optional[str], product_ids: list) -> dict:
    """{(product_id, variant): available} at one location."""
    if not location_id or not product_ids:
        return {}
    items = _rows(db.table("stock_items").select("id, product_id, variant").eq("org_id", org_id)
                  .in_("product_id", [str(p) for p in product_ids]).execute())
    if not items:
        return {}
    levels = {lv["item_id"]: lv for lv in _rows(db.table("stock_levels").select("item_id, on_hand, held, sold_pending")
                                               .eq("org_id", org_id).eq("location_id", str(location_id))
                                               .in_("item_id", [i["id"] for i in items]).execute())}
    out = {}
    for i in items:
        lv = levels.get(i["id"]) or {}
        out[(i["product_id"], i["variant"] or "")] = max(_num(lv.get("on_hand")) - _num(lv.get("held"))
                                                         - _num(lv.get("sold_pending")), 0)
    return out


def stock_fields(prod: dict, avail: dict) -> dict:
    """The product fields the channels read, filled from Opsra: each variant's inventory_quantity / available
    (tracked, no overselling) and products.available (any size can be sold and the product isn't archived)."""
    sizes = {s["title"].lower(): s["title"] for s in inv.product_sizes(prod)}
    pid = prod["id"]
    variants = []
    for v in (prod.get("variants") or []) if isinstance(prod.get("variants"), list) else []:
        if not isinstance(v, dict):
            variants.append(v)
            continue
        title = str(v.get("title") or v.get("option1") or "").strip()
        key = sizes.get(title.lower(), "") if sizes else ""
        qty = avail.get((pid, key), 0) if (key or not sizes) else 0
        variants.append({**v, "inventory_quantity": qty, "inventory_management": "opsra", "inventory_policy": "deny",
                         "available": qty > 0})
    if sizes:
        total = sum(avail.get((pid, t), 0) for t in sizes.values())
    else:
        total = avail.get((pid, ""), 0)
    archived = prod.get("is_active") is False or str(prod.get("status") or "active") == "archived"
    return {"variants": variants, "available": total > 0 and not archived}


def refresh_product(db, org_id: str, product_id: str, settings: Optional[dict] = None,
                    location: Optional[dict] = None) -> bool:
    """Write the online location's numbers onto one product. Never raises (a later change or refresh_all fixes it)."""
    try:
        settings = settings or get_settings(db, org_id)
        if not settings["enabled"]:
            return False
        rows = _rows(db.table("products").select("id, title, variants, is_active, status").eq("org_id", org_id)
                     .eq("id", str(product_id)).limit(1).execute())
        if not rows:
            return False
        loc = location or online_location(db, org_id, settings)
        fields = stock_fields(rows[0], _online_available(db, org_id, loc["id"] if loc else None, [rows[0]["id"]]))
        db.table("products").update(fields).eq("id", rows[0]["id"]).eq("org_id", org_id).execute()
        return True
    except Exception as exc:
        logger.warning("inventory: refresh_product failed org=%s product=%s: %s", org_id, product_id, exc)
        return False


def refresh_all(db, org_id: str) -> int:
    """Every product of the business (after the switch / online location changes; also the daily worker)."""
    settings = get_settings(db, org_id)
    if not settings["enabled"]:
        return 0
    loc = online_location(db, org_id, settings)
    prods = _rows(db.table("products").select("id, title, variants, is_active, status").eq("org_id", org_id).execute())
    avail = _online_available(db, org_id, loc["id"] if loc else None, [p["id"] for p in prods])
    done = 0
    for p in prods:
        try:
            db.table("products").update(stock_fields(p, avail)).eq("id", p["id"]).eq("org_id", org_id).execute()
            done += 1
        except Exception as exc:
            logger.warning("inventory: refresh_all failed org=%s product=%s: %s", org_id, p["id"], exc)
    return done


# ───────────────────────────── locations ─────────────────────────────

def list_locations(db, org_id: str, include_inactive: bool = True) -> list:
    q = db.table("stock_locations").select("id, name, region, is_default, is_active, created_at").eq("org_id", org_id)
    if not include_inactive:
        q = q.eq("is_active", True)
    rows = _rows(q.execute())
    rows.sort(key=lambda r: (not r.get("is_active"), not r.get("is_default"), str(r.get("name") or "").lower()))
    return rows


def _default_location(db, org_id: str) -> Optional[dict]:
    rows = _rows(db.table("stock_locations").select("*").eq("org_id", org_id).eq("is_default", True)
                 .eq("is_active", True).limit(1).execute())
    return rows[0] if rows else None


def _location(db, org_id: str, location_id: Any) -> dict:
    rows = _rows(db.table("stock_locations").select("*").eq("org_id", org_id).eq("id", str(location_id)).limit(1).execute())
    if not rows:
        raise StockError("NOT_FOUND", "Location not found.", 404, "location_id")
    return rows[0]


def _clean_name(db, org_id: str, name: Any, skip_id: Optional[str] = None) -> str:
    text = " ".join(str(name or "").split())
    if not text or len(text) > 100:
        raise StockError("VALIDATION_ERROR", "Give the location a name (up to 100 characters).", 422, "name")
    for r in list_locations(db, org_id):
        if r["id"] != skip_id and str(r.get("name") or "").strip().lower() == text.lower():
            raise StockError("VALIDATION_ERROR", "You already have a location with this name.", 422, "name")
    return text


def _unset_default(db, org_id: str) -> None:
    db.table("stock_locations").update({"is_default": False, "updated_at": _now()}).eq("org_id", org_id) \
        .eq("is_default", True).execute()


def create_location(db, org_id: str, body: dict) -> dict:
    name = _clean_name(db, org_id, body.get("name"))
    region = sales.clean_region(db, org_id, body.get("region"))
    make_default = bool(body.get("is_default")) or not any(r.get("is_default") and r.get("is_active")
                                                          for r in list_locations(db, org_id))
    if make_default:
        _unset_default(db, org_id)
    row = {"org_id": org_id, "name": name, "region": region, "is_default": make_default, "is_active": True,
           "created_at": _now(), "updated_at": _now()}
    return _rows(db.table("stock_locations").insert(row).execute())[0]


def _location_has_stock(db, org_id: str, location_id: str) -> bool:
    for lv in _rows(db.table("stock_levels").select("on_hand, in_transit_in").eq("org_id", org_id)
                    .eq("location_id", location_id).execute()):
        if int(lv.get("on_hand") or 0) > 0 or int(lv.get("in_transit_in") or 0) > 0:
            return True
    return False


def update_location(db, org_id: str, location_id: Any, body: dict) -> dict:
    loc = _location(db, org_id, location_id)
    patch: dict = {"updated_at": _now()}
    if "name" in body and body["name"] is not None:
        patch["name"] = _clean_name(db, org_id, body["name"], skip_id=loc["id"])
    if "region" in body:
        patch["region"] = sales.clean_region(db, org_id, body.get("region"))
    if body.get("is_active") is False and loc.get("is_active"):
        if loc.get("is_default"):
            raise StockError("VALIDATION_ERROR", "Make another location the main one before turning this one off.",
                             422, "is_active")
        if _location_has_stock(db, org_id, loc["id"]):
            raise StockError("VALIDATION_ERROR", "This location still has stock. Move or adjust it to 0 first.",
                             422, "is_active")
        patch["is_active"] = False
    elif body.get("is_active") is True:
        patch["is_active"] = True
    if body.get("is_default") is True and not loc.get("is_default"):
        if not (patch.get("is_active", loc.get("is_active"))):
            raise StockError("VALIDATION_ERROR", "Turn the location on before making it the main one.", 422, "is_default")
        _unset_default(db, org_id)
        patch["is_default"] = True
    db.table("stock_locations").update(patch).eq("id", loc["id"]).eq("org_id", org_id).execute()
    if ("is_default" in patch or "is_active" in patch) and stock_on(db, org_id):
        refresh_all(db, org_id)   # STOCK-3: the online location may have changed
    return _location(db, org_id, loc["id"])


# ───────────────────────────── products and sizes ─────────────────────────────

def _products(db, org_id: str, product_ids: Optional[list] = None) -> list:
    q = db.table("products").select("id, title, image_url, variants, inventory_count, is_active, status").eq("org_id", org_id)
    if product_ids is not None:
        q = q.in_("id", [str(p) for p in product_ids])
    return _rows(q.execute())


def _product(db, org_id: str, product_id: Any) -> dict:
    rows = _products(db, org_id, [product_id])
    if not rows:
        raise StockError("NOT_FOUND", "Product not found.", 404, "product_id")
    return rows[0]


def clean_variant(prod: dict, variant: Any) -> str:
    """The saved spelling of the product's size, or '' for a product with no sizes. Anything else is refused."""
    text = str(variant or "").strip()
    sizes = inv.product_sizes(prod)
    if not sizes:
        if text:
            raise StockError("VALIDATION_ERROR", f"{prod.get('title') or 'This product'} has no sizes.", 422, "variant")
        return ""
    for s in sizes:
        if s["title"].lower() == text.lower():
            return s["title"]
    raise StockError("VALIDATION_ERROR", f"Choose one of the sizes for {prod.get('title') or 'this product'}.",
                     422, "variant")


def _variant_meta(prod: dict) -> dict:
    """size title (lower) -> {sku, qty} from the Shopify variant objects."""
    out = {}
    for v in (prod.get("variants") or []) if isinstance(prod.get("variants"), list) else []:
        if not isinstance(v, dict):
            continue
        title = str(v.get("title") or v.get("option1") or "").strip()
        try:
            qty = int(v.get("inventory_quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        out.setdefault(title.lower(), {"sku": (str(v.get("sku")).strip()[:100] if v.get("sku") else None), "qty": qty})
    return out


def search_products(db, org_id: str, q: Optional[str] = None, limit: int = 25) -> list:
    """Active products with their sizes, for the Receive / Adjust pickers."""
    needle = (q or "").strip().lower()
    out = []
    for p in _products(db, org_id):
        if p.get("is_active") is False or str(p.get("status") or "active") == "archived":
            continue
        if needle and needle not in str(p.get("title") or "").lower():
            continue
        out.append({"id": p["id"], "title": p.get("title"), "image_url": p.get("image_url"),
                    "sizes": [s["title"] for s in inv.product_sizes(p)]})
    out.sort(key=lambda r: str(r["title"] or "").lower())
    return out[:limit]


# ───────────────────────────── the one door: stock_apply ─────────────────────────────

def _short_message(available: Optional[int], label: str) -> str:
    if available is None:
        return f"Not enough {label} in stock."
    if available <= 0:
        return f"No {label} available here."
    return f"Only {available} {label} available here."


def apply(db, org_id: str, user_id: Optional[str], product_id: str, variant: str, location_id: str, kind: str,
          label: str = "of this item", **kw) -> dict:
    params = {"p_org": org_id, "p_product": str(product_id), "p_variant": variant or "", "p_location": str(location_id),
              "p_kind": kind, "p_on_hand": kw.get("on_hand", 0), "p_held": kw.get("held", 0),
              "p_sold": kw.get("sold", 0), "p_transit": kw.get("transit", 0), "p_set_on_hand": kw.get("set_on_hand"),
              "p_user": user_id, "p_reason": kw.get("reason"),
              "p_unit_cost": str(kw["unit_cost"]) if kw.get("unit_cost") is not None else None,
              "p_invoice": kw.get("invoice_id"), "p_invoice_item": kw.get("invoice_item_id"),
              "p_transfer": kw.get("transfer_id"), "p_ref": kw.get("ref"), "p_sku": kw.get("sku")}
    try:
        res = db.rpc("stock_apply", params).execute()
    except Exception as exc:
        m = _ERR.search(str(exc))
        if not m:
            logger.error("inventory: stock_apply failed org=%s product=%s: %s", org_id, product_id, exc)
            raise StockError("STOCK_FAILED", "Stock could not be updated. Please try again.", 500)
        code, bucket, number = m.group(1), m.group(2), m.group(3)
        avail = int(number) if number is not None else None
        if code == "STOCK_BAD_LOCATION":
            raise StockError("VALIDATION_ERROR", "Choose one of your locations that is turned on.", 422, "location_id")
        if code == "STOCK_BAD_PRODUCT":
            raise StockError("NOT_FOUND", "Product not found.", 404, "product_id")
        if code == "STOCK_SHORT" or (code == "STOCK_NEGATIVE" and bucket == "on_hand"):
            raise StockError("STOCK_SHORT", _short_message(avail, label), 422, "quantity")
        raise StockError("STOCK_CONFLICT", "Those stock numbers have changed. Refresh and try again.", 409)
    data = getattr(res, "data", None)
    if isinstance(data, list):
        data = data[0] if data else {}
    if kw.get("refresh", True):   # STOCK-3: the website follows every change
        refresh_product(db, org_id, product_id)
    return data or {}


def _require_on(db, org_id: str) -> dict:
    s = get_settings(db, org_id)
    if not s["enabled"]:
        raise StockError("STOCK_OFF", "Turn on stock in Inventory > Settings first.", 422)
    return s


def import_initial(db, org_id: str, user_id: Optional[str], location_id: str) -> dict:
    """Copy today's numbers in once, into one location: each size's Shopify quantity, or the product's
    inventory_count when it has no sizes. Archived products and numbers at or below 0 are skipped."""
    lines = units = 0
    products = 0
    for p in _products(db, org_id):
        if p.get("is_active") is False or str(p.get("status") or "active") == "archived":
            continue
        sizes = inv.product_sizes(p)
        meta = _variant_meta(p)
        todo = []
        if sizes:
            for s in sizes:
                m = meta.get(s["title"].lower()) or {}
                todo.append((s["title"], int(m.get("qty") or 0), m.get("sku")))
        else:
            only = next(iter(meta.values()), {}) if meta else {}
            qty = p.get("inventory_count")
            todo.append(("", int(qty if qty is not None else (only.get("qty") or 0)), only.get("sku")))
        did = False
        for variant, qty, sku in todo:
            if qty <= 0:
                continue
            qty = min(qty, MAX_QTY)
            try:
                apply(db, org_id, user_id, p["id"], variant, location_id, "import", on_hand=qty,
                      reason="Starting stock copied when stock was turned on", sku=sku, refresh=False)
            except StockError as e:
                logger.warning("inventory: import skipped org=%s product=%s size=%s: %s", org_id, p["id"], variant, e.message)
                continue
            lines += 1
            units += qty
            did = True
        products += int(did)
    logger.info("inventory: import org=%s products=%s lines=%s units=%s", org_id, products, lines, units)
    return {"products": products, "lines": lines, "units": units}


def receive(db, org_id: str, user_id: Optional[str], body: dict) -> dict:
    _require_on(db, org_id)
    loc = _location(db, org_id, body.get("location_id"))
    if not loc.get("is_active"):
        raise StockError("VALIDATION_ERROR", "Choose one of your locations that is turned on.", 422, "location_id")
    items = body.get("lines") or []
    if not items or len(items) > 100:
        raise StockError("VALIDATION_ERROR", "Add between 1 and 100 lines.", 422, "lines")
    ref = (str(body.get("ref") or "").strip()[:200]) or None
    note = (str(body.get("note") or "").strip()[:500]) or None
    prods = {p["id"]: p for p in _products(db, org_id, list({str(i.get("product_id")) for i in items if i.get("product_id")}))}
    plan = []
    for n, line in enumerate(items):          # check every line before changing anything
        prod = prods.get(str(line.get("product_id")))
        if not prod:
            raise StockError("NOT_FOUND", f"Line {n + 1}: product not found.", 404, f"lines.{n}.product_id")
        variant = clean_variant(prod, line.get("variant"))
        plan.append((prod, variant, _qty(line.get("quantity"), f"lines.{n}.quantity"),
                     _money(line.get("unit_cost"), f"lines.{n}.unit_cost")))
    done = []
    for prod, variant, qty, cost in plan:
        r = apply(db, org_id, user_id, prod["id"], variant, loc["id"], "receive", on_hand=qty, unit_cost=cost,
                  reason=note, ref=ref)
        done.append({"product_id": prod["id"], "title": prod.get("title"), "variant": variant, "quantity": qty,
                     "on_hand": r.get("on_hand"), "available": r.get("available")})
    return {"location_id": loc["id"], "lines": done, "units": sum(d["quantity"] for d in done)}


def adjust(db, org_id: str, user_id: Optional[str], body: dict) -> dict:
    _require_on(db, org_id)
    loc = _location(db, org_id, body.get("location_id"))
    prod = _product(db, org_id, body.get("product_id"))
    variant = clean_variant(prod, body.get("variant"))
    reason_code = str(body.get("reason") or "")
    if reason_code not in ADJUST_REASONS:
        raise StockError("VALIDATION_ERROR", "Choose a reason.", 422, "reason")
    note = " ".join(str(body.get("note") or "").split())[:400]
    if reason_code == "other" and not note:
        raise StockError("VALIDATION_ERROR", "Say what happened.", 422, "note")
    reason = ADJUST_REASONS[reason_code] + (f": {note}" if note else "")
    mode = body.get("mode")
    label = f"{prod.get('title')}{' ' + variant if variant else ''}"
    if mode == "set":
        r = apply(db, org_id, user_id, prod["id"], variant, loc["id"], "adjust",
                  set_on_hand=_qty(body.get("quantity"), allow_zero=True), reason=reason, label=label)
    elif mode in ("add", "remove"):
        n = _qty(body.get("quantity"))
        r = apply(db, org_id, user_id, prod["id"], variant, loc["id"], "return" if reason_code == "returned" else "adjust",
                  on_hand=n if mode == "add" else -n, reason=reason, label=label)
    else:
        raise StockError("VALIDATION_ERROR", "Choose add, remove or set the count.", 422, "mode")
    return {"product_id": prod["id"], "variant": variant, "location_id": loc["id"], **r}


def update_item(db, org_id: str, body: dict) -> dict:
    """Cost price, reorder level and SKU for one product + size. Creates the item row if it isn't there yet."""
    prod = _product(db, org_id, body.get("product_id"))
    variant = clean_variant(prod, body.get("variant"))
    patch: dict = {"updated_at": _now()}
    if "cost_price" in body:
        cost = _money(body.get("cost_price"), "cost_price")
        patch["cost_price"] = str(cost) if cost is not None else None
    if "reorder_level" in body:
        patch["reorder_level"] = None if body.get("reorder_level") in (None, "") else \
            _qty(body["reorder_level"], "reorder_level", allow_zero=True)
    if "sku" in body:
        patch["sku"] = (str(body.get("sku") or "").strip()[:100]) or None
    rows = _rows(db.table("stock_items").select("id").eq("org_id", org_id).eq("product_id", prod["id"])
                 .eq("variant", variant).limit(1).execute())
    if rows:
        db.table("stock_items").update(patch).eq("id", rows[0]["id"]).eq("org_id", org_id).execute()
        item_id = rows[0]["id"]
    else:
        try:
            item_id = _rows(db.table("stock_items").insert({"org_id": org_id, "product_id": prod["id"], "variant": variant,
                                                            **patch}).execute())[0]["id"]
        except Exception:                      # made at the same moment by someone else: update it instead
            again = _rows(db.table("stock_items").select("id").eq("org_id", org_id).eq("product_id", prod["id"])
                          .eq("variant", variant).limit(1).execute())
            if not again:
                raise
            item_id = again[0]["id"]
            db.table("stock_items").update(patch).eq("id", item_id).eq("org_id", org_id).execute()
    return _rows(db.table("stock_items").select("*").eq("id", item_id).limit(1).execute())[0]


# ───────────────────────────── reading ─────────────────────────────

def _num(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def overview(db, org_id: str, manager: bool, q: Optional[str] = None, location_id: Optional[str] = None,
             low_only: bool = False) -> dict:
    """One row per product + size (active products, plus any old size that still has stock)."""
    settings = get_settings(db, org_id)
    locations = list_locations(db, org_id)
    loc_ids = {l["id"] for l in locations}
    if location_id and str(location_id) not in loc_ids:
        raise StockError("NOT_FOUND", "Location not found.", 404, "location_id")
    items = _rows(db.table("stock_items").select("id, product_id, variant, sku, cost_price, reorder_level")
                  .eq("org_id", org_id).execute())
    by_key = {(i["product_id"], i["variant"] or ""): i for i in items}
    levels: dict = {}
    for lv in _rows(db.table("stock_levels").select("item_id, location_id, on_hand, held, sold_pending, in_transit_in")
                    .eq("org_id", org_id).execute()):
        levels.setdefault(lv["item_id"], []).append(lv)

    rows = []
    seen = set()
    needle = (q or "").strip().lower()
    for p in _products(db, org_id):
        active = p.get("is_active") is not False and str(p.get("status") or "active") != "archived"
        sizes = [s["title"] for s in inv.product_sizes(p)] or [""]
        meta = _variant_meta(p)
        extra = [i["variant"] for (pid, _v), i in by_key.items() if pid == p["id"] and i["variant"] not in sizes]
        for variant in sizes + extra:
            item = by_key.get((p["id"], variant))
            lv = levels.get(item["id"], []) if item else []
            has_stock = any(_num(x.get("on_hand")) or _num(x.get("in_transit_in")) for x in lv)
            if (not active or variant in extra) and not has_stock:
                continue
            seen.add((p["id"], variant))
            per = []
            for x in lv:
                if location_id and x["location_id"] != str(location_id):
                    continue
                on, held, sold = _num(x.get("on_hand")), _num(x.get("held")), _num(x.get("sold_pending"))
                per.append({"location_id": x["location_id"], "on_hand": on, "held": held, "sold_pending": sold,
                            "in_transit_in": _num(x.get("in_transit_in")), "available": on - held - sold})
            tot = {k: sum(x[k] for x in per) for k in ("on_hand", "held", "sold_pending", "in_transit_in", "available")}
            reorder = item.get("reorder_level") if item and item.get("reorder_level") is not None \
                else settings["default_reorder_level"]
            row = {"product_id": p["id"], "title": p.get("title"), "image_url": p.get("image_url"), "variant": variant,
                   "sku": (item or {}).get("sku") or (meta.get(variant.lower()) or {}).get("sku"),
                   "old_size": variant in extra, "product_active": active,
                   "reorder_level": reorder, "low": tot["available"] <= reorder, **tot, "locations": per}
            if manager:
                row["cost_price"] = float(item["cost_price"]) if item and item.get("cost_price") is not None else None
            if needle and needle not in f"{p.get('title') or ''} {variant} {row['sku'] or ''}".lower():
                continue
            if low_only and not row["low"]:
                continue
            rows.append(row)
    rows.sort(key=lambda r: (str(r["title"] or "").lower(), r["variant"].lower()))
    summary = {"lines": len(rows), "units_on_hand": sum(r["on_hand"] for r in rows),
               "units_available": sum(r["available"] for r in rows), "low": sum(1 for r in rows if r["low"])}
    if manager:
        summary["stock_value"] = round(sum((r.get("cost_price") or 0) * r["on_hand"] for r in rows), 2)
        summary["missing_cost"] = sum(1 for r in rows if r["on_hand"] and r.get("cost_price") is None)
    return {"settings": settings, "locations": locations, "items": rows, "summary": summary}


def history(db, org_id: str, product_id: Optional[str] = None, variant: Optional[str] = None,
            location_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> dict:
    q = db.table("stock_moves").select("*").eq("org_id", org_id)
    item_ids = None
    if product_id:
        iq = db.table("stock_items").select("id").eq("org_id", org_id).eq("product_id", str(product_id))
        if variant is not None:
            iq = iq.eq("variant", variant)
        item_ids = [r["id"] for r in _rows(iq.execute())]
        if not item_ids:
            return {"items": [], "more": False}
        q = q.in_("item_id", item_ids)
    if location_id:
        q = q.eq("location_id", str(location_id))
    moves = _rows(q.order("created_at", desc=True).range(offset, offset + limit).execute())
    more = len(moves) > limit
    moves = moves[:limit]
    items = {r["id"]: r for r in _rows(db.table("stock_items").select("id, product_id, variant").eq("org_id", org_id)
                                       .in_("id", list({m["item_id"] for m in moves})).execute())} if moves else {}
    prods = {p["id"]: p for p in _products(db, org_id, list({i["product_id"] for i in items.values()}))} if items else {}
    locs = {l["id"]: l["name"] for l in list_locations(db, org_id)}
    uids = list({m["created_by"] for m in moves if m.get("created_by")})
    users = {u["id"]: (u.get("full_name") or u.get("email")) for u in
             _rows(db.table("users").select("id, full_name, email").eq("org_id", org_id).in_("id", uids).execute())} if uids else {}
    inv_ids = list({m["invoice_id"] for m in moves if m.get("invoice_id")})   # STOCK-2
    numbers = {d["id"]: d.get("number") for d in
               _rows(db.table("invoices").select("id, number").eq("org_id", org_id).in_("id", inv_ids).execute())} if inv_ids else {}
    out = []
    for m in moves:
        it = items.get(m["item_id"]) or {}
        out.append({"id": m["id"], "created_at": m.get("created_at"), "kind": m.get("kind"),
                    "kind_label": KIND_LABEL.get(m.get("kind"), m.get("kind")),
                    "product_id": it.get("product_id"), "title": (prods.get(it.get("product_id")) or {}).get("title"),
                    "variant": it.get("variant") or "", "location_id": m.get("location_id"),
                    "location": locs.get(m.get("location_id")), "change": _num(m.get("d_on_hand")),
                    "held_change": _num(m.get("d_held")), "on_hand_after": _num(m.get("on_hand_after")),
                    "available_after": _num(m.get("on_hand_after")) - _num(m.get("held_after")) - _num(m.get("sold_after")),
                    "reason": m.get("reason"), "ref": m.get("ref"), "invoice_id": m.get("invoice_id"),
                    "invoice_number": numbers.get(m.get("invoice_id")),
                    "by": users.get(m.get("created_by"))})
    return {"items": out, "more": more}
