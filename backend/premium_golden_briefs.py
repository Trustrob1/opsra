"""
premium_golden_briefs.py - SITE-PREMIUM P2: the golden set of 10 varied briefs (spec section 14).
Every business here is fictional. Content follows SiteContentV1 (checked by a unit test), with NO photos, so
the page's image frames must look designed without them. Used by premium_golden.py.
"""
from __future__ import annotations


def _biz(name, city, tagline, wa="+2348030000000", ig="", delivery=""):
    return {"name": name, "city": city, "tagline": tagline, "whatsapp_e164": wa, "phone_display": "0803 000 0000",
            "instagram": ig, "delivery_note": delivery}


def _items(rows):
    return [{"name": n, "desc": d, "price_ngn": p, "price_style": s, "tag": t} for n, d, p, s, t in rows]


BRIEFS = [
    {"key": "boutique", "personality": "confident, modern, editorial",
     "content": {
         "business": _biz("Zuri Atelier", "Lekki, Lagos", "Ready-to-wear and made-to-measure", ig="@zuriatelier", delivery="Delivery within Lagos in 2 days"),
         "hero": {"headline": "Dressed for the room you walk into", "subhead": "Ready-to-wear and made-to-measure fashion from Lekki."},
         "about": {"title": "Cut slowly, worn often", "body": ["Every piece is cut and finished in our Lekki studio.", "Made-to-measure orders take two weeks."], "owner": "Zuri Okafor", "pull_quote": ""},
         "items": _items([("Adire wrap dress", "Hand-dyed cotton, midi length", 38000, "exact", "Ready now"), ("Tailored jumpsuit", "Crepe, wide leg", 52000, "exact", "Ready now"),
                          ("Custom two-piece", "Made to your measurements", 0, "on_request", "Made to order"), ("Silk headwrap", "Four colours", 9500, "from", None),
                          ("Linen shirt dress", "Relaxed fit", 34000, "exact", None), ("Bridal party sets", "Minimum of four", 0, "on_request", "Made to order")]),
         "categories": [{"name": "Dresses", "teaser": "Day to evening"}, {"name": "Made to order", "teaser": "Cut for you"}],
         "location": {"address": "14 Admiralty Way, Lekki Phase 1, Lagos", "landmark": "Opposite the roundabout"}}},
    {"key": "restaurant", "personality": "warm, lively, appetising",
     "content": {
         "business": _biz("Mama Ife Kitchen", "Yaba, Lagos", "Home-style Nigerian cooking, cooked to order", ig="@mamaifekitchen"),
         "hero": {"headline": "Smoky jollof, slow stews, no shortcuts", "subhead": "Cooked to order in Yaba. Order on WhatsApp before 4 pm for dinner."},
         "about": {"title": "Cooked like at home", "body": ["Recipes from our family kitchen, scaled for the neighbourhood."], "owner": "Ifeoma Nwosu", "pull_quote": ""},
         "menu": [{"name": "Rice dishes", "lines": [{"name": "Party jollof", "desc": "Smoky, with fried plantain", "price_ngn": 3500, "price_style": "exact"}, {"name": "Fried rice", "desc": "With coleslaw", "price_ngn": 3500, "price_style": "exact"}]},
                  {"name": "Soups and swallow", "lines": [{"name": "Egusi with pounded yam", "desc": "Assorted meat", "price_ngn": 5000, "price_style": "exact"}, {"name": "Ogbono with eba", "desc": "", "price_ngn": 4500, "price_style": "exact"}]}],
         "items": _items([("Party jollof", "Smoky, with fried plantain", 3500, "exact", "Favourite"), ("Egusi with pounded yam", "Assorted meat", 5000, "exact", None),
                          ("Peppered snail", "Six pieces", 6500, "exact", None), ("Small chops tray", "For ten people", 25000, "from", "Events")]),
         "hours": [{"days": "Mon to Sat", "time": "11am to 9pm"}], "location": {"address": "7 Herbert Macaulay Way, Yaba, Lagos", "landmark": ""}}},
    {"key": "salon", "personality": "calm, luxurious, precise",
     "content": {
         "business": _biz("Odara Hair Studio", "Victoria Island, Lagos", "Colour, cuts and protective styles"),
         "hero": {"headline": "Hair that holds its shape", "subhead": "Colour, cuts and protective styles by appointment."},
         "about": {"title": "A quiet studio", "body": ["Four chairs, no rush, and a stylist who listens before cutting."], "owner": "Odara Eze", "pull_quote": ""},
         "items": _items([("Silk press", "Wash, treatment, press", 25000, "from", None), ("Knotless braids", "Medium length", 45000, "from", "Popular"), ("Full colour", "Consultation first", 0, "on_request", None), ("Bridal trial", "Two hours", 60000, "exact", None)]),
         "process": {"title": "How a visit works", "steps": [{"title": "Book on WhatsApp", "text": "Tell us the style you want."}, {"title": "Consultation", "text": "We confirm the plan and the price."}, {"title": "Your appointment", "text": "Unhurried, with refreshments."}]},
         "hours": [{"days": "Tue to Sat", "time": "9am to 6pm"}], "location": {"address": "21 Adeola Odeku Street, Victoria Island, Lagos", "landmark": ""}}},
    {"key": "church", "personality": "welcoming, reverent, clear",
     "content": {
         "business": _biz("Grace Assembly", "Ikeja, Lagos", "A family for every season"),
         "hero": {"headline": "Come as you are. Stay for the family.", "subhead": "Sunday services at 8am and 10am in Ikeja."},
         "about": {"title": "Who we are", "body": ["A local church serving Ikeja for over twenty years."], "owner": "Pastor Tunde Adebayo", "pull_quote": ""},
         "items": _items([("Sunday service", "8am and 10am", 0, "on_request", None), ("Midweek prayer", "Wednesday, 6pm", 0, "on_request", None), ("Youth fellowship", "Friday, 5pm", 0, "on_request", None)]),
         "faqs": [{"q": "Is there parking?", "a": "Yes, the compound holds about eighty cars."}, {"q": "Is there a children's service?", "a": "Yes, during both Sunday services."}],
         "hours": [{"days": "Sunday", "time": "8am and 10am"}, {"days": "Wednesday", "time": "6pm"}], "location": {"address": "3 Allen Avenue, Ikeja, Lagos", "landmark": "Beside the fuel station"}}},
    {"key": "school", "personality": "bright, trustworthy, energetic",
     "content": {
         "business": _biz("Bright Path Academy", "Abuja", "Nursery and primary education"),
         "hero": {"headline": "Small classes. Big questions.", "subhead": "Nursery and primary school in Gwarinpa, Abuja."},
         "about": {"title": "Our approach", "body": ["Classes of twenty or fewer, with a teacher who knows every child by name."], "owner": "Mrs Halima Bello", "pull_quote": ""},
         "items": _items([("Nursery", "Ages 2 to 5", 0, "on_request", None), ("Primary 1 to 6", "Ages 6 to 11", 0, "on_request", None), ("After-school club", "Mon to Thu", 0, "on_request", None)]),
         "faqs": [{"q": "When does admission open?", "a": "Applications are open all year for the next available place."}, {"q": "Do you offer school transport?", "a": "Yes, within Gwarinpa and nearby estates."}],
         "location": {"address": "12 Ahmadu Bello Way, Gwarinpa, Abuja", "landmark": ""}}},
    {"key": "real_estate", "personality": "assured, premium, discreet",
     "content": {
         "business": _biz("Lagoon Homes", "Lagos", "Waterside apartments and short-lets"),
         "hero": {"headline": "Apartments with the lagoon outside", "subhead": "Furnished short-lets and sales in Ikoyi and Lekki."},
         "about": {"title": "Who we are", "body": ["We manage a small portfolio so that every apartment is looked after properly."], "owner": "", "pull_quote": ""},
         "items": _items([("Ikoyi two-bedroom", "Furnished, 24-hour power", 0, "on_request", "Short-let"), ("Lekki penthouse", "Terrace and lagoon view", 0, "on_request", "For sale"), ("Banana Island studio", "Serviced", 0, "on_request", "Short-let")]),
         "process": {"title": "How booking works", "steps": [{"title": "Message us", "text": "Tell us dates and guests."}, {"title": "Confirm", "text": "We send photos and a price."}, {"title": "Check in", "text": "Keys and a host on arrival."}]},
         "location": {"address": "Ikoyi, Lagos", "landmark": ""}}},
    {"key": "logistics", "personality": "fast, dependable, industrial",
     "content": {
         "business": _biz("Swift Lane Dispatch", "Lagos", "Same-day delivery across the Mainland and Island"),
         "hero": {"headline": "Picked up at nine. Delivered by noon.", "subhead": "Same-day dispatch riders across Lagos."},
         "about": {"title": "Built for small businesses", "body": ["We run a fleet of forty riders and a simple price per zone."], "owner": "", "pull_quote": ""},
         "items": _items([("Mainland to Mainland", "Same day", 2500, "from", None), ("Mainland to Island", "Same day", 3500, "from", None), ("Interstate parcels", "2 to 3 days", 6000, "from", None)]),
         "process": {"title": "How it works", "steps": [{"title": "Send the details", "text": "Pickup, drop-off and parcel size."}, {"title": "We confirm the price", "text": "Before the rider leaves."}, {"title": "Track the delivery", "text": "A rider updates you on WhatsApp."}]},
         "faqs": [{"q": "What is the weight limit?", "a": "Riders carry up to 15kg. Larger loads go by van."}]}},
    {"key": "events", "personality": "bold, celebratory, high-energy",
     "content": {
         "business": _biz("Afterglow Events", "Lagos", "Weddings, birthdays and brand launches"),
         "hero": {"headline": "Your night, built to be remembered", "subhead": "Planning, decor and coordination for events in Lagos."},
         "about": {"title": "Calm on the day", "body": ["We plan the details so you can enjoy the room."], "owner": "Ngozi Bassey", "pull_quote": ""},
         "items": _items([("Wedding planning", "From first meeting to last dance", 0, "on_request", None), ("Birthday packages", "Decor, cake table, coordinator", 350000, "from", None), ("Brand launches", "Stage, hosting, guest flow", 0, "on_request", None), ("Decor only", "Hire without planning", 150000, "from", None)]),
         "process": {"title": "How we work", "steps": [{"title": "Chat", "text": "Tell us the date and the mood."}, {"title": "Plan", "text": "A clear budget and timeline."}, {"title": "Event day", "text": "We run it so you do not have to."}]}}},
    {"key": "photographer", "personality": "quiet, artistic, minimal",
     "content": {
         "business": _biz("Kofi Lens", "Accra", "Portraits and weddings", wa="+233200000000", ig="@kofilens"),
         "hero": {"headline": "Portraits that sound like you", "subhead": "Portrait and wedding photography in Accra."},
         "about": {"title": "About the work", "body": ["Natural light, unhurried sessions, and a delivery of edited images in seven days."], "owner": "Kofi Mensah", "pull_quote": ""},
         "items": _items([("Portrait session", "One hour, ten edited images", 1500, "exact", None), ("Wedding day", "Full day coverage", 0, "on_request", None), ("Family session", "Up to six people", 2200, "exact", None)]),
         "gallery": [{"caption": "Portrait, Osu"}, {"caption": "Wedding, Aburi"}, {"caption": "Family, Labadi"}]}},
    {"key": "consultant", "personality": "authoritative, clear, understated",
     "content": {
         "business": _biz("Ledger and Co", "Lagos", "Bookkeeping and tax for small businesses"),
         "hero": {"headline": "Books that are ready when the taxman is", "subhead": "Bookkeeping, payroll and tax filing for Nigerian small businesses."},
         "about": {"title": "Plain-English accounting", "body": ["We keep your records current, so tax season is a non-event."], "owner": "Chidi Okoye, ACA", "pull_quote": ""},
         "items": _items([("Monthly bookkeeping", "Reconciled and reported monthly", 45000, "from", None), ("Payroll", "Up to 20 staff", 30000, "from", None), ("Annual tax filing", "Company income tax", 0, "on_request", None)]),
         "faqs": [{"q": "Do you work with startups?", "a": "Yes, most of our clients have fewer than 20 staff."}, {"q": "How do we start?", "a": "Message us on WhatsApp and we will arrange a call."}],
         "process": {"title": "Getting started", "steps": [{"title": "Intro call", "text": "Fifteen minutes, no charge."}, {"title": "Records handover", "text": "Share your bank statements."}, {"title": "Monthly reports", "text": "A summary on the fifth of each month."}]}}},
]
