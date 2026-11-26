"""HANDOFF-CONTACT-1: when Chioma asked a question, the visitor answered and there is no AI answer (AI off or out of credit),
the chat is really handed to the team: the team is told, and a visitor with no details is asked for them in the chat."""
from __future__ import annotations

from unittest.mock import patch

from app.services import webchat_flow_service as flow
from app.services import webchat_handover_service as ho
from app.services import webchat_ai_service as ai_svc
from tests.unit.test_webchat_3 import _cfg, _db, _no_rate_limit, _session  # noqa: F401


def _say(db, s, cfg, text):
    return flow.handle_message(db, s, cfg, kind="text", menu_id=None, text=text, reply_to=None)


def _run(contact, away=False, ai=False):
    db = _db(ai=ai, answer_first=True); s = _session(db, contact=contact, bot_asked=True); cfg = _cfg(db)
    told = []
    with patch.object(ho, "is_away", return_value=away), patch.object(ai_svc, "answer", return_value=None), \
            patch.object(flow, "_notify_human", side_effect=lambda *a, **k: told.append(a[-1])):
        r = _say(db, s, cfg, "Both sides and for 2 person")
    return r, s, told


def test_new_visitor_is_handed_over_and_asked_for_details_in_the_chat():
    r, s, told = _run(contact=False)
    texts = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert texts[0] == flow._REPLY_TO_TEAM
    assert r["human"] is True and r.get("contact_step") == "name" and len(texts) >= 2      # the name question follows
    assert told and "Both sides and for 2 person" in told[0]                               # the team is told


def test_known_visitor_is_handed_over_without_asking_again():
    r, s, told = _run(contact=True)
    assert r["human"] is True and not r.get("contact_step") and r["ask_contact"] is False
    assert [m["text"] for m in r["messages"] if m["role"] == "bot"] == [flow._REPLY_TO_TEAM]
    assert told


def test_team_away_uses_the_away_wording():
    r, s, told = _run(contact=False, away=True)
    bot = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert bot[0] != flow._REPLY_TO_TEAM and "first name" in bot[1] and r["human"] is True and r.get("contact_step") == "name"


def test_no_question_asked_keeps_the_normal_fallback():
    db = _db(ai=False); s = _session(db, contact=False); cfg = _cfg(db)
    with patch.object(ai_svc, "answer", return_value=None), patch.object(flow, "_notify_human") as n:
        r = _say(db, s, cfg, "zzqq unknown thing")
    assert r["human"] is False and not n.called
