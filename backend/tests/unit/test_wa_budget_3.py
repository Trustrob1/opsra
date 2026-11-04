"""WA-BUDGET-3: owner alerts at 80% and 100% of the WhatsApp budget."""
from datetime import datetime, timezone
from unittest.mock import patch

from tests.unit.test_credits_1 import ORG, _metered_db

NOW = datetime.now(timezone.utc).isoformat()


def _db(spent, extra=None):
    ledger = [{"org_id": ORG, "kind": "meta", "unit": "wa_marketing", "amount_kobo": -spent, "created_at": NOW}]
    return _metered_db(wallet={"wa_monthly_budget_kobo": 10000}, credit_ledger=ledger,
                       notifications=list(extra or []),
                       users=[{"id": "u1", "org_id": ORG, "email": "o@x.com", "roles": {"template": "owner"}},
                              {"id": "u2", "org_id": ORG, "email": "s@x.com", "roles": {"template": "staff"}}])


class TestLevels:
    def test_levels(self):
        from app.services.wa_budget_alert_service import level_reached
        assert level_reached(7999, 10000) is None
        assert level_reached(8000, 10000) == (80, "wa_budget_80")
        assert level_reached(10000, 10000) == (100, "wa_budget_100")
        assert level_reached(5, 0) is None


class TestAlert:
    def test_80_percent_notifies_owner_only_and_emails(self):
        from app.services import wa_budget_alert_service as svc
        db = _db(8000)
        with patch.object(svc, "_send_email", return_value=True) as em:
            assert svc.check_and_alert(db, ORG) is True
        rows = db.tables["notifications"] if hasattr(db, "tables") else None
        em.assert_called_once()
        assert em.call_args[0][0] == "o@x.com"

    def test_no_alert_below_80(self):
        from app.services import wa_budget_alert_service as svc
        with patch.object(svc, "_send_email") as em:
            assert svc.check_and_alert(_db(100), ORG) is False
        em.assert_not_called()

    def test_not_sent_twice_in_a_month(self):
        from app.services import wa_budget_alert_service as svc
        db = _db(8500, extra=[{"org_id": ORG, "type": "wa_budget_80", "created_at": NOW}])
        with patch.object(svc, "_send_email") as em:
            assert svc.check_and_alert(db, ORG) is False
        em.assert_not_called()

    def test_100_percent_message_mentions_web_chat(self):
        from app.services.wa_budget_alert_service import _message
        title, body = _message(100, 10000, 10000, "chat")
        assert "used up" in title and "web chat" in body
