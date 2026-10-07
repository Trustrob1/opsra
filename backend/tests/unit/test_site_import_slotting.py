"""
tests/unit/test_site_import_slotting.py
-----------------------------------------
SITE-IMPORT 2 - the DOM that keeps a page byte for byte, outline, applying a plan, filling and proving the result.
No database, no network.
"""
from __future__ import annotations

import pytest

from app.models.sites import SiteContentV1
from app.services import site_import_dom as dom
from app.services import site_import_slotting as sl

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Mama Put Kitchen</title>
<link rel="stylesheet" href="css/style.css"><style>.card>h3{color:red}</style></head>
<body class="home">
<!-- top bar -->
<header id="top"><h1 class="brand">Mama Put Kitchen</h1><button id="menu" onclick="document.body.classList.toggle('open')">Menu</button></header>
<section class="hero"><h2>Home cooked food, delivered</h2><p class="sub">Fresh every morning in Lekki.</p><img src="img/hero.jpg" alt="Hero" width="800" height="400">
<a class="btn" href="https://wa.me/2348012345678?text=Hello">Order on WhatsApp</a></section>
<section class="menu"><h2>Our menu</h2>
<div class="cards">
<div class="card"><img src="img/jollof.jpg" alt="Jollof"><h3>Jollof Rice</h3><p>Smoky party jollof.</p><span class="price">₦2,500</span><a href="https://wa.me/2348012345678?text=Jollof">Order</a></div>
<div class="card"><img src="img/egusi.jpg" alt="Egusi"><h3>Egusi Soup</h3><p>With pounded yam.</p><span class="price">₦3,000</span><a href="https://wa.me/2348012345678?text=Egusi">Order</a></div>
<div class="card"><img src="img/suya.jpg" alt="Suya"><h3>Suya</h3><p>Spicy and fresh.</p><span class="price">₦1,500</span><a href="https://wa.me/2348012345678?text=Suya">Order</a></div>
</div></section>
<section class="hours"><h2>Hours</h2><ul><li><b>Mon-Fri</b> <i>8am - 6pm</i></li><li><b>Sat</b> <i>9am - 4pm</i></li></ul></section>
<footer><p class="addr">12 Admiralty Way, Lekki</p><a class="call" href="tel:+2348012345678">Call us</a> <a class="ig" href="https://instagram.com/mamaput">Instagram</a></footer>
<script>var a=1;if(a<2&&a>0){console.log('x < y && "z"');}</script>
<script src="js/app.js"></script>
</body></html>
"""


def asset_for(src):
    return "asset:" + src


def assets_for(skeleton_result):
    return {i["asset_id"]: {"public_url": "https://cdn/" + i["asset_id"][6:], "export_path": "images/" + i["asset_id"][6:].replace("/", "-")}
            for i in skeleton_result["images"] if i["asset_id"]}


def go(html=PAGE, plan=None):
    return sl.apply_plan(html, plan or build_plan(html), asset_for=asset_for)


def ids_by_text(root, index, text, tag=None):
    for e in index.values():
        if (tag is None or e.tag == tag) and dom.is_leaf_text(e) and dom.text_of(e) == text:
            return e.id
    raise AssertionError(f"no element with text {text}")


def build_plan(html=PAGE):
    root = dom.parse(html)
    ix = dom.assign_ids(root)
    t = lambda s, tag=None: ids_by_text(root, ix, s, tag)  # noqa: E731
    cards = [e for e in ix.values() if e.tag == "div" and e.attrs.get("class") == "card"]
    c0 = cards[0]
    kids = [c for c in c0.children if isinstance(c, dom.Elem)]       # img h3 p span a
    lis = [e for e in ix.values() if e.tag == "li"]
    hero_a = next(e for e in ix.values() if e.tag == "a" and e.attrs.get("class") == "btn")
    hero_img = next(e for e in ix.values() if e.tag == "img" and e.attrs.get("alt") == "Hero")
    call = next(e for e in ix.values() if e.attrs.get("class") == "call")
    ig = next(e for e in ix.values() if e.attrs.get("class") == "ig")
    li0 = lis[0]
    li_kids = [c for c in li0.children if isinstance(c, dom.Elem)]
    return {
        "slots": [
            {"el": t("Mama Put Kitchen", "h1"), "path": "business.name"},
            {"el": t("Home cooked food, delivered"), "path": "hero.headline"},
            {"el": t("Fresh every morning in Lekki."), "path": "hero.subhead"},
            {"el": t("12 Admiralty Way, Lekki"), "path": "location.address"},
        ],
        "images": [{"el": hero_img.id, "path": "hero.image"}],
        "links": [{"el": hero_a.id, "kind": "whatsapp"}, {"el": call.id, "kind": "phone"}, {"el": ig.id, "kind": "instagram"}],
        "repeats": [
            {"path": "items", "instances": [c.id for c in cards],
             "slots": [{"el": kids[1].id, "path": "name"}, {"el": kids[2].id, "path": "desc"},
                       {"el": kids[3].id, "path": "price_ngn", "format": "naira"}],
             "images": [{"el": kids[0].id, "path": "image"}],
             "links": [{"el": kids[4].id, "kind": "whatsapp"}]},
            {"path": "hours", "instances": [l.id for l in lis],
             "slots": [{"el": li_kids[0].id, "path": "days"}, {"el": li_kids[1].id, "path": "time"}]},
        ],
    }


class TestDom:
    def test_roundtrip_is_byte_identical(self):
        assert dom.serialise(dom.parse(PAGE)) == PAGE

    @pytest.mark.parametrize("html", [
        "<p>a<p>b", "<ul><li>a<li>b</ul>", "<img src=x><br><input value=1>text", "<div/><span>x</span>",
        "<!--c--><b>&amp; &lt; &copy; &#169;</b>", "<script>if(a<b&&c){}</script>", "<style>a>b{}</style>", "<table><tr><td>1<td>2<tr><td>3</table>",
    ])
    def test_roundtrip_variants(self, html):
        assert dom.serialise(dom.parse(html)) == html

    def test_implied_end_tags_make_siblings(self):
        r = dom.parse("<ul><li>a<li>b<li>c</ul>")
        ul = dom.find(r, "ul")
        assert [c.tag for c in ul.children if isinstance(c, dom.Elem)] == ["li", "li", "li"]

    def test_void_elements_do_not_swallow_following_content(self):
        r = dom.parse("<div><input value=1><span>x</span></div>")
        assert [c.tag for c in dom.find(r, "div").children if isinstance(c, dom.Elem)] == ["input", "span"]

    def test_set_and_strip_attrs(self):
        assert dom.set_attrs('<a href="x" class=y>', {"data-slot": 'a"b'}) == '<a href="x" class=y data-slot="a&quot;b">'
        assert dom.set_attrs("<img src=x />", {"data-slot-img": "p"}) == '<img src=x data-slot-img="p" />'
        assert dom.strip_attrs('<a data-slot-href="w" data-slot="x" class="c">', ["data-slot-href", "data-slot"]) == '<a class="c">'
        assert dom.strip_attrs('<a data-slot-img="x">', ["data-slot"]) == '<a data-slot-img="x">'     # a longer name is not touched
        assert dom.set_attrs('<a href="x">', {"href": "y"}) == '<a href="y">'

    def test_text_of_ignores_script_and_collapses_space(self):
        r = dom.parse("<p>  a \n b<script>zzz</script> &amp; c</p>")
        assert dom.text_of(dom.find(r, "p")) == "a b & c"

    def test_leaf_text(self):
        r = dom.parse("<p>a <b>b</b></p><h1>x<!--c--></h1>")
        assert not dom.is_leaf_text(dom.find(r, "p")) and dom.is_leaf_text(dom.find(r, "h1"))


class TestOutline:
    def test_outline_lists_ids_text_and_collapses_runs(self):
        root = dom.parse(PAGE)
        dom.assign_ids(root)
        o = sl.outline(root)
        assert "Mama Put Kitchen" in o and "wa.me/2348012345678" in o and "(not shown)" in o and "var a=1" not in o

    def test_long_runs_are_collapsed(self):
        html = "<body>" + "".join(f"<div class=c><h3>Item {i}</h3></div>" for i in range(8)) + "</body>"
        root = dom.parse(html)
        dom.assign_ids(root)
        o = sl.outline(root)
        assert "6 more like" in o and "Item 5" not in o


class TestApplyPlan:
    def test_happy_path(self):
        r = go()
        assert r["errors"] == []
        c = r["content"]
        assert c["business"] == {"name": "Mama Put Kitchen", "whatsapp_e164": "+2348012345678", "phone_display": "+2348012345678", "instagram": "mamaput"}
        assert c["hero"]["headline"] == "Home cooked food, delivered"
        assert c["hero"]["subhead"] == "Fresh every morning in Lekki."
        assert c["hero"]["image_asset_id"] == "asset:img/hero.jpg"
        assert [i["name"] for i in c["items"]] == ["Jollof Rice", "Egusi Soup", "Suya"]
        assert [i["price_ngn"] for i in c["items"]] == [2500.0, 3000.0, 1500.0]
        assert c["hours"] == [{"days": "Mon-Fri", "time": "8am - 6pm"}, {"days": "Sat", "time": "9am - 4pm"}]
        assert c["location"] == {"address": "12 Admiralty Way, Lekki"}
        assert c["hero"]["image_asset_id"] == "asset:img/hero.jpg"
        assert [i["image_asset_id"] for i in c["items"]] == ["asset:img/jollof.jpg", "asset:img/egusi.jpg", "asset:img/suya.jpg"]

    def test_content_is_valid_site_content(self):
        c = go()["content"]
        SiteContentV1.model_validate(c)

    def test_other_blocks_removed_and_markers_written(self):
        sk = go()["skeleton"]
        assert sk.count('class="card"') == 1 and 'data-repeat="items"' in sk and 'data-slot="business.name"' in sk
        assert 'data-slot-href="whatsapp"' in sk and 'data-format="naira"' in sk and "Egusi" not in sk

    def test_scripts_styles_and_comments_are_untouched(self):
        sk = go()["skeleton"]
        for piece in ("<script>var a=1;if(a<2&&a>0){console.log('x < y && \"z\"');}</script>", "<script src=\"js/app.js\"></script>",
                      "<style>.card>h3{color:red}</style>", "<!-- top bar -->", "onclick=\"document.body.classList.toggle('open')\""):
            assert piece in sk

    def test_fill_with_extracted_content_rebuilds_the_original(self):
        r = go()
        filled = sl.fill(r["skeleton"], r["content"], assets_for(r), export=False)
        assert sl.compare(PAGE, filled) == []
        assert "https://cdn/img/egusi.jpg" in filled and "https://cdn/img/suya.jpg" in filled     # every card keeps its own picture
        assert "data-slot" not in filled and "data-repeat" not in filled
        assert "<script>var a=1;if(a<2&&a>0){console.log('x < y && \"z\"');}</script>" in filled

    def test_editing_content_changes_the_page(self):
        r = go()
        c = r["content"]
        c["business"]["name"] = "Mama Put Express"
        c["items"].append({"name": "Pepper Soup", "desc": "Hot.", "price_ngn": 2000, "price_style": "exact"})
        c["items"][0]["price_ngn"] = 2800
        filled = sl.fill(r["skeleton"], c, {}, False)
        assert "Mama Put Express" in filled and "Pepper Soup" in filled and "₦2,800" in filled and filled.count('class="card"') == 4

    def test_empty_optional_field_drops_the_element(self):
        r = go()
        c = r["content"]
        c["items"][1]["desc"] = ""
        filled = sl.fill(r["skeleton"], c, {}, False)
        assert "With pounded yam" not in filled and "Smoky party jollof" in filled

    def test_whatsapp_number_edit_updates_every_link(self):
        r = go()
        c = r["content"]
        c["business"]["whatsapp_e164"] = "+2348099999999"
        filled = sl.fill(r["skeleton"], c, assets_for(r), False)
        assert filled.count("wa.me/2348099999999") == 4 and "wa.me/2348012345678" not in filled

    def test_image_keeps_original_until_a_photo_is_chosen(self):
        r = sl.apply_plan(PAGE, build_plan())            # no asset_for: the pictures are not registered as photos
        assert r["errors"] and "differ but could not be registered" in r["errors"][0]
        r = go()
        c = {**r["content"], "hero": {**r["content"]["hero"], "image_asset_id": None}}
        assert 'src="img/hero.jpg"' in sl.fill(r["skeleton"], c, {}, False)
        c = {**r["content"], "hero": {**r["content"]["hero"], "image_asset_id": "a1"}}
        filled = sl.fill(r["skeleton"], c, {"a1": {"public_url": "https://x/p.jpg", "export_path": "images/hero.jpg"}}, False)
        assert 'src="https://x/p.jpg"' in filled and "img/hero.jpg" not in filled
        assert 'src="images/hero.jpg"' in sl.fill(r["skeleton"], c, {"a1": {"public_url": "https://x/p.jpg", "export_path": "images/hero.jpg"}}, True)

    def test_user_text_is_escaped(self):
        r = go()
        c = r["content"]
        c["business"]["name"] = "<script>alert(1)</script> & Co"
        filled = sl.fill(r["skeleton"], c, {}, False)
        assert "<script>alert(1)</script>" not in filled and "&lt;script&gt;" in filled and "&amp; Co" in filled

    def test_page_already_marked_is_refused(self):
        r = sl.apply_plan(PAGE.replace("<h1", '<h1 data-slot="x"'), build_plan())
        assert any("already contains" in e for e in r["errors"])

    def test_no_whatsapp_link_refused_with_reason(self):
        plan = build_plan()
        plan["links"] = [l for l in plan["links"] if l["kind"] != "whatsapp"]
        plan["repeats"][0]["links"] = []
        r = sl.apply_plan(PAGE, plan)
        assert any("no WhatsApp link" in e for e in r["errors"])


class TestPlanErrors:
    def errs(self, mutate, html=PAGE):
        plan = build_plan(html)
        mutate(plan)
        return sl.apply_plan(html, plan, asset_for=asset_for)["errors"]

    def test_unknown_element(self):
        assert any("does not exist" in e for e in self.errs(lambda p: p["slots"].append({"el": "e9999", "path": "business.city"})))

    def test_text_slot_on_element_with_children_is_refused(self):
        root = dom.parse(PAGE); ix = dom.assign_ids(root)
        hero = next(e for e in ix.values() if e.attrs.get("class") == "hero")
        assert any("would lose them" in e for e in self.errs(lambda p: p["slots"].append({"el": hero.id, "path": "about.title"})))

    def test_script_element_is_not_page_content(self):
        root = dom.parse(PAGE); ix = dom.assign_ids(root)
        sc = next(e for e in ix.values() if e.tag == "script")
        assert any("not page content" in e for e in self.errs(lambda p: p["slots"].append({"el": sc.id, "path": "about.title"})))

    def test_element_used_twice(self):
        e = build_plan()["slots"][0]["el"]
        assert any("more than one slot" in x for x in self.errs(lambda p: p["slots"].append({"el": e, "path": "business.city"})))

    def test_bad_path(self):
        root = dom.parse(PAGE); ix = dom.assign_ids(root)
        e = ids_by_text(root, ix, "Our menu")
        assert any("not a valid content path" in x for x in self.errs(lambda p: p["slots"].append({"el": e, "path": "Bad Path!"})))

    def test_slot_inside_repeat_must_be_listed_under_the_repeat(self):
        root = dom.parse(PAGE); ix = dom.assign_ids(root)
        h3 = ids_by_text(root, ix, "Egusi Soup")
        assert any("inside a repeated block" in e for e in self.errs(lambda p: p["slots"].append({"el": h3, "path": "business.city"})))

    def test_price_that_cannot_be_reproduced(self):
        html = PAGE.replace("₦3,000", "N3000")
        assert any("not written like" in e for e in self.errs(lambda p: None, html))

    def test_blocks_that_differ_without_a_slot(self):
        html = PAGE.replace("<h3>Suya</h3>", "<h4>Suya</h4>")
        assert any("<h4>" in e for e in self.errs(lambda p: None, html))

    def test_block_with_a_different_class_without_a_slot(self):
        html = PAGE.replace('<div class="card"><img src="img/suya.jpg"', '<div class="card" data-x="1"><img src="img/suya.jpg"')
        assert any("differs" in e and "data-x" in e for e in self.errs(lambda p: None, html))

    def test_card_with_an_extra_element(self):
        html = PAGE.replace('<span class="price">₦1,500</span>', '<span class="price">₦1,500</span><em>New</em>')
        assert any("extra <em>" in e for e in self.errs(lambda p: None, html))

    def test_unslotted_text_that_differs_between_blocks(self):
        html = PAGE.replace("Smoky party jollof.", "Smoky party jollof.</p><p class=x>").replace("<p class=x>Smoky", "Smoky")
        plan = build_plan()
        plan["repeats"][0]["slots"] = [s for s in plan["repeats"][0]["slots"] if s["path"] != "desc"]
        errs = sl.apply_plan(PAGE, plan, asset_for=asset_for)["errors"]
        assert any("text of" in e and "no slot" in e for e in errs)

    def test_alt_text_follows_each_card(self):
        html = PAGE.replace('alt="Jollof"', 'alt="Jollof Rice"').replace('alt="Egusi"', 'alt="Egusi Soup"').replace('alt="Suya"', 'alt="Suya"')
        r = go(html)
        c = r["content"]
        c["items"][1]["name"] = "Efo Riro"
        filled = sl.fill(r["skeleton"], c, assets_for(r), False)
        assert 'alt="Efo Riro"' in filled and 'alt="Egusi Soup"' not in filled

    def test_alt_text_that_matches_nothing_falls_back_to_the_name_with_a_warning(self):
        r = go()
        assert any("alt texts differ" in w for w in r["warnings"]) and 'data-slot-alt="name"' in r["skeleton"]

    def test_alt_texts_that_differ_with_no_name_slot_are_refused(self):
        def no_name(p):
            p["repeats"][0]["slots"] = [s for s in p["repeats"][0]["slots"] if s["path"] != "name"]
        assert any("alt texts" in e for e in self.errs(no_name, PAGE.replace("Egusi Soup", "Soup").replace("Jollof Rice", "Rice")))

    def test_whatsapp_numbers_must_agree(self):
        html = PAGE.replace("2348012345678?text=Suya", "2348055555555?text=Suya")
        assert any("different numbers" in e for e in self.errs(lambda p: None, html))

    def test_tel_link_must_be_international(self):
        html = PAGE.replace("tel:+2348012345678", "tel:08012345678")
        assert any("tel:+countrycode" in e for e in self.errs(lambda p: None, html))

    def test_repeat_blocks_must_be_siblings(self):
        plan = build_plan()
        root = dom.parse(PAGE); ix = dom.assign_ids(root)
        li = next(e for e in ix.values() if e.tag == "li")
        plan["repeats"][0]["instances"][1] = li.id
        assert any("siblings" in e for e in sl.apply_plan(PAGE, plan)["errors"])

    def test_plan_not_an_object(self):
        assert sl.apply_plan(PAGE, [1, 2])["errors"]

    def test_missing_optional_element_in_one_block_is_allowed(self):
        html = PAGE.replace('<p>With pounded yam.</p>', "")
        r = go(html)
        assert r["errors"] == [], r["errors"]
        assert r["content"]["items"][1].get("desc") in (None, "")
        assert r["content"]["items"][1]["name"] == "Egusi Soup" and r["content"]["items"][1]["price_ngn"] == 3000.0
        assert sl.compare(html, sl.fill(r["skeleton"], r["content"], assets_for(r), False)) == []


class TestCompare:
    def test_detects_changed_text(self):
        r = go()
        r["content"]["business"]["name"] = "Other"
        assert sl.compare(PAGE, sl.fill(r["skeleton"], r["content"], assets_for(r), False))

    def test_detects_script_change(self):
        r = go()
        filled = sl.fill(r["skeleton"], r["content"], assets_for(r), False).replace("var a=1;", "var a=2;")
        assert sl.compare(PAGE, filled)

    def test_ignores_whitespace_and_comments(self):
        assert sl.compare("<p> a  b </p><!--x-->", "<p>a b</p>") == []


def test_used_top_level():
    r = go()
    from app.services import site_premium_slots as ps
    manifest, errors = ps.analyse(r["skeleton"], r["content"])
    assert not [e for e in errors if "Required slot missing" not in e and "Required: a WhatsApp" not in e]
    assert {"business", "hero", "items", "hours", "location"} <= set(sl.used_top_level(manifest["slots"]))
