"""BOOKING-ALLOWANCE-1: bookings past the plan allowance cost credit; they are never blocked."""
from unittest.mock import patch, MagicMock

from app.services import booking_allowance_service as ba
from app.services import site_feature_registry as reg
from app.services import site_entitlement_service as ent

ORG = "11111111-1111-1111-1111-111111111111"


def _run(*, enforced=True, cap=100, used=1, metering=True, fee=10000, debit_ret=None):
    debit = MagicMock(return_value=debit_ret if debit_ret is not None else {"charged_kobo": fee})
    with patch.object(ba.acc, "is_enforced", return_value=enforced), \
         patch.object(ba.acc, "_compute", return_value={"caps": {"bookings": cap} if cap else {}}), \
         patch.object(ba, "_bump", return_value=used), \
         patch.object(ba.cs, "get_wallet", return_value={"metering_enabled": metering}), \
         patch.object(ba.cs, "find_fee_rule", return_value={"mode": "flat_kobo", "value": fee} if fee else None), \
         patch.object(ba.cs, "_debit", debit):
        return ba.record_booking(MagicMock(), ORG, "demo-1"), debit


def test_inside_allowance_is_free():
    out, debit = _run(used=100)
    assert out["counted"] and not out["over"] and out["charged_kobo"] == 0
    debit.assert_not_called()


def test_over_allowance_charges_the_fee_once_with_a_stable_ref():
    out, debit = _run(used=101)
    assert out["over"] and out["charged_kobo"] == 10000
    args = debit.call_args[0]
    assert args[2] == 10000 and args[3:5] == ("fee", "fee:booking:demo-1")


def test_not_enforced_does_nothing():
    out, debit = _run(enforced=False, used=500)
    assert not out["counted"]
    debit.assert_not_called()


def test_plan_without_allowance_does_nothing():
    out, debit = _run(cap=0, used=500)
    assert not out["counted"]
    debit.assert_not_called()


def test_no_charge_when_metering_off_or_no_fee_rule():
    assert _run(used=150, metering=False)[0]["charged_kobo"] == 0
    assert _run(used=150, fee=0)[0]["charged_kobo"] == 0


def test_failures_never_raise():
    with patch.object(ba.acc, "is_enforced", side_effect=RuntimeError("db down")):
        out = ba.record_booking(MagicMock(), ORG, "demo-1")
    assert out["counted"] is False


def test_bookings_is_a_known_monthly_cap_and_prices_accept_it():
    assert reg.CAPS["bookings"] == "monthly"
    ent.validate_pricing({"addons": {"booking": {"monthly_ngn": 25000, "caps": {"bookings": 100}}},
                          "tiers": {"grow": {"caps": {"bookings": 500}}}})
    cfg = ent.get_config({"pricing": {"addons": {"booking": {"monthly_ngn": 25000, "caps": {"bookings": 100}}}}})
    assert cfg["addons"]["booking"]["caps"] == {"bookings": 100}
    assert cfg["addons"]["booking"]["features"] == ["selling_booking"]
