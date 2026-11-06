"""AI-PILOT-1: a stable share of brand-new WhatsApp contacts goes to the AI rep; results are compared with the humans."""
from app.services import ai_pilot_service as p


class _R:
    def __init__(self, d): self.data = d


class _Q:
    def __init__(self, d): self.d = d
    def __getattr__(self, n): return lambda *a, **k: self
    def execute(self): return _R(self.d)


class _DB:
    def __init__(self, d): self.d = d
    def table(self, n): return _Q(self.d)


def test_share_is_stable_and_roughly_right():
    phones = [f"23480{i:08d}" for i in range(2000)]
    a = [p.in_sample(x, 25) for x in phones]
    assert a == [p.in_sample(x, 25) for x in phones]
    assert 0.20 < sum(a) / len(a) < 0.30
    assert not p.in_sample("234801", 0) and p.in_sample("234801", 100) and not p.in_sample("", 50)


def test_takes_new_contact_in_sample_only():
    row = {"ai_pilot_pct": 100}
    assert p.takes(None, row, "2348011111111", None, None)
    assert not p.takes(None, {"ai_pilot_pct": 0}, "2348011111111", None, None)
    assert not p.takes(None, row, "2348011111111", "cust-1", None)


def test_existing_lead_stays_with_ai_only_while_ai_owned():
    row = {"ai_pilot_pct": 10}
    assert p.takes(_DB([{"ai_pilot": True, "ai_owned": True}]), row, "x", None, "l1")
    assert not p.takes(_DB([{"ai_pilot": True, "ai_owned": False}]), row, "x", None, "l1")   # handed over
    assert not p.takes(_DB([{"ai_pilot": False, "ai_owned": False}]), row, "x", None, "l1")  # old human lead


def test_summary_counts_and_rates():
    rows = [{"stage": "converted", "deal_value": 100000, "first_contacted_at": "t", "response_time_minutes": 4},
            {"stage": "new", "first_contacted_at": None, "response_time_minutes": None},
            {"stage": "contacted", "first_contacted_at": "t", "response_time_minutes": 8},
            {"stage": "new"}]
    s = p._summ(rows)
    assert s["leads"] == 4 and s["converted"] == 1 and s["conversion_pct"] == 25.0
    assert s["contacted_pct"] == 50.0 and s["revenue_ngn"] == 100000 and s["avg_response_minutes"] == 6.0
    assert p._summ([])["conversion_pct"] == 0
