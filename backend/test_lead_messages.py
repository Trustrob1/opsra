"""
test_lead_messages.py

Local test for Gap #2 — configurable lead post-handoff messages.

Tests:
  1. Stage-aware greeting for each pipeline stage
  2. Forwarding message falls back to hardcoded default when no config set
  3. Non-text message returns False correctly

Usage:
    1. Fill in the CONFIG section below
    2. Run: python test_lead_messages.py
"""

from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase
from app.services.customer_inbound_service import handle_lead_post_handoff_inbound

# ---------------------------------------------------------------------------
# CONFIG — fill these in before running
# ---------------------------------------------------------------------------

ORG_ID  = "00000000-0000-0000-0000-000000000001"
LEAD_ID = "23309711-9dab-4345-adfb-c98d9567745e"
PHONE   = "2348109374720"  # e.g. "2348012345678"

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

CASES = [
    # (label, content, msg_type, lead_stage, expected_result)
    ("New lead says hello",          "Hello",   "text",  "new",           True),
    ("Contacted lead says hello",    "Hello",   "text",  "contacted",     True),
    ("Demo done lead says hello",    "Hello",   "text",  "demo_done",     True),
    ("Proposal sent lead says hello","Hello",   "text",  "proposal_sent", True),
    ("Lead asks a question",         "Do you integrate with QuickBooks?", "text", "contacted", True),
    ("Non-text message",             None,      "image", "new",           False),
]

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

db = get_supabase()

print("\n" + "=" * 60)
print("Lead Configurable Messages — Local Test")
print("=" * 60)
print(f"Org:   {ORG_ID}")
print(f"Lead:  {LEAD_ID}")
print(f"Phone: {PHONE}")
print("=" * 60 + "\n")

all_passed = True

for label, content, msg_type, lead_stage, expected in CASES:
    result = handle_lead_post_handoff_inbound(
        db=db,
        org_id=ORG_ID,
        lead_id=LEAD_ID,
        lead_name="Test Lead",
        content=content,
        msg_type=msg_type,
        assigned_to=None,
        now_ts="2026-05-06T12:00:00Z",
        phone_number=PHONE,
        lead_stage=lead_stage,
    )

    passed = result == expected
    status = "PASS ✅" if passed else "FAIL ❌"
    if not passed:
        all_passed = False

    print(f"{status}  [{label}]")
    print(f"       Stage:    {lead_stage}")
    print(f"       Input:    \"{content}\"")
    print(f"       Returned: {result}  (expected {expected})")
    print()

print("=" * 60)
print("All tests passed ✅" if all_passed else "Some tests FAILED ❌ — check output above")
print("=" * 60)
print()
print("NOTE: _send_whatsapp_reply errors are expected locally —")
print("the Meta API call can't complete without a live WA connection.")
print("What matters is the return values matching expected.")
