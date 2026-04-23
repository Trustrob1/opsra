from dotenv import load_dotenv
load_dotenv()
from app.workers.lead_sla_worker import run_lead_sla_check
print(run_lead_sla_check.run())
