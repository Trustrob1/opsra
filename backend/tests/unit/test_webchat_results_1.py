"""WEBCHAT-RESULTS-1: the Web chat page sits in the left menu right under Conversations, for managers only, and Admin links to it.
Source-level checks on the frontend wiring (no browser here)."""
from pathlib import Path

FE = Path(__file__).resolve().parents[3] / "frontend" / "src"
APP = (FE / "App.jsx").read_text(encoding="utf-8")
INS = (FE / "modules/admin/WebChatInsights.jsx").read_text(encoding="utf-8")
SET = (FE / "modules/admin/WebChatSettings.jsx").read_text(encoding="utf-8")


def test_nav_item_directly_after_conversations():
    i = APP.index("{ id: 'conversations'")
    j = APP.index("{ id: 'webchat'")
    k = APP.index("{ id: 'knowledge'")
    assert i < j < k
    assert "group: 'sales_marketing'" in APP[j:APP.index("\n", j)]


def test_only_managers_with_chat_on_see_it():
    line = next(l for l in APP.splitlines() if "item.id === 'webchat'" in l)
    assert "webchatOn" in line and "'owner', 'ops_manager', 'admin'" in line


def test_page_rendered_only_when_allowed():
    assert "view === 'webchat' && webchatOn" in APP
    assert "'webchat'].includes(view)" in APP  # known-views list, no ComingSoon


def test_admin_links_to_the_page():
    assert "opsra:goto" in INS and "detail: 'webchat'" in INS
    assert "opsra:goto" in APP


def test_admin_no_longer_holds_the_big_analytics_card():
    assert "saveWebchatSettings" not in INS
    assert "ads={cfg.campaigns}" not in SET
