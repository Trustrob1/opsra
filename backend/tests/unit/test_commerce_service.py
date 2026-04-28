"""
tests/unit/test_commerce_service.py
COMM-1 — Unit tests for app/services/commerce_service.py

Pattern 63: all patch paths derived from import statements in commerce_service.py.
  httpx is imported at module level → patch "app.services.commerce_service.httpx"
  No app-level imports in commerce_service (no lazy imports to worry about).
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from app.services.commerce_service import (
    get_or_create_commerce_session,
    add_to_cart,
    remove_from_cart,
    get_cart_summary,
    generate_shopify_checkout,
    mark_cart_completed,
    mark_cart_abandoned,
    convert_lead_on_purchase,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_ID   = "org-111"
PHONE    = "+2348012345678"
LEAD_ID  = "lead-aaa"
CUST_ID  = "cust-bbb"
SESSION_ID = "sess-ccc"


def _db():
    """Return a minimal MagicMock Supabase client."""
    db = MagicMock()
    # Default: table().select()...execute() returns empty
    db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .in_.return_value.order.return_value.limit.return_value.execute.return_value \
        .data = []
    db.table.return_value.insert.return_value.execute.return_value.data = []
    db.table.return_value.update.return_value.eq.return_value.execute.return_value = None
    return db


def _session(**kwargs):
    base = {
        "id": SESSION_ID,
        "org_id": ORG_ID,
        "phone_number": PHONE,
        "status": "open",
        "cart": [],
        "subtotal": 0,
    }
    base.update(kwargs)
    return base


def _product(**kwargs):
    base = {
        "id": "prod-1",
        "shopify_id": "sp-1",
        "title": "Test Bag",
        "price": 5000.0,
        "image_url": "https://cdn.shopify.com/bag.jpg",
        "variants": [
            {"id": "var-1", "title": "Red", "price": "5000.00"},
            {"id": "var-2", "title": "Blue", "price": "4500.00"},
        ],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# get_or_create_commerce_session
# ---------------------------------------------------------------------------

class TestGetOrCreateCommerceSession:

    def test_returns_existing_session(self):
        db = _db()
        existing = _session(status="open")
        db.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .in_.return_value.order.return_value.limit.return_value.execute.return_value \
            .data = [existing]

        result = get_or_create_commerce_session(db, ORG_ID, PHONE)

        assert result["id"] == SESSION_ID
        db.table.return_value.insert.assert_not_called()

    def test_creates_new_session_with_lead_id(self):
        db = _db()
        # No existing session
        db.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .in_.return_value.order.return_value.limit.return_value.execute.return_value \
            .data = []
        new_session = _session(lead_id=LEAD_ID)
        db.table.return_value.insert.return_value.execute.return_value.data = [new_session]

        result = get_or_create_commerce_session(db, ORG_ID, PHONE, lead_id=LEAD_ID)

        insert_call = db.table.return_value.insert.call_args[0][0]
        assert insert_call["lead_id"] == LEAD_ID
        assert insert_call["status"] == "open"

    def test_creates_new_session_with_customer_id(self):
        db = _db()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .in_.return_value.order.return_value.limit.return_value.execute.return_value \
            .data = []
        new_session = _session(customer_id=CUST_ID)
        db.table.return_value.insert.return_value.execute.return_value.data = [new_session]

        get_or_create_commerce_session(db, ORG_ID, PHONE, customer_id=CUST_ID)

        insert_call = db.table.return_value.insert.call_args[0][0]
        assert insert_call["customer_id"] == CUST_ID

    def test_s14_returns_empty_dict_on_exception(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        result = get_or_create_commerce_session(db, ORG_ID, PHONE)

        assert result == {}


# ---------------------------------------------------------------------------
# add_to_cart
# ---------------------------------------------------------------------------

class TestAddToCart:

    def _setup_db_update(self, db):
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = None

    def test_appends_new_item_and_calculates_subtotal(self):
        db = _db()
        self._setup_db_update(db)
        session = _session()
        product = _product()

        result = add_to_cart(db, session, product, "var-1", quantity=2)

        cart = result["cart"]
        assert len(cart) == 1
        assert cart[0]["variant_id"] == "var-1"
        assert cart[0]["quantity"] == 2
        assert cart[0]["name"] == "Test Bag — Red"
        assert cart[0]["price"] == 5000.0
        assert result["subtotal"] == 10000.0

    def test_increments_existing_item(self):
        db = _db()
        self._setup_db_update(db)
        session = _session(cart=[{
            "id": "prod-1", "shopify_id": "sp-1",
            "variant_id": "var-1", "name": "Test Bag — Red",
            "price": 5000.0, "quantity": 1, "image_url": None,
        }])
        product = _product()

        result = add_to_cart(db, session, product, "var-1", quantity=1)

        assert len(result["cart"]) == 1
        assert result["cart"][0]["quantity"] == 2
        assert result["subtotal"] == 10000.0

    def test_multiple_items_different_variants(self):
        db = _db()
        self._setup_db_update(db)
        session = _session()
        product = _product()

        result = add_to_cart(db, session, product, "var-1", quantity=1)
        result = add_to_cart(db, result, product, "var-2", quantity=1)

        assert len(result["cart"]) == 2
        assert result["subtotal"] == 5000.0 + 4500.0

    def test_includes_shopify_id_and_image_url(self):
        db = _db()
        self._setup_db_update(db)
        session = _session()
        product = _product()

        result = add_to_cart(db, session, product, "var-1")

        item = result["cart"][0]
        assert item["shopify_id"] == "sp-1"
        assert item["image_url"] == "https://cdn.shopify.com/bag.jpg"

    def test_s14_returns_session_unchanged_on_exception(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")
        session = _session(cart=[{"variant_id": "var-1", "quantity": 1, "price": 100}])

        result = add_to_cart(db, session, _product(), "var-1")

        assert result is session  # returned unchanged


# ---------------------------------------------------------------------------
# remove_from_cart
# ---------------------------------------------------------------------------

class TestRemoveFromCart:

    def test_removes_item_by_product_id(self):
        db = MagicMock()
        session_data = _session(cart=[
            {"id": "prod-1", "variant_id": "var-1", "price": 5000.0, "quantity": 1},
            {"id": "prod-2", "variant_id": "var-2", "price": 2000.0, "quantity": 2},
        ])
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value \
            .execute.return_value.data = session_data
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = None

        result = remove_from_cart(db, SESSION_ID, "prod-1")

        assert len(result["cart"]) == 1
        assert result["cart"][0]["id"] == "prod-2"
        assert result["subtotal"] == 4000.0

    def test_s14_returns_empty_dict_on_exception(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        result = remove_from_cart(db, SESSION_ID, "prod-1")

        assert result == {}


# ---------------------------------------------------------------------------
# get_cart_summary
# ---------------------------------------------------------------------------

class TestGetCartSummary:

    def test_empty_cart(self):
        result = get_cart_summary(_session())
        assert result == "🛒 Your cart is empty."

    def test_correct_format_single_item(self):
        session = _session(cart=[{
            "name": "Test Bag — Red", "price": 5000.0, "quantity": 2
        }], subtotal=10000.0)
        result = get_cart_summary(session)

        assert "Test Bag — Red" in result
        assert "x2" in result
        assert "₦10,000" in result
        assert "Total" in result

    def test_correct_format_multiple_items(self):
        session = _session(cart=[
            {"name": "Product A", "price": 3000.0, "quantity": 1},
            {"name": "Product B", "price": 2000.0, "quantity": 3},
        ], subtotal=9000.0)
        result = get_cart_summary(session)

        assert "Product A" in result
        assert "Product B" in result
        assert "₦9,000" in result


# ---------------------------------------------------------------------------
# generate_shopify_checkout
# ---------------------------------------------------------------------------

class TestGenerateShopifyCheckout:

    def _make_db(self, shopify_connected=True):
        db = MagicMock()
        # org credentials
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value \
            .execute.return_value.data = {
                "shopify_connected": shopify_connected,
                "shopify_shop_domain": "testshop.myshopify.com",
                "shopify_access_token": "shpat_test123",
            }
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = None
        return db

    def test_calls_draft_orders_api_and_returns_url(self):
        db = self._make_db()
        session = _session(cart=[
            {"variant_id": "var-1", "name": "Test Bag — Red", "price": 5000.0, "quantity": 1}
        ])
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "draft_order": {"invoice_url": "https://checkout.myshopify.com/inv/123"}
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.commerce_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            result = generate_shopify_checkout(db, ORG_ID, session)

        assert result == "https://checkout.myshopify.com/inv/123"
        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1]["json"]
        assert "line_items" in body["draft_order"]
        assert len(body["draft_order"]["line_items"]) == 1

    def test_prepopulates_phone_on_draft_order(self):
        db = self._make_db()
        session = _session(cart=[
            {"variant_id": "var-1", "name": "Bag", "price": 5000.0, "quantity": 1}
        ])
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "draft_order": {"invoice_url": "https://checkout.myshopify.com/inv/456"}
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.commerce_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            generate_shopify_checkout(db, ORG_ID, session)

        body = mock_client.post.call_args[1]["json"]
        assert body["draft_order"]["customer"]["phone"] == PHONE

    def test_updates_session_status_to_checkout_sent(self):
        db = self._make_db()
        session = _session(cart=[
            {"variant_id": "var-1", "name": "Bag", "price": 5000.0, "quantity": 1}
        ])
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "draft_order": {"invoice_url": "https://checkout.myshopify.com/inv/789"}
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.commerce_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            generate_shopify_checkout(db, ORG_ID, session)

        update_call = db.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "checkout_sent"
        assert update_call["checkout_url"] == "https://checkout.myshopify.com/inv/789"

    def test_s14_returns_existing_url_on_api_failure(self):
        db = self._make_db()
        session = _session(
            cart=[{"variant_id": "var-1", "name": "Bag", "price": 5000.0, "quantity": 1}],
            checkout_url="https://existing.myshopify.com/old",
        )
        with patch("app.services.commerce_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.side_effect = RuntimeError("Shopify timeout")

            result = generate_shopify_checkout(db, ORG_ID, session)

        assert result == "https://existing.myshopify.com/old"

    def test_s14_returns_empty_string_on_shopify_not_connected(self):
        db = self._make_db(shopify_connected=False)
        session = _session(cart=[
            {"variant_id": "var-1", "name": "Bag", "price": 5000.0, "quantity": 1}
        ])

        result = generate_shopify_checkout(db, ORG_ID, session)

        assert result == ""


# ---------------------------------------------------------------------------
# mark_cart_completed
# ---------------------------------------------------------------------------

class TestMarkCartCompleted:

    def test_updates_status_and_order_id(self):
        db = MagicMock()
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = None

        mark_cart_completed(db, SESSION_ID, shopify_order_id=98765)

        call = db.table.return_value.update.call_args[0][0]
        assert call["status"] == "completed"
        assert call["shopify_order_id"] == 98765
        assert "completed_at" in call

    def test_s14_never_raises(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        # Must not raise
        mark_cart_completed(db, SESSION_ID, 12345)


# ---------------------------------------------------------------------------
# mark_cart_abandoned
# ---------------------------------------------------------------------------

class TestMarkCartAbandoned:

    def test_updates_status_and_abandoned_at(self):
        db = MagicMock()
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = None

        mark_cart_abandoned(db, SESSION_ID)

        call = db.table.return_value.update.call_args[0][0]
        assert call["status"] == "abandoned"
        assert "abandoned_at" in call

    def test_s14_never_raises(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        mark_cart_abandoned(db, SESSION_ID)


# ---------------------------------------------------------------------------
# convert_lead_on_purchase
# ---------------------------------------------------------------------------

class TestConvertLeadOnPurchase:

    def _make_db(self):
        db = MagicMock()
        # lead stage fetch
        db.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {"stage": "qualified"}
        db.table.return_value.update.return_value.eq.return_value.eq.return_value \
            .execute.return_value = None
        db.table.return_value.insert.return_value.execute.return_value = None
        return db

    def test_sets_lead_stage_to_converted(self):
        db = self._make_db()

        convert_lead_on_purchase(db, ORG_ID, LEAD_ID)

        update_calls = db.table.return_value.update.call_args_list
        lead_update = next(
            (c for c in update_calls if "stage" in (c[0][0] if c[0] else {})),
            None,
        )
        assert lead_update is not None
        assert lead_update[0][0]["stage"] == "converted"
        assert "converted_at" in lead_update[0][0]

    def test_writes_audit_log(self):
        db = self._make_db()

        convert_lead_on_purchase(db, ORG_ID, LEAD_ID)

        insert_call = db.table.return_value.insert.call_args[0][0]
        assert insert_call["action"] == "lead.converted_via_commerce"
        assert insert_call["new_value"]["stage"] == "converted"

    def test_s14_never_raises(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        convert_lead_on_purchase(db, ORG_ID, LEAD_ID)


# ---------------------------------------------------------------------------
# S14 omnibus — every public function swallows exceptions
# ---------------------------------------------------------------------------

class TestS14Compliance:

    @pytest.mark.parametrize("fn,args", [
        (get_or_create_commerce_session, (MagicMock(), ORG_ID, PHONE)),
        (add_to_cart, (MagicMock(), {"id": "s1", "cart": []}, {"id": "p1", "variants": []}, "v1")),
        (remove_from_cart, (MagicMock(), SESSION_ID, "prod-1")),
        (get_cart_summary, ({"cart": None},)),
        (generate_shopify_checkout, (MagicMock(), ORG_ID, {"id": "s1", "cart": [], "phone_number": PHONE})),
        (mark_cart_completed, (MagicMock(), SESSION_ID, 123)),
        (mark_cart_abandoned, (MagicMock(), SESSION_ID)),
        (convert_lead_on_purchase, (MagicMock(), ORG_ID, LEAD_ID)),
    ])
    def test_never_raises(self, fn, args):
        """Each function must swallow all exceptions (S14)."""
        db = MagicMock()
        db.table.side_effect = RuntimeError("simulated DB failure")
        # Patch httpx for generate_shopify_checkout
        with patch("app.services.commerce_service.httpx.Client") as m:
            m.side_effect = RuntimeError("simulated")
            try:
                fn(*args)
            except Exception as exc:
                pytest.fail(f"{fn.__name__} raised {type(exc).__name__}: {exc}")
