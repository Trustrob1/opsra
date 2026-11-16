"""WEBCHAT-BUBBLE-1: the launcher flags on /widget, and widget.js / asset checks."""
import json
import os
import re

from app.routers import public_webchat as r
from app.services import webchat_service as wc

_BH = {d: {"start": "08:00", "end": "17:00"} for d in ("mon", "tue", "wed", "thu", "fri")}


def _found(**over):
    cfg = {"allowed_domains": [], "business_name": "RR", "brand_color": "#028090", "widget_side": "right",
           "ai_enabled": False, "_call_org": {"business_hours": None, "timezone": "Africa/Lagos"}}
    cfg.update(over)
    return {"org_id": "o", "config": cfg}


class _Req:
    def __init__(self, o="https://royalrest.com"): self.headers = {"origin": o}


def _data(monkeypatch, found):
    monkeypatch.setattr(wc, "resolve_key", lambda db, k: found)
    monkeypatch.setattr("app.services.webchat_embed_service.record_seen", lambda *a, **k: None)
    return json.loads(r.widget_info("wc_ok123456", _Req(), None).body)["data"]


def test_ai_off_no_hours_no_dot(monkeypatch):
    d = _data(monkeypatch, _found())
    assert d["allowed"] and d["assistant_active"] is False and d["team_available"] is False and d["online"] is False


def test_ai_on_gives_dot_even_without_hours(monkeypatch):
    d = _data(monkeypatch, _found(ai_enabled=True))
    assert d["assistant_active"] is True and d["online"] is True


def test_team_hours_drive_dot(monkeypatch):
    from app.services import webchat_call_service as call
    from datetime import datetime, timezone
    monkeypatch.setattr(call, "open_state", lambda bh, tz, now=None: {"open": True})
    assert _data(monkeypatch, _found(_call_org={"business_hours": _BH, "timezone": "Africa/Lagos"}))["team_available"] is True
    monkeypatch.setattr(call, "open_state", lambda bh, tz, now=None: {"open": False})
    d = _data(monkeypatch, _found(_call_org={"business_hours": _BH, "timezone": "Africa/Lagos"}))
    assert d["team_available"] is False and d["online"] is False


def test_real_open_state_monday_noon(monkeypatch):
    from app.services import webchat_call_service as call
    from datetime import datetime, timezone
    mon_noon = datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)          # 12:00 Lagos, a Monday
    assert call.open_state(_BH, "Africa/Lagos", mon_noon)["open"] is True
    sun = datetime(2026, 11, 15, 11, 0, tzinfo=timezone.utc)
    assert call.open_state(_BH, "Africa/Lagos", sun)["open"] is False


def test_flags_never_raise(monkeypatch):
    from app.services import webchat_call_service as call
    def boom(*a, **k): raise RuntimeError("x")
    monkeypatch.setattr(call, "open_state", boom)
    assert r._chioma_flags({"ai_enabled": False}) == {"assistant_active": False, "team_available": False, "online": False}


def test_refused_site_and_unknown_key_unchanged(monkeypatch):
    f = _found(allowed_domains=["royalrest.com"])
    monkeypatch.setattr(wc, "resolve_key", lambda db, k: f if k == "wc_ok123456" else None)
    assert not json.loads(r.widget_info("wc_ok123456", _Req("https://other.com"), None).body)["data"]["allowed"]
    assert json.loads(r.widget_info("wc_missing00", _Req(), None).body)["data"] == {"allowed": False}


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def test_chioma_assets_exist_and_are_small():
    for n in ("chioma-96", "chioma-192", "chioma-640", "chioma-face-64", "chioma-face-128"):
        p = os.path.join(_ROOT, "frontend", "public", "chioma", n + ".webp")
        assert os.path.isfile(p), n
        assert os.path.getsize(p) < 60_000, n


def test_widget_js_uses_chioma_labels_and_safe_patterns():
    js = open(os.path.join(_ROOT, "frontend", "public", "widget.js"), encoding="utf-8").read()
    assert "Chat with Chioma" in js and "Virtual assistant for" in js
    assert "prefers-reduced-motion" in js and "prefers-color-scheme" in js
    assert "/chioma/chioma-face-" in js
    assert "innerHTML = d." not in js and "eval(" not in js
