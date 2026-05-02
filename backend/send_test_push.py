# send_test_push.py
from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase
from app.routers.push_notifications import send_push_notification

db = get_supabase()
send_push_notification(
    db=db,
    user_id="b7dc7fab-1551-455f-aa05-1644c1b6d235",
    title="Test Notification",
    body="Push notifications are working!",
    url="/"
)
print("Done")