"""
tests/unit/test_site_capture_service.py
SITE-ADDONS A1-1 - the site key, the client workspace, the enquiry form, the tracked links, owner alerts and reminders.
FakeDB stands in for Supabase; lead_service.create_lead is replaced by a plain insert (it is tested on its own) and the
message senders are recorded instead of sent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import lead_service
from app.services import site_capture_service as cap
from app.services import site_entitlement_service as ent
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
GOOD = {"name": "Ada Obi", "phone": "08031234567", "email": "", "message": "How much for 50 cakes?", "consent": True}


def _site(sid="site-1", biz="Alfa Cakes", wa="+2348090000001"):
    return {"id": sid, "org_id": ORG, "deleted_at": None, "client_business_name": biz,
            "content": {"business": {"whatsapp_e164": wa}},
            "legal_owner": {"full_name": "Chidi", "phone": "08030000009", "email": "owner@example.com"}}


def _tier(site="site-1", key="capture", status="active", features_off=False, **kw):
    r = {"id": f"t-{site}", "org_id": ORG, "site_id": site, "kind": "tier", "key": key, "status": status, "source": "staff",
         "billing_mode": "link", "paid_until": None, "grace_until": None, "config": {}, "payer_name": None,
         "payer_phone": None, "payer_email": None}
    r.update(kw)
    return r


def _db(sites=None, tiers=None, pricing=None):
    sites = sites if sites is not None else [_site()]
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": pricing or {}}],
        sites=sites, site_addons=tiers if tiers is not None else [_tier()], site_usage_counters=[], site_events=[],
        site_keys=[], site_workspaces=[], site_lead_events=[], organisations=[], roles=[], users=[], leads=[],
        site_domains=[{"org_id": ORG, "site_id": "site-1", "domain": "alfacakes.ng"}])


@pytest.fixture
def sent(monkeypatch):
    log = {"email": [], "wa": []}
    monkeypatch.setattr(cap, "_send_email", lambda to, subject, text: log["email"].append((to, subject, text)) or True)
    monkeypatch.setattr(cap, "_send_whatsapp", lambda db, org, phone, text, **kw: log["wa"].append((phone, text, kw)) or True)

    def fake_create(db, org_id, user_id, payload, **kw):
        row = {"org_id": org_id, "full_name": payload.full_name, "phone": lead_service._normalise_phone(payload.phone),
               "email": payload.email, "problem_stated": payload.problem_stated, "source": "landing_page", "stage": "new",
               "assigned_to": user_id}
        return db.table("leads").insert(row).execute().data[0]
    monkeypatch.setattr(lead_service, "create_lead", fake_create)
    return log


def _key(db, site="site-1"):
    return cap.get_or_create_key(db, ORG, site)["key"]


# -- the key ------------------------------------------------------------------------

def test_a_site_gets_one_key_and_keeps_it():
    db = _db()
    a = _key(db)
    assert a.startswith("sk_") and _key(db) == a and len(db.rows("site_keys")) == 1


def test_rotating_switches_the_old_key_off():
    db = _db()
    old = _key(db)
    new = cap.rotate_key(db, ORG, "site-1")["key"]
    assert new != old and cap.resolve_key(db, old) is None and cap.resolve_key(db, new)["site"]["id"] == "site-1"


@pytest.mark.parametrize("bad", ["", "nope", "sk_" + "x" * 80, None, 5])
def test_unknown_keys_resolve_to_nothing(bad):
    assert cap.resolve_key(_db(), bad) is None


def test_a_deleted_site_does_not_resolve():
    db = _db()
    k = _key(db)
    db.rows("sites")[0]["deleted_at"] = "2026-10-01T00:00:00Z"
    assert cap.resolve_key(db, k) is None


# -- the form -----------------------------------------------------------------------

def test_a_good_enquiry_makes_a_lead_in_a_new_workspace_and_tells_everyone(sent):
    db = _db()
    k = _key(db)
    r = cap.submit(db, k, GOOD, ip="1.2.3.4", src="product:chocolate-cake")
    assert r["status"] == "ok" and r["business"] == "Alfa Cakes" and r["wa_url"] == "https://wa.me/2348090000001"
    ws = db.rows("site_workspaces")
    assert len(ws) == 1 and ws[0]["site_id"] == "site-1"
    org = db.rows("organisations")[0]
    assert org["is_site_workspace"] is True and org["subscription_status"] == "site_workspace" and org["is_live"] is False
    assert len(db.rows("roles")) == 7
    user = db.rows("users")[0]
    assert user["is_system_user"] is True and user["org_id"] == org["id"] and user["id"] == ws[0]["system_user_id"]
    lead = db.rows("leads")[0]
    assert lead["org_id"] == org["id"] and lead["site_id"] == "site-1" and lead["source_detail"] == "product:chocolate-cake"
    assert lead["consent_version"] == "v1" and lead["consent_at"] and lead["alert_reminder_at"]
    assert lead["assigned_to"] == user["id"]
    ev = db.rows("site_lead_events")[0]
    assert ev["kind"] == "form_submit" and ev["lead_id"] == lead["id"] and ev["ip_hash"] and "1.2.3.4" not in ev["ip_hash"]
    assert any("Thanks" in w[1] or "thanks" in w[1] for w in sent["wa"])           # reply to the visitor
    owner_alert = [w for w in sent["wa"] if w[0] == "08030000009"][0]
    assert "Ada Obi" in owner_alert[1] and cap.answer_url(k, lead["id"]) == owner_alert[2]["cta"][1]
    assert sent["email"][0][0] == "owner@example.com" and k in sent["email"][0][2]


def test_the_workspace_is_made_once_per_site(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    cap.submit(db, k, {**GOOD, "phone": "08039999999", "name": "Bola"})
    assert len(db.rows("organisations")) == 1 and len(db.rows("site_workspaces")) == 1 and len(db.rows("leads")) == 2


@pytest.mark.parametrize("patch, word", [
    ({"name": ""}, "name"), ({"phone": "", "email": ""}, "phone"), ({"phone": "12"}, "phone number"),
    ({"email": "not-an-email", "phone": ""}, "email"), ({"consent": False}, "tick"), ({"message": "x" * 2001}, "too long"),
])
def test_field_problems_are_plain_messages_and_nothing_is_saved(sent, patch, word):
    db = _db()
    with pytest.raises(cap.CaptureError) as e:
        cap.submit(db, _key(db), {**GOOD, **patch})
    assert word in str(e.value)
    assert db.rows("leads") == [] and db.rows("site_workspaces") == []


def test_a_filled_honeypot_looks_like_success_but_saves_nothing(sent):
    db = _db()
    r = cap.submit(db, _key(db), GOOD, honeypot="http://spam.example")
    assert r["status"] == "ok" and r["lead_id"] is None
    assert db.rows("leads") == [] and db.rows("site_workspaces") == [] and sent == {"email": [], "wa": []}
    assert db.rows("site_lead_events")[0]["kind"] == "form_rejected"


def test_a_site_without_the_feature_sends_the_visitor_to_whatsapp(sent):
    db = _db(tiers=[])
    r = cap.submit(db, _key(db), GOOD)
    assert r["status"] == "off" and r["wa_url"] and db.rows("leads") == [] and db.rows("organisations") == []


@pytest.mark.parametrize("status", ["paused", "cancelled", "pending"])
def test_a_plan_that_is_not_live_turns_the_form_off(sent, status):
    db = _db(tiers=[_tier(status=status)])
    assert cap.submit(db, _key(db), GOOD)["status"] == "off"


def test_an_unknown_key_is_reported(sent):
    assert cap.submit(_db(), "sk_nothing", GOOD)["status"] == "unknown"


def test_the_same_phone_twice_is_one_lead_and_a_second_alert(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    replies = len([w for w in sent["wa"] if w[0] == "08031234567"])
    cap.submit(db, k, {**GOOD, "message": "Also a wedding cake"})
    assert len(db.rows("leads")) == 1
    assert len([w for w in sent["wa"] if w[0] == "08031234567"]) == replies          # no second auto-reply
    assert any("Another enquiry" in w[1] for w in sent["wa"] if w[0] == "08030000009")
    assert len([e for e in db.rows("site_lead_events") if e["kind"] == "form_submit"]) == 2


def test_alerts_are_off_when_speed_alerts_is_not_in_the_plan(sent):
    pricing = {"tiers": {"capture": {"features": ["form_instant_reply"]}}}
    db = _db(pricing=pricing)
    cap.submit(db, _key(db), GOOD)
    assert db.rows("leads")[0]["alert_reminder_at"] is None
    assert [w for w in sent["wa"] if w[0] == "08030000009"] == [] and sent["email"] == []


def test_source_is_kept_only_when_source_tracking_is_in_the_plan(sent):
    pricing = {"tiers": {"capture": {"features": ["form_instant_reply"]}}}
    db = _db(pricing=pricing)
    cap.submit(db, _key(db), GOOD, src="hero")
    assert db.rows("leads")[0]["source_detail"] is None


def test_a_broken_message_sender_never_loses_the_lead(sent, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(cap, "_send_whatsapp", boom)
    monkeypatch.setattr(cap, "_send_email", boom)
    db = _db()
    r = cap.submit(db, _key(db), GOOD)
    assert r["status"] == "ok" and len(db.rows("leads")) == 1


def test_two_sites_never_share_a_workspace_or_leads(sent):
    db = _db(sites=[_site(), _site("site-2", "Beta Bags")], tiers=[_tier(), _tier("site-2")])
    ka, kb = _key(db, "site-1"), _key(db, "site-2")
    cap.submit(db, ka, GOOD)
    cap.submit(db, kb, {**GOOD, "phone": "08031112222"})
    orgs = {w["site_id"]: w["workspace_org_id"] for w in db.rows("site_workspaces")}
    assert orgs["site-1"] != orgs["site-2"]
    for lead in db.rows("leads"):
        assert lead["org_id"] == orgs[lead["site_id"]]
    assert cap.answer_redirect(db, ka, [l for l in db.rows("leads") if l["site_id"] == "site-2"][0]["id"]) is None


def test_the_return_link_only_goes_to_the_sites_own_domain(sent):
    db = _db()
    k = _key(db)
    assert cap.submit(db, k, GOOD, return_to="https://alfacakes.ng/contact")["back_url"] == "https://alfacakes.ng/contact"
    assert cap.submit(db, k, {**GOOD, "phone": "08038887777"}, return_to="https://evil.example/x")["back_url"] is None
    assert cap.allowed_return_url(db, ORG, "site-1", "http://alfacakes.ng/") is None            # https only
    assert cap.allowed_return_url(db, ORG, "site-1", "https://www.alfacakes.ng/") == "https://www.alfacakes.ng/"


# -- tracked links -------------------------------------------------------------------

def test_the_whatsapp_link_logs_the_click_and_uses_the_sites_own_number():
    db = _db()
    url = cap.wa_redirect(db, _key(db), "hero", "Hi, I want a cake", ip="9.9.9.9")
    assert url == "https://wa.me/2348090000001?text=Hi%2C%20I%20want%20a%20cake"
    ev = db.rows("site_lead_events")[0]
    assert ev["kind"] == "wa_click" and ev["source"] == "hero"


def test_the_whatsapp_link_still_works_but_stops_counting_without_source_tracking():
    pricing = {"tiers": {"capture": {"features": ["form_instant_reply"]}}}
    db = _db(pricing=pricing)
    assert cap.wa_redirect(db, _key(db), "hero", None).startswith("https://wa.me/2348090000001")
    assert db.rows("site_lead_events") == []


def test_the_whatsapp_link_with_a_bad_key_goes_nowhere():
    assert cap.wa_redirect(_db(), "sk_nope", None, None) is None


def test_answer_now_marks_the_lead_answered_and_opens_whatsapp_to_the_visitor(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    lead = db.rows("leads")[0]
    url = cap.answer_redirect(db, k, lead["id"])
    assert url.startswith("https://wa.me/2348031234567?text=") and "Alfa%20Cakes" in url
    lead = db.rows("leads")[0]
    assert lead["answered_at"] and lead["alert_reminder_at"] is None
    assert [e["kind"] for e in db.rows("site_lead_events")][-1] == "answer_tap"


def test_answer_now_for_an_email_only_lead_opens_a_mail_link(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, {**GOOD, "phone": "", "email": "buyer@example.com"})
    assert cap.answer_redirect(db, k, db.rows("leads")[0]["id"]) == "mailto:buyer%40example.com"


def test_answer_now_with_an_unknown_lead_goes_nowhere(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    assert cap.answer_redirect(db, k, "not-a-lead") is None


# -- reminders ------------------------------------------------------------------------

def test_the_reminder_goes_once_to_an_owner_who_has_not_answered(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    sent["wa"].clear(); sent["email"].clear()
    later = datetime.now(timezone.utc) + timedelta(minutes=cap.REMINDER_MINUTES + 1)
    r = cap.run_reminders(db, later)
    assert r["sent"] == 1 and any("Reminder" in w[1] for w in sent["wa"])
    assert db.rows("leads")[0]["alert_reminder_at"] is None
    assert cap.run_reminders(db, later)["checked"] == 0              # nothing left to send


def test_no_reminder_before_its_time_or_after_the_owner_answered(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    assert cap.run_reminders(db, datetime.now(timezone.utc))["checked"] == 0
    cap.answer_redirect(db, k, db.rows("leads")[0]["id"])
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert cap.run_reminders(db, later)["checked"] == 0


def test_no_reminder_when_the_plan_has_been_paused_meanwhile(sent):
    db = _db()
    cap.submit(db, _key(db), GOOD)
    db.rows("site_addons")[0]["status"] = "paused"
    r = cap.run_reminders(db, datetime.now(timezone.utc) + timedelta(hours=1))
    assert r["skipped"] == 1 and r["sent"] == 0


# -- staff summary, limits, helpers -----------------------------------------------------

def test_the_staff_summary_counts_the_last_30_days(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    cap.wa_redirect(db, k, "hero", None)
    for e in db.rows("site_lead_events"):                       # the database fills created_at; FakeDB does not
        e["created_at"] = datetime.now(timezone.utc).isoformat()
    db.rows("site_lead_events").append({"org_id": ORG, "site_id": "site-1", "kind": "wa_click", "created_at": "2020-01-01T00:00:00+00:00"})
    s = cap.summary(db, ORG, "site-1")
    assert s["key"] == k and s["workspace"] is True and s["leads_total"] == 1
    assert s["events"]["form_submit"] == 1 and s["events"]["wa_click"] == 1
    assert s["features"] == {"form_instant_reply": True, "source_tracking": True, "speed_alerts": True, "my_leads_page": True}
    assert s["form_action"].endswith(f"/api/v1/public/site-leads/{k}") and s["wa_link"].endswith(f"/sl/{k}/wa")


def test_the_summary_for_another_orgs_site_is_not_found():
    with pytest.raises(ent.EntitlementNotFound):
        cap.summary(_db(), "org-2", "site-1")


def test_rate_limit_allows_up_to_the_limit_then_blocks():
    assert [cap.rate_limited("t-bucket", 3, 60, now=100.0 + i) for i in range(5)] == [False, False, False, True, True]
    assert cap.rate_limited("t-bucket", 3, 60, now=500.0) is False            # window passed


def test_source_text_is_cleaned():
    cleaned = cap.clean_source("  product:<script>x</script> ")
    assert cleaned.startswith("product:") and "<" not in cleaned and ">" not in cleaned
    assert cap.clean_source("") is None and len(cap.clean_source("a" * 500)) == 120


# -- the owner's "My leads" page -------------------------------------------------------------

def test_no_leads_token_until_the_site_has_a_workspace(sent):
    assert cap.leads_token(_db(), "site-1") is None


def test_the_leads_token_is_made_once_and_kept(sent):
    db = _db()
    cap.submit(db, _key(db), GOOD)
    t1 = cap.leads_token(db, "site-1")
    assert t1 and len(t1) >= 20 and cap.leads_token(db, "site-1") == t1
    assert cap.leads_url(t1).endswith("/my-leads/" + t1)


def test_my_leads_lists_newest_first_with_answer_links(sent):
    db = _db()
    k = _key(db)
    cap.submit(db, k, GOOD)
    cap.submit(db, k, dict(GOOD, name="Bola Ade", phone="08037654321"))
    for i, row in enumerate(db.rows("leads")):
        row["created_at"] = f"2026-10-0{i + 1}T10:00:00+00:00"
    db.rows("leads")[0]["answered_at"] = "2026-10-01T11:00:00+00:00"
    page = cap.my_leads(db, cap.leads_token(db, "site-1"))
    assert page["available"] is True and page["business"] == "Alfa Cakes" and page["total"] == 2
    assert [x["name"] for x in page["leads"]] == ["Bola Ade", "Ada Obi"]
    assert page["leads"][1]["answered"] is True and page["leads"][0]["answered"] is False
    assert page["leads"][0]["reply_url"] == cap.answer_url(k, page["leads"][0]["id"])


@pytest.mark.parametrize("bad", ["", "short", "x" * 200, None, "a" * 30])
def test_my_leads_unknown_links_show_nothing(sent, bad):
    db = _db()
    cap.submit(db, _key(db), GOOD)
    assert cap.my_leads(db, bad) is None


def test_my_leads_never_shows_another_sites_leads(sent):
    db = _db(sites=[_site(), _site("site-2", "Beta Bags")], tiers=[_tier(), _tier("site-2")])
    cap.submit(db, _key(db), GOOD)
    cap.submit(db, _key(db, "site-2"), dict(GOOD, name="Zed Other", phone="08039999999"))
    page = cap.my_leads(db, cap.leads_token(db, "site-1"))
    assert [x["name"] for x in page["leads"]] == ["Ada Obi"]


def test_my_leads_is_hidden_when_the_plan_does_not_include_it(sent):
    db = _db()
    cap.submit(db, _key(db), GOOD)
    tok = cap.leads_token(db, "site-1")
    db.rows("site_builder_settings")[0]["pricing"] = {"tiers": {"capture": {"features": ["form_instant_reply"]}}}
    page = cap.my_leads(db, tok)
    assert page["available"] is False and page["leads"] == []


def test_the_owner_alert_links_to_my_leads_when_the_plan_has_it(sent):
    db = _db()
    cap.submit(db, _key(db), GOOD)
    tok = cap.leads_token(db, "site-1")
    cap.submit(db, _key(db), dict(GOOD, phone="08035550000"))
    alerts = [w for w in sent["wa"] if w[0] == "08030000009"]
    assert any("/my-leads/" in w[1] for w in alerts) or any("/my-leads/" in e[2] for e in sent["email"])
    assert tok
