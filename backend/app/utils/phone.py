"""
app/utils/phone.py
------------------
9E-B — Phone number normalisation utility.

All inbound phone numbers from Meta arrive in inconsistent formats.
normalize_phone() converts all of them to a consistent pure-digit E.164
format without the "+" prefix so the same contact is never treated as two
different people due to formatting differences.

S14: returns the original string unchanged on any exception — never raises.
PII: never logs the full number — only the last 4 digits.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_COUNTRY_CODES: dict[str, str] = {
    "NG": "234",
    "GH": "233",
    "KE": "254",
    "ZA": "27",
    "US": "1",
    "GB": "44",
}


def normalize_phone(number: str, default_country: str = "NG") -> str:
    """
    Normalise a phone number to pure-digit E.164 without "+".

    Examples (default_country="NG"):
      "08031234567"       → "2348031234567"
      "+2348031234567"    → "2348031234567"
      "2348031234567"     → "2348031234567"
      "234 803 123 4567"  → "2348031234567"

    S14: returns original string on any exception.
    """
    if not number:
        return number

    try:
        # Strip whitespace, dashes, dots, parentheses
        stripped = re.sub(r"[\s\-\.\(\)]", "", number)

        # Strip leading "+"
        if stripped.startswith("+"):
            stripped = stripped[1:]

        # Guard: must be all digits at this point
        if not stripped.isdigit():
            logger.warning(
                "normalize_phone: non-digit chars after stripping ...%s — returning original",
                number[-4:],
            )
            return number

        # Replace leading "0" with country prefix
        if stripped.startswith("0"):
            prefix = _COUNTRY_CODES.get(default_country.upper(), "")
            if not prefix:
                logger.warning(
                    "normalize_phone: unknown country '%s' — returning stripped",
                    default_country,
                )
                return stripped
            stripped = prefix + stripped[1:]

        return stripped

    except Exception as exc:
        logger.warning(
            "normalize_phone: error for ...%s — %s",
            number[-4:] if len(number) >= 4 else number,
            exc,
        )
        return number
