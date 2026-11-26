"""WEBCHAT-BUBBLE-2: Chioma in the chat page - flags, team member names, greeting, AI line, page strings."""
import os
from datetime import datetime, timezone

from app.services import webchat_service as wc
from app.services import webchat_call_service as call

_BH = {d: {"start": "08:00", "end": "17:00"} for d in ("mon", "tue", "wed", "thu", "fri")}
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _cfg(**over):
    c = dict(wc.DEFAULT_CONFIG)
    c.update({"business_name": "RR", "_call_org": {"business_hours": _BH, "timezone": "Africa/Lagos"}})
    c.update(over)
    return c


def test_flags_closed_gives_reopens_words(monkeypatch):
    sat = datetime(2026, 11, 14, 11, 0, tzinfo=timezone.utc)
    real = call.open_state
    monkeypatch.setattr(call, "open_state", lambda bh, tz, now=None: real(bh, tz, sat))
    f = wc.chioma_flags(_cfg())
    assert f["team_available"] is False and f["online"] is False and "Monday" in f["reopens"]


def test_flags_ai_on_is_online_even_when_closed(monkeypatch):
    sat = datetime(2026, 11, 14, 11, 0, tzinfo=timezone.utc)
    real = call.open_state
    monkeypatch.setattr(call, "open_state", lambda bh, tz, now=None: real(bh, tz, sat))
    f = wc.chioma_flags(_cfg(ai_enabled=True))
    assert f["assistant_active"] is True and f["online"] is True and f["team_available"] is False


def test_flags_never_raise(monkeypatch):
    def boom(*a, **k): raise RuntimeError("x")
    monkeypatch.setattr(call, "open_state", boom)
    assert wc.chioma_flags({"ai_enabled": False}) == {"assistant_active": False, "team_available": False, "online": False, "reopens": ""}


def test_public_view_has_chioma_and_human_item():
    cfg = _cfg(menu=[{"id": "a", "label": "Prices"}, {"id": "h", "label": "Talk to us", "action": "human"}])
    v = wc.public_view(cfg)
    assert "chioma" in v and v["human_menu_id"] == "h"
    assert wc.public_view(_cfg(menu=[{"id": "a", "label": "Prices"}]))["human_menu_id"] is None
    assert "action" not in str(v["menu"])


def test_new_default_greeting_leads_with_what_chioma_can_do():
    g = wc.DEFAULT_CONFIG["greeting"]          # CHIOMA-VOICE-1: a warm welcome first, then what to do next
    assert "Chioma" in g and g.startswith("{hello}, welcome to {business}") and "Menu at the top" not in g


class _Q:
    def __init__(self, rows): self.rows = rows
    def select(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def execute(self): return type("R", (), {"data": self.rows})


class _DB:
    def __init__(self, rows): self.rows = rows
    def table(self, n):
        assert n == "users"
        return _Q(self.rows)


def test_rep_first_name_attached_only_to_rep_messages():
    outs = [{"id": "1", "role": "visitor"}, {"id": "2", "role": "rep"}, {"id": "3", "role": "bot"}]
    rows = [{"sent_by": None}, {"sent_by": "u1"}, {"sent_by": None}]
    wc._attach_rep_names(_DB([{"id": "u1", "full_name": "Ada Obi"}]), outs, rows)
    assert outs[1]["by"] == "Ada" and "by" not in outs[0] and "by" not in outs[2]


def test_rep_name_lookup_failure_is_silent():
    class Bad:
        def table(self, n): raise RuntimeError("db down")
    outs = [{"id": "2", "role": "rep"}]
    wc._attach_rep_names(Bad(), outs, [{"sent_by": "u1"}])
    assert "by" not in outs[0]
    wc._attach_rep_names(Bad(), [], [])


def test_ai_prompt_names_chioma_and_forbids_claiming_to_be_human(monkeypatch):
    from app.services import webchat_ai_service as ai
    monkeypatch.setattr(ai, "_knowledge", lambda *a, **k: "Open 8 to 5.")
    p = ai.build_system_prompt(None, {"org_id": "o"}, {"business_name": "Royal Rest", "shop_enabled": False}, "hi")
    assert "You are Chioma" in p and "never claim to be a person" in p and "Royal Rest" in p


def _page():
    return open(os.path.join(_ROOT, "frontend", "src", "pages", "WebChatPage.jsx"), encoding="utf-8").read()


def test_page_shows_label_and_scripted_states():
    js = _page()
    hdr = open(os.path.join(_ROOT, "frontend", "src", "utils", "webchatHeader.js"), encoding="utf-8").read()
    assert "Virtual assistant for ${businessName}" in hdr and "waitingLine" in js          # rule 1: same label in every mode (now built in webchatHeader.js)
    assert "How can I help?" in js and "Need a person?" in js
    assert "Talk to the team" in js and "Open menu" in js                # stock reply gets Menu + Talk to the team
    assert "/chioma/chioma-face-64.webp" in js
    assert "Chioma is typing" in js


def test_page_swaps_header_for_team_member():
    js = _page()
    assert "withTeam ? (teamWho ||" in js and "'Chioma'" in js           # team name while a person is in, Chioma otherwise
