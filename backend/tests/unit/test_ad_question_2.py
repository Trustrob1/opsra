"""AD-Q-2: a real follow-up after the bot's catalogue answer gives the lead to the rep on shift."""
import pytest

from app.services import ad_question_service as adq

ORG, LEAD = "org-1", "lead-1"
NUM = {"org_id": ORG, "wa_sales_mode": "human"}


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self._rows = [r for r in self._rows if r.get(k) == v]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _DB:
    def __init__(self, leads, timeline):
        self.t = {"leads": leads, "lead_timeline": timeline}

    def table(self, name):
        return _Q(list(self.t.get(name, [])))


def _db(assigned=None, action="bot_catalog", ai_owned=False):
    leads = [{"id": LEAD, "org_id": ORG, "assigned_to": assigned, "ai_owned": ai_owned, "deleted_at": None}]
    tl = [{"org_id": ORG, "lead_id": LEAD, "event_type": "ad_question", "metadata": {"action": action}}] if action else []
    return _DB(leads, tl)


@pytest.fixture
def assigned(monkeypatch):
    calls = []
    import app.services.lead_assignment_service as las
    monkeypatch.setattr(las, "auto_assign_lead", lambda db, o, l, src, u: calls.append((o, l, src)) or "rep-9")
    import app.services.lead_service as ls
    monkeypatch.setattr(ls, "write_timeline_event", lambda *a, **k: None)
    return calls


@pytest.mark.parametrize("text", ["Are you in lagos", "Please is there a 3x6?", "6x6", "No smaller sizes?", "6/7"])
def test_real_questions_count(text):
    assert adq.is_real_follow_up("text", text) is True


@pytest.mark.parametrize("text", ["Ok", "Okay", "Alright thanks", "Good night", "Thank you!!", "Browse Catalog", "", "\U0001F44D"])
def test_small_talk_does_not_count(text):
    assert adq.is_real_follow_up("text", text) is False


def test_photo_and_voice_count_but_reactions_do_not():
    assert adq.is_real_follow_up("image", None) is True
    assert adq.is_real_follow_up("audio", None) is True
    assert adq.is_real_follow_up("reaction", None) is False


def test_real_follow_up_assigns_as_ready_to_buy(assigned):
    assert adq.follow_up(_db(), NUM, LEAD, "text", "Please is there a 3x6?") == "rep-9"
    assert assigned == [(ORG, LEAD, "ready_to_buy")]


def test_small_talk_leaves_it_alone(assigned):
    assert adq.follow_up(_db(), NUM, LEAD, "text", "Okay") is None
    assert assigned == []


def test_already_assigned_or_ai_owned_left_alone(assigned):
    assert adq.follow_up(_db(assigned="rep-1"), NUM, LEAD, "text", "6x6") is None
    assert adq.follow_up(_db(ai_owned=True), NUM, LEAD, "text", "6x6") is None
    assert assigned == []


def test_only_bot_catalog_leads(assigned):
    assert adq.follow_up(_db(action="rep"), NUM, LEAD, "text", "6x6") is None
    assert adq.follow_up(_db(action=None), NUM, LEAD, "text", "6x6") is None
    assert assigned == []


def test_ai_and_redirect_numbers_skipped(assigned):
    for mode in ("ai_agent", "webchat_redirect"):
        assert adq.follow_up(_db(), {"org_id": ORG, "wa_sales_mode": mode}, LEAD, "text", "6x6") is None
    assert adq.follow_up(_db(), NUM, None, "text", "6x6") is None
    assert assigned == []


def test_never_raises():
    assert adq.follow_up(None, NUM, LEAD, "text", "6x6") is None
