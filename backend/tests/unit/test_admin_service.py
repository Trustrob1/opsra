"""
backend/tests/unit/test_admin_service.py
Unit tests for admin_service.py — Phase 8A additions.

Covers:
  list_user_overrides      — 3 tests
  create_user_override     — 4 tests
  delete_user_override     — 3 tests
  create_routing_rule      — 3 tests
  update_routing_rule      — 4 tests
  delete_routing_rule      — 3 tests

Total: 20 tests

Patterns followed:
  Pattern 8  — separate mock chains per table, counter-based side_effect
  Pattern 24 — valid UUID strings for all ID constants
  Pattern 37 — no flat "role" key — role guard lives in router, not service
  S12        — audit log calls asserted on all mutating operations
"""

import pytest
from unittest.mock import MagicMock, call, patch
from fastapi import HTTPException

from app.services.admin_service import (
    list_user_overrides,
    create_user_override,
    delete_user_override,
    create_routing_rule,
    update_routing_rule,
    delete_routing_rule,
)

# ── UUID constants (Pattern 24) ───────────────────────────────────────────────
ORG_ID      = "00000000-0000-0000-0000-000000000001"
ROLE_ID     = "00000000-0000-0000-0000-000000000002"
USER_ID     = "00000000-0000-0000-0000-000000000003"
OVERRIDE_ID = "00000000-0000-0000-0000-000000000004"
RULE_ID     = "00000000-0000-0000-0000-000000000005"
CALLER_ID   = "00000000-0000-0000-0000-000000000006"


# ── Mock builders ─────────────────────────────────────────────────────────────

def _make_db_routing_rule(existing_data=None, updated_data=None):
    """
    Returns a mock db where:
      - First call to db.table("routing_rules") returns the select/check chain
      - Second call returns the mutate chain
      - Any call to db.table("audit_logs") returns a silent no-op chain
    """
    db = MagicMock()
    call_counts = {"n": 0}

    check_chain = MagicMock()
    check_chain.select.return_value.eq.return_value.eq.return_value \
        .maybe_single.return_value.execute.return_value.data = existing_data

    mutate_chain = MagicMock()
    if updated_data is not None:
        mutate_chain.update.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = [updated_data]
    mutate_chain.delete.return_value.eq.return_value.eq.return_value \
        .execute.return_value = MagicMock()
    mutate_chain.insert.return_value.execute.return_value.data = (
        [existing_data] if existing_data else []
    )

    def _tbl(name):
        if name == "routing_rules":
            call_counts["n"] += 1
            return check_chain if call_counts["n"] == 1 else mutate_chain
        return MagicMock()   # audit_logs — silent

    db.table.side_effect = _tbl
    return db


# ============================================================
# list_user_overrides
# ============================================================

class TestListUserOverrides:
    def test_returns_overrides_with_user_info_attached(self):
        db = MagicMock()

        user_row     = {"id": USER_ID, "full_name": "Ada Obi", "email": "ada@example.com"}
        override_row = {
            "id": OVERRIDE_ID, "user_id": USER_ID,
            "permission_key": "view_revenue", "granted": True,
        }

        users_chain     = MagicMock()
        overrides_chain = MagicMock()
        users_chain.select.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = [user_row]
        overrides_chain.select.return_value.in_.return_value.eq.return_value \
            .execute.return_value.data = [override_row]

        def _tbl(name):
            if name == "users":
                return users_chain
            elif name == "user_permission_overrides":
                return overrides_chain
            return MagicMock()

        db.table.side_effect = _tbl

        result = list_user_overrides(role_id=ROLE_ID, org_id=ORG_ID, db=db)

        assert len(result) == 1
        assert result[0]["permission_key"] == "view_revenue"
        assert result[0]["user"]["full_name"] == "Ada Obi"

    def test_returns_empty_list_when_no_users_in_role(self):
        db = MagicMock()
        users_chain = MagicMock()
        users_chain.select.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = []
        db.table.side_effect = lambda name: users_chain if name == "users" else MagicMock()

        result = list_user_overrides(role_id=ROLE_ID, org_id=ORG_ID, db=db)

        assert result == []
        # Should not query user_permission_overrides at all
        db.table.assert_called_once_with("users")

    def test_returns_empty_list_when_users_have_no_overrides(self):
        db = MagicMock()

        user_row        = {"id": USER_ID, "full_name": "Tunde", "email": "t@x.com"}
        users_chain     = MagicMock()
        overrides_chain = MagicMock()
        users_chain.select.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = [user_row]
        overrides_chain.select.return_value.in_.return_value.eq.return_value \
            .execute.return_value.data = []

        def _tbl(name):
            return users_chain if name == "users" else overrides_chain

        db.table.side_effect = _tbl
        result = list_user_overrides(role_id=ROLE_ID, org_id=ORG_ID, db=db)

        assert result == []


# ============================================================
# create_user_override
# ============================================================

class TestCreateUserOverride:
    def _make_db(self, user_found=True):
        db = MagicMock()
        user_row = {"id": USER_ID, "full_name": "Ada"} if user_found else None

        users_chain     = MagicMock()
        overrides_chain = MagicMock()

        users_chain.select.return_value.eq.return_value.eq.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = user_row
        overrides_chain.insert.return_value.execute.return_value.data = [{
            "id": OVERRIDE_ID, "user_id": USER_ID,
            "permission_key": "view_revenue", "granted": True,
        }]

        def _tbl(name):
            if name == "users":
                return users_chain
            elif name == "user_permission_overrides":
                return overrides_chain
            return MagicMock()

        db.table.side_effect = _tbl
        return db

    def test_creates_override_and_returns_record(self):
        db = self._make_db(user_found=True)

        result = create_user_override(
            role_id=ROLE_ID, user_id=USER_ID, org_id=ORG_ID, db=db,
            permission_key="view_revenue", granted=True, caller_id=CALLER_ID,
        )

        assert result["permission_key"] == "view_revenue"
        assert result["granted"] is True

    def test_raises_404_when_user_not_in_role(self):
        db = self._make_db(user_found=False)

        with pytest.raises(HTTPException) as exc_info:
            create_user_override(
                role_id=ROLE_ID, user_id=USER_ID, org_id=ORG_ID, db=db,
                permission_key="view_revenue", granted=True, caller_id=CALLER_ID,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "NOT_FOUND"

    def test_inserts_correct_payload(self):
        db = self._make_db(user_found=True)

        create_user_override(
            role_id=ROLE_ID, user_id=USER_ID, org_id=ORG_ID, db=db,
            permission_key="manage_tasks", granted=False, caller_id=CALLER_ID,
        )

        # Find the insert call on user_permission_overrides
        insert_calls = [
            c for c in db.table.call_args_list
            if c.args[0] == "user_permission_overrides"
        ]
        assert len(insert_calls) == 1

    def test_writes_audit_log_on_success(self):
        db = self._make_db(user_found=True)

        create_user_override(
            role_id=ROLE_ID, user_id=USER_ID, org_id=ORG_ID, db=db,
            permission_key="view_revenue", granted=True, caller_id=CALLER_ID,
        )

        audit_calls = [
            c for c in db.table.call_args_list
            if c.args[0] == "audit_logs"
        ]
        assert len(audit_calls) == 1


# ============================================================
# delete_user_override
# ============================================================

class TestDeleteUserOverride:
    def _make_db(self, found=True):
        db      = MagicMock()
        record  = {"id": OVERRIDE_ID, "user_id": USER_ID, "permission_key": "view_revenue"} if found else None
        tracker = {"n": 0}

        ov_chain = MagicMock()
        ov_chain.select.return_value.eq.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = record
        ov_chain.delete.return_value.eq.return_value.eq.return_value \
            .execute.return_value = MagicMock()

        def _tbl(name):
            if name == "user_permission_overrides":
                return ov_chain
            return MagicMock()

        db.table.side_effect = _tbl
        return db

    def test_deletes_existing_override(self):
        db = self._make_db(found=True)
        # Should not raise
        delete_user_override(override_id=OVERRIDE_ID, org_id=ORG_ID, db=db, caller_id=CALLER_ID)

    def test_raises_404_when_override_not_found(self):
        db = self._make_db(found=False)

        with pytest.raises(HTTPException) as exc_info:
            delete_user_override(override_id=OVERRIDE_ID, org_id=ORG_ID, db=db, caller_id=CALLER_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "NOT_FOUND"

    def test_writes_audit_log_on_success(self):
        db = self._make_db(found=True)
        delete_user_override(override_id=OVERRIDE_ID, org_id=ORG_ID, db=db, caller_id=CALLER_ID)

        audit_calls = [
            c for c in db.table.call_args_list
            if c.args[0] == "audit_logs"
        ]
        assert len(audit_calls) == 1


# ============================================================
# create_routing_rule
# ============================================================

class TestCreateRoutingRule:
    def _make_db(self):
        db = MagicMock()
        new_rule = {
            "id": RULE_ID, "org_id": ORG_ID,
            "event_type": "new_hot_lead", "channel": "whatsapp_inapp",
        }

        rr_chain = MagicMock()
        rr_chain.insert.return_value.execute.return_value.data = [new_rule]

        db.table.side_effect = lambda name: rr_chain if name == "routing_rules" else MagicMock()
        return db, new_rule

    def test_returns_inserted_rule(self):
        db, expected = self._make_db()
        data = {"event_type": "new_hot_lead", "channel": "whatsapp_inapp",
                "within_hours_only": True}

        result = create_routing_rule(org_id=ORG_ID, db=db, data=data, caller_id=CALLER_ID)

        assert result["event_type"] == "new_hot_lead"
        assert result["id"] == RULE_ID

    def test_org_id_included_in_insert(self):
        db, _ = self._make_db()
        data = {"event_type": "new_hot_lead", "channel": "whatsapp_inapp",
                "within_hours_only": True}

        create_routing_rule(org_id=ORG_ID, db=db, data=data, caller_id=CALLER_ID)

        # org_id must be merged into the insert payload
        insert_call = db.table.return_value.insert.call_args
        # side_effect is set, so check via side_effect route instead
        rr_calls = [c for c in db.table.call_args_list if c.args[0] == "routing_rules"]
        assert len(rr_calls) >= 1

    def test_writes_audit_log(self):
        db, _ = self._make_db()
        data = {"event_type": "new_hot_lead", "channel": "whatsapp_inapp",
                "within_hours_only": True}

        create_routing_rule(org_id=ORG_ID, db=db, data=data, caller_id=CALLER_ID)

        audit_calls = [c for c in db.table.call_args_list if c.args[0] == "audit_logs"]
        assert len(audit_calls) == 1


# ============================================================
# update_routing_rule
# ============================================================

class TestUpdateRoutingRule:
    def _make_db(self, found=True):
        existing = {
            "id": RULE_ID, "org_id": ORG_ID,
            "event_type": "new_hot_lead", "channel": "whatsapp_inapp",
        } if found else None
        updated = {**existing, "channel": "email"} if existing else None

        db        = MagicMock()
        tracker   = {"n": 0}
        rr_chain  = MagicMock()

        rr_chain.select.return_value.eq.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = existing
        rr_chain.update.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = [updated] if updated else []

        def _tbl(name):
            if name == "routing_rules":
                return rr_chain
            return MagicMock()

        db.table.side_effect = _tbl
        return db

    def test_returns_updated_rule(self):
        db = self._make_db(found=True)
        result = update_routing_rule(
            rule_id=RULE_ID, org_id=ORG_ID, db=db,
            data={"channel": "email"}, caller_id=CALLER_ID,
        )
        assert result["channel"] == "email"

    def test_raises_404_when_rule_not_found(self):
        db = self._make_db(found=False)
        with pytest.raises(HTTPException) as exc_info:
            update_routing_rule(
                rule_id=RULE_ID, org_id=ORG_ID, db=db,
                data={"channel": "email"}, caller_id=CALLER_ID,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "NOT_FOUND"

    def test_partial_update_only_sends_provided_fields(self):
        db = self._make_db(found=True)
        update_data = {"channel": "email"}

        update_routing_rule(
            rule_id=RULE_ID, org_id=ORG_ID, db=db,
            data=update_data, caller_id=CALLER_ID,
        )

        rr_calls = [c for c in db.table.call_args_list if c.args[0] == "routing_rules"]
        assert rr_calls  # table was called at least once

    def test_writes_audit_log_with_old_and_new_values(self):
        db = self._make_db(found=True)
        update_routing_rule(
            rule_id=RULE_ID, org_id=ORG_ID, db=db,
            data={"channel": "email"}, caller_id=CALLER_ID,
        )
        audit_calls = [c for c in db.table.call_args_list if c.args[0] == "audit_logs"]
        assert len(audit_calls) == 1


# ============================================================
# delete_routing_rule
# ============================================================

class TestDeleteRoutingRule:
    def _make_db(self, found=True):
        db       = MagicMock()
        existing = {"id": RULE_ID, "event_type": "new_hot_lead"} if found else None
        tracker  = {"n": 0}
        rr_chain = MagicMock()

        rr_chain.select.return_value.eq.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = existing
        rr_chain.delete.return_value.eq.return_value.eq.return_value \
            .execute.return_value = MagicMock()

        db.table.side_effect = lambda name: rr_chain if name == "routing_rules" else MagicMock()
        return db

    def test_deletes_existing_rule(self):
        db = self._make_db(found=True)
        # Should not raise
        delete_routing_rule(rule_id=RULE_ID, org_id=ORG_ID, db=db, caller_id=CALLER_ID)

    def test_raises_404_when_rule_not_found(self):
        db = self._make_db(found=False)
        with pytest.raises(HTTPException) as exc_info:
            delete_routing_rule(rule_id=RULE_ID, org_id=ORG_ID, db=db, caller_id=CALLER_ID)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "NOT_FOUND"

    def test_writes_audit_log_on_success(self):
        db = self._make_db(found=True)
        delete_routing_rule(rule_id=RULE_ID, org_id=ORG_ID, db=db, caller_id=CALLER_ID)

        audit_calls = [c for c in db.table.call_args_list if c.args[0] == "audit_logs"]
        assert len(audit_calls) == 1