"""TEMPLATE-BLOCK-1: blocked templates and paid marketing templates inside a free reply window."""
from app.services import credit_service as cs

ORG = "org-1"


class _Res:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, rows): self.rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self): return _Res(self.rows)


class _DB:
    def __init__(self, category="marketing", referral=False):
        self.category, self.referral = category, referral
    def table(self, name):
        if name == "whatsapp_templates":
            return _Q([{"category": self.category}])
        return _Q([{"id": "m1"}] if self.referral else [])


def _wallet(monkeypatch, **kw):
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: {"org_id": org, **kw})


def test_blocked_template_is_refused(monkeypatch):
    _wallet(monkeypatch, wa_blocked_templates=["post_sales"])
    assert cs.template_block_reason(_DB(), ORG, "post_sales")
    assert cs.template_block_reason(_DB(), ORG, "other") is None


def test_marketing_in_open_window_refused_only_when_rule_on(monkeypatch):
    _wallet(monkeypatch, wa_block_free_window_marketing=True)
    assert cs.template_block_reason(_DB(), ORG, "t", window_open=True)
    _wallet(monkeypatch, wa_block_free_window_marketing=False)
    assert cs.template_block_reason(_DB(), ORG, "t", window_open=True) is None


def test_marketing_after_ad_click_window_refused(monkeypatch):
    _wallet(monkeypatch, wa_block_free_window_marketing=True)
    assert cs.template_block_reason(_DB(referral=True), ORG, "t", window_open=False, lead_id="l1")
    assert cs.template_block_reason(_DB(referral=False), ORG, "t", window_open=False, lead_id="l1") is None


def test_utility_template_and_closed_window_allowed(monkeypatch):
    _wallet(monkeypatch, wa_block_free_window_marketing=True)
    assert cs.template_block_reason(_DB(category="utility"), ORG, "t", window_open=True) is None


def test_never_raises(monkeypatch):
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: (_ for _ in ()).throw(RuntimeError("x")))
    assert cs.template_block_reason(_DB(), ORG, "t") is None
