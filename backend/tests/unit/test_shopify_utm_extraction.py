"""
tests/unit/test_shopify_utm_extraction.py
GPM-1D — 6 unit tests for _parse_utm_from_url and handle_order_created.
"""
from unittest.mock import MagicMock, patch, call
import pytest

from app.services.shopify_service import _parse_utm_from_url, handle_order_created


# ---------------------------------------------------------------------------
# _parse_utm_from_url tests
# ---------------------------------------------------------------------------

def test_parse_utm_full_string():
    url = "https://example.com/?utm_source=facebook&utm_campaign=summer_sale&utm_medium=cpc&utm_ad=ad_001"
    result = _parse_utm_from_url(url)
    assert result["utm_source"]   == "facebook"
    assert result["utm_campaign"] == "summer_sale"
    assert result["utm_medium"]   == "cpc"
    assert result["utm_ad"]       == "ad_001"


def test_parse_utm_partial_source_only():
    url = "https://example.com/products/shirt?utm_source=instagram"
    result = _parse_utm_from_url(url)
    assert result["utm_source"]   == "instagram"
    assert result["utm_campaign"] is None
    assert result["utm_medium"]   is None
    assert result["utm_ad"]       is None


def test_parse_utm_no_params():
    url = "https://example.com/collections/all"
    result = _parse_utm_from_url(url)
    assert result == {"utm_source": None, "utm_campaign": None, "utm_medium": None, "utm_ad": None}


def test_parse_utm_malformed_url_no_exception():
    result = _parse_utm_from_url("not a valid :// url %%")
    # Must not raise — returns all-None
    assert result["utm_source"]   is None
    assert result["utm_campaign"] is None
    assert result["utm_medium"]   is None
    assert result["utm_ad"]       is None


def test_parse_utm_empty_string_no_exception():
    result = _parse_utm_from_url("")
    assert result == {"utm_source": None, "utm_campaign": None, "utm_medium": None, "utm_ad": None}


# ---------------------------------------------------------------------------
# handle_order_created: landing_site UTM stored on commerce_session
# ---------------------------------------------------------------------------

def test_handle_order_created_landing_site_utm_stored_on_session():
    """
    When order["landing_site"] has UTM params, they should be written to the
    matching commerce_session row.
    """
    db = MagicMock()

    order = {
        "id":           9001,
        "name":         "#1001",
        "phone":        "+2348000000001",
        "landing_site": "https://myshop.com/?utm_source=facebook&utm_campaign=promo&utm_ad=ad_42",
    }

    # commerce_sessions.update (close open session) — return nothing special
    close_chain = MagicMock()
    close_chain.eq.return_value = close_chain
    close_chain.execute.return_value = MagicMock(data=[])

    # commerce_sessions lookup for UTM update — return a matching session
    session_row = {"id": "cs-001", "lead_id": None}
    lookup_chain = MagicMock()
    lookup_chain.select.return_value = lookup_chain
    lookup_chain.eq.return_value = lookup_chain
    lookup_chain.maybe_single.return_value = lookup_chain
    lookup_chain.execute.return_value = MagicMock(data=session_row)

    # commerce_sessions update for UTM write
    utm_update_chain = MagicMock()
    utm_update_chain.eq.return_value = utm_update_chain
    utm_update_chain.execute.return_value = MagicMock(data=[])

    # Route db.table() calls
    update_calls = []

    def table_router(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = MagicMock(data=session_row if name == "commerce_sessions" else [])

        def update_capture(payload):
            update_calls.append((name, payload))
            uc = MagicMock()
            uc.eq.return_value = uc
            uc.execute.return_value = MagicMock(data=[])
            return uc

        chain.update.side_effect = update_capture
        return chain

    db.table.side_effect = table_router

    with patch("app.services.whatsapp_service.send_order_confirmation_message"):
        handle_order_created(db=db, org_id="org-1", order=order)

    # At least one update to commerce_sessions should carry utm_source
    utm_updates = [p for (name, p) in update_calls if name == "commerce_sessions" and "utm_source" in p]
    assert len(utm_updates) >= 1
    assert utm_updates[0]["utm_source"] == "facebook"
    assert utm_updates[0].get("utm_campaign") == "promo"
    assert utm_updates[0].get("utm_ad") == "ad_42"
