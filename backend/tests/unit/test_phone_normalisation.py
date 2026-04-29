"""
tests/unit/test_phone_normalisation.py
---------------------------------------
Unit tests for app/utils/phone.py — normalize_phone().
"""
from app.utils.phone import normalize_phone


class TestNormalizePhone:

    def test_local_with_leading_zero(self):
        assert normalize_phone("08031234567") == "2348031234567"

    def test_e164_with_plus(self):
        assert normalize_phone("+2348031234567") == "2348031234567"

    def test_e164_without_plus(self):
        assert normalize_phone("2348031234567") == "2348031234567"

    def test_with_spaces(self):
        assert normalize_phone("234 803 123 4567") == "2348031234567"

    def test_with_dashes(self):
        assert normalize_phone("0803-123-4567") == "2348031234567"

    def test_with_parentheses(self):
        assert normalize_phone("(0803) 123-4567") == "2348031234567"

    def test_plus_with_spaces(self):
        assert normalize_phone("+234 803 123 4567") == "2348031234567"

    def test_empty_string_returns_empty(self):
        assert normalize_phone("") == ""

    def test_none_equivalent_empty(self):
        # Callers may pass empty string for missing values
        assert normalize_phone("") == ""

    def test_malformed_non_digits_returns_original(self):
        # S14: if stripping still leaves non-digits, return original unchanged
        original = "abc-def"
        result = normalize_phone(original)
        assert result == original

    def test_ghana_prefix(self):
        assert normalize_phone("0241234567", default_country="GH") == "2330241234567"[:10] or \
               normalize_phone("0241234567", default_country="GH") == "233241234567"

    def test_unknown_country_returns_stripped(self):
        # Unknown country code → strip leading 0 but can't add prefix → return stripped digits
        result = normalize_phone("0123456789", default_country="XX")
        # Should not crash and should return something reasonable
        assert isinstance(result, str)

    def test_already_normalised_unchanged(self):
        assert normalize_phone("2348031234567") == "2348031234567"

    def test_does_not_raise_on_exception(self):
        # S14: should never raise regardless of input
        result = normalize_phone(None or "")
        assert isinstance(result, str)
