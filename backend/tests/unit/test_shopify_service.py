"""
tests/unit/test_shopify_service.py
SHOP-1A — unit tests (12 tests)
"""
import pytest
from unittest.mock import MagicMock, patch
from app.services import shopify_service as svc


# ── verify_webhook ────────────────────────────────────────────────────────────

def test_verify_webhook_valid():
    import base64, hashlib, hmac as _hmac
    secret = "test_secret"
    body = b'{"id": 1}'
    sig = base64.b64encode(
        _hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    assert svc.verify_webhook(body, sig, secret) is True


def test_verify_webhook_invalid():
    assert svc.verify_webhook(b'{"id": 1}', "bad_signature", "test_secret") is False


def test_verify_webhook_missing_header():
    assert svc.verify_webhook(b'{"id": 1}', None, "test_secret") is False


def test_verify_webhook_empty_secret():
    assert svc.verify_webhook(b'{"id": 1}', "anything", "") is False


# ── sync_product ──────────────────────────────────────────────────────────────

def test_sync_product_new():
    db = MagicMock()
    upsert_chain = MagicMock()
    upsert_chain.execute.return_value = MagicMock(data=[{"id": "prod-1"}])
    db.table.return_value.upsert.return_value = upsert_chain

    product = {
        "id": 123456,
        "title": "Test Shirt",
        "body_html": "<p>A shirt</p>",
        "handle": "test-shirt",
        "status": "active",
        "images": [{"src": "https://cdn.shopify.com/test.jpg"}],
        "variants": [{"price": "19.99", "compare_at_price": "24.99"}],
        "tags": "cotton, sale",
    }
    result = svc.sync_product(db, "org-1", product)
    assert result == {"id": "prod-1"}
    db.table("products").upsert.assert_called_once()


def test_sync_product_upsert_called_with_correct_shopify_id():
    db = MagicMock()
    upsert_chain = MagicMock()
    upsert_chain.execute.return_value = MagicMock(data=[{"id": "prod-1"}])
    db.table.return_value.upsert.return_value = upsert_chain

    svc.sync_product(db, "org-1", {"id": 999, "title": "Item", "status": "active"})
    call_args = db.table("products").upsert.call_args
    row = call_args[0][0]
    assert row["shopify_id"] == 999


# ── handle_product_deleted ────────────────────────────────────────────────────

def test_handle_product_deleted():
    db = MagicMock()
    update_chain = MagicMock()
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[])
    db.table.return_value.update.return_value = update_chain

    svc.handle_product_deleted(db, "org-1", 123456)
    db.table("products").update.assert_called_once()
    call_kwargs = db.table("products").update.call_args[0][0]
    assert call_kwargs["is_active"] is False
    assert call_kwargs["status"] == "archived"


# ── bulk_sync_products ────────────────────────────────────────────────────────

def test_bulk_sync_products_returns_count():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    products = [{"id": i, "title": f"P{i}", "status": "active"} for i in range(3)]

    with patch("httpx.Client") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"products": products}
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_response

        with patch.object(svc, "sync_product", return_value={"id": "x"}) as mock_sync:
            result = svc.bulk_sync_products(db, "org-1", "token", "shop.myshopify.com")

    assert result["synced"] == 3
    assert result["failed"] == 0


# ── handle_abandoned_cart ─────────────────────────────────────────────────────

def test_handle_abandoned_cart_with_existing_lead():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=None)
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    checkout = {
        "id": 1001,
        "phone": "+2348012345678",
        "abandoned_checkout_url": "https://shop.com/checkouts/1",
        "line_items": [{"title": "Shirt", "quantity": 1, "price": "10.00"}],
    }

    with patch.object(svc, "_match_phone_to_record", return_value=("lead-1", None)):
        with patch("app.services.whatsapp_service.send_abandoned_cart_message") as mock_send:
            svc.handle_abandoned_cart(db, "org-1", checkout)

    mock_send.assert_called_once()


def test_handle_abandoned_cart_new_contact_auto_creates_lead():
    """New contact (no existing record) — lead auto-created, message still sent."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=None)
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    checkout = {
        "id": 1002,
        "phone": "+2348099999999",
        "abandoned_checkout_url": "https://shop.com/checkouts/2",
        "billing_address": {"name": "John Doe"},
        "line_items": [{"title": "Cap", "quantity": 1, "price": "5.00"}],
    }

    with patch.object(svc, "_match_phone_to_record", return_value=(None, None)):
        with patch.object(svc, "_auto_create_lead_from_checkout", return_value="new-lead-1") as mock_create:
            with patch("app.services.whatsapp_service.send_abandoned_cart_message") as mock_send:
                svc.handle_abandoned_cart(db, "org-1", checkout)

    mock_create.assert_called_once()
    mock_send.assert_called_once()


def test_handle_abandoned_cart_no_phone_skips_entirely():
    """No phone on checkout — nothing created, no message sent."""
    db = MagicMock()
    checkout = {"id": 1003, "phone": "", "line_items": []}

    with patch("app.services.whatsapp_service.send_abandoned_cart_message") as mock_send:
        svc.handle_abandoned_cart(db, "org-1", checkout)

    mock_send.assert_not_called()


# ── handle_order_created ──────────────────────────────────────────────────────

def test_handle_order_created_sends_confirmation():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

    order = {
        "id": 9001,
        "name": "#1001",
        "phone": "+2348012345678",
        "total_price": "29.99",
    }

    with patch("app.services.whatsapp_service.send_order_confirmation_message") as mock_send:
        svc.handle_order_created(db, "org-1", order)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args[1]
    assert call_kwargs["order_name"] == "#1001"
    assert call_kwargs["total"] == "29.99"


# ── handle_fulfillment_created ────────────────────────────────────────────────

def test_handle_fulfillment_with_tracking():
    db = MagicMock()
    fulfillment = {
        "tracking_info": {"url": "https://track.dhl.com/xyz", "company": "DHL"},
        "order": {"phone": "+2348012345678"},
    }

    with patch("app.services.whatsapp_service.send_fulfillment_message") as mock_send:
        svc.handle_fulfillment_created(db, "org-1", fulfillment)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args[1]
    assert call_kwargs["tracking_url"] == "https://track.dhl.com/xyz"
    assert call_kwargs["tracking_company"] == "DHL"


def test_handle_fulfillment_without_tracking():
    db = MagicMock()
    fulfillment = {
        "tracking_info": {},
        "order": {"phone": "+2348012345678"},
    }

    with patch("app.services.whatsapp_service.send_fulfillment_message") as mock_send:
        svc.handle_fulfillment_created(db, "org-1", fulfillment)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args[1]
    assert call_kwargs["tracking_url"] is None
