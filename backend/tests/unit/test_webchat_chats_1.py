"""WEBCHAT-CHATS-1: the Chats tab backend. Every web chat (incl. visitors with no contact), filters, transcript, manager-only routes."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import webchat_chats_service as cs

ORG = "11111111-1111-4111-a111-111111111111"
S1 = "4f2a0000-0000-4000-a000-000000000001"     # no contact, asked, viewing a product
S2 = "9bc10000-0000-4000-a000-000000000002"     # lead, ordered and paid
S3 = "aa000000-0000-4000-a000-000000000003"     # no contact, no messages, gap + handed to team
LEAD = "22222222-2222-4222-a222-222222222222"


def _db(sessions=None, events=None, messages=None):
    db = MagicMock()
    data = {"webchat_sessions": sessions or [], "webchat_events": events or [], "whatsapp_messages": messages or []}

    def _table(name):
        t = MagicMock()
        for m in ("select", "eq", "gte", "order", "limit", "in_"):
            getattr(t, m).return_value = t
        t.execute.return_value.data = data.get(name, [])
        return t
    db.table.side_effect = _table
    return db


def _sess(sid, **kw):
    base = {"id": sid, "lead_id": None, "contact_name": None, "source": "link", "state": {}, "turn_count": 0,
            "created_at": "2026-11-20T10:00:00+00:00", "last_activity_at": "2026-11-20T10:05:00+00:00", "history": []}
    base.update(kw)
    return base


def _all():
    return _db(
        sessions=[
            _sess(S1, turn_count=3, state={"viewing_title": "Elite Cool", "cart": [{"title": "Elite Cool", "qty": 2}]}, source="elite-cool-sales"),
            _sess(S2, lead_id=LEAD, contact_name="Ada", turn_count=5, source="catalog"),
            _sess(S3, state={"human_at": "x", "gap_at": "y"}),
        ],
        events=[{"session_id": S2, "kind": "order"}, {"session_id": S2, "kind": "paid"}],
    )


def test_visitor_code_is_stable_and_short():
    assert cs.visitor_code(S1) == "Visitor 4F2A"
    assert cs.visitor_code(S1) == cs.visitor_code(S1)


def test_list_includes_visitors_without_contact():
    out = cs.list_chats(_all(), ORG)
    assert out["total"] == 3
    by = {c["id"]: c for c in out["chats"]}
    assert by[S1]["has_contact"] is False and by[S1]["name"] is None and by[S1]["code"] == "Visitor 4F2A"
    assert by[S2]["name"] == "Ada" and by[S2]["lead_id"] == LEAD


def test_list_never_returns_phone_or_email():
    blob = str(cs.list_chats(_all(), ORG))
    assert "contact_phone" not in blob and "contact_email" not in blob


def test_flags_and_counts():
    out = cs.list_chats(_all(), ORG)
    by = {c["id"]: c for c in out["chats"]}
    assert by[S1]["cart_items"] == 2 and by[S1]["viewing"] == "Elite Cool"
    assert by[S2]["ordered"] and by[S2]["paid"]
    assert by[S3]["handed"] and by[S3]["gap"]
    assert out["counts"] == {"all": 3, "asked": 2, "no_contact": 2, "gap": 1, "ordered": 1, "human": 1}


@pytest.mark.parametrize("flt,ids", [("asked", {S1, S2}), ("no_contact", {S1, S3}), ("gap", {S3}), ("ordered", {S2}), ("human", {S3})])
def test_filters(flt, ids):
    assert {c["id"] for c in cs.list_chats(_all(), ORG, flt=flt)["chats"]} == ids


def test_unknown_filter_means_all():
    assert cs.list_chats(_all(), ORG, flt="bogus")["total"] == 3


def test_source_filter_and_source_list():
    out = cs.list_chats(_all(), ORG, source="catalog")
    assert [c["id"] for c in out["chats"]] == [S2]
    assert out["sources"] == ["catalog", "elite-cool-sales", "link"]


def test_paging():
    out = cs.list_chats(_all(), ORG, limit=2, offset=2)
    assert out["total"] == 3 and len(out["chats"]) == 1


def test_query_failure_gives_empty_list_not_an_error():
    db = MagicMock()
    db.table.side_effect = RuntimeError("down")
    out = cs.list_chats(db, ORG)
    assert out["chats"] == [] and out["total"] == 0


def test_transcript_without_lead_reads_history():
    s = _sess(S1, history=[{"id": "m1", "role": "bot", "text": "Hi", "at": "t1"}, {"id": "m2", "role": "visitor", "text": "price?", "at": "t2"}],
              state={"cart": [{"title": "Elite", "qty": 1, "price": 100}]})
    got = cs.get_chat(_db(sessions=[s]), ORG, S1)
    assert [m["role"] for m in got["messages"]] == ["bot", "visitor"]
    assert got["cart"] == [{"title": "Elite", "qty": 1, "price": 100}]


def test_transcript_with_lead_reads_whatsapp_messages():
    s = _sess(S2, lead_id=LEAD)
    msgs = [{"id": "a", "content": "hello", "direction": "inbound", "sent_by": None, "created_at": "1"},
            {"id": "b", "content": "hi!", "direction": "outbound", "sent_by": None, "created_at": "2"},
            {"id": "c", "content": "call me", "direction": "outbound", "sent_by": "user1", "created_at": "3"}]
    got = cs.get_chat(_db(sessions=[s], messages=msgs), ORG, S2)
    assert [m["role"] for m in got["messages"]] == ["visitor", "bot", "rep"]


def test_transcript_unknown_chat_is_none():
    assert cs.get_chat(_db(), ORG, S1) is None


# ── routes ──
def test_routes_are_manager_only():
    from app.routers import webchat as r
    rep = {"org_id": ORG, "roles": {"template": "sales_agent"}}
    for call in (lambda: r.chats(30, "all", None, 50, 0, MagicMock(), rep), lambda: r.chat_one(S1, MagicMock(), rep)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 403


def test_route_404_for_unknown_chat():
    from app.routers import webchat as r
    owner = {"org_id": ORG, "roles": {"template": "owner"}}
    with patch.object(r, "_require_plan"), patch("app.services.webchat_chats_service.get_chat", return_value=None):
        with pytest.raises(HTTPException) as e:
            r.chat_one(S1, MagicMock(), owner)
    assert e.value.status_code == 404


def test_gap_marker_is_recorded_on_the_session():
    from app.services import webchat_flow_service as flow
    s = {"id": S1, "org_id": ORG, "state": {}}
    with patch.object(flow.kgap, "record"), patch.object(flow.wc, "set_state") as ss:
        flow._record_gap(MagicMock(), s, "do you deliver to mars")
    assert ss.call_args.kwargs.get("gap_at")


# ── frontend wiring (source checks) ──
def test_chats_tab_wired_into_the_page():
    from pathlib import Path
    fe = Path(__file__).resolve().parents[3] / "frontend" / "src"
    mod = (fe / "modules/webchat/WebChatModule.jsx").read_text(encoding="utf-8")
    assert "WebChatChats" in mod and "['chats', 'Chats']" in mod
    chats = (fe / "modules/webchat/WebChatChats.jsx").read_text(encoding="utf-8")
    assert "getWebchatChats" in chats and "getWebchatChat(" in chats
    svc = (fe / "services/webchat.service.js").read_text(encoding="utf-8")
    assert "/api/v1/webchat/chats" in svc
