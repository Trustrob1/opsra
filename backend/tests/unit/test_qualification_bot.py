"""
tests/unit/test_qualification_bot.py

Unit and integration tests for M01-3 — WhatsApp Qualification Bot:
  - ai_service.run_qualification_turn()
  - ai_service.generate_qualification_defaults()
  - webhooks._handle_qualification_turn()
  - POST /api/v1/leads/capture — session creation + WA link
  - GET/PATCH /api/v1/admin/qualification-bot

Patterns:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 28 : get_current_org overridden
  - Pattern 32 : pop() teardown
  - Pattern 42 : patch() on module-level imports
  - S14        : AI failure returns fallback, never crashes
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID   = "00000000-0000-0000-0000-000000000001"
LEAD_ID  = "00000000-0000-0000-0000-000000000010"
USER_ID  = "00000000-0000-0000-0000-000000000099"
ORG_SLUG = "test-org"

_ORG_CONFIG = {
    "id":                             ORG_ID,
    "name":                           "Test Organisation",
    "industry":                       "software",
    "whatsapp_phone_id":              "phone-id-001",
    "org_whatsapp_number":            "2348012345678",
    "qualification_bot_name":         "Amaka",
    "qualification_opening_message":  "",
    "qualification_script":           "",
    "qualification_fields":           ["problem_stated", "business_type", "business_size"],
    "qualification_handoff_triggers": "demo, pricing, ready to start",
    "qualification_fallback_hours":   2,
}

_SESSION = {
    "id":              "00000000-0000-0000-0000-000000000020",
    "org_id":          ORG_ID,
    "lead_id":         LEAD_ID,
    "stage":           "collecting",
    "collected":       {"problem_stated": "We lose track of stock"},
    "ai_active":       True,
    "turn_count":      1,
    "last_message_at": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain(data=None, count=None):
    chain = MagicMock()
    result = MagicMock()
    result.data  = data if data is not None else []
    result.count = count if count is not None else (len(data) if isinstance(data, list) else 0)
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "order", "limit", "maybe_single",
              "update", "insert", "neq", "in_"):
        getattr(chain, m).return_value = chain
    return chain


# ===========================================================================
# 1 — ai_service.run_qualification_turn
# ===========================================================================

class TestRunQualificationTurn:

    def test_returns_reply_and_extracted_fields(self):
        from app.services.ai_service import run_qualification_turn
        ai_response = '{"reply":"Got it! What type of business do you run?","extracted_fields":{"problem_stated":"stock tracking"},"next_stage":"collecting","trigger_handoff":false,"handoff_reason":null}'
        with patch("app.services.ai_service.call_claude", return_value=ai_response):
            result = run_qualification_turn(
                org_config=_ORG_CONFIG,
                session=_SESSION,
                conversation_history=[],
                new_message="We lose track of stock across our branches",
            )
        assert result["reply"] == "Got it! What type of business do you run?"
        assert result["extracted_fields"]["problem_stated"] == "stock tracking"
        assert result["trigger_handoff"] is False

    def test_returns_fallback_on_ai_failure(self):
        """S14 — empty AI response returns safe fallback reply."""
        from app.services.ai_service import run_qualification_turn
        with patch("app.services.ai_service.call_claude", return_value=""):
            result = run_qualification_turn(
                org_config=_ORG_CONFIG,
                session=_SESSION,
                conversation_history=[],
                new_message="Hello",
            )
        assert result["reply"]           != ""
        assert result["trigger_handoff"] is True
        assert result["next_stage"]      == "handed_off"

    def test_returns_fallback_on_invalid_json(self):
        """S14 — malformed JSON response returns safe fallback."""
        from app.services.ai_service import run_qualification_turn
        with patch("app.services.ai_service.call_claude", return_value="not json at all"):
            result = run_qualification_turn(
                org_config=_ORG_CONFIG,
                session=_SESSION,
                conversation_history=[],
                new_message="Hello",
            )
        assert result["trigger_handoff"] is True

    def test_forces_handoff_at_max_turns(self):
        """After 20 turns, trigger_handoff must be True regardless of AI response."""
        from app.services.ai_service import run_qualification_turn
        ai_response = '{"reply":"Still chatting","extracted_fields":{},"next_stage":"collecting","trigger_handoff":false,"handoff_reason":null}'
        high_turn_session = {**_SESSION, "turn_count": 20}
        with patch("app.services.ai_service.call_claude", return_value=ai_response):
            result = run_qualification_turn(
                org_config=_ORG_CONFIG,
                session=high_turn_session,
                conversation_history=[],
                new_message="Hello",
            )
        assert result["trigger_handoff"] is True

    def test_detects_handoff_trigger(self):
        """When trigger_handoff=true in AI response, result reflects it."""
        from app.services.ai_service import run_qualification_turn
        ai_response = '{"reply":"Great! Let me connect you.","extracted_fields":{},"next_stage":"handed_off","trigger_handoff":true,"handoff_reason":"user requested demo"}'
        with patch("app.services.ai_service.call_claude", return_value=ai_response):
            result = run_qualification_turn(
                org_config=_ORG_CONFIG,
                session=_SESSION,
                conversation_history=[],
                new_message="I want a demo please",
            )
        assert result["trigger_handoff"] is True
        assert result["handoff_reason"]  == "user requested demo"

    def test_uses_org_handoff_triggers_in_prompt(self):
        """Org-configured handoff triggers are injected into the system prompt."""
        from app.services.ai_service import run_qualification_turn
        captured_system = []
        def mock_claude(prompt, model, max_tokens, system=None):
            captured_system.append(system or "")
            return '{"reply":"ok","extracted_fields":{},"next_stage":"collecting","trigger_handoff":false,"handoff_reason":null}'
        with patch("app.services.ai_service.call_claude", side_effect=mock_claude):
            run_qualification_turn(
                org_config=_ORG_CONFIG,
                session=_SESSION,
                conversation_history=[],
                new_message="Hello",
            )
        assert "demo, pricing, ready to start" in captured_system[0]


# ===========================================================================
# 2 — webhooks._handle_qualification_turn
# ===========================================================================

class TestHandleQualificationTurn:

    def _make_db(self, session=None, org=None):
        db = MagicMock()
        session_chain = _chain([session] if session else [])
        org_chain     = _chain(org or _ORG_CONFIG)
        history_chain = _chain([])
        leads_chain   = _chain([{"id": LEAD_ID, "phone": "2348012345678", "whatsapp": "2348012345678"}])
        wa_chain      = _chain([{"id": "wa-001"}])
        notif_chain   = _chain([])
        audit_chain   = _chain([])
        update_chain  = _chain([])

        def _tbl(name):
            if name == "lead_qualification_sessions": return session_chain
            if name == "organisations":               return org_chain
            if name == "whatsapp_messages":           return wa_chain
            if name == "leads":                       return leads_chain
            if name == "notifications":               return notif_chain
            if name == "audit_logs":                  return audit_chain
            return _chain()

        db.table.side_effect = _tbl
        return db, session_chain, notif_chain

    def test_raises_when_no_active_session(self):
        """No active session → raises ValueError so caller falls back."""
        from app.routers.webhooks import _handle_qualification_turn
        db, _, _ = self._make_db(session=None)
        with pytest.raises(ValueError, match="No active qualification session"):
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="Hello", now_ts="2026-04-08T10:00:00+00:00",
            )

    def test_calls_ai_and_sends_reply(self):
        """Happy path: active session → AI turn → reply sent via DB."""
        from app.routers.webhooks import _handle_qualification_turn
        db, session_chain, _ = self._make_db(session=_SESSION)
        ai_result = {
            "reply":            "What type of business do you run?",
            "extracted_fields": {},
            "next_stage":       "collecting",
            "trigger_handoff":  False,
            "handoff_reason":   None,
        }
        with patch("app.services.ai_service.run_qualification_turn", return_value=ai_result), \
             patch("app.routers.webhooks._send_qualification_reply") as mock_send:
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="Hello", now_ts="2026-04-08T10:00:00+00:00",
            )
        mock_send.assert_called_once()

    def test_notifies_rep_on_handoff(self):
        """When trigger_handoff=True, rep notification is inserted."""
        from app.routers.webhooks import _handle_qualification_turn
        db, _, notif_chain = self._make_db(session=_SESSION)
        ai_result = {
            "reply":            "Let me connect you with our team!",
            "extracted_fields": {"business_type": "supermarket"},
            "next_stage":       "handed_off",
            "trigger_handoff":  True,
            "handoff_reason":   "user requested demo",
        }
        with patch("app.services.ai_service.run_qualification_turn", return_value=ai_result), \
             patch("app.routers.webhooks._send_qualification_reply"):
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="I want a demo", now_ts="2026-04-08T10:00:00+00:00",
            )
        notif_chain.insert.assert_called()
        notif_row = notif_chain.insert.call_args[0][0]
        assert notif_row["type"] == "qualification_complete"

    def test_scoring_triggered_at_handoff(self):
        """When trigger_handoff=True, score_lead is called after session update."""
        from app.routers.webhooks import _handle_qualification_turn
        db, _, _ = self._make_db(session=_SESSION)
        ai_result = {
            "reply":            "Let me connect you with our team!",
            "extracted_fields": {"business_type": "supermarket", "branches": "3"},
            "next_stage":       "handed_off",
            "trigger_handoff":  True,
            "handoff_reason":   "user requested demo",
        }
        with patch("app.services.ai_service.run_qualification_turn", return_value=ai_result), \
             patch("app.routers.webhooks._send_qualification_reply"), \
             patch("app.services.lead_service.score_lead") as mock_score:
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="I want a demo", now_ts="2026-04-08T10:00:00+00:00",
            )
        mock_score.assert_called_once_with(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
        )

    def test_scoring_failure_does_not_disrupt_handoff(self):
        """S14 — if score_lead raises, handoff still completes cleanly."""
        from app.routers.webhooks import _handle_qualification_turn
        db, _, notif_chain = self._make_db(session=_SESSION)
        ai_result = {
            "reply":            "Connecting you now.",
            "extracted_fields": {},
            "next_stage":       "handed_off",
            "trigger_handoff":  True,
            "handoff_reason":   "user requested demo",
        }
        with patch("app.services.ai_service.run_qualification_turn", return_value=ai_result), \
             patch("app.routers.webhooks._send_qualification_reply"), \
             patch("app.services.lead_service.score_lead", side_effect=Exception("AI unavailable")):
            # Must not raise — S14
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="I want a demo", now_ts="2026-04-08T10:00:00+00:00",
            )
        # Notification still sent despite scoring failure
        notif_chain.insert.assert_called()

    def test_scoring_not_triggered_without_handoff(self):
        """score_lead must NOT fire on a normal non-handoff turn."""
        from app.routers.webhooks import _handle_qualification_turn
        db, _, _ = self._make_db(session=_SESSION)
        ai_result = {
            "reply":            "What type of business do you run?",
            "extracted_fields": {"problem_stated": "stock tracking"},
            "next_stage":       "collecting",
            "trigger_handoff":  False,
            "handoff_reason":   None,
        }
        with patch("app.services.ai_service.run_qualification_turn", return_value=ai_result), \
             patch("app.routers.webhooks._send_qualification_reply"), \
             patch("app.services.lead_service.score_lead") as mock_score:
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="Hello", now_ts="2026-04-08T10:00:00+00:00",
            )
        mock_score.assert_not_called()

    def test_ai_failure_raises_so_caller_falls_back(self):
        """If AI errors and returns handoff, session is updated but no crash."""
        from app.routers.webhooks import _handle_qualification_turn
        db, _, _ = self._make_db(session=_SESSION)
        # run_qualification_turn itself handles AI failure — returns fallback
        fallback = {
            "reply": "Let me connect you with our team.",
            "extracted_fields": {},
            "next_stage": "handed_off",
            "trigger_handoff": True,
            "handoff_reason": "AI error",
        }
        with patch("app.services.ai_service.run_qualification_turn", return_value=fallback), \
             patch("app.routers.webhooks._send_qualification_reply"):
            # Should not raise
            _handle_qualification_turn(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, content="Hello", now_ts="2026-04-08T10:00:00+00:00",
            )


# ===========================================================================
# 3 — POST /api/v1/leads/capture — session creation + WA deep link
# ===========================================================================

class TestCaptureLeadWithQualification:

    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def _configure_db(self, org_row=None, wa_number="2348012345678"):
        org = {
            "id": ORG_ID, "slug": ORG_SLUG,
            "org_whatsapp_number": wa_number,
            "name": "Test Organisation",
        }
        if org_row is not None:
            org = org_row
        org_chain     = _chain(org)
        session_chain = _chain([])
        leads_chain   = _chain([])
        notif_chain   = _chain([])
        audit_chain   = _chain([])

        def _tbl(name):
            if name == "organisations":               return org_chain
            if name == "lead_qualification_sessions": return session_chain
            if name == "leads":                       return leads_chain
            if name == "notifications":               return notif_chain
            if name == "audit_logs":                  return audit_chain
            return _chain()

        self.mock_db.table.side_effect = _tbl
        return session_chain

    def test_returns_whatsapp_link_on_success(self):
        session_chain = self._configure_db()
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        new_lead = {"id": LEAD_ID, "org_id": ORG_ID, "full_name": "Emeka", "phone": "08012345678", "source": "landing_page"}
        with patch("app.routers.leads.lead_service.create_lead", return_value=new_lead):
            resp = client.post("/api/v1/leads/capture", json={
                "org_slug": ORG_SLUG, "full_name": "Emeka", "phone": "08012345678",
            })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "whatsapp_link" in data
        assert "wa.me" in data["whatsapp_link"]
        assert "2348012345678" in data["whatsapp_link"]

    def test_wa_link_contains_prefilled_message(self):
        self._configure_db()
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        new_lead = {"id": LEAD_ID, "org_id": ORG_ID, "full_name": "Emeka", "phone": "08012345678", "source": "landing_page"}
        with patch("app.routers.leads.lead_service.create_lead", return_value=new_lead):
            resp = client.post("/api/v1/leads/capture", json={
                "org_slug": ORG_SLUG, "full_name": "Emeka", "phone": "08012345678",
            })
        link = resp.json()["data"]["whatsapp_link"]
        assert "text=" in link
        assert "Emeka" in link

    def test_session_created_for_new_lead(self):
        session_chain = self._configure_db()
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        new_lead = {"id": LEAD_ID, "org_id": ORG_ID, "full_name": "Emeka", "phone": "08012345678", "source": "landing_page"}
        with patch("app.routers.leads.lead_service.create_lead", return_value=new_lead):
            client.post("/api/v1/leads/capture", json={
                "org_slug": ORG_SLUG, "full_name": "Emeka", "phone": "08012345678",
            })
        session_chain.insert.assert_called()
        inserted = session_chain.insert.call_args[0][0]
        assert inserted["lead_id"] == LEAD_ID
        assert inserted["stage"]   == "awaiting_first_message"
        assert inserted["ai_active"] is True

    def test_empty_wa_link_when_no_number_configured(self):
        self._configure_db(org_row={
            "id": ORG_ID, "slug": ORG_SLUG,
            "org_whatsapp_number": None,
            "name": "Test Organisation",
        })
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        new_lead = {"id": LEAD_ID, "org_id": ORG_ID, "full_name": "Emeka", "phone": "08012345678", "source": "landing_page"}
        with patch("app.routers.leads.lead_service.create_lead", return_value=new_lead):
            resp = client.post("/api/v1/leads/capture", json={
                "org_slug": ORG_SLUG, "full_name": "Emeka", "phone": "08012345678",
            })
        assert resp.status_code == 201
        assert resp.json()["data"]["whatsapp_link"] == ""


# ===========================================================================
# 4 — GET/PATCH /api/v1/admin/qualification-bot
# ===========================================================================

class TestQualificationBotAdminRoutes:

    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        self.mock_db = MagicMock()
        self._org = {
            "id": USER_ID, "org_id": ORG_ID,
            "roles": {"template": "owner", "permissions": {"is_admin": True}},
        }
        # require_permission() is a factory — each call returns a NEW _check function,
        # so the callable registered in the router and any callable captured in the test
        # are different objects; dependency_overrides lookup by identity will never match.
        # Also, has_permission() does NOT auto-grant owners — it checks permissions.get(key)
        # only. Correct approach: override get_current_org so _check receives our stub org,
        # then patch has_permission to always return True (Pattern 43).
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: self._org
        self._patcher = patch("app.dependencies.has_permission", return_value=True)
        self._patcher.start()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase,    None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_returns_200_with_config(self):
        self.mock_db.table.return_value = _chain(_ORG_CONFIG)
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        resp = client.get("/api/v1/admin/qualification-bot")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_patch_saves_and_returns_200(self):
        update_chain = _chain([_ORG_CONFIG])
        self.mock_db.table.return_value = update_chain
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        resp = client.patch("/api/v1/admin/qualification-bot", json={
            "qualification_bot_name":  "Amaka from Ovaloop",
            "org_whatsapp_number":     "2348012345678",
            "qualification_fallback_hours": 2,
        })
        assert resp.status_code == 200

    def test_ai_recommendations_endpoint_returns_200(self):
        self.mock_db.table.return_value = _chain(_ORG_CONFIG)
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        ai_suggestions = {
            "qualification_bot_name": "Amaka",
            "qualification_opening_message": "Hi! I'm Amaka...",
            "qualification_script": "Focus on retail challenges.",
            "qualification_handoff_triggers": "demo, pricing",
        }
        with patch("app.services.ai_service.generate_qualification_defaults",
                   return_value=ai_suggestions):
            resp = client.post("/api/v1/admin/qualification-bot/ai-recommendations")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["qualification_bot_name"] == "Amaka"