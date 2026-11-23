"""ORDER-PAID-1: a team member marks a held web chat order as paid from the conversation."""
from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from app.services import webchat_order_service as orders
from app.services import webchat_service as wc
from tests.unit.test_webchat_3b import ORG, _session, _shop_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
FE = ROOT.parent / "frontend" / "src"


def _held(db, status="awaiting_stock"):
    s = _session(db)
    s["lead_id"] = "lead-1"
    s["state"]["pending_order"] = {"summary": "Cotton Pillow x1 = ₦50,000", "total": 50000.0, "at": "2026-11-23T19:00:00+00:00", "status": status}
    s["state"]["last_checkout"] = {"total": 50000.0, "reference": "ref-1"}
    return s


def test_no_order_means_no_view():
    db = _shop_db(); s = _session(db); s["lead_id"] = "lead-1"
    with patch.object(wc, "latest_session_for_lead", return_value=s):
        assert orders.order_view(db, ORG, "lead-1") is None


def test_view_shows_status_total_and_summary():
    db = _shop_db(); s = _held(db, "receipt_uploaded")
    with patch.object(wc, "latest_session_for_lead", return_value=s):
        v = orders.order_view(db, ORG, "lead-1")
    assert v["status"] == "receipt_uploaded" and v["total"] == 50000.0 and "Cotton Pillow" in v["summary"]


def test_mark_paid_records_paid_event_timeline_and_tells_the_customer():
    db = _shop_db(); s = _held(db)
    with patch.object(wc, "latest_session_for_lead", return_value=s), patch.object(wc, "rep_send") as rs, \
         patch("app.services.lead_service.write_timeline_event") as tl:
        v = orders.mark_paid(db, ORG, "lead-1", "user-1", "Tolu Olukoya")
    assert v["status"] == "paid" and v["paid_by_name"] == "Tolu Olukoya"
    ev = [r for r in db.rows("webchat_events") if r["kind"] == "paid"]
    assert len(ev) == 1 and ev[0]["value_kobo"] == 5000000 and ev[0]["ref"] == "ref-1"
    assert "₦50,000" in tl.call_args.kwargs["description"] and tl.call_args.kwargs["actor_id"] == "user-1"
    assert "received your payment of ₦50,000" in rs.call_args[0][3]


def test_marking_twice_is_refused_and_counts_once():
    db = _shop_db(); s = _held(db)
    with patch.object(wc, "latest_session_for_lead", return_value=s), patch.object(wc, "rep_send"), patch("app.services.lead_service.write_timeline_event"):
        orders.mark_paid(db, ORG, "lead-1", "u", "A")
        with pytest.raises(ValueError):
            orders.mark_paid(db, ORG, "lead-1", "u", "A")
    assert len([r for r in db.rows("webchat_events") if r["kind"] == "paid"]) == 1


def test_mark_paid_without_an_order_is_refused():
    db = _shop_db(); s = _session(db); s["lead_id"] = "lead-1"
    with patch.object(wc, "latest_session_for_lead", return_value=s):
        with pytest.raises(LookupError):
            orders.mark_paid(db, ORG, "lead-1", "u", "A")


def test_routes_check_the_lead_belongs_to_the_business():
    r = (ROOT / "app" / "routers" / "webchat.py").read_text(encoding="utf-8")
    assert '@router.get("/conversations/webchat/order")' in r
    assert '@router.post("/conversations/webchat/order/mark-paid")' in r
    assert r.count("_lead_of_org(db, org,") == 2
    assert '.eq("org_id", org["org_id"])' in r


def test_inbox_shows_the_order_bar_only_for_web_chat_leads():
    m = (FE / "modules" / "conversations" / "ConversationsModule.jsx").read_text(encoding="utf-8")
    assert "{isWebchat && isLead && active.contact_id && <WebchatOrderBar leadId={active.contact_id} refreshKey={messages.length} onChanged={onRefresh} />}" in m
    b = (FE / "modules" / "conversations" / "WebchatOrderBar.jsx").read_text(encoding="utf-8")
    assert "Payment received?" in b and "Yes, mark as paid" in b and "Mark as paid" in b
    assert "markWebchatOrderPaid(leadId)" in b
