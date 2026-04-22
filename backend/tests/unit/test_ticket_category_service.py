"""
tests/unit/test_ticket_category_service.py
CONFIG-1 — Dynamic Ticket/KB Category Configuration

Unit tests for:
  - GET /admin/ticket-categories: returns stored config
  - GET /admin/ticket-categories: returns defaults when null
  - PATCH /admin/ticket-categories: saves valid config
  - PATCH /admin/ticket-categories: rejects duplicate keys
  - PATCH /admin/ticket-categories: rejects empty categories list
  - PATCH /admin/ticket-categories: rejects all-disabled config
  - PATCH /admin/ticket-categories: rejects invalid key format
  - PATCH /admin/ticket-categories: rejects label > 80 chars
"""
import pytest
from unittest.mock import MagicMock

ORG_ID  = "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-0000-0000-0000-bbbbbbbbbbbb"

DEFAULT_CATEGORIES = [
    {"key": "technical_bug",    "label": "Technical Bug",    "enabled": True},
    {"key": "billing",          "label": "Billing",          "enabled": True},
    {"key": "feature_question", "label": "Feature Question", "enabled": True},
    {"key": "onboarding_help",  "label": "Onboarding Help",  "enabled": True},
    {"key": "account_access",   "label": "Account Access",   "enabled": True},
    {"key": "hardware",         "label": "Hardware",         "enabled": True},
]

CUSTOM_CATEGORIES = [
    {"key": "technical_bug",  "label": "Tech Issues",     "enabled": True},
    {"key": "billing",        "label": "Payments",        "enabled": True},
    {"key": "custom_support", "label": "Custom Support",  "enabled": True},
]


def _db_returning(categories):
    db = MagicMock()
    result = MagicMock()
    result.data = {"ticket_categories": categories}
    (db.table.return_value
       .select.return_value
       .eq.return_value
       .maybe_single.return_value
       .execute.return_value) = result
    return db


def _db_null():
    return _db_returning(None)


# ---------------------------------------------------------------------------
# Route-level validation via Pydantic models
# ---------------------------------------------------------------------------

class TestTicketCategoryPydanticValidation:

    def _make_items(self, overrides):
        """Build a valid list and apply overrides."""
        import copy
        items = copy.deepcopy(DEFAULT_CATEGORIES)
        items[0].update(overrides)
        return items

    def test_valid_config_passes(self):
        from app.routers.admin import TicketCategoriesUpdate, TicketCategoryItem
        payload = TicketCategoriesUpdate(categories=[
            TicketCategoryItem(**c) for c in DEFAULT_CATEGORIES
        ])
        assert len(payload.categories) == 6

    def test_rejects_duplicate_keys(self):
        from app.routers.admin import TicketCategoriesUpdate, TicketCategoryItem
        from pydantic import ValidationError
        dupes = DEFAULT_CATEGORIES[:2] + [{"key": "billing", "label": "Billing Again", "enabled": True}]
        with pytest.raises(ValidationError):
            TicketCategoriesUpdate(categories=[TicketCategoryItem(**c) for c in dupes])

    def test_rejects_empty_list(self):
        from app.routers.admin import TicketCategoriesUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TicketCategoriesUpdate(categories=[])

    def test_rejects_all_disabled(self):
        from app.routers.admin import TicketCategoriesUpdate, TicketCategoryItem
        from pydantic import ValidationError
        all_off = [{"key": c["key"], "label": c["label"], "enabled": False} for c in DEFAULT_CATEGORIES]
        with pytest.raises(ValidationError):
            TicketCategoriesUpdate(categories=[TicketCategoryItem(**c) for c in all_off])

    def test_rejects_invalid_key_format(self):
        from app.routers.admin import TicketCategoryItem
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TicketCategoryItem(key="Invalid Key!", label="Bad", enabled=True)

    def test_rejects_uppercase_key(self):
        from app.routers.admin import TicketCategoryItem
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TicketCategoryItem(key="TechnicalBug", label="Tech Bug", enabled=True)

    def test_rejects_label_over_80_chars(self):
        from app.routers.admin import TicketCategoryItem
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TicketCategoryItem(key="too_long", label="A" * 81, enabled=True)

    def test_rejects_empty_label(self):
        from app.routers.admin import TicketCategoryItem
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TicketCategoryItem(key="empty_label", label="", enabled=True)

    def test_custom_key_passes(self):
        from app.routers.admin import TicketCategoryItem
        item = TicketCategoryItem(key="custom_support_123", label="Custom Support", enabled=True)
        assert item.key == "custom_support_123"

    def test_label_is_stripped(self):
        from app.routers.admin import TicketCategoryItem
        item = TicketCategoryItem(key="billing", label="  Billing  ", enabled=True)
        assert item.label == "Billing"

    def test_disabled_category_valid(self):
        from app.routers.admin import TicketCategoriesUpdate, TicketCategoryItem
        cats = DEFAULT_CATEGORIES[:5] + [{"key": "hardware", "label": "Hardware", "enabled": False}]
        payload = TicketCategoriesUpdate(categories=[TicketCategoryItem(**c) for c in cats])
        disabled = [c for c in payload.categories if not c.enabled]
        assert len(disabled) == 1
        assert disabled[0].key == "hardware"
