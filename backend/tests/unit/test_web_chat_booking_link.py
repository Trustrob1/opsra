"""BOOKING-LINK: a business with Opsra's full booking gets a personal calendar link from Chioma's Book a call button; others keep the request form."""
from __future__ import annotations

from unittest.mock import patch

from app.services import webchat_flow_service as flow
from app.services import webchat_service as wc
from tests.unit.test_webchat_3 import _cfg, _db, _session, _no_rate_limit  # noqa: F401

BK = "app.services.booking_service."
BOOKING_MENU = [{"id": "book", "label": "Book a call", "action": "booking", "keywords": ["book"]},
                {"id": "human", "label": "Talk to the team", "action": "human", "keywords": []}]


def _env(native=True, services=1):
    return [patch(BK + "get_settings", return_value={"native_enabled": native}),
            patch(BK + "list_services", return_value=[{"id": f"svc{i}"} for i in range(services)]),
            patch(BK + "create_link", return_value="TOKEN123"),
            patch(BK + "public_base", return_value="https://opsra.com.ng")]


def _run(fn, **kw):
    ps = _env(**kw)
    mocks = [p.start() for p in ps]
    try:
        return fn(), mocks
    finally:
        for p in ps:
            p.stop()


def _tap(db, s, cfg):
    return flow.handle_message(db, s, cfg, kind="menu", menu_id="book")


def _setup(contact=True):
    db = _db(menu=BOOKING_MENU)
    return db, _session(db, contact=contact), _cfg(db)


def test_native_booking_sends_a_personal_link_and_no_form():
    db, s, cfg = _setup()
    r, _ = _run(lambda: _tap(db, s, cfg))
    assert r["form"] is None
    assert r["messages"][-1]["text"] == "Here is your personal booking link. Pick a time that suits you: https://opsra.com.ng/b/TOKEN123"


def test_link_is_made_for_the_visitors_lead_and_first_service():
    db, s, cfg = _setup()
    _, (_, _, create, _) = _run(lambda: _tap(db, s, cfg))
    args = create.call_args.args
    assert args[0] is db and args[1] == s["org_id"] and args[2] == s["lead_id"] and args[3] == "svc0" and args[4] is None


def test_second_tap_reuses_the_link():
    db, s, cfg = _setup()
    def go():
        _tap(db, s, cfg)
        return _tap(db, s, cfg)
    r, (_, _, create, _) = _run(go)
    assert create.call_count == 1 and "TOKEN123" in r["messages"][-1]["text"]


def test_an_old_stored_link_is_not_reused():
    db, s, cfg = _setup()
    wc.set_state(db, s, booking_link={"url": "https://old/b/x", "at": "2020-01-01T00:00:00+00:00"})
    r, (_, _, create, _) = _run(lambda: _tap(db, s, cfg))
    assert create.call_count == 1 and "TOKEN123" in r["messages"][-1]["text"]


def test_without_native_booking_the_request_form_is_used():
    db, s, cfg = _setup()
    r, (_, _, create, _) = _run(lambda: _tap(db, s, cfg), native=False)
    assert r["form"] == "booking" and not create.called and "personal booking link" not in r["messages"][-1]["text"]


def test_without_a_bookable_service_the_request_form_is_used():
    db, s, cfg = _setup()
    r, (_, _, create, _) = _run(lambda: _tap(db, s, cfg), services=0)
    assert r["form"] == "booking" and not create.called


def test_a_booking_error_falls_back_to_the_form_and_never_breaks_the_chat():
    db, s, cfg = _setup()
    ps = _env()
    ps[2] = patch(BK + "create_link", side_effect=RuntimeError("db down"))
    for p in ps:
        p.start()
    try:
        r = _tap(db, s, cfg)
    finally:
        for p in ps:
            p.stop()
    assert r["form"] == "booking"


def test_visitor_without_details_is_asked_first_then_gets_the_link():
    db, s, cfg = _setup(contact=False)
    r, _ = _run(lambda: _tap(db, s, cfg))
    assert r.get("contact_step") == "name" and s["state"].get("pending") == "booking"
    s["lead_id"] = "L9"                       # the details script finished and a lead now exists
    ps = _env()
    for p in ps:
        p.start()
    try:
        out = flow.handle_contact(db, s, cfg, name="Ada Obi", phone="08031234567", email=None, consent=True)
    finally:
        for p in ps:
            p.stop()
    assert "personal booking link" in out["messages"][-1]["text"] and out["form"] is None
