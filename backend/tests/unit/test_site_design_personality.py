"""
tests/unit/test_site_design_personality.py
SITE-1C-2 — personality question, layout-aware anti-sameness picker, shortlist, fingerprint, AI choice.
"""
from __future__ import annotations

import pytest

from app.services import site_copy_service, site_design_registry as reg, site_design_service as svc, site_renderer

PRESET = {
    "key": "boutique", "sections": ["hero", "about", "items", "reviews", "order"],
    "allowed_themes": ["atelier", "market", "studio"],
    "default_palettes": ["berry", "cobalt", "sage", "terracotta", "midnight", "gold", "blush", "plum"],
    "allowed_fonts": [], "token_options": {}, "allowed_variants": {},
}
RICH = {"photos": 6, "items": 6, "reviews": 3}


# ---- registry ----------------------------------------------------------------

def test_personality_answers_map_by_label_or_key():
    for key, meta in reg.PERSONALITIES.items():
        assert reg.personality_from_answer(meta["label"]) == key
        assert reg.personality_from_answer(key.upper()) == key
    assert reg.personality_from_answer(None) is None
    assert reg.personality_from_answer("") is None
    assert reg.personality_from_answer("nonsense") is None


def test_personality_preferences_only_name_real_options():
    for key, p in reg.PERSONALITIES.items():
        assert set(p["themes"]) <= set(site_renderer.THEMES), key
        assert set(p["font_groups"]) <= set(reg.FONT_GROUPS), key
        for tok, prefs in p["tokens"].items():
            assert set(prefs) <= set(reg.TOKENS[tok]), (key, tok)
        for sec, prefs in p["variants"].items():
            assert set(prefs) <= set(reg.SECTION_VARIANTS[sec]), (key, sec)


def test_every_palette_personality_tag_is_a_known_personality():
    for k, m in reg.PALETTE_META.items():
        assert set(m["personality"]) <= set(reg.PERSONALITIES), k


def test_question_is_added_once_before_photos_and_never_duplicated():
    qs = [{"key": "business_name", "type": "text"}, {"key": "photos", "type": "photos"}]
    out = reg.with_personality_question(qs)
    assert [q["key"] for q in out] == ["business_name", "personality", "photos"]
    assert reg.with_personality_question(out) == out
    assert reg.with_personality_question(None)[0]["key"] == "personality"
    q = reg.personality_question()
    assert q["type"] == "choice" and q["required"] is False and q["skip_ok"] is True
    assert len(q["choices"]) == len(reg.PERSONALITIES)


def test_a_template_with_its_own_personality_question_is_left_alone():
    own = [{"key": "personality", "type": "choice", "choices": ["A", "B"]}]
    assert reg.with_personality_question(own) == own


def test_allowed_variants_default_all_and_narrow():
    assert reg.allowed_variants({}, "hero") == list(reg.SECTION_VARIANTS["hero"])
    assert reg.allowed_variants({"allowed_variants": {"hero": ["centered"]}}, "hero") == ["centered"]
    assert reg.allowed_variants({"allowed_variants": {"hero": ["bogus"]}}, "hero") == list(reg.SECTION_VARIANTS["hero"])


def test_validate_preset_allowed_variants():
    reg.validate_preset_design_fields([], {}, [], {"hero": ["centered", "collage"]})
    with pytest.raises(ValueError):
        reg.validate_preset_design_fields([], {}, [], {"nope": ["x"]})
    with pytest.raises(ValueError):
        reg.validate_preset_design_fields([], {}, [], {"hero": ["nope"]})
    with pytest.raises(ValueError):
        reg.validate_preset_design_fields([], {}, [], ["hero"])


def test_renderer_uses_the_registry_layout_list():
    assert site_renderer.SECTION_VARIANTS is reg.SECTION_VARIANTS


def test_recipe_variant_outside_preset_allowance_is_rejected():
    preset = {**PRESET, "allowed_variants": {"hero": ["centered"]}}
    recipe = svc.first_choice_recipe(preset)
    recipe["variants"] = {"hero": "collage"}
    with pytest.raises(ValueError):
        site_renderer.validate_recipe(preset, recipe)
    recipe["variants"] = {"hero": "centered"}
    site_renderer.validate_recipe(preset, recipe)


# ---- picker ------------------------------------------------------------------

def test_pick_is_valid_stable_and_sets_layouts():
    for i in range(40):
        r = svc.pick_recipe(PRESET, f"site-{i}", None, "bold", None, RICH)
        site_renderer.validate_recipe(PRESET, r)
        assert set(r["variants"]) == {"hero", "items", "about", "reviews"}
        assert r == svc.pick_recipe(PRESET, f"site-{i}", None, "bold", None, RICH)


def test_picker_respects_allowed_layouts_and_content():
    preset = {**PRESET, "allowed_variants": {"hero": ["centered"], "items": ["rows"]}}
    for i in range(30):
        r = svc.pick_recipe(preset, f"s{i}", None, "playful", None, RICH)
        assert r["variants"]["hero"] == "centered" and r["variants"]["items"] == "rows"
    bare = {"photos": 0, "items": 1, "reviews": 0}
    for i in range(60):
        v = svc.pick_recipe(PRESET, f"b{i}", None, "elegant", None, bare)["variants"]
        assert v["hero"] != "collage" and v["items"] != "featured" and v["about"] == "quote" and v["reviews"] != "spotlight"


def test_personality_steers_the_look():
    def share(personality, pred, n=150):
        return sum(pred(svc.pick_recipe(PRESET, f"x{i}", None, personality, None, RICH)) for i in range(n)) / n
    assert share("bold", lambda r: r["theme"] == "market") > share("minimal", lambda r: r["theme"] == "market") + 0.3
    assert share("minimal", lambda r: r["theme"] == "studio") > share("bold", lambda r: r["theme"] == "studio") + 0.3
    assert share("elegant", lambda r: r["tokens"]["divider"] in ("ornament", "line")) > share("playful", lambda r: r["tokens"]["divider"] in ("ornament", "line"))


def test_no_personality_still_varies():
    looks = {svc.fingerprint(svc.pick_recipe(PRESET, f"n{i}", None, None, None, RICH)) for i in range(60)}
    assert len(looks) > 40


def test_named_colour_answer_is_kept():
    r = svc.pick_recipe(PRESET, "c1", "#1A7F5A", "warm", None, RICH)
    assert r["custom_colour"] == "#1A7F5A" and r["palette"] is None
    assert svc.pick_recipe(PRESET, "c2", "Sage", None, None, RICH)["palette"] == "sage"


def test_shortlist_is_distinct_valid_and_first_is_the_pick():
    short = svc.design_shortlist(PRESET, "abc", None, "warm", None, RICH)
    assert 2 <= len(short) <= svc.SHORTLIST_SIZE
    assert len({svc.fingerprint(r) for r in short}) == len(short)
    for r in short:
        site_renderer.validate_recipe(PRESET, r)
    assert svc.pick_recipe(PRESET, "abc", None, "warm", None, RICH) == short[0]
    assert svc.pick_recipe(PRESET, "abc", None, "warm", None, RICH, choice=2) == short[2]
    assert svc.pick_recipe(PRESET, "abc", None, "warm", None, RICH, choice=99) == short[0]


def test_avoids_recent_looks():
    base = svc.pick_recipe(PRESET, "same-seed", None, "bold", None, RICH)
    again = svc.pick_recipe(PRESET, "same-seed", None, "bold", [base], RICH)
    assert svc.fingerprint(again) != svc.fingerprint(base)
    assert svc.distance(again, base) >= 1
    # a recent list of many looks: the pick is still not an exact repeat of any of them
    recents = [svc.pick_recipe(PRESET, f"r{i}", None, "bold", None, RICH) for i in range(12)]
    got = svc.pick_recipe(PRESET, "fresh", None, "bold", recents, RICH)
    assert svc.fingerprint(got) not in {svc.fingerprint(r) for r in recents}


def test_exhausted_pool_still_returns_a_valid_recipe():
    tiny = {**PRESET, "allowed_themes": ["studio"], "default_palettes": ["berry"], "allowed_fonts": ["fraunces_karla"],
            "token_options": {k: [reg.TOKENS[k][0]] for k in reg.TOKENS},
            "allowed_variants": {"hero": ["centered"], "items": ["grid"], "about": ["quote"], "reviews": ["list"]}}
    only = svc.pick_recipe(tiny, "t1", None, "warm", None, RICH)
    site_renderer.validate_recipe(tiny, only)
    again = svc.pick_recipe(tiny, "t2", None, "warm", [only], RICH)   # every candidate is a repeat
    site_renderer.validate_recipe(tiny, again)


def test_fingerprint_ignores_hidden_and_is_stable():
    r = svc.pick_recipe(PRESET, "fp", None, None, None, RICH)
    assert svc.fingerprint(r) == svc.fingerprint({**r, "hidden": ["about"]})
    assert svc.fingerprint(r) != svc.fingerprint({**r, "tokens": {**r["tokens"], "radius": "pill" if r["tokens"]["radius"] != "pill" else "sharp"}})


