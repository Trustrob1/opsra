"""OPENING-CTA-2: ads ("campaigns"): per-ad greeting and starting button keyed by the link's tag, and the pieces that carry the tag."""
from __future__ import annotations

import pathlib

from app.routers import public_webchat as router
from app.services import webchat_service as wc

MENU = [{"id": "buy", "label": "Place an order", "answer": "x"},
        {"id": "inspect", "label": "Book inspection", "action": "booking"},
        {"id": "faq", "label": "Prices", "answer": "y"},
        {"id": "talk", "label": "Talk to the team", "action": "human"}]
CAMPS = [{"tag": "lekki-3bed", "label": "Lekki 3-bed", "main": "inspect", "main_label": "", "greeting": "Hi, asking about the Lekki 3-bed?"},
         {"tag": "promo", "label": "Promo", "main": "buy", "main_label": "Buy now", "greeting": ""},
         {"tag": "gone", "label": "Gone", "main": "deleted", "main_label": "", "greeting": "Old ad greeting"}]


def _cfg(**kw):
    return wc.sanitise_config({}) | {"menu": MENU, "business_name": "T", "brand_color": "#028090", "greeting": "Hi, I'm Chioma.", "contact_prompt": "c",
                                     "consent_text": "c", "fallback": "f", "booking_fields": [], "campaigns": CAMPS, **kw}


# ── settings ────────────────────────────────────────────────────────────────

def test_default_has_no_campaigns():
    assert wc.DEFAULT_CONFIG["campaigns"] == []


def test_clean_keeps_good_entries_and_defaults_the_label():
    out = wc.sanitise_config({"campaigns": [{"tag": "Lekki-3-Bed", "label": "  Lekki  ", "main": "Inspect", "greeting": " Hello "}, {"tag": "x1"}]})["campaigns"]
    assert out[0] == {"tag": "lekki-3-bed", "label": "Lekki", "main": "inspect", "main_label": "", "greeting": "Hello", "shortcuts": [], "product": "", "image": "", "video": ""}
    assert out[1]["label"] == "x1" and out[1]["main"] == "" and out[1]["greeting"] == ""


def test_clean_drops_reserved_duplicate_empty_and_junk():
    raw = [{"tag": "instagram"}, {"tag": "whatsapp"}, {"tag": "link"}, {"tag": "a"}, {"tag": "A"}, {"tag": "!!!"}, {}, "x", None, 5]
    assert [c["tag"] for c in wc.sanitise_config({"campaigns": raw})["campaigns"]] == ["a"]
    assert wc.sanitise_config({"campaigns": "nope"})["campaigns"] == []


def test_clean_caps_count_and_lengths():
    many = [{"tag": f"t{i}"} for i in range(80)]
    assert len(wc.sanitise_config({"campaigns": many})["campaigns"]) == wc.CAMPAIGNS_MAX
    c = wc.sanitise_config({"campaigns": [{"tag": "t" * 80, "label": "l" * 200, "main_label": "m" * 200, "greeting": "g" * 900}]})["campaigns"][0]
    assert len(c["tag"]) == 30 and len(c["label"]) == 60 and len(c["main_label"]) == 40 and len(c["greeting"]) == 400


# ── lookup by the link's tag ────────────────────────────────────────────────

def test_campaign_for_matches_the_tag_and_ignores_the_rest():
    cfg = _cfg()
    assert wc.campaign_for(cfg, "lekki-3bed")["label"] == "Lekki 3-bed"
    assert wc.campaign_for(cfg, "LEKKI-3BED")["tag"] == "lekki-3bed"
    for none in (None, "", "instagram", "unknown", "website"):
        assert wc.campaign_for(cfg, none) is None


def test_greeting_for_uses_the_ad_greeting_else_the_normal_one():
    cfg = _cfg()
    assert wc.greeting_for(cfg, "lekki-3bed") == "Hi, asking about the Lekki 3-bed?"
    assert wc.greeting_for(cfg, "promo") == "Hi, I'm Chioma."             # the ad has no words of its own
    assert wc.greeting_for(cfg, "unknown") == "Hi, I'm Chioma." and wc.greeting_for(cfg) == "Hi, I'm Chioma."


def test_opening_for_ad_main_button_leads_even_on_the_list_style():
    cfg = _cfg(opening={"style": "list"})
    v = wc.opening_for(cfg, "lekki-3bed")
    assert v["style"] == "pair" and v["main"] == {"id": "inspect", "kind": "menu", "label": "Book inspection"}
    assert wc.opening_for(cfg, "promo")["main"]["label"] == "Buy now"
    assert wc.opening_for(cfg, "direct") == {"style": "list"}


def test_opening_for_keeps_the_business_second_button_words():
    cfg = _cfg(opening={"style": "pair", "main": "buy", "speak_label": "Talk to Chioma", "speak_reply": "Ask away"})
    v = wc.opening_for(cfg, "lekki-3bed")
    assert v["main"]["id"] == "inspect" and v["speak_label"] == "Talk to Chioma" and v["speak_reply"] == "Ask away"


def test_opening_for_falls_back_when_the_ad_button_is_gone_or_shop_is_off():
    cfg = _cfg(opening={"style": "pair", "main": "buy"})
    assert wc.opening_for(cfg, "gone")["main"]["id"] == "buy"                  # the business's own first screen
    cfg2 = _cfg(campaigns=[{"tag": "s", "main": "shop"}], shop_enabled=False)
    assert wc.opening_for(cfg2, "s") == {"style": "list"}


# ── what the visitor's browser gets ─────────────────────────────────────────

def test_public_view_applies_the_ad_and_leaks_no_other_ad():
    pv = wc.public_view(_cfg(), "lekki-3bed")
    assert pv["greeting"] == "Hi, asking about the Lekki 3-bed?" and pv["opening"]["main"]["id"] == "inspect"
    text = str(pv)
    assert "Old ad greeting" not in text and "promo" not in text and "campaigns" not in pv


def test_public_view_without_a_source_is_unchanged():
    pv = wc.public_view(_cfg())
    assert pv["greeting"] == "Hi, I'm Chioma." and pv["opening"] == {"style": "list"}


def test_snapshot_uses_the_session_source():
    s = {"source": "lekki-3bed", "id": "s1", "state": {}, "status": "active"}
    snap = router._snapshot(s, _cfg(), [])
    assert snap["config"]["greeting"] == "Hi, asking about the Lekki 3-bed?"
    assert router._snapshot({**s, "source": "instagram"}, _cfg(), [])["config"]["greeting"] == "Hi, I'm Chioma."


# ── the pieces that carry the tag ───────────────────────────────────────────

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_session_start_uses_the_ad_greeting():
    src = (ROOT / "backend" / "app" / "routers" / "public_webchat.py").read_text(encoding="utf-8")
    assert 'wc.greeting_for(cfg, s.get("source"))' in src and 'wc.public_view(cfg, s.get("source"), s.get("org_id"))' in src


def test_widget_reads_the_chioma_address_tag_and_keeps_old_hooks():
    js = (ROOT / "frontend" / "public" / "widget.js").read_text(encoding="utf-8")
    assert "get('chioma')" in js and "opsra_chioma_src" in js
    assert "&o=menu" in js and "data-chioma-menu" in js


def test_ad_links_screen_is_wired_in():
    admin = ROOT / "frontend" / "src" / "modules" / "admin"
    comp = (admin / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    for needle in ("Links for ads", "1. Ad with no website", "2. Ad that opens WhatsApp", "3. Ad that goes to your website", "?chioma=", "data-chioma-menu", "data-chioma-open=\"shop\""):
        assert needle in comp or needle.replace("?chioma=", "chioma=") in comp, needle
    settings = (admin / "WebChatSettings.jsx").read_text(encoding="utf-8")
    assert "import WebChatAdLinks" in settings and "<WebChatAdLinks " in settings


def test_reserved_tags_match_the_built_in_share_links():
    for t in ("instagram", "qr", "site", "facebook", "google", "whatsapp_status", "email", "sms"):
        assert t in wc.RESERVED_TAGS                                         # the six channel links + QR + site keep their own stats lines
    comp = (ROOT / "frontend" / "src" / "modules" / "admin" / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    for t in wc.RESERVED_TAGS:
        assert f"'{t}'" in comp, t                                           # the screen warns about the same names the server drops


# ── the per-ad report and the WhatsApp reply link ───────────────────────────

def test_insights_shows_ads_by_name_even_with_no_visits_yet():
    admin = ROOT / "frontend" / "src" / "modules" / "admin"
    ins = (admin / "WebChatInsights.jsx").read_text(encoding="utf-8")
    assert "ads = []" in ins and "adByTag" in ins and "Ad · " in ins
    assert "rows.map(" in ins and "f.sources.map(" not in ins            # the table is drawn from sources plus the ads with no visits
    assert "ads={cfg.campaigns}" in (admin / "WebChatSettings.jsx").read_text(encoding="utf-8")


def test_whatsapp_reply_visitor_is_not_asked_for_a_number_again():
    from app.services import webchat_flow_service as flow
    from app.services import webchat_service as svc
    # the one-time reply link makes a session that already carries the proven number and the lead
    src = (ROOT / "backend" / "app" / "services" / "webchat_service.py").read_text(encoding="utf-8")
    assert '"phone_verified": True' in src and '"lead_id": lead_id' in src and '"contact_phone": phone' in src
    assert flow._has_contact({"lead_id": "L1", "contact_phone": "+2348000000000"}) is True
    assert flow._has_contact({}) is False
    assert svc.create_handoff                                              # exists; the link carries ?h=


# ── the website ask bar leads with the ad's button ──────────────────────────

def _bar(**kw):
    return _cfg(ask_bar=True, **kw)


def test_ask_bar_normal_visitor_unchanged():
    b = wc.ask_bar_view(_bar())
    assert [c["id"] for c in b["chips"]][0] == "inspect" and b["chips"][0]["primary"] is True      # Book still first without an ad
    assert wc.ask_bar_view(_bar(), "unknown") == b and wc.ask_bar_view(_bar(), "instagram") == b


def test_ask_bar_ad_main_button_leads_and_is_solid():
    b = wc.ask_bar_view(_bar(), "promo")
    assert b["chips"][0] == {"id": "buy", "label": "Buy now", "primary": True}                      # the ad's own words
    assert [c["primary"] for c in b["chips"]].count(True) == 1 and len({c["id"] for c in b["chips"]}) == len(b["chips"])


def test_ask_bar_ad_button_shows_even_if_not_featured_and_never_the_human_button():
    cfg = _bar(menu=[{**m, "featured": m["id"] == "faq"} for m in MENU])
    assert wc.ask_bar_view(cfg, "lekki-3bed")["chips"][0]["id"] == "inspect"
    cfg2 = _bar(campaigns=[{"tag": "t", "main": "talk"}])
    assert wc.ask_bar_view(cfg2, "t")["chips"][0]["id"] != "talk"
    assert wc.ask_bar_view(_bar(campaigns=[{"tag": "s", "main": "shop"}], shop_enabled=True), "s")["chips"][0]["id"] == "inspect"
    assert wc.ask_bar_view(_bar(), "gone")["chips"][0]["id"] == "inspect"                           # deleted button: ordinary bar


def test_ask_bar_off_stays_off_for_ads():
    assert wc.ask_bar_view(_cfg(), "promo") is None


def test_widget_sends_the_ad_tag_to_the_bar_and_endpoint_accepts_it():
    js = (ROOT / "frontend" / "public" / "widget.js").read_text(encoding="utf-8")
    assert "'?s=' + encodeURIComponent(source)" in js and "'/widget'" in js
    src = (ROOT / "backend" / "app" / "routers" / "public_webchat.py").read_text(encoding="utf-8")
    assert "wc.ask_bar_view(cfg, s)" in src and "def widget_info(key: str, request: Request, s:" in src


# ── the ad's picture ────────────────────────────────────────────────────────

ORG = "11111111-2222-3333-4444-555555555555"
KEY = "a" * 32 + ".jpg"


def test_only_a_key_we_issued_is_kept_as_the_picture():
    good = wc.sanitise_config({"campaigns": [{"tag": "a", "image": KEY}]})["campaigns"][0]["image"]
    assert good == KEY
    for bad in ("https://evil.example/x.jpg", "../../x.jpg", "A" * 32 + ".jpg", "a" * 31 + ".jpg", "a" * 32 + ".gif", "a" * 32 + ".svg", "", None, 5, ["x"]):
        assert wc.sanitise_config({"campaigns": [{"tag": "a", "image": bad}]})["campaigns"][0]["image"] == ""


def test_picture_address_is_built_from_the_business_id_and_key():
    url = wc.ad_image_url(ORG, KEY)
    assert url.endswith(f"/storage/v1/object/public/catalog/{ORG}/webchat-ads/{KEY}")
    for org, key in (("../x", KEY), (None, KEY), (ORG, "x.jpg"), (ORG, None), (ORG, "https://evil/x.jpg")):
        assert wc.ad_image_url(org, key) is None


def test_visitor_gets_the_picture_only_from_its_own_ad_and_never_a_list():
    cfg = _cfg(campaigns=[{"tag": "lekki-3bed", "main": "inspect", "image": KEY}, {"tag": "promo", "main": "buy", "image": "b" * 32 + ".png"}])
    pv = wc.public_view(cfg, "lekki-3bed", ORG)
    assert pv["ad_image"].endswith(KEY) and "b" * 32 not in str(pv)
    assert wc.public_view(cfg, "promo", ORG)["ad_image"].endswith("b" * 32 + ".png")
    assert wc.public_view(cfg, "instagram", ORG)["ad_image"] is None and wc.public_view(cfg, None, ORG)["ad_image"] is None
    assert wc.public_view(cfg, "lekki-3bed")["ad_image"] is None                     # no business id: nothing to build from
    assert wc.public_view(_cfg(), "promo", ORG)["ad_image"] is None                   # an ad with no picture


def test_upload_endpoint_checks_the_real_file_and_the_screen_shows_the_picture():
    root = ROOT / "backend" / "app" / "routers" / "webchat.py"
    src = root.read_text(encoding="utf-8")
    body = src.split('@router.post("/webchat/ad-image")', 1)[1].split("@router.put", 1)[0]
    assert "_require_manager(org)" in body and "_sniff(data" in body and '("jpg", "png", "webp")' in body      # owners and managers only; the real file type is checked
    assert '"ad_images":' in src
    page = (ROOT / "frontend" / "src" / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "{cfg.ad_image && !cfg.ad_video && !hiddenIds && (" in page and "src={cfg.ad_image}" in page
    comp = (ROOT / "frontend" / "src" / "modules" / "admin" / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    assert "uploadWebchatAdImage" in comp and "Add a picture" in comp
    assert "export async function uploadWebchatAdImage" in (ROOT / "frontend" / "src" / "services" / "webchat.service.js").read_text(encoding="utf-8")


# ── the ad's video ──────────────────────────────────────────────────────────

VKEY = "c" * 32 + ".mp4"


def test_only_a_video_key_we_issued_is_kept():
    ok = wc.sanitise_config({"campaigns": [{"tag": "a", "video": VKEY}, {"tag": "b", "video": "d" * 32 + ".webm"}]})["campaigns"]
    assert ok[0]["video"] == VKEY and ok[1]["video"].endswith(".webm")
    for bad in ("https://evil.example/v.mp4", "../v.mp4", "c" * 32 + ".mov", "c" * 32 + ".jpg", VKEY.upper(), "", None, 7):
        assert wc.sanitise_config({"campaigns": [{"tag": "a", "video": bad}]})["campaigns"][0]["video"] == ""
    assert wc.sanitise_config({"campaigns": [{"tag": "a", "video": VKEY}]})["campaigns"][0]["image"] == ""     # picture and video are separate


def test_video_address_is_built_here_and_a_picture_key_is_not_a_video():
    assert wc.ad_video_url(ORG, VKEY).endswith(f"/public/catalog/{ORG}/webchat-ads/{VKEY}")
    assert wc.ad_video_url(ORG, KEY) is None and wc.ad_image_url(ORG, VKEY) is None
    assert wc.ad_video_url("../x", VKEY) is None and wc.ad_video_url(None, VKEY) is None and wc.ad_video_url(ORG, None) is None


def test_visitor_gets_the_video_only_from_its_own_ad():
    cfg = _cfg(campaigns=[{"tag": "lekki-3bed", "main": "inspect", "video": VKEY, "image": KEY}, {"tag": "promo", "main": "buy", "video": "d" * 32 + ".webm"}])
    pv = wc.public_view(cfg, "lekki-3bed", ORG)
    assert pv["ad_video"].endswith(VKEY) and pv["ad_image"].endswith(KEY) and "d" * 32 not in str(pv)
    assert wc.public_view(cfg, "promo", ORG)["ad_image"] is None and wc.public_view(cfg, "promo", ORG)["ad_video"].endswith(".webm")
    assert wc.public_view(cfg, "instagram", ORG)["ad_video"] is None and wc.public_view(cfg, "lekki-3bed")["ad_video"] is None


def test_video_type_is_judged_from_the_bytes():
    assert wc.sniff_video(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00") == ("video/mp4", "mp4")
    assert wc.sniff_video(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00") == ("video/mp4", "mp4")
    assert wc.sniff_video(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01") == ("video/webm", "webm")
    for bad in (b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00", b"GIF89a" + b"0" * 20, b"<svg onload=1>", b"", b"MZ" + b"0" * 30):
        assert wc.sniff_video(bad) is None


def test_video_upload_endpoint_and_screens_are_wired():
    src = (ROOT / "backend" / "app" / "routers" / "webchat.py").read_text(encoding="utf-8")
    body = src.split('@router.post("/webchat/ad-video")', 1)[1].split("@router.put", 1)[0]
    assert "_require_manager(org)" in body and "wc.sniff_video(data)" in body and "wc.AD_VIDEO_MAX_BYTES" in body and "rate_limited" in body
    assert '"ad_videos":' in src and wc.AD_VIDEO_MAX_BYTES == 25 * 1024 * 1024
    page = (ROOT / "frontend" / "src" / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "{cfg.ad_video && !hiddenIds && (" in page and 'preload="metadata"' in page and "playsInline" in page and "controls" in page
    assert "autoPlay" not in page                                                       # nothing plays or downloads until the visitor taps
    assert "cfg.ad_image && !cfg.ad_video" in page                                      # a video replaces the picture, which becomes its cover
    comp = (ROOT / "frontend" / "src" / "modules" / "admin" / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    assert "uploadWebchatAdVideo" in comp and "Add a video" in comp and "25 * 1024 * 1024" in comp
    assert "export async function uploadWebchatAdVideo" in (ROOT / "frontend" / "src" / "services" / "webchat.service.js").read_text(encoding="utf-8")


# ── the upload endpoints, called directly ───────────────────────────────────

class _Up:
    def __init__(self, data, name="ad.mp4"):
        import io as _io
        self.file, self.filename = _io.BytesIO(data), name


class _Bucket:
    def __init__(self, log, fail): self.log, self.fail = log, fail
    def upload(self, path, file, file_options):
        if self.fail:
            raise RuntimeError("storage down")
        self.log.append((path, len(file), file_options["content-type"]))


class _DB:
    def __init__(self, fail=False): self.log, self.fail = [], fail
    @property
    def storage(self):
        outer = self
        class _S:
            def from_(self, name): return _Bucket(outer.log, outer.fail)
        return _S()


OWNER = {"org_id": ORG, "id": "u1", "roles": {"template": "owner"}}
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00" + b"0" * 64


def _call(fn, up, org=OWNER, db=None):
    from unittest.mock import patch
    from app.routers import webchat as r
    with patch.object(wc, "rate_limited", return_value=False):
        return fn(file=up, db=db or _DB(), org=org)


def test_video_upload_saves_a_real_mp4_under_a_random_key_in_this_business_folder():
    from app.routers import webchat as r
    db = _DB()
    res = _call(r.upload_ad_video, _Up(MP4), db=db).data
    assert wc.AD_VIDEO_KEY.match(res["video"]) and res["url"].endswith(f"/{ORG}/webchat-ads/{res['video']}")
    assert db.log[0][0] == f"{ORG}/webchat-ads/{res['video']}" and db.log[0][2] == "video/mp4"


def test_video_upload_refuses_big_wrong_type_and_non_managers():
    from fastapi import HTTPException
    from app.routers import webchat as r
    for up, code in ((_Up(MP4 + b"0" * wc.AD_VIDEO_MAX_BYTES), 422), (_Up(b"<script>alert(1)</script>", "x.mp4"), 422), (_Up(b"\x00\x00\x00\x14ftypqt  " + b"0" * 40, "x.mov"), 422)):
        try:
            _call(r.upload_ad_video, up)
            assert False, "should refuse"
        except HTTPException as e:
            assert e.status_code == code
    try:
        _call(r.upload_ad_video, _Up(MP4), org={**OWNER, "roles": {"template": "sales_rep"}})
        assert False, "a sales rep must not upload"
    except HTTPException as e:
        assert e.status_code == 403
    try:
        _call(r.upload_ad_video, _Up(MP4), db=_DB(fail=True))
        assert False
    except HTTPException as e:
        assert e.status_code == 503


def test_picture_upload_accepts_jpg_and_refuses_svg_gif_and_other_files():
    from fastapi import HTTPException
    from app.routers import webchat as r
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 64
    res = _call(r.upload_ad_image, _Up(jpg, "a.jpg")).data
    assert wc.AD_IMAGE_KEY.match(res["image"])
    for bad in (b"<svg xmlns='http://www.w3.org/2000/svg' onload='x()'/>", b"GIF89a" + b"0" * 40, b"%PDF-1.4" + b"0" * 40):
        try:
            _call(r.upload_ad_image, _Up(bad, "a.jpg"))
            assert False, "should refuse"
        except HTTPException as e:
            assert e.status_code == 422
