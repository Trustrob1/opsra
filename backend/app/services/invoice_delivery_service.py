"""
app/services/invoice_delivery_service.py
----------------------------------------
INV-3 - getting an issued quote or invoice to the customer, and the customer's own page.

  Links        public_url(doc) -> <FRONTEND_URL>/i/<public_token>. The token (made at issue, 32 random characters) is the
               only key; it never reveals org, lead or document ids.
  Channels     options(db, org_id, doc)  which ways this document can go out right now (and why not).
               send(db, org_id, user_id, doc_id, channel, email=None)
                 whatsapp  the PDF as a document, then a short message with the link (inside the 24-hour window only:
                           outside it Meta needs an approved template, which costs the business money - not done here)
                 webchat   the PDF into the customer's open web chat, then the link
                 email     Resend, PDF attached, reply-to = the business; the "from" name is the business's name
               Sets sent_at the first time and writes an audit row for every send.
  Public page  public_view(db, token)   what /i/<token> shows (no internal ids; drafts are never shown)
               public_pdf(db, token)    the PDF
               public_answer(db, token, accepted)  the customer accepts or declines a quote. The team gets a task.
  Lead button  draft_for_lead(db, org_id, lead_id)  the WhatsApp "Get invoice" button makes a draft for the team to finish.

Problems the caller should see raise invoice_service.InvoiceError. Sends that fail at Meta / Resend raise InvoiceError
with a plain message; nothing here writes partial state before a send has gone out.
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import invoice_pdf_service as pdf
from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

CHANNELS = ("whatsapp", "webchat", "email")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[A-Za-z]{2,}$")
TITLE = {"quote": "Quote", "invoice": "Invoice"}


def _base_url() -> str:
    base = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    if not base:
        try:
            from app.config import settings
            base = (getattr(settings, "FRONTEND_URL", "") or "").strip().rstrip("/")
        except Exception:
            base = ""
    return base or "https://opsra.com.ng"


def public_url(doc: dict) -> Optional[str]:
    token = doc.get("public_token")
    return f"{_base_url()}/i/{token}" if token else None


def _business(doc: dict) -> str:
    name = ((doc.get("issuer") or {}).get("business_name") or "").strip()
    return name or "Your supplier"


def _naira(v) -> str:
    try:
        return f"₦{float(v or 0):,.2f}".replace(".00", "")
    except (TypeError, ValueError):
        return "₦0"


def _sendable(doc: dict) -> None:
    if doc.get("status") == "draft":
        raise inv.InvoiceError("INVALID_TRANSITION", "Issue the document before sending it.", 400)
    if doc.get("status") == "void":
        raise inv.InvoiceError("INVALID_TRANSITION", "This document is void and cannot be sent.", 400)
    if not doc.get("public_token"):
        raise inv.InvoiceError("INVALID_TRANSITION", "This document has no link yet. Issue it again.", 400)


def message_text(doc: dict) -> str:
    """The short note that goes with the PDF on WhatsApp / web chat."""
    first = (doc.get("customer_name") or "").split(" ")[0].strip()
    hello = f"Hello {first}, " if first else "Hello, "
    if doc.get("doc_type") == "quote":
        lines = [f"{hello}here is your quote {doc.get('number')} from {_business(doc)} for {_naira(doc.get('total'))}."]
        if doc.get("due_date"):
            lines.append(f"It is valid until {_nice(doc['due_date'])}.")
        lines.append(f"View it and accept it here: {public_url(doc)}")
    else:
        bal = doc.get("balance_due", doc.get("total"))
        lines = [f"{hello}here is your invoice {doc.get('number')} from {_business(doc)}. Amount due: {_naira(bal)}."]
        if doc.get("due_date"):
            lines.append(f"Due by {_nice(doc['due_date'])}.")
        lines.append(f"View it and see how to pay here: {public_url(doc)}")
    return " ".join(lines)


def _nice(d) -> str:
    try:
        x = datetime.fromisoformat(str(d)[:10])
        return f"{x.day} {x.strftime('%b %Y')}"
    except Exception:
        return str(d)


# ───────────────────────────── options ─────────────────────────────

def _lead_contact(db, org_id: str, lead_id: Optional[str]) -> Optional[dict]:
    if not lead_id:
        return None
    try:
        res = db.table("leads").select("id, whatsapp, phone").eq("id", lead_id).eq("org_id", org_id) \
            .is_("deleted_at", "null").limit(1).execute()
        rows = (res.data or []) if res else []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("invoice_delivery: lead lookup failed org=%s: %s", org_id, exc)
        return None


def _wa_window_open(db, org_id: str, doc: dict) -> bool:
    try:
        from app.services import whatsapp_service as wa
        if doc.get("lead_id"):
            return bool(wa._is_lead_window_open(db, org_id, str(doc["lead_id"])))
        if doc.get("customer_id"):
            return bool(wa._is_window_open(db, org_id, str(doc["customer_id"])))
    except Exception as exc:
        logger.warning("invoice_delivery: window check failed org=%s: %s", org_id, exc)
    return False


def _webchat_session(db, org_id: str, doc: dict) -> Optional[dict]:
    if not doc.get("lead_id"):
        return None
    try:
        from app.services import webchat_service as wc
        return wc.latest_session_for_lead(db, org_id, str(doc["lead_id"]))
    except Exception as exc:
        logger.warning("invoice_delivery: web chat lookup failed org=%s: %s", org_id, exc)
        return None


def options(db, org_id: str, doc: dict) -> dict:
    """{link, channels: {whatsapp|webchat|email: {ok, reason}}} - reasons are shown under a disabled button."""
    out = {"link": public_url(doc) if doc.get("status") not in ("draft",) else None, "channels": {}}
    lead = _lead_contact(db, org_id, doc.get("lead_id"))
    has_wa_contact = bool(doc.get("customer_id") or (lead and (lead.get("whatsapp") or lead.get("phone"))))
    if not has_wa_contact:
        wa = {"ok": False, "reason": "No WhatsApp number for this customer."}
    elif not _wa_window_open(db, org_id, doc):
        wa = {"ok": False, "reason": "The customer has not messaged in the last 24 hours, so WhatsApp will not deliver it. "
                                     "Send by email or copy the link."}
    else:
        wa = {"ok": True, "reason": None}
    s = _webchat_session(db, org_id, doc)
    if not s:
        webchat = {"ok": False, "reason": "This customer has no web chat."}
    elif s.get("status") != "active":
        webchat = {"ok": False, "reason": "The customer's web chat has ended."}
    else:
        webchat = {"ok": True, "reason": None}
    em = (doc.get("customer_email") or "").strip()
    email = {"ok": True, "reason": None, "to": em or None}
    if not em:
        email["reason"] = "Type the customer's email address."
    out["channels"] = {"whatsapp": wa, "webchat": webchat, "email": email}
    return out


# ───────────────────────────── send ─────────────────────────────

def _render(db, org_id: str, doc: dict) -> tuple[bytes, str]:
    settings = inv.get_settings(db, org_id) if not doc.get("issuer") else {}
    data, name = pdf.render(doc, settings, doc["doc_type"])
    if not data:
        raise inv.InvoiceError("INTEGRATION_ERROR", "Could not make the PDF. Please try again.", 503)
    return data, name


def _http_message(exc: Exception, fallback: str) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict) and detail.get("message"):
        return str(detail["message"])
    return fallback


def _send_whatsapp(db, org_id: str, user_id: Optional[str], doc: dict, data: bytes, name: str,
                   text: Optional[str] = None) -> None:
    from fastapi import HTTPException
    from app.models.whatsapp import SendMessageRequest
    from app.services import whatsapp_service as wa
    if not _wa_window_open(db, org_id, doc):
        raise inv.InvoiceError("WINDOW_CLOSED", "The customer has not messaged in the last 24 hours, so WhatsApp will not "
                               "deliver it. Send by email or copy the link.", 400)
    ids = {"lead_id": str(doc["lead_id"])} if doc.get("lead_id") else {"customer_id": str(doc["customer_id"])}
    try:
        wa.send_whatsapp_media_message(db=db, org_id=org_id, user_id=user_id, file_bytes=data, filename=name,
                                       content_type="application/pdf", **ids)
    except HTTPException as exc:
        raise inv.InvoiceError("INTEGRATION_ERROR", _http_message(exc, "WhatsApp did not accept the file. Please try again."),
                               400 if exc.status_code < 500 else 503)
    except Exception as exc:
        logger.error("invoice_delivery: whatsapp document failed org=%s doc=%s: %s", org_id, doc.get("id"), exc)
        raise inv.InvoiceError("INTEGRATION_ERROR", "WhatsApp did not accept the file. Please try again.", 503)
    try:   # the link text is a bonus: the PDF already went, so a failure here is only logged
        wa.send_whatsapp_message(db=db, org_id=org_id, user_id=user_id,
                                 payload=SendMessageRequest(content=text or message_text(doc), **ids))
    except Exception as exc:
        logger.warning("invoice_delivery: whatsapp link text failed org=%s doc=%s: %s", org_id, doc.get("id"), exc)


def _send_webchat(db, org_id: str, user_id: Optional[str], doc: dict, data: bytes, name: str,
                  text: Optional[str] = None) -> None:
    from app.services import webchat_attachment_service as att
    from app.services import webchat_service as wc
    s = _webchat_session(db, org_id, doc)
    if not s:
        raise inv.InvoiceError("VALIDATION_ERROR", "This customer has no web chat.", 422)
    if s.get("status") != "active":
        raise inv.InvoiceError("VALIDATION_ERROR", "The customer's web chat has ended.", 400)
    clean = {"mime": "application/pdf", "ext": "pdf", "name": att.clean_filename(name, "document", "pdf")}
    try:
        att.save_attachment(db, s, "document", clean, data, sent_by=user_id)
    except Exception as exc:
        logger.error("invoice_delivery: web chat file failed org=%s doc=%s: %s", org_id, doc.get("id"), exc)
        raise inv.InvoiceError("INTEGRATION_ERROR", "Could not put the file in the chat. Please try again.", 503)
    try:
        wc.rep_send(db, org_id, str(doc["lead_id"]), text or message_text(doc), user_id)
    except Exception as exc:
        logger.warning("invoice_delivery: web chat link text failed org=%s doc=%s: %s", org_id, doc.get("id"), exc)


def _clean_name(name: str) -> str:
    return re.sub(r"[\r\n<>\"\\,;:@]+", " ", name).strip()[:60] or "Opsra"


def email_bodies(doc: dict) -> tuple[str, str, str]:
    """(subject, text, html) - every value from the document is escaped in the HTML."""
    kind = TITLE.get(doc.get("doc_type"), "Document")
    biz = _business(doc)
    subject = f"{kind} {doc.get('number')} from {biz}"
    text = message_text(doc) + "\n\nThe PDF is attached."
    footer = ((doc.get("issuer") or {}).get("footer") or "").strip()
    if footer:
        text += f"\n\n{footer}"
    url = public_url(doc) or ""
    e = html.escape
    colour = (doc.get("issuer") or {}).get("brand_colour") or "#0d9488"
    if not re.match(r"^#[0-9a-fA-F]{6}$", str(colour)):
        colour = "#0d9488"
    body = (
        f'<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a;max-width:560px">'
        f'<p>{e(message_text(doc).split(" View it")[0])}</p>'
        f'<p><a href="{e(url)}" style="display:inline-block;background:{colour};color:#fff;padding:12px 20px;'
        f'border-radius:8px;text-decoration:none;font-weight:bold">View {e(kind.lower())}</a></p>'
        f'<p style="color:#666;font-size:13px">The PDF is attached. You can reply to this email to reach {e(biz)}.</p>'
        + (f'<p style="color:#666;font-size:13px">{e(footer)}</p>' if footer else "")
        + "</div>"
    )
    return subject, text, body


def _send_email(db, org_id: str, doc: dict, data: bytes, name: str, to: str,
                bodies: Optional[tuple] = None) -> None:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise inv.InvoiceError("INTEGRATION_ERROR", "Email is not set up on this server.", 503)
    sender = os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io")
    iss = doc.get("issuer") or {}
    reply_to = next((x.strip() for x in (iss.get("email_reply_to"), iss.get("email")) if x and EMAIL_RE.match(x.strip())), None)
    if not reply_to:
        st = inv.get_settings(db, org_id)
        reply_to = next((x.strip() for x in (st.get("email_reply_to"), st.get("email")) if x and EMAIL_RE.match(str(x).strip())), None)
    subject, text, body = bodies or email_bodies(doc)
    msg = {"from": f"{_clean_name(_business(doc))} <{sender}>", "to": [to], "subject": subject[:200],
           "text": text, "html": body, "attachments": [{"filename": name, "content": list(data)}]}
    if reply_to:
        msg["reply_to"] = reply_to
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send(msg)
    except Exception as exc:
        logger.error("invoice_delivery: email failed org=%s doc=%s: %s", org_id, doc.get("id"), exc)
        raise inv.InvoiceError("INTEGRATION_ERROR", "The email did not go out. Please try again.", 503)


def send(db, org_id: str, user_id: Optional[str], doc_id: str, channel: str, email: Optional[str] = None) -> dict:
    if channel not in CHANNELS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose WhatsApp, web chat or email.", 422, "channel")
    doc = inv.get_doc(db, org_id, doc_id)
    _sendable(doc)
    to = None
    if channel == "email":
        to = (email or doc.get("customer_email") or "").strip()
        if not to or not EMAIL_RE.match(to) or len(to) > 254:
            raise inv.InvoiceError("VALIDATION_ERROR", "Type a valid email address.", 422, "email")
    elif channel == "whatsapp" and not (doc.get("lead_id") or doc.get("customer_id")):
        raise inv.InvoiceError("VALIDATION_ERROR", "This document is not linked to a contact with WhatsApp.", 422)
    elif channel == "webchat" and not doc.get("lead_id"):
        raise inv.InvoiceError("VALIDATION_ERROR", "This customer has no web chat.", 422)
    data, name = _render(db, org_id, doc)
    if channel == "whatsapp":
        _send_whatsapp(db, org_id, user_id, doc, data, name)
    elif channel == "webchat":
        _send_webchat(db, org_id, user_id, doc, data, name)
    else:
        _send_email(db, org_id, doc, data, name, to)
    now = inv._now_iso()
    try:
        patch = {"updated_at": now}
        if not doc.get("sent_at"):
            patch["sent_at"] = now
        db.table("invoices").update(patch).eq("id", doc["id"]).eq("org_id", org_id).execute()
    except Exception as exc:  # S14 - it went out; only the stamp failed
        logger.warning("invoice_delivery: sent_at write failed org=%s doc=%s: %s", org_id, doc["id"], exc)
    inv._audit(db, org_id, user_id, f"{doc['doc_type']}.sent", doc["id"], {"channel": channel, **({"to": to} if to else {})})
    return {"channel": channel, "sent_at": doc.get("sent_at") or now, "link": public_url(doc)}


# ───────────────────────────── public page ─────────────────────────────

def _by_token(db, token: str) -> dict:
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        raise inv.InvoiceError("NOT_FOUND", "This link is not valid.", 404)
    res = db.table("invoices").select("*").eq("public_token", token).limit(1).execute()
    rows = (res.data or []) if res else []
    if not rows or rows[0].get("status") == "draft":
        raise inv.InvoiceError("NOT_FOUND", "This link is not valid.", 404)
    return inv.get_doc(db, rows[0]["org_id"], rows[0]["id"])


PUBLIC_ISSUER = ("business_name", "address", "phone", "email", "rc_number", "tin", "logo_url", "bank_name",
                 "account_name", "account_number", "brand_colour", "footer")


def public_view(db, token: str) -> dict:
    doc = _by_token(db, token)
    iss = doc.get("issuer") or {}
    status = doc.get("display_status")
    out = {
        "doc_type": doc["doc_type"], "number": doc.get("number"), "status": status,
        "issue_date": doc.get("issue_date"), "due_date": doc.get("due_date"), "currency": doc.get("currency") or "NGN",
        "customer": {"name": doc.get("customer_name"), "address": doc.get("customer_address")},
        "items": [{"description": it.get("description"), "quantity": it.get("quantity"),
                   "unit_price": it.get("unit_price"), "line_total": it.get("line_total")} for it in doc.get("items") or []],
        **{k: doc.get(k) for k in ("subtotal", "discount", "vat_rate", "vat_amount", "total", "amount_paid", "balance_due",
                                   "notes", "terms")},
        "issuer": {k: iss.get(k) for k in PUBLIC_ISSUER},
        "can_answer": doc["doc_type"] == "quote" and status == "issued",
        "voided": status == "void",
        "pdf_name": pdf.filename(doc, doc["doc_type"]),
    }
    if doc["doc_type"] == "invoice":   # INV-4
        from app.services import invoice_payment_service as pay
        out["can_pay"] = pay.can_pay(db, doc)
        out["receipts"] = [{"number": r.get("number"), "amount": r.get("amount"), "paid_at": r.get("paid_at"),
                            "method": r.get("method"), "token": r.get("public_token")}
                           for r in pay.receipts_for_invoice(db, doc["org_id"], doc["id"])
                           if not r.get("voided_at") and r.get("public_token")]
    if out["voided"]:   # a cancelled document shows no bank details
        for k in ("bank_name", "account_name", "account_number"):
            out["issuer"][k] = None
    return out


def public_pdf(db, token: str) -> tuple[bytes, str]:
    doc = _by_token(db, token)
    return _render(db, doc["org_id"], doc)


def _notify_team(db, doc: dict, accepted: bool) -> None:
    """A task for whoever made the document (S14: never raises)."""
    try:
        who = doc.get("created_by") or doc.get("issued_by")
        if not who:
            return
        name = doc.get("customer_name") or "The customer"
        title = (f"{name} accepted quote {doc.get('number')} - turn it into an invoice" if accepted
                 else f"{name} declined quote {doc.get('number')}")
        row = {"org_id": doc["org_id"], "title": title[:200], "task_type": "system_event", "assigned_to": who,
               "priority": "high" if accepted else "medium", "status": "pending",
               "due_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(), "created_at": inv._now_iso()}
        if doc.get("lead_id"):
            row.update(source_module="leads", source_record_id=doc["lead_id"])
        db.table("tasks").insert(row).execute()
    except Exception as exc:
        logger.warning("invoice_delivery: team task failed doc=%s: %s", doc.get("id"), exc)


def public_answer(db, token: str, accepted: bool) -> dict:
    doc = _by_token(db, token)
    if doc["doc_type"] != "quote":
        raise inv.InvoiceError("INVALID_TRANSITION", "Only a quote can be accepted.", 400)
    if doc.get("display_status") == "expired":
        raise inv.InvoiceError("INVALID_TRANSITION", "This quote has expired. Please ask for a new one.", 400)
    if doc.get("status") != "issued":
        raise inv.InvoiceError("INVALID_TRANSITION", "This quote has already been answered.", 409)
    inv.set_quote_answer(db, doc["org_id"], None, doc["id"], accepted)
    inv._audit(db, doc["org_id"], None, "quote.answered_by_customer", doc["id"], {"accepted": accepted})
    _notify_team(db, doc, accepted)
    return public_view(db, token)


# ───────────────────────────── WhatsApp "Get invoice" button ─────────────────────────────

def draft_for_lead(db, org_id: str, lead_id: str) -> Optional[str]:
    """A blank draft invoice for this lead, unless one was started in the last 7 days. Returns the draft id or None.
    Skipped for a business whose plan does not include invoices. S14: never raises."""
    try:
        from app.services import plan_gate_service as plan_gate
        if not plan_gate.allowed(db, org_id, "invoices"):
            return None
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        res = db.table("invoices").select("id").eq("org_id", org_id).eq("lead_id", lead_id).eq("doc_type", "invoice") \
            .eq("status", "draft").gte("created_at", since).limit(1).execute()
        rows = (res.data or []) if res else []
        if rows:
            return rows[0]["id"]
        return inv.create_draft(db, org_id, None, {"doc_type": "invoice", "lead_id": lead_id})["id"]
    except Exception as exc:
        logger.warning("invoice_delivery: draft for lead failed org=%s lead=%s: %s", org_id, lead_id, exc)
        return None


# ───────────────────────────── INV-4: receipts ─────────────────────────────

RECEIPT_CHANNELS = ("whatsapp", "email", "webchat")


def receipt_text(r: dict) -> str:
    """The short note that goes with a receipt PDF."""
    first = (r.get("customer_name") or "").split(" ")[0].strip()
    hello = f"Hello {first}, " if first else "Hello, "
    biz = _business(r)
    line = f"{hello}thank you. {biz} has received {_naira(r.get('amount'))} from you"
    if r.get("paid_at"):
        line += f" on {_nice(r['paid_at'])}"
    line += f". Your receipt {r.get('number')} is attached."
    if r.get("invoice_number"):
        bal = float(r.get("invoice_balance") or 0)
        line += (f" Invoice {r['invoice_number']} is now fully paid." if bal <= 0
                 else f" Balance left on invoice {r['invoice_number']}: {_naira(bal)}.")
    return line


def receipt_email_bodies(r: dict) -> tuple[str, str, str]:
    biz = _business(r)
    subject = f"Receipt {r.get('number')} from {biz}"
    text = receipt_text(r)
    footer = ((r.get("issuer") or {}).get("footer") or "").strip()
    if footer:
        text += f"\n\n{footer}"
    e = html.escape
    body = (f'<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a;max-width:560px">'
            f'<p>{e(receipt_text(r))}</p>'
            f'<p style="color:#666;font-size:13px">You can reply to this email to reach {e(biz)}.</p>'
            + (f'<p style="color:#666;font-size:13px">{e(footer)}</p>' if footer else "") + "</div>")
    return subject, text, body


def _receipt_email(db, org_id: str, r: dict) -> Optional[str]:
    em = (r.get("customer_email") or "").strip()
    if not em and (r.get("lead_id") or r.get("customer_id")):
        try:
            em = (inv._customer_snapshot(db, org_id, {"lead_id": r.get("lead_id"),
                                                       "customer_id": r.get("customer_id")}).get("customer_email") or "").strip()
        except Exception:
            em = ""
    return em if em and EMAIL_RE.match(em) else None


def receipt_options(db, org_id: str, r: dict) -> dict:
    lead = _lead_contact(db, org_id, r.get("lead_id"))
    has_wa = bool(r.get("customer_id") or (lead and (lead.get("whatsapp") or lead.get("phone"))))
    if r.get("voided_at"):
        no = {"ok": False, "reason": "This receipt is void."}
        return {"channels": {"whatsapp": no, "webchat": no, "email": {**no, "to": None}}}
    if not has_wa:
        wa = {"ok": False, "reason": "No WhatsApp number for this customer."}
    elif not _wa_window_open(db, org_id, r):
        wa = {"ok": False, "reason": "The customer has not messaged in the last 24 hours, so WhatsApp will not deliver it."}
    else:
        wa = {"ok": True, "reason": None}
    s = _webchat_session(db, org_id, r)
    webchat = ({"ok": True, "reason": None} if s and s.get("status") == "active"
               else {"ok": False, "reason": "This customer has no open web chat."})
    to = _receipt_email(db, org_id, r)
    email = {"ok": True, "reason": None if to else "Type the customer's email address.", "to": to}
    return {"channels": {"whatsapp": wa, "webchat": webchat, "email": email}}


def send_receipt(db, org_id: str, user_id: Optional[str], receipt_id: str, channel: Optional[str] = None,
                 email: Optional[str] = None) -> dict:
    """Send a receipt PDF. channel None = pick for the customer (WhatsApp if the window is open, else email, else web
    chat); with nothing usable it returns {"channel": None} instead of raising (used after a Paystack payment)."""
    from app.services import invoice_payment_service as pay
    r = pay.receipt_doc(db, org_id, pay.get_receipt(db, org_id, receipt_id))
    if r.get("voided_at"):
        raise inv.InvoiceError("INVALID_TRANSITION", "This receipt is void and cannot be sent.", 400)
    to = None
    if channel is None:
        opts = receipt_options(db, org_id, r)["channels"]
        if opts["whatsapp"]["ok"]:
            channel = "whatsapp"
        elif opts["email"].get("to"):
            channel, to = "email", opts["email"]["to"]
        elif opts["webchat"]["ok"]:
            channel = "webchat"
        else:
            return {"channel": None, "sent": False}
    elif channel not in RECEIPT_CHANNELS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose WhatsApp, web chat or email.", 422, "channel")
    if channel == "email" and not to:
        to = (email or _receipt_email(db, org_id, r) or "").strip()
        if not to or not EMAIL_RE.match(to) or len(to) > 254:
            raise inv.InvoiceError("VALIDATION_ERROR", "Type a valid email address.", 422, "email")
    if channel == "whatsapp" and not (r.get("lead_id") or r.get("customer_id")):
        raise inv.InvoiceError("VALIDATION_ERROR", "This receipt is not linked to a contact with WhatsApp.", 422)
    if channel == "webchat" and not r.get("lead_id"):
        raise inv.InvoiceError("VALIDATION_ERROR", "This customer has no web chat.", 422)
    data, name = pay.render_receipt(db, org_id, r)
    text = receipt_text(r)
    if channel == "whatsapp":
        _send_whatsapp(db, org_id, user_id, r, data, name, text)
    elif channel == "webchat":
        _send_webchat(db, org_id, user_id, r, data, name, text)
    else:
        _send_email(db, org_id, r, data, name, to, receipt_email_bodies(r))
    inv._audit(db, org_id, user_id, "receipt.sent", r.get("invoice_id") or r["id"],
               {"receipt": r.get("number"), "channel": channel, **({"to": to} if to else {})})
    return {"channel": channel, "sent": True}


def public_receipt_pdf(db, token: str) -> tuple[bytes, str]:
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        raise inv.InvoiceError("NOT_FOUND", "This link is not valid.", 404)
    res = db.table("receipts").select("*").eq("public_token", token).limit(1).execute()
    rows = (res.data or []) if res else []
    if not rows:
        raise inv.InvoiceError("NOT_FOUND", "This link is not valid.", 404)
    from app.services import invoice_payment_service as pay
    return pay.render_receipt(db, rows[0]["org_id"], rows[0])


def public_pay(db, token: str) -> str:
    """Start a Paystack checkout for the balance. Returns the URL to send the customer to."""
    from app.services import invoice_payment_service as pay
    doc = _by_token(db, token)
    return pay.start_checkout(db, doc, public_url(doc))


def public_verify(db, token: str, reference: str) -> dict:
    from app.services import invoice_payment_service as pay
    doc = _by_token(db, token)
    paid = pay.verify_return(db, doc, reference)
    return {"paid": paid, "doc": public_view(db, token)}
