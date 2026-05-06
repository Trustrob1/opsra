from dotenv import load_dotenv
load_dotenv()
from app.database import get_supabase
from app.services.customer_inbound_service import handle_lead_post_handoff_inbound

db = get_supabase()

result = handle_lead_post_handoff_inbound(
    db=db,
    org_id="00000000-0000-0000-0000-000000000001",
    lead_id="23309711-9dab-4345-adfb-c98d9567745e",
    lead_name="Test Lead",
    content="Hello",
    msg_type="text",
    assigned_to=None,
    now_ts="2026-05-06T12:00:00Z",
    phone_number="2348109374720",
    lead_stage="contacted",
)
print(result)