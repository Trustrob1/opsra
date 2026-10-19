"""
app/services/plan_gate_service.py
---------------------------------
ACCOUNT-PLANS AP-5: the ONE small door every automation and screen uses to ask "does this business's plan include X?"

  allowed(db, org_id, key)        True/False for a feature key from site_feature_registry
  use(db, org_id, key, n=1)       take n units from the feature's monthly allowance (True = go ahead)

Rules (all inherited from account_entitlement_service)
  * A business that has not been switched on (organisations.plans_enforced false) gets True and nothing is counted.
  * A switched-on business with no live plan, or whose plan lacks the feature, gets False.
  * If the check itself breaks, a live business keeps working (True) and the problem is logged.
  * Opsra's own billing, payment confirmations and anything already paid for never call this.
"""
from __future__ import annotations

import logging

from app.services import account_entitlement_service as acc

logger = logging.getLogger(__name__)

PLAN_MESSAGE = "Your plan doesn't include this. Open Billing to see the plans."
PLAN_CODE = "PLAN_REQUIRED"


def allowed(db, org_id, key: str) -> bool:
    try:
        return bool(acc.has_feature(db, key, org_id=org_id))
    except Exception as exc:
        logger.warning("plan_gate: check failed org=%s key=%s - allowing: %s", org_id, key, exc)
        return True


def use(db, org_id, key: str, n: int = 1) -> bool:
    try:
        return bool(acc.consume(db, key, org_id=org_id, n=n))
    except Exception as exc:
        logger.warning("plan_gate: allowance failed org=%s key=%s - allowing: %s", org_id, key, exc)
        return True


def http_error():
    """The 403 a screen or API call gets when the plan lacks the feature."""
    from fastapi import HTTPException, status
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": PLAN_CODE, "message": PLAN_MESSAGE})


def require(key: str):
    """FastAPI dependency for a whole router: every call needs `key` in the caller's plan, else 403 PLAN_REQUIRED.
    Usage: router = APIRouter(dependencies=[Depends(plan_gate_service.require("team_tasks"))])"""
    from fastapi import Depends
    from app.database import get_supabase
    from app.dependencies import get_current_org

    async def _check(org: dict = Depends(get_current_org), db=Depends(get_supabase)) -> None:
        org_id = (org or {}).get("org_id")
        if org_id and not allowed(db, org_id, key):
            raise http_error()

    return _check


def check_can_add_user(db, org_id) -> None:
    """Adding a second active user needs multi_rep_inbox in the plan, and the plan's `reps` allowance (when it sets one)
    caps the total. Not switched on = no limit. If the check itself breaks the owner can still add people."""
    from fastapi import HTTPException, status
    try:
        if not acc.is_enforced(db, org_id):
            return
        rows = (db.table("users").select("id, email").eq("org_id", org_id).eq("is_active", True).execute().data) or []
        n = len([r for r in rows if not (r.get("email") or "").endswith("@system.opsra.internal")])
        limit = None
        if not acc.has_feature(db, "multi_rep_inbox", org_id=org_id):
            limit = 1
        else:
            cap = int((acc.get_entitlements(db, org_id).get("caps") or {}).get("reps") or 0)
            if cap > 0:
                limit = cap
        if limit is not None and n >= limit:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
                "code": PLAN_CODE,
                "message": f"Your plan allows {limit} user{'s' if limit != 1 else ''}. Open Billing to see the plans."})
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("plan_gate: user-limit check failed org=%s - allowing: %s", org_id, exc)


def tell_managers(db, org_id, title: str, body: str, kind: str = "plan_limit") -> None:
    """In-app note to the owners and managers. Never raises."""
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, kind, None)
    except Exception as exc:
        logger.warning("plan_gate: tell_managers failed org=%s: %s", org_id, exc)
