"""WEB-ONLY-1c-FALLBACK: the stock reply when Chioma cannot answer points to the menu and the team, and never says 'I did not catch that'."""
from __future__ import annotations

from app.services import webchat_service as wc

OLD_A = "I did not catch that. Pick one of the options below, or tap Talk to us."
OLD_B = "I did not catch that. Tap Menu at the top to see what we can help with, or type your question again."


class _Q:
    def __init__(self, row): self.row = row
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self): return type("R", (), {"data": [self.row]})


class _DB:
    def __init__(self, cfg): self.cfg = cfg
    def table(self, n): return _Q({"name": "Shop", "webchat_config": self.cfg})


def test_new_default_wording():
    t = wc.get_config(_DB({}), "o1")["fallback"]
    assert "did not catch" not in t and "unable to answer that at the moment" in t and "Menu" in t and "Talk to the team" in t


def test_both_old_defaults_are_upgraded():
    for old in (OLD_A, OLD_B):
        assert "unable to answer" in wc.get_config(_DB({"fallback": old}), "o1")["fallback"]


def test_a_business_own_wording_is_kept():
    assert wc.get_config(_DB({"fallback": "Sorry, say that again?"}), "o1")["fallback"] == "Sorry, say that again?"


def test_talk_to_the_team_matches_the_built_in_menu_label():
    labels = [m["label"] for m in wc.get_config(_DB({}), "o1")["menu"]]
    assert "Talk to the team" in labels
