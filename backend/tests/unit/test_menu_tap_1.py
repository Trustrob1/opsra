"""MENU-TAP-1 - a known lead tapping an older menu (session over) still gets the answer."""
from unittest.mock import MagicMock, patch

from app.services import returning_menu_service as rm

CFG = {"unknown": {"items": [
    {"id": "pay", "label": "Payment plan", "action": "info", "reply_text": "30% deposit"},
    {"id": "book", "label": "Book an advisor call", "action": "book"},
    {"id": "q", "label": "Start my enquiry", "action": "qualify"},
    {"id": "p", "label": "Talk to a person", "action": "route_to_role"}]}}


def _org(enabled=True):
    return {"whatsapp_triage_config": CFG, "returning_menu_enabled": enabled}


def test_info_tap_is_answered_and_menu_resent():
    with patch.object(rm, "_org", return_value=_org()), patch.object(rm, "run_info_action") as info, patch.object(rm, "show") as show:
        assert rm.answer_stale_tap(MagicMock(), "o", "234", "Payment plan", "Ada", lead_id="l1") is True
    assert info.call_args.args[3] is None and info.call_args.args[4]["id"] == "pay"
    assert show.called


def test_label_match_ignores_case_and_spacing():
    with patch.object(rm, "_org", return_value=_org()), patch.object(rm, "run_info_action") as info, patch.object(rm, "show"):
        assert rm.answer_stale_tap(MagicMock(), "o", "234", "  payment   PLAN ", "Ada") is True
    assert info.called


def test_book_tap_opens_picker_when_available():
    with patch.object(rm, "_org", return_value=_org()), patch.object(rm, "booking_available", return_value=True), \
         patch.object(rm, "run_book_action") as book:
        assert rm.answer_stale_tap(MagicMock(), "o", "234", "Book an advisor call") is True
    assert book.call_args.args[3] is None


def test_book_tap_falls_through_when_booking_unavailable():
    with patch.object(rm, "_org", return_value=_org()), patch.object(rm, "booking_available", return_value=False):
        assert rm.answer_stale_tap(MagicMock(), "o", "234", "Book an advisor call") is False


def test_other_actions_and_unknown_labels_fall_through():
    with patch.object(rm, "_org", return_value=_org()):
        for label in ("Start my enquiry", "Talk to a person", "Something nobody configured", "", None):
            assert rm.answer_stale_tap(MagicMock(), "o", "234", label) is False


def test_switched_off_menu_falls_through():
    with patch.object(rm, "_org", return_value=_org(False)):
        assert rm.answer_stale_tap(MagicMock(), "o", "234", "Payment plan") is False


def test_never_raises():
    with patch.object(rm, "_org", side_effect=RuntimeError("db down")):
        assert rm.answer_stale_tap(MagicMock(), "o", "234", "Payment plan") is False


def test_info_action_without_session_still_sends():
    ts = MagicMock()
    with patch("app.services.triage_service.update_session", ts), \
         patch("app.services.whatsapp_service._get_org_wa_credentials", return_value=("pid", "tok", None)), \
         patch("app.services.whatsapp_service._call_meta_send") as send, patch.object(rm, "_lead_for_phone", return_value="l1"):
        rm.run_info_action(MagicMock(), "o", "234", None, {"label": "Payment plan", "reply_text": "30% deposit"})
    assert send.called and not ts.called
