from dotenv import load_dotenv
load_dotenv()

from app.database import get_supabase

db = get_supabase()
rows = db.table("users").select("id, email, push_token").execute().data
for r in rows:
    print(r["email"], r["id"], "has_token:", bool(r.get("push_token")))