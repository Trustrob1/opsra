"""REVISE-1: a sales rep revises their own unpaid invoice (old one voided, editable copy made), and each rep can have a
home region whose bank accounts are the only ones they can pick (a region may have several accounts)."""
from __future__ import annotations

import pathlib

import pytest

from app.services import invoice_service as inv
from app.services import invoice_sales_service as sales
from tests.unit.test_bank_1 import ACCTS, _db, _draft, _id
from tests.unit.test_invoices_1 import ORG, USER

REP = {"region": None}
LAGOS_TWO = [ACCTS[0], {**ACCTS[1], "label": "Lagos 2", "region": "Lagos Sales", "is_default": False}, ACCTS[2]]


def _setup(accts=LAGOS_TWO):
    db = _db()
    db.tables.setdefault("users", []).append({"id": USER, "org_id": ORG, "full_name": "Ada Rep", "sales_region": None})
    return db, inv.save_settings(db, ORG, {"bank_accounts": accts})


def _issued(db, **kw):
    return inv.issue(db, ORG, USER, _draft(db, region="Lagos Sales", **kw)["id"])


# ── revise ──

def test_revise_voids_the_old_and_returns_an_editable_copy():
    db, s = _setup()
    old = _issued(db, notes="Deliver Friday", bank_account_id=_id(s, "Lagos 2"))
    new = inv.revise(db, ORG, USER, old["id"], "wrong size")
    assert new["status"] == "draft" and new["revised_from_id"] == old["id"] and new["revised_from_number"] == old["number"]
    assert [i["description"] for i in new["items"]] == ["Mattress"] and float(new["total"]) == float(old["total"])
    assert new["notes"] == "Deliver Friday" and new["region"] == "Lagos Sales" and new["bank_account_id"] == _id(s, "Lagos 2")
    gone = inv.get_doc(db, ORG, old["id"])
    assert gone["status"] == "void" and "Revised" in gone["void_reason"] and "wrong size" in gone["void_reason"]
    assert gone["replaced_by"]["id"] == new["id"]
    again = inv.issue(db, ORG, USER, new["id"])            # the copy issues with a new number
    assert again["status"] == "issued" and again["number"] != old["number"]


def test_paid_or_draft_cannot_be_revised():
    db, s = _setup()
    d = _draft(db, region="Lagos Sales")
    with pytest.raises(inv.InvoiceError) as e:
        inv.revise(db, ORG, USER, d["id"])
    assert "draft can just be edited" in e.value.message
    old = _issued(db)
    db.table("invoices").update({"amount_paid": 1000}).eq("id", old["id"]).execute()
    with pytest.raises(inv.InvoiceError) as e:
        inv.revise(db, ORG, USER, old["id"])
    assert "Money has been recorded" in e.value.message
    assert len([r for r in db.tables["invoices"] if r.get("revised_from_id") == old["id"]]) == 0   # nothing left behind


def test_a_payment_waiting_for_approval_blocks_revise():
    db, s = _setup()
    old = _issued(db)
    db.tables.setdefault("payment_approvals", []).append({"id": "pa1", "org_id": ORG, "invoice_id": old["id"], "status": "pending",
                                                         "amount": 1000, "requested_at": "2026-11-27T10:00:00Z"})
    with pytest.raises(inv.InvoiceError) as e:
        inv.revise(db, ORG, USER, old["id"])
    assert "waiting for approval" in e.value.message and inv.get_doc(db, ORG, old["id"])["status"] == "issued"


# ── regions and bank accounts ──

def test_accounts_for_region():
    s = {"bank_accounts": [{**a, "id": a["label"]} for a in LAGOS_TWO]}
    assert [a["label"] for a in inv.accounts_for_region(s, "Lagos Sales")] == ["Lagos", "Lagos 2"]
    assert [a["label"] for a in inv.accounts_for_region(s, "Kano")] == ["Lagos", "Lagos 2", "Night"]   # none linked, none unlinked: all
    s2 = {"bank_accounts": [{**ACCTS[0], "id": "a"}, {**ACCTS[1], "id": "b", "region": None}]}
    assert [a["id"] for a in inv.accounts_for_region(s2, "Abuja Sales")] == ["b"]                       # unlinked accounts


def test_rep_picks_only_their_region_accounts():
    db, s = _setup()
    rep = {"region": "Lagos Sales"}
    d = inv.create_draft(db, ORG, USER, {"doc_type": "invoice", "region": "Abuja Sales", "bank_account_id": _id(s, "Lagos 2"),
                                         "items": [{"description": "Bed", "quantity": 1, "unit_price": 1}]}, rep=rep)
    assert d["region"] == "Lagos Sales" and d["bank_account_id"] == _id(s, "Lagos 2")      # home region wins
    with pytest.raises(inv.InvoiceError) as e:
        inv.update_draft(db, ORG, USER, d["id"], {"bank_account_id": _id(s, "Night")}, rep=rep)
    assert "Lagos Sales bank accounts" in e.value.message
    d2 = inv.update_draft(db, ORG, USER, d["id"], {"region": "Abuja Sales", "notes": "x"}, rep=rep)
    assert d2["region"] == "Lagos Sales" and d2["notes"] == "x"                            # cannot move to another region


def test_rep_without_home_region_is_limited_to_the_invoice_region():
    db, s = _setup()
    d = inv.create_draft(db, ORG, USER, {"doc_type": "invoice", "region": "Night Shift Sales",
                                         "items": [{"description": "Bed", "quantity": 1, "unit_price": 1}]}, rep=dict(REP))
    with pytest.raises(inv.InvoiceError):
        inv.update_draft(db, ORG, USER, d["id"], {"bank_account_id": _id(s, "Lagos")}, rep=dict(REP))
    ok = inv.update_draft(db, ORG, USER, d["id"], {"bank_account_id": _id(s, "Night")}, rep=dict(REP))
    assert ok["bank_account_id"] == _id(s, "Night")
    moved = inv.update_draft(db, ORG, USER, d["id"], {"region": "Lagos Sales"}, rep=dict(REP))
    assert moved["bank_account_id"] is None                                                 # old region's account dropped


def test_manager_can_pick_any_account():
    db, s = _setup()
    d = _draft(db, region="Lagos Sales", bank_account_id=_id(s, "Night"))
    assert d["bank_account_id"] == _id(s, "Night")


def test_home_regions_are_saved_and_checked():
    db, s = _setup()
    assert sales.set_rep_regions(db, ORG, {USER: "lagos sales"}) == {USER: "Lagos Sales"}
    assert sales.rep_region(db, ORG, USER) == "Lagos Sales"
    with pytest.raises(inv.InvoiceError):
        sales.set_rep_regions(db, ORG, {USER: "Kano"})
    with pytest.raises(inv.InvoiceError):
        sales.set_rep_regions(db, ORG, {"99999999-9999-9999-9999-999999999999": "Lagos Sales"})
    sales.set_rep_regions(db, ORG, {USER: None})
    assert sales.rep_region(db, ORG, USER) is None


def test_wiring():
    root = pathlib.Path(__file__).resolve().parents[2]
    r = (root / "app" / "routers" / "invoices.py").read_text(encoding="utf-8")
    assert '@router.post("/invoices/{doc_id}/revise", status_code=201, dependencies=_OWN_DOC)' in r
    assert "rep=_rep(org, db)" in r and '@router.put("/invoices/settings/rep-regions")' in r
    assert 'data["can_pick_any_bank"] = rep is None' in r
    mig = (root.parent / "supabase" / "migrations" / "2026_11_27_revise_1.sql").read_text(encoding="utf-8")
    assert "revised_from_id" in mig and "sales_region" in mig
