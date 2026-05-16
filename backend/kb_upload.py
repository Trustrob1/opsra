import requests

BASE = "https://opsra.onrender.com"
TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6ImQwODA2MTRjLTg4MGItNDJkNy1hMzk4LTg2YjIxYTk2NWExOCIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2p1bXd0anpya21lcmNmcWdndGN5LnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJkNzhmNjZkZC1hNzk0LTQyNzktOTU4My1iOTZhYjc0ZjAwYWYiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzc4OTM1OTE4LCJpYXQiOjE3Nzg5MzIzMTgsImVtYWlsIjoiYWRtaW5Acm95YWxyZXN0LmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZW1haWwiLCJwcm92aWRlcnMiOlsiZW1haWwiXX0sInVzZXJfbWV0YWRhdGEiOnsiZW1haWxfdmVyaWZpZWQiOnRydWV9LCJyb2xlIjoiYXV0aGVudGljYXRlZCIsImFhbCI6ImFhbDEiLCJhbXIiOlt7Im1ldGhvZCI6InBhc3N3b3JkIiwidGltZXN0YW1wIjoxNzc4OTMyMzE4fV0sInNlc3Npb25faWQiOiJkNTZhYjRhNS00Y2VhLTQ2ZTYtOTU3OC00YzgxNjM4ZDgyZWEiLCJpc19hbm9ueW1vdXMiOmZhbHNlfQ.gMkLkSNHJJfPJWN-bdSoAYa4fX6ajwpP4_3loDPD5eevg-NNf3UGHLEpTnkw_ZQH3-A9Z5NTnZKGS_sJ_3nBBg"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
URL = f"{BASE}/api/v1/knowledge-base"

articles = [
    # ── FAQ ──────────────────────────────────────────────────────────────
    {
        "category": "faq",
        "title": "Is the Royal Rest mattress good for back pain?",
        "content": "Yes — Royal Rest mattresses are engineered with orthopedic pocket coils and pressure-relieving comfort layers to support your spine and reduce tension on your lower back. The design helps to align your spine while cushioning pressure points, which can significantly ease back pain over time.",
        "tags": ["back pain", "orthopedic", "spine", "pocket coils"]
    },
    {
        "category": "faq",
        "title": "Will I sleep hot on the Royal Rest mattress?",
        "content": "No — our mattresses are built for temperature-neutral sleep. They feature breathable covers, airflow channels, and cooling gel foams to ensure heat does not build up, making them ideal for hot sleepers and warm climates.",
        "tags": ["heat", "cooling", "temperature", "gel foam", "breathable"]
    },
    {
        "category": "faq",
        "title": "Is the mattress soft or firm?",
        "content": "It's both. Royal Rest combines soft comfort where you need it (shoulders, hips) with firm, spinal support. This dual feel helps relieve pressure while keeping your spine properly aligned.",
        "tags": ["soft", "firm", "comfort", "support"]
    },
    {
        "category": "faq",
        "title": "How long will the Royal Rest mattress last?",
        "content": "With regular use and proper care, our mattress is built to last at least 10 years. The high-density support foam and durable coil system are engineered for long-term resilience.",
        "tags": ["durability", "lifespan", "warranty", "10 years"]
    },
    {
        "category": "faq",
        "title": "What sleeping positions is the Royal Rest mattress best for?",
        "content": "Our design is versatile:\n- **Back sleepers:** get full spinal support.\n- **Side sleepers:** enjoy pressure relief on shoulders and hips.\n- **Combination sleepers:** benefit from the instant response and bounce-back feel.",
        "tags": ["sleeping position", "back sleeper", "side sleeper", "combination sleeper"]
    },
    {
        "category": "faq",
        "title": "Can I feel my partner move on the mattress?",
        "content": "Thanks to our individually wrapped support coils, the mattress isolates motion, so you won't be easily disturbed by your partner's movements at night.",
        "tags": ["motion isolation", "partner", "couples", "pocket coils"]
    },
    {
        "category": "faq",
        "title": "What are the layers made of inside the mattress?",
        "content": "The Royal Rest mattress is made up of four layers:\n1. **Cool-Touch Cover** — Breathable, moisture-wicking fabric\n2. **Comfort Layer** — Pressure-relief foam or gel that allows airflow\n3. **Support Core** — Individually wrapped pocket coils\n4. **Base** — High-density foam for structure and durability",
        "tags": ["layers", "materials", "construction", "pocket coils", "foam"]
    },
    {
        "category": "faq",
        "title": "Do I need a special bed frame or base for this mattress?",
        "content": "You don't need anything unusual — a sturdy base or platform bed is enough. For optimal performance, use a frame that supports the full mattress surface evenly.",
        "tags": ["bed frame", "base", "platform bed", "setup"]
    },
    {
        "category": "faq",
        "title": "Does the mattress have a trial period or warranty?",
        "content": "Yes. Every Royal Rest mattress comes with a **10-year warranty**. Please contact us for details on any available sleep trial period.",
        "tags": ["warranty", "trial", "guarantee", "10 years"]
    },
    {
        "category": "faq",
        "title": "Is there any off-gassing or chemical smell?",
        "content": "There may be a very mild odor initially (common with foam-based or hybrid mattresses), but it dissipates within a few days in a ventilated room. We use high-quality, low-emission materials to minimize any smell.",
        "tags": ["smell", "off-gassing", "foam", "new mattress"]
    },
    {
        "category": "faq",
        "title": "How do I clean and maintain my mattress?",
        "content": "- Use a mattress protector to guard against spills and dust.\n- Rotate the mattress head-to-foot every 3–6 months to even out wear.\n- Clean stains with a mild upholstery cleaner and air-dry completely before putting bedding back on.",
        "tags": ["cleaning", "maintenance", "care", "mattress protector", "rotate"]
    },
    {
        "category": "faq",
        "title": "Is the Royal Rest mattress good for couples?",
        "content": "Yes — with motion isolation from pocket coils and strong edge support, it's designed to minimize partner disturbance and provide a stable, comfortable sleep surface for two.",
        "tags": ["couples", "motion isolation", "edge support", "partner"]
    },
    {
        "category": "faq",
        "title": "What are the delivery times and shipping costs?",
        "content": "- **Lagos & Abuja:** Same-day delivery.\n- **Other Nigeria locations:** 3–5 days.\n- **International:** Estimated 7 days.\n- **Shipping:** Free nationwide.\n\nFor support, call +2348168782936 or email info@royalrestmattressng.com.",
        "tags": ["delivery", "shipping", "Lagos", "Abuja", "nationwide", "free shipping"]
    },
    # ── PRICING — Mattresses ─────────────────────────────────────────────
    {
        "category": "pricing",
        "title": "Mattress Prices — Full Product List",
        "content": "Current Royal Rest mattress prices (NGN):\n\n| Product | Price |\n|---|---|\n| Sleep Royalty | ₦845,000 |\n| Premium Organic Mattress Elite Cool | ₦805,000 *(was ₦830,000)* |\n| Holiday Sleep Mosquito Repellent | ₦705,000 *(was ₦720,000)* |\n| Luxury Hybrid Royal Rest Black | ₦565,000 |\n| Dual Faced Mattress Sleep Royalty | ₦575,000 *(was ₦650,000)* |\n| Victoria Edition Sleep Magnificent | ₦605,000 *(was ₦650,000)* |\n| Cloud Mattress | ₦485,000 |\n\nAll prices in Nigerian Naira. Sale prices shown where applicable.",
        "tags": ["price", "mattress", "cost", "how much", "NGN", "naira"]
    },
    # ── PRICING — Pillows ────────────────────────────────────────────────
    {
        "category": "pricing",
        "title": "Pillow Prices — Full Product List",
        "content": "Current Royal Rest pillow prices (NGN):\n\n| Product | Price | Availability |\n|---|---|---|\n| Memory Coolant Pillow | ₦70,000 *(was ₦125,000)* | Out of stock |\n| Cotton Pillow | ₦50,000 | In stock |\n\nAll prices in Nigerian Naira.",
        "tags": ["price", "pillow", "cost", "how much", "NGN", "naira", "memory foam", "cotton"]
    },
]

print(f"Uploading {len(articles)} articles to {URL}\n")
success, failed = 0, []

for i, article in enumerate(articles, 1):
    resp = requests.post(URL, json=article, headers=HEADERS)
    if resp.status_code in (200, 201):
        print(f"  ✓ [{i}/{len(articles)}] {article['title'][:60]}")
        success += 1
    else:
        print(f"  ✗ [{i}/{len(articles)}] {article['title'][:60]} — {resp.status_code}: {resp.text[:120]}")
        failed.append(article['title'])

print(f"\n{'='*60}")
print(f"Done: {success} succeeded, {len(failed)} failed")
if failed:
    print("Failed articles:")
    for t in failed:
        print(f"  - {t}")
