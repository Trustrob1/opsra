"""RETURN-MENU-1 - returning leads / customers get their menu again."""
import inspect
from unittest.mock import MagicMock, patch

from app.services import returning_menu_service as rm

CFG = {
    "unknown": {"items": [{"id": "u1", "label": "Talk to sales", "action": "qualify"}, {"id": "u2", "label": "Book a time", "action": "book"}]},
    "returning_contact_menu": {"items": []},
    "known_customer_menu": {"items": []},
    "customer": {"items": [{"id": "c1", "label": "Support", "action": "create_ticket"}]},
}


def test_is_menu_request():
    for t in ("hi", "Hello!", "menu", "Help", "hey there", "good morning", "hello team"):
        assert rm.is_menu_request(t), t
    for t in ("", None, "Hello, I want a refund for my order please", "hi, what is the price?", "I need help with my order"):
        assert not rm.is_menu_request(t), t


def test_pick_menu_lead_falls_back_to_unknown_and_drops_book():
    with patch.object(rm, "booking_available", return_value=False):
        key, items, _ = rm.pick_menu(MagicMock(), "o", CFG, "lead")
    assert key == "unknown" and [i["id"] for i in items] == ["u1"]


def test_pick_menu_keeps_book_when_available():
    with patch.object(rm, "booking_available", return_value=True):
        key, items, _ = rm.pick_menu(MagicMock(), "o", CFG, "lead")
    assert [i["id"] for i in items] == ["u1", "u2"]


def test_pick_menu_customer_prefers_known_then_customer():
    key, items, _ = rm.pick_menu(MagicMock(), "o", CFG, "customer")
    assert key == "customer" and items[0]["id"] == "c1"
    cfg = dict(CFG, known_customer_menu={"items": [{"id": "k1", "label": "Orders", "action": "free_form"}]})
    assert rm.pick_menu(MagicMock(), "o", cfg, "customer")[0] == "known_customer_menu"


def test_pick_menu_nothing_configured():
    assert rm.pick_menu(MagicMock(), "o", {}, "lead")[0] is None


def test_section_for():
    assert rm.section_for({"session_data": {"returning_menu": "returning_contact_menu"}}, "unknown") == "returning_lead"
    assert rm.section_for({"session_data": {"returning_menu": "known_customer_menu"}}, "customer") == "known_customer"
    assert rm.section_for(None, "customer") == "customer"
    assert rm.section_for({"session_data": {}}, "unknown") == "unknown"


def _show(org=None, replied=False, existing=None, creds=("pid", "tok", None), kind="lead"):
    org = {"whatsapp_triage_config": CFG, "returning_menu_enabled": True} if org is None else org
    sent = MagicMock()
    ts = MagicMock()
    ts.get_active_session.return_value = existing
    ts.get_or_create_session.return_value = {"id": "s1", "session_data": {}}
    wps = MagicMock(); wps.menu_on.return_value = True
    with patch.object(rm, "_org", return_value=org), patch.object(rm, "_rep_replied_recently", return_value=replied), \
         patch.object(rm, "booking_available", return_value=False), \
         patch("app.services.triage_service.get_active_session", ts.get_active_session), \
         patch("app.services.triage_service.get_or_create_session", ts.get_or_create_session), \
         patch("app.services.triage_service.update_session", ts.update_session), \
         patch("app.services.wa_plan_service.menu_on", wps.menu_on), \
         patch("app.services.whatsapp_service._get_org_wa_credentials", return_value=creds), \
         patch("app.services.whatsapp_service._call_meta_send", sent):
        ok = rm.show(MagicMock(), "o", "234", "Ada", kind, lead_id="l1", prefix="P")
    return ok, sent, ts


def test_show_sends_menu_and_marks_session():
    ok, sent, ts = _show()
    assert ok and sent.call_count == 1
    assert sent.call_args.kwargs["token"] == "tok"
    rows = sent.call_args.args[1]["interactive"]["action"]["sections"][0]["rows"]
    assert [r["id"] for r in rows] == ["u1"]
    args = ts.update_session.call_args
    assert args.args[2] == "triage_sent" and args.kwargs["session_data"]["returning_menu"] == "unknown"


def test_show_skips_when_switched_off():
    ok, sent, _ = _show(org={"whatsapp_triage_config": CFG, "returning_menu_enabled": False})
    assert not ok and not sent.called


def test_show_skips_when_rep_replied():
    ok, sent, _ = _show(replied=True)
    assert not ok and not sent.called


def test_show_skips_mid_flow():
    ok, sent, _ = _show(existing={"id": "s", "session_state": "active"})
    assert not ok and not sent.called


def test_show_allows_stale_triage_session():
    ok, sent, _ = _show(existing={"id": "s", "session_state": "triage_sent"})
    assert ok and sent.called


def test_show_skips_without_credentials():
    ok, sent, _ = _show(creds=("", None, None))
    assert not ok and not sent.called


def test_show_never_raises():
    with patch.object(rm, "_org", side_effect=RuntimeError("boom")):
        assert rm.show(MagicMock(), "o", "234", None, "lead") is False


def test_run_book_action_starts_picker():
    bw = MagicMock(); bw.start_picker.return_value = {"started": True}
    with patch.object(rm, "_lead_for_phone", return_value="l1"), patch.object(rm, "booking_available", return_value=True), \
         patch("app.services.triage_service.update_session") as up, patch("app.services.booking_wa_service.start_picker", bw.start_picker):
        rm.run_book_action(MagicMock(), "o", "234", "s1")
    bw.start_picker.assert_called_once()
    assert up.call_args.args[2] == "active"


def test_run_book_action_falls_back_to_text():
    sent = MagicMock()
    with patch.object(rm, "_lead_for_phone", return_value=None), patch.object(rm, "booking_available", return_value=False), \
         patch("app.services.triage_service.update_session"), \
         patch("app.services.whatsapp_service._get_org_wa_credentials", return_value=("pid", "tok", None)), \
         patch("app.services.whatsapp_service._call_meta_send", sent):
        rm.run_book_action(MagicMock(), "o", "234", "s1")
    assert sent.call_args.args[1]["type"] == "text"


def test_handle_customer_inbound_accepts_phone_number():
    from app.services.customer_inbound_service import handle_customer_inbound
    assert "phone_number" in inspect.signature(handle_customer_inbound).parameters
