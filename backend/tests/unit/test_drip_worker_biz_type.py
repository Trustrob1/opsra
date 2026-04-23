# tests/unit/test_drip_worker_biz_type.py
# CONFIG-2 gap fix — drip worker business_type matching
# Tests _build_key_set() and _business_type_matches() in isolation.
# No DB or Celery involved — pure logic tests.

import pytest
from app.workers.drip_worker import _build_key_set, _business_type_matches


# ── _build_key_set ─────────────────────────────────────────────────────────

class TestBuildKeySet:

    def test_empty_list(self):
        assert _build_key_set([]) == {}

    def test_none_list(self):
        assert _build_key_set(None) == {}

    def test_key_maps_to_itself(self):
        m = _build_key_set([{"key": "pharmacy", "label": "Pharmacy"}])
        assert m["pharmacy"] == "pharmacy"

    def test_label_maps_to_key(self):
        m = _build_key_set([{"key": "pharmacy", "label": "Pharmacy"}])
        assert m["Pharmacy"] == "pharmacy"

    def test_label_lower_maps_to_key(self):
        m = _build_key_set([{"key": "pharmacy", "label": "Pharmacy"}])
        assert m["pharmacy"] == "pharmacy"

    def test_multiple_entries(self):
        m = _build_key_set([
            {"key": "pharmacy",    "label": "Pharmacy"},
            {"key": "supermarket", "label": "Supermarket"},
        ])
        assert m["Supermarket"] == "supermarket"
        assert m["pharmacy"]    == "pharmacy"

    def test_multi_word_label(self):
        m = _build_key_set([{"key": "retail_shop", "label": "Retail Shop"}])
        assert m["Retail Shop"] == "retail_shop"
        assert m["retail shop"] == "retail_shop"

    def test_missing_label_key_only(self):
        m = _build_key_set([{"key": "clinic", "label": ""}])
        assert m["clinic"] == "clinic"

    def test_missing_key_label_only(self):
        # If key is blank, label→key mapping still uses blank — effectively skipped
        m = _build_key_set([{"key": "", "label": "Ghost"}])
        # blank key should not pollute the map in a meaningful way
        assert m.get("Ghost") == "" or "Ghost" not in m or m.get("Ghost") == ""


# ── _business_type_matches ─────────────────────────────────────────────────

class TestBusinessTypeMatches:

    def _map(self):
        return _build_key_set([
            {"key": "pharmacy",    "label": "Pharmacy"},
            {"key": "supermarket", "label": "Supermarket"},
            {"key": "retail_shop", "label": "Retail Shop"},
        ])

    # Empty message types = send to all
    def test_empty_message_types_always_matches(self):
        assert _business_type_matches("Pharmacy", [], self._map()) is True

    def test_empty_message_types_no_customer_type(self):
        assert _business_type_matches(None, [], self._map()) is True

    # No customer type
    def test_no_customer_type_restricted_message(self):
        assert _business_type_matches(None, ["pharmacy"], self._map()) is False

    def test_empty_customer_type_restricted_message(self):
        assert _business_type_matches("", ["pharmacy"], self._map()) is False

    # Exact key match
    def test_exact_key_match(self):
        assert _business_type_matches("pharmacy", ["pharmacy"], self._map()) is True

    # Case-insensitive key match
    def test_key_uppercase_customer(self):
        assert _business_type_matches("PHARMACY", ["pharmacy"], self._map()) is True

    def test_key_mixedcase_customer(self):
        assert _business_type_matches("Pharmacy", ["pharmacy"], self._map()) is True

    # Label on customer side, key on message side (legacy customer records)
    def test_customer_label_message_key(self):
        """Customer record has 'Pharmacy' (label), message has 'pharmacy' (key)."""
        assert _business_type_matches("Pharmacy", ["pharmacy"], self._map()) is True

    # Key on customer side, label on message side (edge case)
    def test_customer_key_message_label(self):
        """Customer record has 'pharmacy', message accidentally stored 'Pharmacy'."""
        assert _business_type_matches("pharmacy", ["Pharmacy"], self._map()) is True

    # Both sides are labels
    def test_both_sides_labels(self):
        assert _business_type_matches("Pharmacy", ["Pharmacy"], self._map()) is True

    # Multi-word label
    def test_multiword_label_match(self):
        assert _business_type_matches("Retail Shop", ["retail_shop"], self._map()) is True

    def test_multiword_label_both_sides(self):
        assert _business_type_matches("Retail Shop", ["Retail Shop"], self._map()) is True

    # No match
    def test_no_match_different_type(self):
        assert _business_type_matches("clinic", ["pharmacy"], self._map()) is False

    def test_no_match_partial_string(self):
        """'pharma' should not match 'pharmacy'."""
        assert _business_type_matches("pharma", ["pharmacy"], self._map()) is False

    # Multiple message types — matches any
    def test_matches_one_of_multiple(self):
        assert _business_type_matches(
            "pharmacy", ["supermarket", "pharmacy"], self._map()
        ) is True

    def test_no_match_against_multiple(self):
        assert _business_type_matches(
            "clinic", ["supermarket", "pharmacy"], self._map()
        ) is False

    # No org config — fallback to raw case-insensitive comparison
    def test_no_org_config_exact_match(self):
        assert _business_type_matches("pharmacy", ["pharmacy"], {}) is True

    def test_no_org_config_case_insensitive(self):
        assert _business_type_matches("Pharmacy", ["pharmacy"], {}) is True

    def test_no_org_config_no_match(self):
        assert _business_type_matches("clinic", ["pharmacy"], {}) is False
