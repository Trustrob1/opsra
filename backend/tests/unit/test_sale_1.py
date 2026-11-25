"""SALE-1: Make a sale (invoice + issue + payment + delivered in one go), reps see only what they made, and payments
that wait for an admin's OK when the business turns that on."""
from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.test_invoices_1 import LEAD, ORG, USER, _plan_allows  # noqa: F401  (autouse fixture)
from tests.unit.test_stock_2 import BED, PILLOW, REP, _avail, _client, _no_side_effects, _sdb  # noqa: F401
from app.services import invoice_payment_service as pay
from app.services import invoice_report_service as rep
from app.services import invoice_service as inv
from app.services import payment_approval_service as approvals
from app.services import sale_service as sale

REP2 = "99999999-0000-0000-0000-000000000002"
OWNER = {"id": USER, "org_id": ORG, "full_name": "Ada Owner", "roles": {"template": "owner"}}
RITA = {"id": REP, "org_id": ORG, "full_name": "Rita Rep", "roles": {"template": "sales_agent"}}
BOLA = {"id": REP2, "org_id": ORG, "full_name": "Bola Rep", "roles": {"template": "sales_agent"}}


def _db(confirm=False):
    db, main, lagos = _sdb()
    for u in db.rows("users"):
        u["roles"] = {"template": "owner"} if u["id"] == USER else {"template": "sales_agent"}
    db.tables["users"].append({"id": REP2, "org_id": ORG, "full_name": "Bola Rep", "roles": {"template": "sales_agent"}})
    if confirm:
        inv.save_settings(db, ORG, {"payments_need_approval": True})
    return db, main, lagos


def _sale(db, who, main, status="paid", amount=None, delivered=False, qty=1, **kw):
    pay_in = {"status": status}
    if status != "unpaid":
        pay_in.update(method="cash")
    if amount is not None:
        pay_in["amount"] = amount
    body = {"lead_id": LEAD, "location_id": main["id"], "region": "Abuja Sales",
            "items": [{"product_id": BED, "variant": "Queen", "quantity": qty}], "payment": pay_in,
            "delivered": delivered, **kw}
    return sale.create(db, who, body)


def _notes(db, user_id):
    return [n for n in db.rows("notifications") if n["user_id"] == user_id and n["type"] == "payment_approval"]


# ───────────────────────────── making a sale ─────────────────────────────

def test_paid_sale_taken_away_is_one_step():
    db, main, _ = _db()
    out = _sale(db, OWNER, main, delivered=True)
    d = out["invoice"]
    assert d["status"] == "paid" and d["number"] and out["receipt"]["amount"] == 400000
    assert out["delivered"] is True and out["pending_payment"] is None
    lv_after = _avail(db, BED, "Queen", main)
    assert lv_after == 4 and d["items"][0]["stock_delivered"] == 1


def test_part_and_unpaid_sales():
    db, main, _ = _db()
    part = _sale(db, RITA, main, status="part", amount=100000)
    assert part["invoice"]["status"] == "part_paid" and part["receipt"]["owner_id"] == REP
    none = _sale(db, RITA, main, status="unpaid")
    assert none["invoice"]["status"] == "issued" and none["receipt"] is None


def test_sale_checks_come_before_anything_is_saved():
    db, main, _ = _db()
    bad = [
        dict(status="part"),                                     # no amount
        dict(status="unpaid", delivered=True),                   # can't hand over unpaid goods
    ]
    for kw in bad:
        with pytest.raises(inv.InvoiceError):
            _sale(db, RITA, main, **kw)
    with pytest.raises(inv.InvoiceError) as e:
        sale.create(db, RITA, {"lead_id": LEAD, "location_id": main["id"], "items": [{"product_id": BED,
                               "variant": "Queen", "quantity": 1}], "payment": {"status": "paid"}})
    assert e.value.field == "payment.method"
    assert db.rows("invoices") == []
    with pytest.raises(inv.InvoiceError) as e:   # part amount that is really the whole
        _sale(db, RITA, main, status="part", amount=400000)
    assert e.value.field == "payment.amount"


def test_issue_failure_other_than_stock_deletes_the_draft():
    db, main, _ = _db()
    with pytest.raises(inv.InvoiceError) as e:   # the main store has no region, and the business needs one to issue
        _sale(db, RITA, main, region=None)
    assert e.value.field == "region"
    assert db.rows("invoices") == []


def test_short_stock_keeps_the_draft_and_finish_completes_it():
    db, main, lagos = _db()
    with pytest.raises(sale.SaleShort) as e:
        _sale(db, RITA, lagos, qty=4, region="Lagos Sales")
    doc_id = e.value.doc_id
    assert e.value.code == "STOCK_SHORT" and inv.get_doc(db, ORG, doc_id)["status"] == "draft"
    # a manager takes it from the main store, then the sale is finished
    inv.issue(db, ORG, USER, doc_id, sources={i["id"]: main["id"] for i in db.rows("invoice_items")
                                                if i["invoice_id"] == doc_id}, allow_other=True)
    out = sale.finish(db, RITA, doc_id, {"status": "paid", "method": "pos"}, delivered=True)
    assert out["invoice"]["status"] == "paid" and out["delivered"] is True
    with pytest.raises(inv.InvoiceError) as e:   # another rep can't finish it
        sale.finish(db, BOLA, doc_id, {"status": "unpaid"})
    assert e.value.status == 404


# ───────────────────────────── payments waiting for an admin ─────────────────────────────

def test_rep_payment_waits_and_counts_nothing_until_approved():
    db, main, _ = _db(confirm=True)
    out = _sale(db, RITA, main, status="part", amount=150000)
    d, p = out["invoice"], out["pending_payment"]
    assert out["receipt"] is None and p["status"] == "pending" and p["amount"] == 150000
    assert d["status"] == "issued" and Decimal(str(d.get("amount_paid") or 0)) == 0 and db.rows("receipts") == []
    assert len(_notes(db, USER)) == 1 and _notes(db, REP) == []
    with pytest.raises(inv.InvoiceError) as e:   # the waiting amount counts against the balance
        approvals.request_invoice_payment(db, RITA, d["id"], {"amount": "300000", "method": "cash"})
    assert e.value.field == "amount" and "waiting" in e.value.message
    with pytest.raises(inv.InvoiceError) as e:
        approvals.approve(db, RITA, p["id"])
    assert e.value.status == 403
    got = approvals.approve(db, OWNER, p["id"])
    r = got["receipt"]
    assert got["invoice"]["status"] == "part_paid"
    stored = next(x for x in db.rows("receipts") if x["id"] == r["id"])
    assert stored["recorded_by"] == REP and stored["owner_id"] == REP and stored["approved_by"] == USER
    assert next(a for a in db.rows("payment_approvals") if a["id"] == p["id"])["receipt_id"] == r["id"]
    assert len(_notes(db, REP)) == 1
    with pytest.raises(inv.InvoiceError) as e:   # a second click
        approvals.approve(db, OWNER, p["id"])
    assert e.value.status == 409
    with pytest.raises(inv.InvoiceError) as e:   # and a late reject can't undo it
        approvals.reject(db, OWNER, p["id"], "Too late")
    assert e.value.status == 409
    # an admin's payment on a rep's invoice still belongs to the rep
    r2 = pay.record_payment(db, ORG, USER, d["id"], {"amount": "1000", "method": "cash"})["receipt"]
    assert next(x for x in db.rows("receipts") if x["id"] == r2["id"])["owner_id"] == REP


def test_owner_payments_and_setting_off_are_never_held():
    db, main, _ = _db(confirm=True)
    assert _sale(db, OWNER, main)["receipt"] is not None
    db2, main2, _ = _db(confirm=False)
    assert _sale(db2, RITA, main2)["receipt"] is not None


def test_paid_and_taken_away_is_delivered_when_approved():
    db, main, _ = _db(confirm=True)
    out = _sale(db, RITA, main, delivered=True)
    assert out["pending_payment"]["deliver"] is True and out["delivered"] is False
    assert _avail(db, BED, "Queen", main) == 4   # held, not yet gone
    got = approvals.approve(db, OWNER, out["pending_payment"]["id"])
    assert got["fully_paid"] and got["delivered"] is True
    assert inv.get_doc(db, ORG, out["invoice"]["id"])["items"][0]["stock_delivered"] == 1


def test_reject_needs_a_reason_and_cancel_is_for_the_rep():
    db, main, _ = _db(confirm=True)
    d = _sale(db, RITA, main, status="unpaid")["invoice"]
    a1 = approvals.request_invoice_payment(db, RITA, d["id"], {"amount": "100000", "method": "cash"})
    a2 = approvals.request_invoice_payment(db, RITA, d["id"], {"amount": "50000", "method": "pos"})
    with pytest.raises(inv.InvoiceError):
        approvals.reject(db, OWNER, a1["id"], " ")
    out = approvals.reject(db, OWNER, a1["id"], "No transfer seen")
    assert out["status"] == "rejected" and out["decision_note"] == "No transfer seen"
    assert "No transfer seen" in _notes(db, REP)[-1]["body"]
    with pytest.raises(inv.InvoiceError) as e:
        approvals.cancel(db, BOLA, a2["id"])
    assert e.value.status == 404
    assert approvals.cancel(db, RITA, a2["id"])["status"] == "cancelled"
    assert approvals.waiting_total(db, ORG, d["id"]) == 0
    assert approvals.list_approvals(db, BOLA)["items"] == []
    assert [a["id"] for a in approvals.list_approvals(db, RITA, "rejected")["items"]] == [a1["id"]]


def test_void_rejects_what_is_waiting():
    db, main, _ = _db(confirm=True)
    out = _sale(db, RITA, main, status="part", amount=100000)
    inv.void(db, ORG, USER, out["invoice"]["id"], "Customer changed their mind")
    a = next(x for x in db.rows("payment_approvals") if x["id"] == out["pending_payment"]["id"])
    assert a["status"] == "rejected" and a["decision_note"] == "Invoice voided"
    with pytest.raises(inv.InvoiceError):
        approvals.approve(db, OWNER, a["id"])


def test_standalone_receipt_waits_and_failed_approval_goes_back_to_pending():
    db, main, _ = _db(confirm=True)
    a = approvals.request_standalone(db, RITA, {"customer_name": "Walk-in", "amount": "20000", "method": "cash",
                                                "description": "Pillow", "region": "Abuja Sales"})
    assert a["kind"] == "standalone" and db.rows("receipts") == []
    got = approvals.approve(db, OWNER, a["id"])
    stored = next(x for x in db.rows("receipts") if x["id"] == got["receipt"]["id"])
    assert stored["owner_id"] == REP and stored["approved_by"] == USER and stored["invoice_id"] is None
    # an invoice payment that no longer fits (paid meanwhile) is refused and stays waiting
    d = _sale(db, OWNER, main, status="unpaid")["invoice"]
    db.rows("invoices")[-1]["created_by"] = REP
    w = approvals.request_invoice_payment(db, RITA, d["id"], {"amount": "400000", "method": "cash"})
    pay.record_payment(db, ORG, USER, d["id"], {"amount": "400000", "method": "pos"})
    with pytest.raises(inv.InvoiceError):
        approvals.approve(db, OWNER, w["id"])
    assert next(x for x in db.rows("payment_approvals") if x["id"] == w["id"])["status"] == "pending"


# ───────────────────────────── reps see only their own ─────────────────────────────

def test_lists_summary_and_reports_are_own_only():
    db, main, _ = _db()
    mine = _sale(db, RITA, main, status="part", amount=100000)
    theirs = _sale(db, BOLA, main, status="part", amount=50000)
    assert [d["id"] for d in inv.list_docs(db, ORG, mine=REP)["items"]] == [mine["invoice"]["id"]]
    assert len(inv.list_docs(db, ORG)["items"]) == 2
    assert [r["id"] for r in pay.list_receipts(db, ORG, mine=REP)["items"]] == [mine["receipt"]["id"]]
    assert inv.summary(db, ORG, mine=REP2)["outstanding_count"] == 1
    assert pay.paid_this_month(db, ORG, mine=REP) == 100000
    assert pay.paid_this_month(db, ORG) == 150000
    assert rep.receipts_csv(db, ORG, mine=REP2).count(theirs["receipt"]["number"]) == 1
    assert mine["receipt"]["number"] not in rep.receipts_csv(db, ORG, mine=REP2)
    assert len(sale.my_sales(db, RITA)["items"]) == 1 and len(sale.my_sales(db, OWNER)["items"]) == 2


def test_routes_guard_other_reps_documents_and_receipts():
    db, main, _ = _db(confirm=True)
    rita, bola, boss = _client(db, RITA), _client(db, BOLA), _client(db, OWNER)
    body = {"lead_id": LEAD, "location_id": main["id"], "region": "Abuja Sales",
            "items": [{"product_id": BED, "variant": "Queen", "quantity": 1}],
            "payment": {"status": "part", "amount": "100000", "method": "cash"}}
    r = rita.post("/api/v1/sales", json=body)
    assert r.status_code == 201, r.json()
    d, p = r.json()["data"]["invoice"], r.json()["data"]["pending_payment"]
    assert rita.get(f"/api/v1/invoices/{d['id']}").json()["data"]["pending_payments"][0]["id"] == p["id"]
    for path in (f"/api/v1/invoices/{d['id']}", f"/api/v1/invoices/{d['id']}/pdf"):
        assert bola.get(path).status_code == 404
    assert bola.post(f"/api/v1/invoices/{d['id']}/payments", json={"amount": "10", "method": "cash"}).status_code == 404
    assert bola.get("/api/v1/invoices").json()["data"]["items"] == []
    assert boss.get("/api/v1/invoices/summary").json()["data"]["payments_waiting"] == 1
    assert rita.post(f"/api/v1/payments/approvals/{p['id']}/approve").status_code == 403
    assert len(boss.get("/api/v1/payments/approvals").json()["data"]["items"]) == 1
    got = boss.post(f"/api/v1/payments/approvals/{p['id']}/approve").json()["data"]
    rid = got["receipt"]["id"]
    assert "public_token" not in got["receipt"]
    assert rita.get(f"/api/v1/receipts/{rid}/send-options").status_code == 200
    assert bola.get(f"/api/v1/receipts/{rid}/pdf").status_code == 404
    assert bola.get("/api/v1/receipts").json()["data"]["items"] == []
    # rep payments wait on the ordinary routes too
    r = rita.post(f"/api/v1/invoices/{d['id']}/payments", json={"amount": "1000", "method": "cash"}).json()["data"]
    assert r["receipt"] is None and r["pending_payment"]["status"] == "pending"
    r = rita.post("/api/v1/receipts", json={"customer_name": "Walk-in", "amount": "500", "method": "cash",
                                            "description": "Pillow", "region": "Abuja Sales"}).json()["data"]
    assert r["pending_payment"]["kind"] == "standalone"
    # short stock keeps the draft and tells the screen which one
    short = rita.post("/api/v1/sales", json={**body, "items": [{"product_id": BED, "variant": "Queen", "quantity": 50}]})
    assert short.status_code == 422 and short.json()["error"]["code"] == "STOCK_SHORT"
    assert short.json()["data"]["doc_id"]
    # the setting is admin-only and round-trips
    assert rita.put("/api/v1/invoices/settings", json={"payments_need_approval": False}).status_code == 403
    assert boss.put("/api/v1/invoices/settings", json={"payments_need_approval": False}).json()["data"][
        "payments_need_approval"] is False
