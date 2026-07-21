"""
One-off diagnostic for the Shopify 401 on draft_orders.json.
Tests the SAME stored credentials against 3 different calls to isolate
whether this is a dead token, a retired API version, or a missing scope.

Usage (from backend/, venv active):
    python diagnose_shopify_401.py <ORG_ID>
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase
import httpx

if len(sys.argv) < 2:
    print("Usage: python diagnose_shopify_401.py <ORG_ID>")
    sys.exit(1)

org_id = sys.argv[1]
db = get_supabase()

result = (
    db.table("organisations")
    .select("shopify_shop_domain, shopify_access_token, shopify_connected")
    .eq("id", org_id)
    .maybe_single()
    .execute()
)
org = result.data
if isinstance(org, list):
    org = org[0] if org else None

if not org:
    print("Org not found.")
    sys.exit(1)

shop_domain = org.get("shopify_shop_domain")
access_token = org.get("shopify_access_token")

print(f"shop_domain: {shop_domain}")
print(f"shopify_connected flag: {org.get('shopify_connected')}")
print(f"has_token: {bool(access_token)}")
print()

headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}

with httpx.Client(timeout=15.0) as client:
    # Test 1: is the token valid AT ALL, on the CURRENT API version?
    print("Test 1 — token validity (GET /shop.json, current API version 2025-01)...")
    r1 = client.get(f"https://{shop_domain}/admin/api/2025-01/shop.json", headers=headers)
    print(f"  -> {r1.status_code}")
    if r1.status_code != 200:
        print(f"  body: {r1.text[:500]}")
    print()

    # Test 2: is the OLD API version (2024-01) still supported at all?
    print("Test 2 — old API version validity (GET /shop.json, 2024-01)...")
    r2 = client.get(f"https://{shop_domain}/admin/api/2024-01/shop.json", headers=headers)
    print(f"  -> {r2.status_code}")
    if r2.status_code != 200:
        print(f"  body: {r2.text[:500]}")
    print()

    # Test 3: does the token have write_draft_orders, on the CURRENT version?
    print("Test 3 — write_draft_orders scope (POST /draft_orders.json, 2025-01, minimal payload)...")
    r3 = client.post(
        f"https://{shop_domain}/admin/api/2025-01/draft_orders.json",
        headers=headers,
        json={"draft_order": {"line_items": [{"title": "Diagnostic test item", "price": "1.00", "quantity": 1}]}},
    )
    print(f"  -> {r3.status_code}")
    if r3.status_code not in (200, 201):
        print(f"  body: {r3.text[:500]}")
    elif r3.status_code in (200, 201):
        draft_id = r3.json().get("draft_order", {}).get("id")
        print(f"  Created diagnostic draft order id={draft_id} — you may want to delete this in Shopify Admin.")

print()
print("=== Interpretation ===")
print("Test 1 fails       -> token itself is dead/invalid (reconnect needed)")
print("Test 1 OK, Test 2 fails -> 2024-01 API version is retired (code needs updating to 2025-01)")
print("Test 1 & 2 OK, Test 3 fails -> token is valid but missing write_draft_orders scope")
print("All 3 OK           -> the original 401 may have been transient — retry the real flow")
