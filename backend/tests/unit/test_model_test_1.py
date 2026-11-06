"""MODEL-TEST-1: per-business test model for the sales agent, on a share of conversations."""
from app.services import credit_service as cs

D = "claude-sonnet-5"


def _w(monkeypatch, **kw):
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: {"org_id": org, **kw})


def test_default_when_not_set(monkeypatch):
    _w(monkeypatch)
    assert cs.ai_agent_model(None, "o", "k", D) == D


def test_full_share(monkeypatch):
    _w(monkeypatch, ai_agent_model="claude-haiku-5-5", ai_agent_model_pct=100)
    assert cs.ai_agent_model(None, "o", "k", D) == "claude-haiku-5-5"


def test_partial_share_is_stable_and_roughly_right(monkeypatch):
    _w(monkeypatch, ai_agent_model="claude-haiku-5-5", ai_agent_model_pct=30)
    got = [cs.ai_agent_model(None, "o", f"lead-{i}", D) for i in range(1000)]
    assert got == [cs.ai_agent_model(None, "o", f"lead-{i}", D) for i in range(1000)]
    share = got.count("claude-haiku-5-5") / 1000
    assert 0.2 < share < 0.4


def test_unknown_model_and_zero_pct_ignored(monkeypatch):
    _w(monkeypatch, ai_agent_model="gpt-9", ai_agent_model_pct=100)
    assert cs.ai_agent_model(None, "o", "k", D) == D
    _w(monkeypatch, ai_agent_model="claude-haiku-5-5", ai_agent_model_pct=0)
    assert cs.ai_agent_model(None, "o", "k", D) == D


def test_never_raises(monkeypatch):
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: (_ for _ in ()).throw(RuntimeError("x")))
    assert cs.ai_agent_model(None, "o", "k", D) == D
