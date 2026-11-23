"""EMAIL-STEP-1: an optional email after the number in the in-chat details script."""
from unittest.mock import patch

from tests.unit.test_webchat_3 import _db, _session, _cfg, _no_rate_limit, ORG  # noqa: F401
from app.services import webchat_contact_service as c
from app.services import webchat_flow_service as f
from app.services import webchat_service as wc


def _open(db, cfg):
    s = _session(db, contact=False)
    c.start(db, s, cfg, "Happy to help.")
    return s


def _say(db, s, cfg, text):
    with patch.object(wc, "notify_managers"):
        return f.handle_message(db, s, cfg, kind="text", text=text)


def test_email_is_asked_after_the_number_with_a_skip_button():
    db = _db(); cfg = _cfg(db); s = _open(db, cfg)
    _say(db, s, cfg, "Ada"); r = _say(db, s, cfg, "08031234567")
    assert r["contact_step"] == "email" and [ch["label"] for ch in r["choices"]] == ["Skip"]


def test_a_good_email_is_kept_and_never_shown_in_the_chat_text():
    db = _db(); cfg = _cfg(db); s = _open(db, cfg)
    _say(db, s, cfg, "Ada"); _say(db, s, cfg, "08031234567")
    assert c.shown_text(s, "ada@example.com") == "My email address"
    r = _say(db, s, cfg, "Ada@Example.com")
    assert r["contact_step"] == "consent" and "and by email" in r["messages"][-1]["text"]
    assert s["state"]["contact_tmp"]["email"] == "ada@example.com"


def test_a_bad_email_gets_one_retry_then_carries_on_without_a_form():
    db = _db(); cfg = _cfg(db); s = _open(db, cfg)
    _say(db, s, cfg, "Ada"); _say(db, s, cfg, "08031234567")
    r = _say(db, s, cfg, "not an email")
    assert r["contact_step"] == "email" and "does not look right" in r["messages"][-1]["text"]
    r = _say(db, s, cfg, "still not")
    assert r["contact_step"] == "consent" and not r["ask_contact"] and "and by email" not in r["messages"][-1]["text"]


def test_switched_off_goes_straight_to_consent():
    db = _db(); cfg = _cfg(db); cfg["ask_email"] = False; s = _open(db, cfg)
    _say(db, s, cfg, "Ada"); r = _say(db, s, cfg, "08031234567")
    assert r["contact_step"] == "consent"


def test_skip_words():
    for w in ("skip", "Skip", "no", "not now", "no thanks"):
        assert c.is_skip(w), w
    assert not c.is_skip("ada@example.com") and not c.is_skip("what is your price?")


def test_setting_is_saved_and_on_by_default():
    assert wc.DEFAULT_CONFIG["ask_email"] is True
    assert wc.sanitise_config({"ask_email": False})["ask_email"] is False


def test_the_email_reaches_the_saved_contact():
    db = _db(); cfg = _cfg(db); s = _open(db, cfg)
    for t in ("Ada", "08031234567", "ada@example.com"):
        _say(db, s, cfg, t)
    seen = {}
    real = wc.validate_contact
    def spy(name, phone, email, consent, **kw):
        seen["email"] = email
        return real(name, phone, email, consent, **kw)
    with patch.object(wc, "validate_contact", spy), \
         patch("app.services.funnel_service._find_org_lead", return_value=None), \
         patch("app.services.lead_service.create_lead", return_value={"id": "L1"}):
        _say(db, s, cfg, "yes")
    assert seen.get("email") == "ada@example.com"
