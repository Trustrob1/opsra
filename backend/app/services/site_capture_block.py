"""
app/services/site_capture_block.py
SITE-ADDONS A1b - the enquiry form and tracked WhatsApp links for Premium and imported pages.

Standard pages get their form from site_renderer. Premium pages (written by a model, then filled by the server) and imported
pages (uploaded finished HTML) are not rendered by that code, so this module adds the same sanctioned block to them:

  * a plain HTML form post - no script, nothing written by a model or by the uploaded page; every string is escaped
  * for imported pages: contact-type forms are replaced in place; other forms (search, newsletter) are left alone
  * for imported pages: WhatsApp links to the site's own number go through the tracked link

Pure functions: no database, no network, never raise (a problem leaves the page as it was).
"""
from __future__ import annotations

import logging
import re
from html import escape
from typing import Optional
from urllib.parse import parse_qs, quote, urlsplit

logger = logging.getLogger(__name__)

# Neutral on purpose: it takes the page's own font and colours, so it sits in any design without a theme of its own.
FORM_CSS = (
    ".opsra-enq{max-width:640px;margin:0 auto}"
    ".opsra-enq form{display:grid;gap:14px}"
    ".opsra-enq label{display:grid;gap:6px;font-size:.9rem;font-weight:600}"
    ".opsra-enq input,.opsra-enq textarea{font:inherit;font-weight:400;color:inherit;background:transparent;"
    "border:1.5px solid currentColor;border-color:color-mix(in srgb,currentColor 30%,transparent);border-radius:8px;"
    "padding:12px 14px;min-height:44px;width:100%;box-sizing:border-box}"
    ".opsra-enq textarea{min-height:110px;resize:vertical}"
    ".opsra-enq input:focus,.opsra-enq textarea:focus{outline:2px solid var(--accent,currentColor);outline-offset:1px}"
    ".opsra-enq .opsra-consent{display:flex;gap:10px;align-items:flex-start;font-weight:400;font-size:.85rem;opacity:.8}"
    ".opsra-enq .opsra-consent input{width:20px;min-height:20px;margin-top:2px;flex:none}"
    ".opsra-enq button{cursor:pointer;justify-self:start;font:inherit;font-weight:600;border:0;border-radius:999px;"
    "padding:13px 26px;min-height:44px;background:var(--accent,#111);color:var(--accent-ink,#fff)}"
    ".opsra-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}"
)


def form_html(business: str, cap: dict, heading: bool = True, src: str = "enquiry-form") -> str:
    """The sanctioned form. `cap` is site_capture_service.render_config(); `heading` adds a title (for a new section)."""
    biz = escape(business or "us", quote=True)
    ret = f'<input type="hidden" name="return_to" value="{escape(cap["return_to"], quote=True)}">' if cap.get("return_to") else ""
    head = (f'<h2>Send us an enquiry</h2><p>Tell us what you need and {biz} will get back to you.</p>') if heading else ""
    return (f'<div class="opsra-enq" id="enquire">{head}'
            f'<form method="post" action="{escape(cap["form_action"], quote=True)}" accept-charset="utf-8">'
            f'<input type="hidden" name="src" value="{escape(src, quote=True)}">{ret}'
            '<label>Your name<input name="name" required maxlength="120" autocomplete="name"></label>'
            '<label>Phone or WhatsApp number<input name="phone" type="tel" inputmode="tel" maxlength="20" autocomplete="tel"></label>'
            '<label>Email (optional)<input name="email" type="email" maxlength="200" autocomplete="email"></label>'
            '<label>Your message<textarea name="message" rows="4" maxlength="2000"></textarea></label>'
            '<div class="opsra-hp" aria-hidden="true"><label>Leave this empty<input name="website" tabindex="-1" autocomplete="off"></label></div>'
            f'<label class="opsra-consent"><input type="checkbox" name="consent" value="on" required>'
            f'<span>I agree that {biz} may contact me about my enquiry.</span></label>'
            '<button type="submit">Send enquiry</button></form></div>')


# -- Premium --------------------------------------------------------------------------------

_FOOTER_RX = re.compile(r"<footer\b", re.I)


def add_form_section(body: str, business: str, cap: Optional[dict]) -> str:
    """Put an enquiry section before the page's footer (or at the end). Returns `body` unchanged when the plan has no form."""
    try:
        if not cap or not cap.get("form") or not cap.get("form_action"):
            return body
        block = f'<section class="opsra-enq-sec" style="padding:64px 20px">{form_html(business, cap)}</section>'
        m = _FOOTER_RX.search(body)
        return body[:m.start()] + block + body[m.start():] if m else body + block
    except Exception as exc:  # S14
        logger.warning("site_capture_block: add_form_section failed: %s", exc)
        return body


def tracked_wa(cap: Optional[dict], msg: str, src: str) -> Optional[str]:
    """The tracked WhatsApp address for a button, or None when source tracking is not in the plan."""
    if not cap or not cap.get("track") or not cap.get("wa_base"):
        return None
    return f"{cap['wa_base']}?src={quote(src or 'site', safe='')}&t={quote(msg or '')}"


# -- imported pages -------------------------------------------------------------------------

_FORM_RX = re.compile(r"<form\b[^>]*>.*?</form\s*>", re.I | re.S)
_INPUT_RX = re.compile(r"<(input|textarea|select)\b([^>]*)>", re.I | re.S)
_NAME_RX = re.compile(r"""(?:name|id|type|placeholder|autocomplete)\s*=\s*["']?([^"'\s>]*)""", re.I)
_CONTACT_WORDS = re.compile(r"name|phone|tel|mobile|whatsapp|email|e-mail|message|enquir|inquir|comment", re.I)
_NOT_CONTACT = re.compile(r"password|search|\bq\b|coupon|promo|card", re.I)


def is_contact_form(form_html_text: str) -> bool:
    """A form that collects a person's contact details or message. Search boxes, logins and single-field newsletter forms
    are left alone."""
    if re.search(r"<textarea\b", form_html_text, re.I):
        return not re.search(r"type\s*=\s*[\"']?password", form_html_text, re.I)
    fields = _INPUT_RX.findall(form_html_text)
    hits, bad = 0, False
    for tag, attrs in fields:
        words = " ".join(_NAME_RX.findall(attrs))
        if re.search(r"type\s*=\s*[\"']?(hidden|submit|button|checkbox)", attrs, re.I):
            continue
        if _NOT_CONTACT.search(words):
            bad = True
        if _CONTACT_WORDS.search(words):
            hits += 1
    return not bad and hits >= 2


def replace_contact_forms(html: str, business: str, cap: Optional[dict]) -> tuple[str, int]:
    """Swap each contact-type <form> of an imported page for the sanctioned form, where it stands. -> (html, how many)."""
    try:
        if not cap or not cap.get("form") or not cap.get("form_action"):
            return html, 0
        count = 0

        def swap(m: "re.Match") -> str:
            nonlocal count
            if not is_contact_form(m.group(0)):
                return m.group(0)
            count += 1
            style = f"<style>{FORM_CSS}</style>" if count == 1 else ""
            return style + form_html(business, cap, heading=False, src="imported-form")

        out = _FORM_RX.sub(swap, html)
        return (out, count) if count else (html, 0)
    except Exception as exc:  # S14
        logger.warning("site_capture_block: replace_contact_forms failed: %s", exc)
        return html, 0


_WA_HREF_RX = re.compile(r"""(href\s*=\s*)(["'])(https?://(?:wa\.me/\+?(\d{6,15})|api\.whatsapp\.com/send/?\?[^"']*?phone=\+?(\d{6,15}))[^"']*)\2""", re.I)


def track_wa_links(html: str, cap: Optional[dict], number: str) -> tuple[str, int]:
    """Send WhatsApp links that go to the site's own number through the tracked link. Links to other numbers stay as written."""
    try:
        if not cap or not cap.get("track") or not cap.get("wa_base"):
            return html, 0
        mine = re.sub(r"\D", "", number or "")
        if not mine:
            return html, 0
        count = 0

        def swap(m: "re.Match") -> str:
            nonlocal count
            digits = m.group(4) or m.group(5) or ""
            if digits != mine:
                return m.group(0)
            q = parse_qs(urlsplit(m.group(3).replace("&amp;", "&")).query)
            text = (q.get("text") or [""])[0]
            count += 1
            url = f"{cap['wa_base']}?src=imported&t={quote(text)}"
            return f"{m.group(1)}{m.group(2)}{escape(url, quote=True)}{m.group(2)}"

        out = _WA_HREF_RX.sub(swap, html)
        return (out, count) if count else (html, 0)
    except Exception as exc:  # S14
        logger.warning("site_capture_block: track_wa_links failed: %s", exc)
        return html, 0


def form_target_origin(cap: Optional[dict]) -> Optional[str]:
    """scheme://host of the form post address, for the page's form-action rule."""
    try:
        if not cap or not cap.get("form") or not cap.get("form_action"):
            return None
        u = urlsplit(cap["form_action"])
        return f"{u.scheme}://{u.netloc}" if u.scheme == "https" and u.netloc else None
    except Exception:
        return None
