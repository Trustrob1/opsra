# tests/unit/test_drip_business_types.py
# CONFIG-2 — Drip Business Types unit tests
# Tests the Pydantic validation models for DripBusinessTypeItem
# and DripBusinessTypesUpdate.

import pytest
from pydantic import ValidationError

# Import the models directly from admin router
import importlib, sys, types

# We import from the router module directly.
# Because admin.py defines models at module level we can import them.
from app.routers.admin import DripBusinessTypeItem, DripBusinessTypesUpdate


class TestDripBusinessTypeItem:

    def test_valid_item(self):
        item = DripBusinessTypeItem(key="pharmacy", label="Pharmacy", enabled=True)
        assert item.key == "pharmacy"
        assert item.label == "Pharmacy"
        assert item.enabled is True

    def test_label_stripped(self):
        item = DripBusinessTypeItem(key="pharmacy", label="  Pharmacy  ")
        assert item.label == "Pharmacy"

    def test_label_too_long(self):
        with pytest.raises(ValidationError):
            DripBusinessTypeItem(key="x", label="A" * 81)

    def test_key_invalid_chars(self):
        with pytest.raises(ValidationError):
            DripBusinessTypeItem(key="has space", label="Has Space")

    def test_key_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            DripBusinessTypeItem(key="Pharmacy", label="Pharmacy")

    def test_key_hyphen_rejected(self):
        with pytest.raises(ValidationError):
            DripBusinessTypeItem(key="pharma-cy", label="Pharmacy")

    def test_key_underscore_allowed(self):
        item = DripBusinessTypeItem(key="small_pharma", label="Small Pharma")
        assert item.key == "small_pharma"

    def test_enabled_defaults_true(self):
        item = DripBusinessTypeItem(key="retail", label="Retail")
        assert item.enabled is True

    def test_disabled_explicitly(self):
        item = DripBusinessTypeItem(key="retail", label="Retail", enabled=False)
        assert item.enabled is False

    def test_empty_key_rejected(self):
        with pytest.raises(ValidationError):
            DripBusinessTypeItem(key="", label="Something")

    def test_empty_label_rejected(self):
        with pytest.raises(ValidationError):
            DripBusinessTypeItem(key="x", label="")


class TestDripBusinessTypesUpdate:

    def _item(self, key, label, enabled=True):
        return {"key": key, "label": label, "enabled": enabled}

    def test_valid_list(self):
        payload = DripBusinessTypesUpdate(business_types=[
            self._item("pharmacy", "Pharmacy"),
            self._item("supermarket", "Supermarket"),
        ])
        assert len(payload.business_types) == 2

    def test_empty_list_allowed(self):
        """Empty list means all types are eligible — unrestricted."""
        payload = DripBusinessTypesUpdate(business_types=[])
        assert payload.business_types == []

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ValidationError, match="keys must be unique"):
            DripBusinessTypesUpdate(business_types=[
                self._item("pharmacy", "Pharmacy"),
                self._item("pharmacy", "Pharmacy 2"),
            ])

    def test_duplicate_keys_different_labels(self):
        with pytest.raises(ValidationError, match="keys must be unique"):
            DripBusinessTypesUpdate(business_types=[
                self._item("pharmacy", "Pharmacy"),
                self._item("pharmacy", "Another Pharmacy"),
            ])

    def test_single_item(self):
        payload = DripBusinessTypesUpdate(business_types=[
            self._item("restaurant", "Restaurant"),
        ])
        assert payload.business_types[0].key == "restaurant"

    def test_mixed_enabled_disabled(self):
        payload = DripBusinessTypesUpdate(business_types=[
            self._item("pharmacy", "Pharmacy", enabled=True),
            self._item("bakery",   "Bakery",   enabled=False),
        ])
        assert payload.business_types[0].enabled is True
        assert payload.business_types[1].enabled is False
