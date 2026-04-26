"""
Dry-run script — GPM-2 growth_insights_worker
Tests both tasks against live Supabase data without sending any WhatsApp messages.

Usage:
  python dry_run_growth_insights_worker.py

Expected output (all zeroes in failed):
  [anomaly_check]  {'orgs_processed': N, 'anomalies_fired': N, 'failed': 0}
  [weekly_digest]  {'orgs_processed': N, 'digests_sent': N, 'skipped_no_data': N, 'failed': 0}
"""

from dotenv import load_dotenv
load_dotenv()

# ── Task 1: run_growth_anomaly_check ─────────────────────────────────────────

print("\n--- Task 1: run_growth_anomaly_check ---")
try:
    from app.workers.growth_insights_worker import run_growth_anomaly_check
    result = run_growth_anomaly_check()
    print("[anomaly_check] ", result)
    assert result.get("failed", 1) == 0, f"FAILED: {result}"
    print("[anomaly_check]  ✓ failed == 0")
except Exception as e:
    print(f"[anomaly_check]  ERROR: {e}")
    raise

# ── Task 2: run_weekly_growth_digest ─────────────────────────────────────────

print("\n--- Task 2: run_weekly_growth_digest ---")
try:
    from app.workers.growth_insights_worker import run_weekly_growth_digest
    result = run_weekly_growth_digest()
    print("[weekly_digest]  ", result)
    assert result.get("failed", 1) == 0, f"FAILED: {result}"
    print("[weekly_digest]   ✓ failed == 0")
except Exception as e:
    print(f"[weekly_digest]   ERROR: {e}")
    raise

print("\n✓ All dry-run checks passed.")
