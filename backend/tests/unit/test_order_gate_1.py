"""ORDER-GATE-1: only leads that are ready to buy are given to a rep."""
from app.services import order_request_service as ors
from app.services import lead_assignment_service as las


class _R:
    def __init__(self, d): self.data = d


class _Q:
    def __init__(self, d): self.d = d
    def __getattr__(self, n): return lambda *a, **k: self
    def execute(self): return _R(self.d)


class _DB:
    def __init__(self, d): self.d = d
    def table(self, n): return _Q(self.d)


def test_tag_is_stripped_and_detected():
    txt, tag = ors.parse_order_tag("Hi, I'm interested in the Dual Faced Mattress [ord:dual-faced]")
    assert txt == "Hi, I'm interested in the Dual Faced Mattress" and tag == "dual-faced"
    assert ors.parse_order_tag("Hello") == ("Hello", None)
    assert ors.parse_order_tag(None) == ("", None)


def test_product_name_from_message():
    assert ors._product_from_text("Hi, I'm interested in the King size Luxury Hybrid") == "King size Luxury Hybrid"
    assert ors._product_from_text("") == "a product"


def test_gate_flag():
    assert ors.gate_on(_DB([{"assign_on_order": True}]), "o") is True
    assert ors.gate_on(_DB([{"assign_on_order": False}]), "o") is False
    assert ors.gate_on(_DB([]), "o") is False
    assert ors.gate_on(_DB([]), None) is False


def test_enquiry_not_assigned_but_order_is(monkeypatch):
    org = {"lead_assignment_mode": "auto", "timezone": "Africa/Lagos", "assign_on_order": True}
    assert las.auto_assign_lead(_DB(org), "o", "l", "whatsapp_inbound", None) is None


def test_late_notice_goes_to_managers_only():
    sent = []

    class DB(_DB):
        def table(self, n):
            if n == "notifications":
                return type("N", (), {"insert": lambda s, row: type("E", (), {"execute": lambda s2: sent.append(row)})()})()
            return _Q([{"id": "u1", "roles": {"template": "owner"}}, {"id": "u2", "roles": [{"template": "sales_agent"}]},
                       {"id": "u3", "roles": {"template": "ops_manager"}}])
    assert ors.notify_managers(DB([]), "o", "l", "X") == 2
    assert {r["user_id"] for r in sent} == {"u1", "u3"}
