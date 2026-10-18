"""
app/services/ai_cost.py
-----------------------
CREDITS-1 — one place that knows what a Claude call costs.

Prices are US dollars per million tokens (input, output). Cached input is
priced as a multiple of the input price: a cache read costs 10% and a
5-minute cache write costs 125%.

The model string is matched on family and version, so a dated name such as
"claude-haiku-4-5-20251001" resolves the same as "claude-haiku-4-5".
A model nobody has priced is charged at Sonnet 4.6 rates (an over-estimate
is safer than an under-estimate when the number is billed to a customer).

Pure functions. No I/O, never raises.
"""
from __future__ import annotations

import re
from typing import Optional

CACHE_READ_MULT = 0.10
CACHE_WRITE_MULT = 1.25

# (family, major, minor) → (input_usd_per_mtok, output_usd_per_mtok)
# minor None matches any minor of that major.
_PRICES: list[tuple[str, int, Optional[int], float, float]] = [
    ("sonnet", 5, None, 2.00, 10.00),
    ("sonnet", 4, None, 3.00, 15.00),
    ("sonnet", 3, None, 3.00, 15.00),
    ("haiku",  5, None, 0.10, 0.50),
    ("haiku",  4, None, 1.00, 5.00),
    ("haiku",  3, None, 0.80, 4.00),
    ("opus",   5, None, 4.00, 20.00),
    ("opus",   4, None, 15.00, 75.00),
]

FALLBACK_RATE = (3.00, 15.00)

_MODEL_RE = re.compile(r"(sonnet|haiku|opus)[-_ ]?(\d+)(?:[-_.](\d+))?", re.I)


def get_rate(model: Optional[str]) -> tuple[float, float, bool]:
    """Return (input_usd_per_mtok, output_usd_per_mtok, matched)."""
    try:
        m = _MODEL_RE.search(model or "")
        if m:
            family = m.group(1).lower()
            major = int(m.group(2))
            minor = int(m.group(3)) if m.group(3) is not None else None
            for fam, mj, mn, inp, out in _PRICES:
                if fam == family and mj == major and (mn is None or mn == minor):
                    return inp, out, True
    except Exception:
        pass
    return FALLBACK_RATE[0], FALLBACK_RATE[1], False


def cost_usd(
    model: Optional[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """
    Dollar cost of one call. `input_tokens` is the uncached input only
    (that is what Anthropic reports in usage.input_tokens); cache reads and
    cache writes are reported separately and priced here.
    """
    inp, out, _ = get_rate(model)
    total = (
        max(int(input_tokens or 0), 0) * inp
        + max(int(output_tokens or 0), 0) * out
        + max(int(cache_read_tokens or 0), 0) * inp * CACHE_READ_MULT
        + max(int(cache_creation_tokens or 0), 0) * inp * CACHE_WRITE_MULT
    ) / 1_000_000
    return round(total, 6)
