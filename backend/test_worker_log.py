from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.WARNING)

from datetime import datetime, timezone
from app.database import get_supabase
from app.services.monitoring_service import write_worker_log

db = get_supabase()

# Test 1: direct insert
print("Testing direct insert...")
try:
    db.table("worker_run_log").insert({
        "worker_name": "test_direct",
        "status": "passed",
        "items_processed": 0,
        "items_failed": 0,
        "items_skipped": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    print("Direct insert: OK")
except Exception as e:
    print("Direct insert FAILED:", e)

# Test 2: via write_worker_log
print("Testing write_worker_log...")
try:
    write_worker_log(
        db,
        worker_name="test_write_worker_log",
        status="passed",
        items_processed=1,
    )
    print("write_worker_log: completed")
except Exception as e:
    print("write_worker_log raised (should not happen - S14):", e)

print("Done. Check worker_run_log table in Supabase.")
