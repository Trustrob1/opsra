"""WEB-ONLY-1c-LOOK: the owner picks the chat look (classic, blue, midnight, ink). Unknown values fall back to classic, the visitor's page
receives it, new web chat only sign-ups start on blue, and an owner's earlier choice is never overwritten."""
from __future__ import annotations

import pytest

from app.services import webchat_service as wc
from tests.unit.test_webchat_3 import _cfg, _db  # noqa: F401


def test_existing_businesses_keep_the_classic_look():
    assert wc.DEFAULT_CONFIG["chat_theme"] == "classic"
    db = _db()
    assert wc.public_view(_cfg(db))["chat_theme"] == "classic"


@pytest.mark.parametrize("value,expected", [("blue", "blue"), ("midnight", "midnight"), ("ink", "ink"), ("classic", "classic"),
                                            ("neon", "classic"), ("", "classic"), (None, "classic"), (5, "classic"), ("BLUE", "classic")])
def test_the_choice_is_checked(value, expected):
    assert wc.sanitise_config({"chat_theme": value})["chat_theme"] == expected


def test_a_save_without_the_setting_leaves_it_alone():
    assert "chat_theme" not in wc.sanitise_config({"greeting": "Hi"})


def test_the_visitor_page_receives_the_look():
    db = _db()
    cfg = _cfg(db)
    cfg["chat_theme"] = "midnight"
    assert wc.public_view(cfg)["chat_theme"] == "midnight"
    cfg["chat_theme"] = "weird"
    assert wc.public_view(cfg)["chat_theme"] == "classic"


def test_the_list_of_looks_matches_the_front_end():
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    js = open(os.path.join(root, "frontend", "src", "utils", "webchatTheme.js"), encoding="utf-8").read()
    ids = re.search(r"THEME_IDS = \[([^\]]*)\]", js).group(1)
    assert tuple(x.strip(" '\"") for x in ids.split(",")) == wc.CHAT_THEMES


def test_new_signups_start_on_blue_but_a_chosen_look_is_kept():
    from app.services import chat_signup_service as svc
    from tests.unit.test_account_plans_1 import FakeDB
    org = "00000000-0000-0000-0000-00000000dd02"
    db = FakeDB(organisations=[{"id": org, "webchat_config": None}])
    svc._turn_on_ai(db, org)
    assert db.tables["organisations"][0]["webchat_config"]["chat_theme"] == "blue"
    db = FakeDB(organisations=[{"id": org, "webchat_config": {"chat_theme": "midnight"}}])
    svc._turn_on_ai(db, org)
    assert db.tables["organisations"][0]["webchat_config"]["chat_theme"] == "midnight"          # never overwritten
