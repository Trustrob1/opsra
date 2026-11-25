"""REPORT-1: sales + inventory reports (JSON / PDF / CSV, admins only), owner report emails (daily + weekly, sent once),
per-rep payment confirmation and named confirmers, and the receipts CSV's Recorded by / Region columns."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.unit.test_invoices_1 import LEAD, ORG, USER, _plan_allows  # noqa: F401  (autouse fixture)
from tests.unit.test_stock_2 import BED, PILLOW, REP, _avail, _client, _no_side_effects, _sdb  # noqa: F401
from tests.unit.test_sale_1 import BOLA, OWNER, REP2, RITA, _db, _notes, _sale
from app.services import business_report_service as biz
from app.services import invoice_report_service as rep
from app.services import invoice_service as inv
from app.services import payment_approval_service as approvals
from app.services import report_email_service as mail

ADMIN_REP = {**BOLA, "roles": {"template": "sales_agent", "permissions": {"is_admin": True}}}


def _csv(text: str) -> list:
    return list(csv.reader(io.StringIO(text)))


def _today_sales(db, main, lagos):
    a = _sale(db, RITA, main, status="part", amount=100000)                       # Abuja, Main store, 400k
    b = _sale(db, BOLA, lagos, region="Lagos Sales")                              # Lagos, paid 400k
    c = _sale(db, BOLA, main, status="unpaid", items=[{"product_id": PILLOW, "quantity": 2}])
    return a, b, c


# ───────────────────────────── sales report ─────────────────────────────

def test_sales_report_totals_and_groups():
    db, main, lagos = _db()
    a, b, c = _today_sales(db, main, lagos)
    d = biz.sales_data(db, ORG)
    t = d["totals"]
    assert t["count"] == 3 and t["value"] == 830000 and t["paid"] == 500000 and t["owed"] == 330000
    assert t["received"] == 500000 and t["payments"] == 2
    reps = {g["name"]: g for g in d["by_rep"]}
    assert reps["Rita Rep"]["count"] == 1 and reps["Bola Rep"]["value"] == 430000 and reps["Bola Rep"]["owed"] == 30000
    assert {g["name"]: g["count"] for g in d["by_region"]} == {"Abuja Sales": 2, "Lagos Sales": 1}
    assert {g["name"]: g["count"] for g in d["by_location"]} == {"Main store": 2, "Lagos Store": 1}
    prods = {(p["name"], p["size"]): p for p in d["by_product"]}
    assert prods[next(k for k in prods if k[1] == "Queen")]["units"] == 2
    assert [s["number"] for s in d["part_paid"]] == [a["invoice"]["number"]]
    assert d["by_method"][0]["method"] == "cash" and d["by_method"][0]["amount"] == 500000


def test_sales_report_filters_and_drafts_voids_left_out():
    db, main, lagos = _db()
    a, b, c = _today_sales(db, main, lagos)
    inv.void(db, ORG, USER, c["invoice"]["id"], "Wrong")
    assert biz.sales_data(db, ORG)["totals"]["count"] == 2          # void left out
    r = biz.sales_data(db, ORG, rep_id=REP)
    assert r["totals"]["count"] == 1 and r["filters"]["rep"] == "Rita Rep" and r["totals"]["received"] == 100000
    r = biz.sales_data(db, ORG, region="lagos sales")
    assert [s["number"] for s in r["sales"]] == [b["invoice"]["number"]] and r["totals"]["received"] == 400000
    r = biz.sales_data(db, ORG, location_id=main["id"])
    assert all(s["location"] == "Main store" for s in r["sales"]) and r["totals"]["received"] == 100000
    yesterday = inv.today() - timedelta(days=1)
    assert biz.sales_data(db, ORG, yesterday, yesterday)["totals"]["count"] == 0
    with pytest.raises(inv.InvoiceError):
        biz.sales_data(db, ORG, date(2026, 5, 2), date(2026, 5, 1))


def test_sales_csv_and_pdf_are_safe():
    db, main, lagos = _db()
    for l in db.rows("leads"):
        l["full_name"] = "=HYPERLINK(\"x\") <b>"
    _today_sales(db, main, lagos)
    d = biz.sales_data(db, ORG)
    rows = _csv(biz.sales_csv(d))
    assert rows[0][:4] == ["Invoice", "Date", "Customer", "Rep"] and len(rows) == 4
    assert all(not r[2].startswith("=") for r in rows[1:])
    html = biz.sales_html(d, inv.get_settings(db, ORG))
    assert "&lt;b&gt;" in html and "HYPERLINK(&quot;x&quot;) <b>" not in html
    assert "Sales report" in html and "Rita Rep" in html
    assert biz.filename("sales", {"start": "2026-11-24", "end": "2026-11-24"}, "pdf") == "sales-report-2026-11-24.pdf"


def test_receipts_csv_has_recorded_by_and_region():
    db, main, lagos = _db()
    a, b, _ = _today_sales(db, main, lagos)
    rows = _csv(rep.receipts_csv(db, ORG))
    assert rows[0][-2:] == ["Recorded by", "Region"]
    by_num = {r[0]: r for r in rows[1:]}
    assert by_num[a["receipt"]["number"]][-2:] == ["Rita Rep", "Abuja Sales"]
    assert by_num[b["receipt"]["number"]][-2:] == ["Bola Rep", "Lagos Sales"]


# ───────────────────────────── inventory report ─────────────────────────────

def test_inventory_report_stock_moves_low_and_waiting():
    db, main, lagos = _db()
    _sale(db, RITA, main)   # paid, not taken: waits delivery
    d = biz.inventory_data(db, ORG)
    queen = next(i for i in d["items"] if i["size"] == "Queen")
    assert queen["on_hand"] == 7 and queen["to_deliver"] == 1 and queen["available"] == 6
    assert any(k["kind"] == "receive" and k["units"] == 17 for k in d["moves"])
    assert len(d["waiting"]) == 1 and "x1" in d["waiting"][0]["lines"]
    only_lagos = biz.inventory_data(db, ORG, location_id=lagos["id"])
    assert only_lagos["filters"]["location"] == "Lagos Store"
    assert next(i for i in only_lagos["items"] if i["size"] == "Queen")["on_hand"] == 2
    assert only_lagos["waiting"] == []
    assert next(k for k in only_lagos["moves"] if k["kind"] == "receive")["units"] == 2   # only Lagos's moves
    rows = _csv(biz.inventory_csv(d))
    assert rows[0][0] == "Product" and len(rows) == len(d["items"]) + 1
    assert "Inventory report" in biz.inventory_html(d, inv.get_settings(db, ORG))


# ───────────────────────────── routes ─────────────────────────────

def test_report_routes_are_admin_only_and_download():
    db, main, lagos = _db()
    _today_sales(db, main, lagos)
    rita, boss = _client(db, RITA), _client(db, OWNER)
    for path in ("/api/v1/reports/sales", "/api/v1/reports/sales?format=csv", "/api/v1/inventory/report",
                 "/api/v1/inventory/report?format=csv"):
        assert rita.get(path).status_code == 403, path
    j = boss.get("/api/v1/reports/sales").json()["data"]
    assert j["totals"]["count"] == 3 and {r["name"] for r in j["reps"]} >= {"Rita Rep", "Bola Rep"}
    assert "Lagos Sales" in j["regions"] and {l["name"] for l in j["locations"]} == {"Main store", "Lagos Store"}
    r = boss.get(f"/api/v1/reports/sales?format=csv&rep_id={REP}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and len(_csv(r.content.decode("utf-8-sig"))) == 2
    r = boss.get("/api/v1/inventory/report?format=csv")
    assert r.status_code == 200 and "inventory-report" in r.headers["content-disposition"]
    assert _client(db, ADMIN_REP).get("/api/v1/reports/sales").status_code == 200


def test_pdf_routes(monkeypatch):
    db, main, lagos = _db()
    _today_sales(db, main, lagos)
    monkeypatch.setattr(biz, "_render", lambda h, n: (b"%PDF-1.4 x", n))
    boss = _client(db, OWNER)
    r = boss.get("/api/v1/reports/sales?format=pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert boss.get("/api/v1/inventory/report?format=pdf").status_code == 200
    monkeypatch.setattr(biz, "_render", lambda h, n: (None, n))
    assert boss.get("/api/v1/reports/sales?format=pdf").status_code == 503


# ───────────────────────────── settings ─────────────────────────────

def test_settings_keep_only_this_business_people_and_good_emails():
    db, main, lagos = _db()
    boss = _client(db, OWNER)
    stranger = "99999999-0000-0000-0000-00000000dead"
    r = boss.put("/api/v1/invoices/settings", json={"payment_confirm_reps": [REP, stranger], "payment_confirmers": [REP2],
                                                    "report_emails": ["Info.RoyalRest@gmail.com", "info.royalrest@gmail.com"],
                                                    "daily_sales_report": True})
    assert r.status_code == 200, r.json()
    st = r.json()["data"]
    assert st["payment_confirm_reps"] == [REP] and st["payment_confirmers"] == [REP2]
    assert st["report_emails"] == ["info.royalrest@gmail.com"] and st["daily_sales_report"] is True
    assert boss.put("/api/v1/invoices/settings", json={"report_emails": ["not-an-email"]}).status_code == 422
    assert _client(db, RITA).put("/api/v1/invoices/settings", json={"payment_confirmers": [REP]}).status_code == 403
    people = {p["id"]: p for p in boss.get("/api/v1/invoices/settings/people").json()["data"]}
    assert people[USER]["manager"] is True and people[REP]["manager"] is False and people[REP]["name"] == "Rita Rep"
    assert _client(db, RITA).get("/api/v1/invoices/settings/people").status_code == 403


# ───────────────────────────── per-rep confirmation + named confirmers ─────────────────────────────

def test_only_the_named_reps_wait():
    db, main, _ = _db()
    inv.save_settings(db, ORG, {"payment_confirm_reps": [REP]})
    assert _sale(db, RITA, main)["pending_payment"] is not None      # remote rep waits
    assert _sale(db, BOLA, main)["receipt"] is not None              # the others don't


def test_named_confirmer_confirms_others_but_not_their_own():
    db, main, _ = _db()
    inv.save_settings(db, ORG, {"payments_need_approval": True, "payment_confirmers": [REP2]})
    assert approvals.can_confirm(BOLA, db) and not approvals.can_confirm(BOLA) and not approvals.can_confirm(RITA, db)
    own = _sale(db, BOLA, main)   # a confirmer is never held
    assert own["receipt"] is not None and own["pending_payment"] is None
    p = _sale(db, RITA, main, delivered=True)["pending_payment"]
    assert len(_notes(db, REP2)) == 1                               # the named confirmer is told
    assert len(approvals.list_approvals(db, BOLA)["items"]) == 1
    got = approvals.approve(db, BOLA, p["id"])
    assert got["fully_paid"] and got["delivered"] is True             # delivered as the rep who sold
    # a confirmer still sees only their own invoices
    assert all(d["created_by"] == REP2 for d in inv.list_docs(db, ORG, mine=REP2)["items"])


def test_nobody_confirms_a_payment_they_recorded():
    db, main, _ = _db()
    inv.save_settings(db, ORG, {"payment_confirm_reps": [REP], "payment_confirmers": [REP2]})
    p = _sale(db, RITA, main)["pending_payment"]
    a = next(x for x in db.rows("payment_approvals") if x["id"] == p["id"])
    a["requested_by"] = REP2   # as if the confirmer had recorded it before being named
    with pytest.raises(inv.InvoiceError) as e:
        approvals.approve(db, BOLA, p["id"])
    assert e.value.status == 403 and "Someone else" in e.value.message
    approvals.reject(db, OWNER, p["id"], "Duplicate")


# ───────────────────────────── emails ─────────────────────────────

class _Sent(list):
    def __call__(self, to, business, subject, lines, files):
        self.append({"to": to, "subject": subject, "lines": lines, "files": [n for n, d in files if d]})
        return len(to)


def _mail_setup(monkeypatch, db, **settings):
    sent = _Sent()
    monkeypatch.setattr(mail, "_send", sent)
    monkeypatch.setattr(biz, "_render", lambda h, n: (b"%PDF", n))
    org = next(o for o in db.rows("organisations") if o["id"] == ORG)
    org["subscription_status"] = "active"
    inv.save_settings(db, ORG, settings)
    return sent


def test_daily_report_goes_once_to_the_report_email(monkeypatch):
    db, main, lagos = _db()
    sent = _mail_setup(monkeypatch, db, daily_sales_report=True, report_emails=["info.royalrest@gmail.com"])
    _today_sales(db, main, lagos)
    tomorrow_7am = datetime.combine(inv.today() + timedelta(days=1), datetime.min.time(), tzinfo=inv.LAGOS) \
        + timedelta(hours=7)
    assert mail.daily_all(db, tomorrow_7am) == {"orgs": 1, "sent": 1, "failed": 0}
    s = sent[0]
    assert s["to"] == ["info.royalrest@gmail.com"] and "sales for" in s["subject"]
    assert any("Sales: 3" in l for l in s["lines"]) and s["files"][0].endswith(".pdf") and s["files"][1].endswith(".csv")
    assert mail.daily_all(db, tomorrow_7am)["orgs"] == 0 and len(sent) == 1        # never twice
    assert mail.daily_all(db, tomorrow_7am + timedelta(days=1))["sent"] == 1       # next day goes


def test_daily_off_or_lapsed_sends_nothing(monkeypatch):
    db, main, _ = _db()
    sent = _mail_setup(monkeypatch, db, report_emails=["a@b.co"])
    assert mail.daily_all(db)["orgs"] == 0
    inv.save_settings(db, ORG, {"daily_sales_report": True})
    next(o for o in db.rows("organisations") if o["id"] == ORG)["subscription_status"] = "suspended"
    assert mail.daily_all(db)["orgs"] == 0 and sent == []


def test_weekly_report_has_both_reports_and_falls_back_to_owner(monkeypatch):
    db, main, lagos = _db()
    sent = _mail_setup(monkeypatch, db, weekly_reports=True)
    for u in db.rows("users"):
        if u["id"] == USER:
            u["email"], u["is_active"] = "owner@biz.ng", True
    monday = datetime(2026, 11, 30, 7, 0, tzinfo=inv.LAGOS)
    assert mail.weekly_all(db, monday)["sent"] == 1
    s = sent[0]
    assert s["to"] == ["owner@biz.ng"] and "weekly" in s["subject"]
    assert any(n.startswith("inventory-report-2026-11-23-to-2026-11-29") for n in s["files"])
    assert any(n.startswith("sales-report-2026-11-23-to-2026-11-29") for n in s["files"])
    assert mail.weekly_all(db, monday + timedelta(days=2))["orgs"] == 0          # same week: not again


def test_send_test_route(monkeypatch):
    db, main, _ = _db()
    sent = _mail_setup(monkeypatch, db)
    boss = _client(db, OWNER)
    r = boss.post("/api/v1/reports/send-test", json={"kind": "daily"})
    assert r.status_code == 422 and r.json()["error"]["field"] == "report_emails"   # nobody to send to
    inv.save_settings(db, ORG, {"report_emails": ["a@b.co"]})
    r = boss.post("/api/v1/reports/send-test", json={"kind": "weekly"})
    assert r.status_code == 200 and r.json()["data"]["sent_to"] == ["a@b.co"] and len(sent) == 1
    assert _client(db, RITA).post("/api/v1/reports/send-test", json={}).status_code == 403


def test_lagos_dates():
    late = datetime(2026, 11, 24, 23, 30, tzinfo=timezone.utc)   # 00:30 on the 25th in Lagos
    assert mail.lagos_today(late) == date(2026, 11, 25)
    assert mail.clean_emails([" A@B.co ", "bad", "a@b.co", None]) == ["a@b.co"]
