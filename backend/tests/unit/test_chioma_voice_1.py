"""CHIOMA-VOICE-1: Chioma greets like a person in the shop, for any business (its own name, time of day, what visitors come for)."""
from app.services import webchat_service as wc

OLD = "Hi, I'm Chioma. I can answer your questions, share prices and help you order or book. Pick an option below, or type your question."


def test_hello_word_by_hour():
    assert [wc.hello_word(h) for h in (4, 5, 11, 12, 16, 17, 23, 0)] == [
        "Hello", "Good morning", "Good morning", "Good afternoon", "Good afternoon", "Good evening", "Good evening", "Hello"]


def test_default_greeting_fills_in_for_any_business():
    cfg = {"greeting": wc.DEFAULT_CONFIG["greeting"], "business_name": "Glow Salon"}
    out = wc.fill_greeting(cfg["greeting"], cfg, hour=10)
    assert out.startswith("Good morning, welcome to Glow Salon! I'm Chioma")
    assert "{" not in out and "virtual assistant" not in out


def test_owner_text_without_placeholders_is_left_alone():
    cfg = {"business_name": "X"}
    assert wc.fill_greeting("Hi there, how can we help?", cfg, hour=9) == "Hi there, how can we help?"
    assert wc.fill_greeting("{hello}! Welcome to {business}.", cfg, hour=19) == "Good evening! Welcome to X."


def test_greeting_for_uses_business_timezone_and_campaigns():
    cfg = {"greeting": "{hello} from {business}", "business_name": "Royal Rest", "_call_org": {"timezone": "Africa/Lagos"}, "campaigns": []}
    out = wc.greeting_for(cfg)
    assert out.endswith("from Royal Rest") and out.split(" from")[0] in ("Good morning", "Good afternoon", "Good evening", "Hello")
    cfg["_call_org"]["timezone"] = "Not/AZone"
    assert "{hello}" not in wc.greeting_for(cfg)


def test_old_defaults_are_upgraded_but_custom_text_kept():
    assert wc._LEGACY_TEXT["greeting"][OLD] == wc.DEFAULT_CONFIG["greeting"]
    assert wc._LEGACY_TEXT["ask_bar_text"]["Ask me anything…"] == "Type your question…"
    assert wc.DEFAULT_CONFIG["ask_bar_text"] == "Type your question…"


def test_visitor_goal_is_saved_and_capped():
    assert wc.sanitise_config({"visitor_goal": "  a new   mattress "})["visitor_goal"] == "a new mattress"
    assert len(wc.sanitise_config({"visitor_goal": "x" * 200})["visitor_goal"]) <= wc.VISITOR_GOAL_MAX
    assert wc.DEFAULT_CONFIG["visitor_goal"] == ""
