"""BANK-1: several bank accounts, linked to regions, one default; an invoice picks which one it shows."""
from __future__ import annotations

import pytest

from app.services import invoice_pdf_service as pdf
from app.services import invoice_service as inv
from tests.unit.test_invoices_1 import ORG, USER, LEAD, InvDB

REGIONS = {"transactions": {"regions": [{"name": "Lagos Sales"}, {"name": "Abuja Sales"}, {"name": "Night Shift Sales"}]}}
ACCTS = [
    {"label": "Lagos", "bank_name": "Providus Bank", "account_name": "Royalrest Mattress", "account_number": "1000009433",
     "region": "Lagos Sales", "is_default": True},
    {"label": "Abuja", "bank_name": "GTBank", "account_name": "Royalrest Abuja", "account_number": "2000001111",
     "region": "abuja sales"},
    {"label": "Night", "bank_name": "Moniepoint", "account_name": "Royalrest Remote", "account_number": "3000002222",
     "region": "Night Shift Sales"},
]


def _db():
    return InvDB(organisations=[{"id": ORG, "name": "Royal Rest Mattress", "sheet_sources": REGIONS}], leads=[
        {"id": LEAD, "org_id": ORG, "full_name": "Ada Obi", "whatsapp": "2348011111111", "phone": None,
         "email": None, "location": None, "deleted_at": None}])


def _setup():
    db = _db()
    s = inv.save_settings(db, ORG, {"bank_accounts": ACCTS})
    return db, s


def _draft(db, **kw):
    return inv.create_draft(db, ORG, USER, {"doc_type": "invoice", "lead_id": LEAD,
                                             "items": [{"description": "Mattress", "quantity": 1, "unit_price": 805000}], **kw})


def _id(s, label):
    return next(a["id"] for a in s["bank_accounts"] if a["label"] == label)


def test_save_cleans_accounts_and_mirrors_default_into_old_fields():
    db, s = _setup()
    assert [a["region"] for a in s["bank_accounts"]] == ["Lagos Sales", "Abuja Sales", "Night Shift Sales"]   # saved spelling
    assert [a["is_default"] for a in s["bank_accounts"]] == [True, False, False]
    assert all(a["id"] for a in s["bank_accounts"]) and len({a["id"] for a in s["bank_accounts"]}) == 3
    assert (s["bank_name"], s["account_number"]) == ("Providus Bank", "1000009433")


def test_old_single_account_shows_as_default():
    db = _db()
    s = inv.save_settings(db, ORG, {"bank_name": "Providus Bank", "account_name": "RR", "account_number": "1234567890"})
    assert s["bank_accounts"] == [{"id": "main", "label": "Providus Bank", "bank_name": "Providus Bank", "account_name": "RR",
                                   "account_number": "1234567890", "region": None, "is_default": True}]


@pytest.mark.parametrize("bad, msg", [
    ([{**ACCTS[0], "account_number": "12ab"}], "6 to 20 digits"),
    ([{**ACCTS[0], "bank_name": " "}], "bank name"),
    ([{**ACCTS[0], "region": "Kano"}], "regions"),
    ([ACCTS[0], {**ACCTS[1], "region": "Lagos Sales"}], "already linked"),
    ([ACCTS[0]] * 11, "up to 10"),
])
def test_bad_accounts_are_refused(bad, msg):
    with pytest.raises(inv.InvoiceError) as e:
        inv.save_settings(_db(), ORG, {"bank_accounts": bad})
    assert msg in e.value.message


def test_one_default_only_and_first_when_none():
    db = _db()
    s = inv.save_settings(db, ORG, {"bank_accounts": [{**a, "is_default": True} for a in ACCTS]})
    assert [a["is_default"] for a in s["bank_accounts"]] == [True, False, False]
    s = inv.save_settings(db, ORG, {"bank_accounts": [{**a, "is_default": False} for a in ACCTS]})
    assert [a["is_default"] for a in s["bank_accounts"]] == [True, False, False]


def test_issue_uses_region_account_when_none_picked():
    db, s = _setup()
    d = _draft(db, region="Abuja Sales")
    issued = inv.issue(db, ORG, USER, d["id"])
    assert issued["issuer"]["bank_name"] == "GTBank" and issued["issuer"]["account_number"] == "2000001111"


def test_issue_uses_picked_account_over_region():
    db, s = _setup()
    d = _draft(db, region="Abuja Sales", bank_account_id=_id(s, "Night"))
    issued = inv.issue(db, ORG, USER, d["id"])
    assert issued["issuer"]["account_number"] == "3000002222"


def test_issue_falls_back_to_default():
    db, s = _setup()
    inv.save_settings(db, ORG, {"bank_accounts": [{**ACCTS[0], "region": None}, ACCTS[1]]})
    d = _draft(db, region="Lagos Sales")
    assert inv.issue(db, ORG, USER, d["id"])["issuer"]["account_number"] == "1000009433"


def test_unknown_account_is_refused_and_blank_clears():
    db, s = _setup()
    with pytest.raises(inv.InvoiceError):
        _draft(db, bank_account_id="nope")
    d = _draft(db, bank_account_id=_id(s, "Abuja"))
    assert inv.update_draft(db, ORG, USER, d["id"], {"bank_account_id": ""}).get("bank_account_id") is None


def test_settings_change_after_issue_keeps_printed_account():
    db, s = _setup()
    issued = inv.issue(db, ORG, USER, _draft(db, region="Lagos Sales")["id"])
    inv.save_settings(db, ORG, {"bank_accounts": [{**ACCTS[0], "account_number": "9999999999"}]})
    assert inv.get_doc(db, ORG, issued["id"])["issuer"]["account_number"] == "1000009433"


def test_draft_preview_prints_the_chosen_account():
    db, s = _setup()
    d = _draft(db, region="Night Shift Sales")
    html = pdf.build_html(d, inv.settings_for_doc(inv.get_settings(db, ORG), d), "invoice")
    assert "3000002222" in html and "1000009433" not in html


def test_quote_to_invoice_keeps_the_account():
    db, s = _setup()
    q = inv.create_draft(db, ORG, USER, {"doc_type": "quote", "lead_id": LEAD, "bank_account_id": _id(s, "Abuja"), "region": "Lagos Sales",
                                         "items": [{"description": "Bed", "quantity": 1, "unit_price": 1000}]})
    q = inv.issue(db, ORG, USER, q["id"])
    inv.set_quote_answer(db, ORG, USER, q["id"], True)
    new = inv.convert_quote(db, ORG, USER, q["id"])
    assert new["bank_account_id"] == _id(s, "Abuja")


def test_wiring():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    r = (root / "app" / "routers" / "invoices.py").read_text(encoding="utf-8")
    dl = (root / "app" / "services" / "invoice_delivery_service.py").read_text(encoding="utf-8")
    assert "bank_accounts: Optional[List[BankAccountIn]]" in r and "bank_account_id: Optional[str]" in r
    assert "inv.settings_for_doc(inv.get_settings(db, org_id), doc)" in r and "inv.settings_for_doc(" in dl
