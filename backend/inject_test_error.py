"""
inject_test_error.py
Injects a fake system error into system_error_log so you can verify
the health dashboard error panel is working end-to-end.
Run from backend folder: python inject_test_error.py
"""
from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase
from app.services.monitoring_service import log_system_error

db = get_supabase()

print("Injecting test error into system_error_log...")

log_system_error(
    db,
    error_type="test_error",
    error_message="This is a simulated error to verify the health dashboard is working correctly. You can delete this row after confirming.",
    org_slug="test",
    http_status=500,
    file_path="app/services/test_service.py",
    function_name="simulate_error",
    line_number=42,
    route="/api/v1/test",
    generate_hint=True,  # will call Haiku to generate a fix hint
)

print("Done. Check the Errors panel in the health dashboard.")
print("You should see a row with error_type='test_error' and a fix hint.")
