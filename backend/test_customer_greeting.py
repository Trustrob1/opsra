"""
test_customer_greeting.py

Local test for the customer pure-greeting fix (Gap #1).
Tests that a customer sending "Hello" gets a warm reply instead of silence.

Usage:
    1. Fill in the three variables in CONFIG below
    2. Run: python test_customer_greeting.py
"""

from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase
from app.services.customer_inbound_service import handle_customer_inbound

# ---------------------------------------------------------------------------
# CONFIG — fill these in before running
# ---------------------------------------------------------------------------

ORG_ID      = "00000000-0000-0000-0000-000000000001"
CUSTOMER_ID = "089e1745-699f-4a5e-a9c2-dbdd57f29499"
PHONE       = "2348109374722"

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

CASES = [
    # (label, content, expected_outcome)
    ("Pure hello",              "Hello",                 True),
    ("Hi with emoji",           "Hi 😊",                 True),
    ("Good morning",            "Good morning",          True),
    ("Good morning with name",  "Good morning sir",      True),
    ("Hey oga",                 "Hey oga",               True),
    ("Greeting + question",     "Hello, how do I reset my password?", False),
]

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

db = get_supabase()

print("\n" + "=" * 60)
print("Customer Greeting Fix — Local Test")
print("=" * 60)
print(f"Org:      {ORG_ID}")
print(f"Customer: {CUSTOMER_ID}")
print(f"Phone:    {PHONE}")
print("=" * 60 + "\n")

all_passed = True

for label, content, should_handle in CASES:
    result = handle_customer_inbound(
        db=db,
        org_id=ORG_ID,
        customer_id=CUSTOMER_ID,
        content=content,
        msg_type="text",
        assigned_to=None,
        now_ts="2026-05-06T12:00:00Z",
        phone_number=PHONE,
    )

    passed = result == should_handle
    status = "PASS ✅" if passed else "FAIL ❌"
    if not passed:
        all_passed = False

    print(f"{status}  [{label}]")
    print(f"       Input:    \"{content}\"")
    print(f"       Returned: {result}  (expected {should_handle})")
    print()

print("=" * 60)
print("All tests passed ✅" if all_passed else "Some tests FAILED ❌ — check output above")
print("=" * 60)
print()
print("NOTE: _send_whatsapp_reply errors are expected locally —")
print("the Meta API call can't complete without a live WA connection.")
print("What matters is the return value and that no exception crashed the function.")
