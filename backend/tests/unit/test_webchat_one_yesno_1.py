"""ONE-YESNO-1: the consent question shows one Yes / No pair (the server's), not a second pair in the dock."""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")


def test_no_second_yes_no_pair_in_the_dock():
    assert "Yes, that is okay" not in SRC
    assert "No thanks</button>\n            </div>\n          )}\n" not in SRC.split("contactStep === 'consent'")[-1][:400]


def test_server_still_sends_the_yes_no_choices():
    t = (pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "webchat_contact_service.py").read_text(encoding="utf-8")
    assert t.count('choices=[{"id": "say", "label": "Yes"}, {"id": "say", "label": "No"}]') >= 3
