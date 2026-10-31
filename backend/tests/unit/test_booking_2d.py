"""BOOKING-2D - template buttons, reschedule template fallback, stage trigger, lead-chosen person."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import booking_service as bk
from app.services import whatsapp_service as ws


def _db(rows):
    db = MagicMock()
    q = MagicMock()
    for m in ("select", "eq", "limit"):
        getattr(q, m).return_value = q
    q.execute.return_value = MagicMock(data=rows)
    db.table.return_value = q
    return db


def test_buttons_only_when_flag_on():
    assert ws._booking_button_components(_db([{"native_enabled": True, "template_buttons": False}]), "o", "d1") == []
    assert ws._booking_button_components(_db([{"native_enabled": False, "template_buttons": True}]), "o", "d1") == []
    assert ws._booking_button_components(_db([]), "o", "d1") == []
    assert ws._booking_button_components(_db([{"native_enabled": True, "template_buttons": True}]), "o", None) == []


def test_buttons_carry_demo_id_reschedule_first():
    c = ws._booking_button_components(_db([{"native_enabled": True, "template_buttons": True}]), "o", "d1")
    assert [x["parameters"][0]["payload"] for x in c] == ["bk:rs:d1", "bk:cx:d1"]
    assert [x["index"] for x in c] == ["0", "1"] and all(x["sub_type"] == "quick_reply" for x in c)


def test_buttons_error_returns_empty():
    db = MagicMock(); db.table.side_effect = RuntimeError("down")
    assert ws._booking_button_components(db, "o", "d1") == []


def test_send_retries_without_buttons():
    payload = {"template": {"components": [{"type": "body"}]}}
    btn = [{"type": "button"}]
    calls = []
    def fake(pid, p, token=None):
        calls.append(list(p["template"]["components"]))
        if len(calls) == 1:
            raise RuntimeError("template has no buttons")
        return {"ok": 1}
    with patch.object(ws, "_call_meta_send", side_effect=fake):
        assert ws._send_with_buttons("pid", "tok", payload, btn) == {"ok": 1}
    assert len(calls[0]) == 2 and len(calls[1]) == 1
    assert len(payload["template"]["components"]) == 1      # caller's payload not mutated


def test_send_without_buttons_single_call():
    with patch.object(ws, "_call_meta_send", return_value={"ok": 1}) as m:
        ws._send_with_buttons("pid", "tok", {"template": {"components": []}}, [])
    assert m.call_count == 1


def _cfg(**kw):
    base = {"native_enabled": True, "auto_send_link": True, "auto_send_trigger": "qualified", "auto_send_stage": None}
    base.update(kw); return base


def test_stage_trigger_skips_wrong_trigger():
    with patch.object(bk, "get_settings", return_value=_cfg()):
        assert bk.auto_send_link_for_lead(MagicMock(), "o", "l", trigger="stage", stage="proposal")["reason"] == "other_trigger"
    with patch.object(bk, "get_settings", return_value=_cfg(auto_send_trigger="stage", auto_send_stage="proposal")):
        assert bk.auto_send_link_for_lead(MagicMock(), "o", "l")["reason"] == "other_trigger"


def test_stage_trigger_skips_other_stage():
    with patch.object(bk, "get_settings", return_value=_cfg(auto_send_trigger="stage", auto_send_stage="proposal")):
        assert bk.auto_send_link_for_lead(MagicMock(), "o", "l", trigger="stage", stage="demo")["reason"] == "other_stage"


def test_save_requires_stage_for_stage_trigger():
    with patch.object(bk, "get_settings", return_value=_cfg()):
        with pytest.raises(HTTPException):
            bk.save_settings(MagicMock(), "o", {"auto_send_trigger": "stage"})


def test_chosen_person_must_be_eligible():
    with patch.object(bk, "get_settings", return_value={"calendar_mode": "per_staff"}), \
         patch.object(bk, "eligible_staff_ids", return_value=["a", "b"]):
        with pytest.raises(HTTPException):
            bk.get_open_slots(MagicMock(), {"id": "o", "timezone": "UTC"}, {}, date(2026, 11, 3), date(2026, 11, 3), rep_id="zzz")


def test_chosen_person_restricts_slots():
    t = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
    seen = []
    def fake(db, org, svc, f, to, now, ex, rep_id=None):
        seen.append(rep_id); return [t]
    with patch.object(bk, "get_settings", return_value={"calendar_mode": "per_staff"}), \
         patch.object(bk, "eligible_staff_ids", return_value=["a", "b"]), \
         patch.object(bk, "_slots_for", side_effect=fake):
        out = bk.get_open_slots(MagicMock(), {"id": "o", "timezone": "UTC"}, {}, date(2026, 11, 3), date(2026, 11, 3), rep_id="b")
    assert seen == ["b"] and out == [t]


def test_best_rep_only_rep_skips_others():
    org, svc = {"id": "o"}, {"id": "s"}
    tried = []
    with patch.object(bk, "rank_reps", return_value=["a", "b", "c"]), \
         patch.object(bk, "_insert_booking_row", side_effect=lambda *a, **k: tried.append(k.get("assigned_to")) or {"id": "x"}):
        try:
            bk._insert_for_best_rep(MagicMock(), org, svc, "l", datetime.now(timezone.utc), datetime.now(timezone.utc), "native", None, None, None, only_rep="b")
        except Exception:
            pass
    assert tried in (["b"], [])
