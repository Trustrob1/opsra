"""
One-off dry-run script for AI-AGENT-1B.
Confirms _get_or_create_ai_agent_user() creates (and then re-fetches) a
valid AI Agent system user row for a real org.

Usage (from the backend/ directory, with your venv active):
    python dryrun_ai_agent_user.py <REAL_ORG_ID>

Expected output: the same UUID printed both times it's called.
"""
import sys

from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase
from app.services.ai_agent_service import _get_or_create_ai_agent_user

if len(sys.argv) < 2:
    print("Usage: python dryrun_ai_agent_user.py <REAL_ORG_ID>")
    sys.exit(1)

org_id = sys.argv[1]
db = get_supabase()

user_id_1 = _get_or_create_ai_agent_user(db, org_id)
print("First call  -> AI Agent user id:", user_id_1)

user_id_2 = _get_or_create_ai_agent_user(db, org_id)
print("Second call -> AI Agent user id:", user_id_2)

if user_id_1 and user_id_1 == user_id_2:
    print("PASS: same user row reused on second call.")
elif not user_id_1:
    print("FAIL: got None — check that this org has a 'sales_agent' role template.")
else:
    print("FAIL: different ids returned — a new row was created twice instead of reused.")
