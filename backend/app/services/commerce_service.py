"""
COMM-1 — Commerce Service
Handles cart, session lifecycle, and checkout state for WhatsApp commerce.
Aligned with existing commerce_sessions schema.
"""

from typing import List, Dict


# ---------------------------------------------------------------------------
# Get or Create Active Session
# ---------------------------------------------------------------------------

def get_or_create_session(db, org_id: str, phone_number: str) -> Dict:
    existing = (
        db.table("commerce_sessions")
        .select("*")
        .eq("org_id", org_id)
        .eq("phone_number", phone_number)
        .in_("status", ["browsing", "checkout_initiated"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    data = existing.data if isinstance(existing.data, list) else []
    if data:
        return data[0]

    new_session = {
        "org_id": org_id,
        "phone_number": phone_number,
        "status": "browsing",
        "cart": [],
        "last_activity_at": "now()",
        "updated_at": "now()",
    }

    result = db.table("commerce_sessions").insert(new_session).execute()
    return result.data[0]


# ---------------------------------------------------------------------------
# Add to Cart
# ---------------------------------------------------------------------------

def add_to_cart(
    db,
    session: Dict,
    product: Dict,
    variant_id: str,
    quantity: int = 1
) -> List[Dict]:
    cart = session.get("cart") or []

    found = False
    for item in cart:
        if item["variant_id"] == variant_id:
            item["quantity"] += quantity
            found = True
            break

    if not found:
        cart.append({
            "product_id": product.get("id"),
            "variant_id": variant_id,
            "name": product.get("name"),
            "price": product.get("price"),
            "quantity": quantity,
        })

    db.table("commerce_sessions").update({
        "cart": cart,
        "last_activity_at": "now()",
        "updated_at": "now()",
    }).eq("id", session["id"]).execute()

    return cart


# ---------------------------------------------------------------------------
# Remove from Cart
# ---------------------------------------------------------------------------

def remove_from_cart(db, session: Dict, variant_id: str) -> List[Dict]:
    cart = session.get("cart") or []

    new_cart = [item for item in cart if item["variant_id"] != variant_id]

    db.table("commerce_sessions").update({
        "cart": new_cart,
        "last_activity_at": "now()",
        "updated_at": "now()",
    }).eq("id", session["id"]).execute()

    return new_cart


# ---------------------------------------------------------------------------
# Get Cart Summary (WhatsApp-friendly)
# ---------------------------------------------------------------------------

def get_cart_summary(session: Dict) -> str:
    cart = session.get("cart") or []

    if not cart:
        return "🛒 Your cart is empty."

    lines = ["🛒 Your Cart:\n"]
    total = 0

    for i, item in enumerate(cart, start=1):
        line_total = item["price"] * item["quantity"]
        total += line_total

        lines.append(
            f"{i}. {item['name']} ×{item['quantity']} — ₦{line_total:,}"
        )

    lines.append(f"\nTotal: ₦{total:,}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mark Checkout Initiated
# ---------------------------------------------------------------------------

def mark_checkout_initiated(
    db,
    session_id: str,
    checkout_id: str,
    checkout_url: str
) -> None:
    db.table("commerce_sessions").update({
        "status": "checkout_initiated",
        "shopify_checkout_id": checkout_id,
        "checkout_url": checkout_url,
        "last_activity_at": "now()",
        "updated_at": "now()",
    }).eq("id", session_id).execute()


# ---------------------------------------------------------------------------
# Mark Session Completed
# ---------------------------------------------------------------------------

def mark_session_completed(
    db,
    session_id: str,
    shopify_order_id: int
) -> None:
    db.table("commerce_sessions").update({
        "status": "completed",
        "shopify_order_id": shopify_order_id,
        "completed_at": "now()",
        "updated_at": "now()",
    }).eq("id", session_id).execute()


# ---------------------------------------------------------------------------
# Mark Session Abandoned
# ---------------------------------------------------------------------------

def mark_session_abandoned(db, session_id: str) -> None:
    db.table("commerce_sessions").update({
        "status": "abandoned",
        "abandoned_at": "now()",
        "updated_at": "now()",
    }).eq("id", session_id).execute()


def extract_variant(product: dict):
    """
    Extract first/default variant from product JSON.
    Assumes Shopify sync structure.
    """
    variants = product.get("variants") or []

    if not variants:
        return None

    variant = variants[0]

    return {
        "variant_id": variant.get("id"),
        "price": float(variant.get("price") or product.get("price") or 0),
        "name": f"{product.get('title')} ({variant.get('title')})"
    }