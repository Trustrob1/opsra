"""
app/services/webchat_flow_service.py
------------------------------------
WEBCHAT-1 — the scripted chat: menu → fixed answer → link → booking form → lead + alert.

Pure Python, no model. Everything a visitor can be told comes from the org's own
settings (webchat_config), so a web chat message costs nothing but the database write.

Rules (Trust, 18 Oct 2026):
  • After the first answer the page asks for contact (name + WhatsApp number and/or email +
    consent). A visitor who came from WhatsApp already has a proven number, so only an
    optional email is asked.
  • Booking needs contact first.
  • Once a rep takes over (or the visitor taps Talk to us) the script stops answering;
    messages are stored and the team is told.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import webchat_service as wc
from app.services import webchat_ai_service
from app.services import webchat_shop_service
from app.services import webchat_contact_service as contact
from app.services import webchat_greeting_service as greet
from app.services import webchat_handover_service as handover
from app.services import webchat_guard_service as guard
from app.services import webchat_smart_service as smart
from app.services import knowledge_gap_service as kgap


logger = logging.getLogger(__name__)

HUMAN_NOTIFY_EVERY_MIN = 10
MAX_TURNS_PER_SESSION = 200


def _has_contact(s: dict) -> bool:
    return bool(s.get("lead_id"))


_SHORT_WORDS = 3          # MATCH-2: up to this many words is a button word; longer is a sentence
_BROAD = re.compile(r"\b(?:your services|our services|what (?:do|can) you (?:do|offer|help)|what (?:services|else)|tell me more|more about (?:you|your|what)|"
                    r"what is (?:this|it) about|about you|what you (?:do|offer))\b", re.I)


def _match_item(cfg: dict, text: str, strict: bool = False) -> Optional[dict]:
    """Keyword / label match for typed text. First item with the most keyword hits wins; no hits → None.
    MATCH-2 (strict, used when Chioma's AI can read the message instead): a sentence of more than 3 words needs two keyword hits or the
    whole button label as a phrase, and a broad question ('tell me about your services') is never taken for one button."""
    t = f" {re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower())} "
    long_msg = strict and len(t.split()) > _SHORT_WORDS
    broad = bool(_BROAD.search(text or ""))          # 'your services', 'tell me more': a question about everything, not about one button
    ranked = smart.rank(cfg, text)                   # SMART-1: forgives plurals, filler words and small typos
    best_hits, best = (ranked[0][0], ranked[0][1]) if ranked else (0, None)
    if best_hits <= 0:
        best = None
    if (long_msg or broad) and best_hits < 2:
        return None
    return best


_BOOK_Q = re.compile(r"\b(?:book|booking|appointment|schedule|reserve)\b", re.I)


def _booking_offer(cfg: dict, answer: str) -> Optional[dict]:
    """OPEN-OFFER-1: the booking button when this answer ends by offering a booking ('Want to book a time?'), else None. The offer stays open
    until the visitor takes it or does something else, so a typed 'yes' means yes and a details ask in between cannot swallow it."""
    tail = (answer or "").strip().splitlines()[-1:] or [""]
    if not tail[0].rstrip().endswith("?") or not _BOOK_Q.search(tail[0]):
        return None
    return next((m for m in cfg.get("menu", []) if m.get("action") == "booking" and m.get("id")), None)


def _open_offer_item(cfg: dict, s: dict) -> Optional[dict]:
    oid = (s.get("state") or {}).get("open_offer")
    return next((m for m in cfg.get("menu", []) if m.get("id") == oid and m.get("action") == "booking"), None) if oid else None


def _overview(cfg: dict) -> Optional[dict]:
    """{'text', 'choices'} for a broad question when no AI is reading it: the business's own buttons to tap, never one wrong answer."""
    topics = [m for m in cfg.get("menu", []) if m.get("action") != "human" and m.get("id") and m.get("label")]
    if not topics:
        return None
    topics.sort(key=lambda m: (0 if m.get("featured") else 1, 0 if m.get("action") == "booking" else 1))
    choices = [{"id": "item", "menu_id": m["id"], "label": str(m["label"])[:40]} for m in topics[:4]]
    if len(topics) > 4:
        choices.append({"id": "menu", "label": "More"})
    return {"text": "Here is what I can help with. Tap one to find out more.", "choices": choices}


def _native_booking_link(db, s: dict) -> Optional[str]:
    """A personal link to the business's real calendar (Opsra booking), or None when the business has not switched native booking on, has no
    bookable service, or the visitor has no lead yet. The same link is reused for a day so repeated taps do not make a pile of links.
    Never raises: on any problem the caller falls back to the booking request form."""
    try:
        from app.services import booking_service as bk
        state = s.get("state") or {}
        old = state.get("booking_link") or {}
        if old.get("url") and old.get("at") and (datetime.now(timezone.utc) - datetime.fromisoformat(old["at"])) < timedelta(hours=24):
            return old["url"]
        if not s.get("lead_id") or not bk.get_settings(db, s["org_id"]).get("native_enabled"):
            return None
        services = bk.list_services(db, s["org_id"], active_only=True)
        if not services:
            return None
        token = bk.create_link(db, s["org_id"], s["lead_id"], services[0]["id"], None)
        url = f"{bk.public_base()}/b/{token}"
        wc.set_state(db, s, booking_link={"url": url, "at": datetime.now(timezone.utc).isoformat()})
        return url
    except Exception as exc:
        logger.warning("webchat native booking link failed org=%s: %s", s.get("org_id"), exc)
        return None


def _booking_link_text(url: str) -> str:
    return f"Here is your personal booking link. Pick a time that suits you: {url}"


def _human_offer(db, s: dict, cfg: dict, kind: str) -> Optional[dict]:
    """HUMAN-OFFER-1: a visitor whose very first action is tapping Talk to the team is offered one quick answer first: the business's top buttons,
    plus a clear button to carry straight on to the team. Once per chat, never for typed requests (they asked for a person in words), and
    never when the visitor has already asked or been answered something. The second tap goes straight through."""
    st = s.get("state") or {}
    if (not cfg.get("human_offer") or kind != "menu" or st.get("offer") or st.get("answers")
            or wc.is_human(s, cfg)):
        return None
    topics = [m for m in cfg.get("menu", []) if m.get("action") != "human" and m.get("id") and m.get("label")]
    if not topics:
        return None
    topics.sort(key=lambda m: (0 if m.get("featured") else 1, 0 if m.get("action") == "booking" else 1))
    away = handover.is_away(cfg)
    text = ("Our team is away right now, but I can often answer straight away. What is it about?" if away
            else "Happy to connect you. What is it about? I can often answer straight away.")
    choices = [{"id": "item", "menu_id": m["id"], "label": str(m["label"])[:40]} for m in topics[:3]]
    choices.append({"id": "human", "label": "Leave a message for the team" if away else "No, connect me to the team"})
    wc.set_state(db, s, offer="shown")
    wc.log_event(db, s["org_id"], s["id"], "tap", s.get("source"), ref="offer_shown")
    return {"messages": [wc.append_message(db, s, "bot", text)], "ask_contact": False, "ask_email": False, "form": None, "human": False, "choices": choices}


def _record_gap(db, s: dict, text: str) -> None:
    """SMART-1: a typed question nobody could answer goes on the owner's 'not answered' list (never raises, numbers and emails hidden)."""
    try:
        kgap.record(db, s["org_id"], text, s.get("lead_id"))
    except Exception as exc:
        logger.warning("webchat gap record failed: %s", exc)


def _to_team(db, s: dict, cfg: dict, out: list, note: str, reply_text: Optional[str] = None) -> dict:
    """Hand the chat to the team: the bot goes quiet, the team is told, and details are asked in the chat if the visitor is new."""
    wc.set_human(db, s)
    out.append(wc.append_message(db, s, "bot", reply_text or handover.human_reply(cfg, has_contact=_has_contact(s))))
    if handover.is_away(cfg):
        wc.set_state(db, s, awaiting_message=True)        # the visitor has not written anything yet: their next typed message is the one to save
    _notify_human(db, s, cfg, note)
    if not _has_contact(s) and contact.enabled(cfg):          # ask in the chat, not with the pop-up form
        out.append(contact.start(db, s, cfg, ""))
        return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True, "contact_step": "name"}
    return {"messages": out, "ask_contact": not _has_contact(s), "ask_email": False, "form": None, "human": True}


def _guide_answer(db, s: dict, cfg: dict, out: list, g: dict, text: str) -> Optional[dict]:
    """SMART-1: the visitor is answering a guided question. Their answer is stored; the next question is asked, or at the end the
    team gets one tidy summary. A real question (a ? or a long message) leaves the guide and is answered normally (returns None)."""
    item = next((m for m in cfg.get("menu", []) if m.get("id") == g.get("id") and m.get("guide")), None)
    if not item or "?" in text or len(text.split()) > 10:
        wc.set_state(db, s, guide=None)
        return None
    steps = item["guide"]["steps"]
    answers = list(g.get("answers") or []) + [text[:100]]
    if len(answers) < len(steps):
        wc.set_state(db, s, guide={"id": item["id"], "answers": answers})
        pr = smart.guide_prompt(item["guide"], len(answers))
        out.append(wc.append_message(db, s, "bot", pr["text"]))
        return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False, "choices": pr["choices"]}
    wc.set_state(db, s, guide=None)
    summary = smart.guide_summary(item, answers)
    wc.log_event(db, s["org_id"], s["id"], "tap", s.get("source"), ref="guide_done")
    done = item["guide"].get("done") or "Thank you. I have passed this to the team and they will reply here."
    return _to_team(db, s, cfg, out, "New request: " + summary, reply_text=done)


def _product_focus(db, s: dict, cfg: dict, text: str, out: list):
    """PRODUCT-ASK-1: a chat with a product in focus (an ad, a product page) or in the cart. (1) The visitor answers 'Which one do you mean?': that
    product becomes the focus and the question they first asked is answered about it. (2) A typed product name moves the focus to that product.
    (3) A product-specific question that names none, with two or more products in play, gets 'Which one do you mean?' with a button for each.
    Returns a finished reply, or None to carry on as normal."""
    pend = (s.get("state") or {}).get("ask_which")
    if pend:
        wc.set_state(db, s, ask_which=None)                              # asked once: whatever they do next, the question is settled
        pick = webchat_shop_service.pick_from(db, s, pend, text)
        if pick:
            fb = webchat_shop_service.product_answer(db, s, cfg, pend.get("q") or "") or cfg.get("_fallback_base") or cfg.get("fallback")
            res = handle_message(db, s, {**cfg, "fallback": fb}, kind="text", text=pend.get("q") or "", _replay=True)
            res["messages"] = out + list(res.get("messages") or [])
            return res
    r = webchat_shop_service.focus_check(db, s, cfg, text)
    if r.get("ask"):
        out.append(wc.append_message(db, s, "bot", "Which one do you mean?"))
        return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False,
                "choices": [{"id": "say", "label": c["title"]} for c in r["ask"]]}
    return None


def _ad_shortcut_tap(cfg: dict, s: dict, item: dict):
    """AD-PRODUCT-1: the visitor tapped one of the shortcut buttons of the ad their chat came from; its entry, or None."""
    return next((sc for sc in wc.ad_shortcuts(cfg, s.get("source")) if sc["id"] == item.get("id")), None)


def _ad_shortcut_text(db, s: dict, cfg: dict, item: dict, sc: dict) -> str:
    """The owner's wording for this shortcut on this ad when they wrote one. Otherwise the menu item's general answer, followed (when the ad is
    about a catalogue product) by one line from the catalogue about that product. Nothing is invented."""
    if sc.get("answer"):
        return sc["answer"]
    base = _answer_text(item)
    line = webchat_shop_service.product_line(db, s, cfg)
    return f"{base}\n\n{line}" if line else base


def _ad_followups(cfg: dict, s: dict, item: dict) -> list:
    """AD-PRODUCT-1: the buttons under a shortcut's answer: the ad's other shortcuts, then More options (the menu, whose first row is All products)."""
    out = [smart._item_choice({"id": sc["id"], "label": sc["label"]}) for sc in wc.ad_shortcuts(cfg, s.get("source")) if sc["id"] != item.get("id")]
    out.append({"id": "menu", "label": "More options"})
    return out


def _answer_text(item: dict) -> str:
    text = item.get("answer") or ""
    link = item.get("link")
    if link and link.get("url"):
        text = (text + "\n" if text else "") + f"{link.get('label') or 'Open'}: {link['url']}"
    return text or "Thanks for asking."


def _notify_human(db, s: dict, cfg: dict, why: str) -> None:
    """Tell the team a visitor wants a person; at most once every 10 minutes per session."""
    state = s.get("state") or {}
    last = state.get("notified_at")
    now = datetime.now(timezone.utc)
    try:
        if last and now - datetime.fromisoformat(last) < timedelta(minutes=HUMAN_NOTIFY_EVERY_MIN):
            return
    except Exception:
        pass
    name = s.get("contact_name") or "A web chat visitor"
    wc.notify_managers(db, s["org_id"], f"{name} is waiting on web chat", why[:300], s.get("lead_id"), "webchat_message", to_assigned_rep=True)
    wc.set_state(db, s, notified_at=now.isoformat())
    handover.email_owner(db, s, cfg, why)           # ONLY-1c-DOWN: the owner may not be logged in, so they get an email too


def handle_message(db, s: dict, cfg: dict, *, kind: str, menu_id: Optional[str] = None,
                   text: Optional[str] = None, reply_to: Optional[str] = None, _replay: bool = False) -> dict:
    """
    One visitor action. kind = 'menu' (tapped an option) or 'text'.
    Returns {messages, ask_contact, ask_email, form, human}; `messages` are the new messages in order
    (the visitor's own first), already stored.
    """
    if int(s.get("turn_count") or 0) >= MAX_TURNS_PER_SESSION:
        return {"messages": [wc.append_message(db, s, "bot", "This chat has reached its limit. Please use Talk to us or contact us directly.")],
                "ask_contact": False, "ask_email": False, "form": None, "human": True}

    item = None
    if kind == "menu":
        item = next((m for m in cfg["menu"] if m["id"] == menu_id), None)
        if not item:
            return {"messages": [], "ask_contact": False, "ask_email": False, "form": None, "human": wc.is_human(s, cfg)}
        visitor_text = item["label"]
        if item.get("action") == "human" and handover.is_away(cfg):
            visitor_text = "Leave a message"          # AWAY: the button said Leave a message, so the bubble says it too
    else:
        visitor_text = wc._clean_text(text, wc.MAX_TEXT)
        if not visitor_text:
            return {"messages": [], "ask_contact": False, "ask_email": False, "form": None, "human": wc.is_human(s, cfg)}

    out = []
    if not _replay:           # a replay answers a question that was just stored: do not store or count it twice
        shown = contact.shown_text(s, visitor_text) if kind == "text" else visitor_text      # WEBCHAT-CONTACT-1: a typed number is not kept in the chat text
        wc.typing_clear("visitor", str(s["id"]))                     # WEBCHAT-CONTACT-1e: the message arrived, so they are no longer typing
        out.append(wc.append_message(db, s, "visitor", shown, reply_to=reply_to))
        wc.update_session(db, s, {"turn_count": int(s.get("turn_count") or 0) + 1})
        if int(s.get("turn_count") or 0) == 1:
            wc.log_event(db, s["org_id"], s["id"], "started", s.get("source"))

    if kind == "text" and not _replay:
        hc = guard.human_check(db, s, visitor_text)       # SAFE: a burst of messages (or a burst of new chats) gets a one-line sum before Chioma carries on
        if hc:
            if hc.get("reply"):
                out.append(wc.append_message(db, s, "bot", hc["reply"]))
            return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": wc.is_human(s, cfg)}

    state = s.get("state") or {}
    if state.get("human"):
        taps_option = kind == "menu" and item is not None and item.get("action") != "human"
        answering_details = kind == "text" and bool(contact.step_of(s)) and not _replay      # the visitor is typing their name or number, not writing to the team
        if answering_details:
            pass                                  # typing their name or number: the in-chat script below handles it and the hand-over stays on
        elif wc.is_human(s, cfg) and not taps_option:
            _notify_human(db, s, cfg, visitor_text)
            # AWAY: nobody on the team is there to reply, so Chioma must not go silent. A person has not answered yet and the team is outside hours.
            nobody_here = kind == "text" and not state.get("rep_last_at") and handover.is_away(cfg)
            if nobody_here and state.get("awaiting_message") and _replay:
                wc.set_state(db, s, awaiting_message=False)     # DEFLECT: a question typed while asked for a name is answered below, and the team already has it
            elif nobody_here and state.get("awaiting_message"):
                wc.set_state(db, s, awaiting_message=False)
                out.append(wc.append_message(db, s, "bot", handover.message_saved(cfg)))
                return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True}
            if not nobody_here:
                return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True}
            # away and the message is already saved: fall through so Chioma answers as normal
        else:
            wc.set_state(db, s, human=False)      # team quiet for a while, or the visitor chose an option: the bot is back

    if contact.step_of(s) and kind == "text" and not _replay and contact.drops_quietly(s, visitor_text):
        contact._clear(db, s)                                    # the gentle ask was ignored: carry on with what they actually said
    if contact.step_of(s) and kind == "text" and not _replay and contact.can_deflect(s, visitor_text):
        # The team asked for details but the visitor asked a real question: answer it first, then ask once more.
        res = handle_message(db, s, cfg, kind=kind, menu_id=menu_id, text=text, reply_to=reply_to, _replay=True)
        again = contact.reask(db, s, cfg)
        if again:
            res["messages"] = out + list(res.get("messages") or []) + [again]
            res["contact_step"] = contact.step_of(s)
            res["ask_contact"], res["form"] = False, None
        else:
            res["messages"] = out + list(res.get("messages") or [])
        return res
    if contact.step_of(s) and not _replay:                       # WEBCHAT-CONTACT-1: Chioma is asking for details in the chat
        if kind == "text":
            r = contact.step(db, s, cfg, visitor_text, handle_contact)
            res = {"messages": out + r["messages"], "ask_contact": r["ask_contact"], "ask_email": False, "form": r["form"],
                   "human": wc.is_human(s, cfg), "cards": r["cards"], "contact_step": r["contact_step"]}
            if r.get("cart") is not None:                                # ORDER-CONFIRM-1: checkout ran right after the details
                res["cart"], res["human"] = r["cart"], bool(r.get("human"))
            if r.get("choices"):
                res["choices"] = r["choices"]
            return res
        wc.set_state(db, s, contact_step=None, contact_tries=0, contact_tmp={}, contact_optional=False, contact_nudged=True)   # tapped an option: moved on, do not nag

    offer_item = _open_offer_item(cfg, s)
    if offer_item and not _replay:
        wc.set_state(db, s, open_offer=None)              # OPEN-OFFER-1: whatever the visitor does next, the offer is settled (a new answer can open another)
        if kind == "text" and contact.is_yes(visitor_text):
            item = offer_item                              # 'yes' to "Want to book a time?" is the Book button
        elif kind == "text" and contact.is_no(visitor_text):
            out.append(wc.append_message(db, s, "bot", "No problem. Is there anything else I can help with?"))
            ov = _overview(cfg)
            res = {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False}
            if ov:
                res["choices"] = ov["choices"]
            return res
        state = s.get("state") or {}

    if kind == "menu" and state.get("ask_which"):
        wc.set_state(db, s, ask_which=None)                  # PRODUCT-ASK-1: they tapped a button instead of answering which product: the question is dropped
    if kind == "menu" and state.get("guide"):
        wc.set_state(db, s, guide=None)                    # they tapped something else: the guided questions are dropped
    if kind == "text" and state.get("guide") and not _replay:
        res = _guide_answer(db, s, cfg, out, state["guide"], visitor_text)
        if res is not None:
            return res

    if kind == "text":
        g = greet.classify(visitor_text, cfg.get("business_name") or "")
        if g:            # WEB-ONLY-1c-GREET: a greeting, thanks or goodbye gets a warm reply from Chioma herself (no AI call, no credit)
            out.append(wc.append_message(db, s, "bot", greet.reply(g, cfg.get("business_name") or "", turn=int(s.get("turn_count") or 0))))
            return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False}

    if kind == "text" and cfg.get("ai_enabled"):
        sc = guard.screen_input(db, s, visitor_text, cfg.get("business_name") or "", ip=cfg.get("_ip"))
        if sc:          # SAFE: an override attempt, a question about how she works, or something outside the business: fixed reply, no AI call
            out.append(wc.append_message(db, s, "bot", sc["reply"]))
            if sc.get("blocked"):
                _notify_human(db, s, cfg, "The assistant was switched off for this chat after repeated attempts to override it.")
            return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False}

    if kind == "text" and not _replay:
        asked = _product_focus(db, s, cfg, visitor_text, out)          # PRODUCT-ASK-1: which product does the visitor mean
        if asked is not None:
            return asked

    loose_item = None
    if item is None:
        ai_reads = kind == "text" and bool(cfg.get("ai_enabled"))
        item = _match_item(cfg, visitor_text, strict=ai_reads)         # MATCH-2: a sentence goes to the AI when she is on
        if item is None and ai_reads:
            loose_item = _match_item(cfg, visitor_text)               # kept for when the AI has no answer (allowance used up, error)
        if item is not None and kind == "text":
            ties = smart.weak_ties(cfg, visitor_text)                 # SMART-1: two buttons fit equally well: ask which, do not guess
            if len(ties) >= 2:
                out.append(wc.append_message(db, s, "bot", "Which of these do you mean?"))
                return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False,
                        "choices": [smart._item_choice(m) for m in ties]}

    form = None
    cards: list = []
    choices: list = []
    just_answered = False
    if item and item.get("action") == "human":
        offer = _human_offer(db, s, cfg, kind)
        if offer:
            offer["messages"] = out + offer["messages"]
            return offer
        if (s.get("state") or {}).get("offer") == "shown":
            wc.set_state(db, s, offer="skipped")                 # they took the offer's "connect me" button: counted, then straight through
            wc.log_event(db, s["org_id"], s["id"], "tap", s.get("source"), ref="offer_skipped")
        return _to_team(db, s, cfg, out, "Asked to talk to the team." if not handover.is_away(cfg) else "Asked to leave a message (team away).")

    if item and item.get("action") == "guide" and item.get("guide"):
        wc.set_state(db, s, guide={"id": item["id"], "answers": []})      # SMART-1: a few tap-to-answer questions
        pr = smart.guide_prompt(item["guide"], 0)
        out.append(wc.append_message(db, s, "bot", pr["text"]))
        return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False, "choices": pr["choices"]}

    if item and item.get("action") == "booking":
        if not _has_contact(s):
            wc.set_state(db, s, pending="booking")
            if contact.enabled(cfg):
                out.append(contact.start(db, s, cfg, "Happy to help you book."))
                return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False, "contact_step": "name"}
            out.append(wc.append_message(db, s, "bot", "Happy to help you book. First, " + cfg["contact_prompt"][0].lower() + cfg["contact_prompt"][1:]))
            return {"messages": out, "ask_contact": True, "ask_email": False, "form": None, "human": False}
        link = _native_booking_link(db, s)
        if link:          # BOOKING-LINK: a business with the full booking gets a real calendar, not a request form
            out.append(wc.append_message(db, s, "bot", _booking_link_text(link)))
        else:
            out.append(wc.append_message(db, s, "bot", "Great. Fill in the details below and we will confirm."))
            form = "booking"
    elif item:
        ad_sc = _ad_shortcut_tap(cfg, s, item) if kind == "menu" else None
        reply_text = _ad_shortcut_text(db, s, cfg, item, ad_sc) if ad_sc else _answer_text(item)          # AD-PRODUCT-1: this ad's own wording, or the general answer plus a catalogue line
        out.append(wc.append_message(db, s, "bot", reply_text))
        bk_offer = _booking_offer(cfg, reply_text) if item.get("action") != "booking" else None
        wc.set_state(db, s, answers=int(state.get("answers") or 0) + 1, open_offer=(bk_offer or {}).get("id"))
        just_answered = True
        choices = _ad_followups(cfg, s, item) if ad_sc else smart.related(cfg, item)                # SMART-1: where to go next, so the visitor is never at a dead end
    elif kind == "text" and (info := smart.info_answer(cfg, visitor_text)):
        out.append(wc.append_message(db, s, "bot", info))           # SMART-1: hours, phone, address from the business's own details, free
        wc.set_state(db, s, answers=int(state.get("answers") or 0) + 1)
        just_answered = True
        choices = smart.related(cfg, {})
    elif kind == "text" and handover.asks_where_team(visitor_text) and handover.where_team(cfg):
        wt = handover.where_team(cfg)         # a question about the screen: show the button, no hand-over, no AI call
        out.append(wc.append_message(db, s, "bot", wt["text"]))
        choices = wt["choices"]
    elif kind == "text" and cfg.get("ai_enabled") and not _has_contact(s) and not cfg.get("answer_first"):
        # WEBCHAT-3: AI needs a contact first, so ask for one instead of the generic fallback
        wc.set_state(db, s, pending_question=visitor_text[:300])
        if contact.enabled(cfg):
            out.append(contact.start(db, s, cfg, "Happy to help with that."))
            return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": False, "contact_step": "name"}
        out.append(wc.append_message(db, s, "bot", "Happy to help with that. First, " + cfg["contact_prompt"][0].lower() + cfg["contact_prompt"][1:]))
        return {"messages": out, "ask_contact": True, "ask_email": False, "form": None, "human": False}
    else:
        junk = not re.search(r"[A-Za-z0-9]{2}", visitor_text or "")      # COST: an emoji, a lone letter or '???' is not worth an AI call
        ai = webchat_ai_service.answer(db, s, cfg, visitor_text) if (kind == "text" and not junk) else None
        if not ai and loose_item and loose_item.get("action") not in ("human", "booking"):
            out.append(wc.append_message(db, s, "bot", _answer_text(loose_item)))        # no AI answer: the old keyword answer beats "I cannot answer"
            wc.set_state(db, s, answers=int(state.get("answers") or 0) + 1)
            just_answered = True
        elif ai:
            if ai["handoff"] and (cfg.get("shop_enabled") or cfg.get("products_read")):
                # BASIC-Q-1: the AI could not find the detail, but the visitor is looking at a product: answer from its catalogue
                # text and offer the team, instead of calling the team in and asking for contact details.
                pa = webchat_shop_service.product_answer(db, s, cfg, visitor_text)
                if pa:
                    ai = {"reply": pa, "handoff": False, "products": [], "offer_team": True}
            out.append(wc.append_message(db, s, "bot", ai["reply"]))
            if not ai["handoff"]:
                wc.set_state(db, s, answers=int((s.get("state") or {}).get("answers") or 0) + 1)     # counts as the first answer: details are asked next
                just_answered = True
            if cfg.get("shop_enabled") and ai.get("products"):
                cards = webchat_shop_service.cards_for(db, s["org_id"], ai["products"])
            if not ai["handoff"]:
                choices = handover.reply_choices(cfg, ai["reply"], bool(ai.get("offer_team")))     # buttons she names or offers are shown
            if ai["handoff"]:
                _record_gap(db, s, visitor_text)
                wc.set_human(db, s)
                _notify_human(db, s, cfg, "The assistant could not answer: " + visitor_text)
                if not _has_contact(s):          # answer_first: the team cannot reach a visitor with no details, so ask for them now
                    if contact.enabled(cfg):
                        out.append(contact.start(db, s, cfg, ""))
                        return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True, "cards": cards, "contact_step": "name"}
                    return {"messages": out, "ask_contact": True, "ask_email": False, "form": None, "human": True, "cards": cards}
                return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True, "cards": cards}
        elif kind == "text" and not junk and cfg.get("shop_enabled") and (pm := webchat_shop_service.text_matches(db, s["org_id"], visitor_text)):
            out.append(wc.append_message(db, s, "bot", webchat_shop_service.match_reply(pm)))        # BOT-PRODUCTS-1: no AI, but the words name a product: show it
            cards = webchat_shop_service.cards_for(db, s["org_id"], [str(p["id"]) for p in pm])
            wc.set_state(db, s, answers=int(state.get("answers") or 0) + 1)
            just_answered = True
        elif kind == "text" and _BROAD.search(visitor_text or "") and _overview(cfg):
            ov = _overview(cfg)                   # MATCH-2: a broad question and nobody to read it: show the buttons, not a wrong answer
            out.append(wc.append_message(db, s, "bot", ov["text"]))
            choices = ov["choices"]
        else:
            na = handover.no_answer(cfg)          # ONLY-1c-DOWN: hours-aware, with menu / message / call choices
            out.append(wc.append_message(db, s, "bot", na["text"]))
            choices = na["choices"]
            if kind == "text" and not junk:
                _record_gap(db, s, visitor_text)
            if handover.is_away(cfg):                # SMART-1: nobody is there now, so a booking is the most useful first button
                bk = next((m for m in cfg.get("menu", []) if m.get("action") == "booking"), None)
                if bk:
                    choices = [smart._item_choice(bk)] + [c for c in choices if c.get("id") != "item"]

    state = s.get("state") or {}
    answered = int(state.get("answers") or 0) >= 1
    ask_contact = answered and not _has_contact(s)
    if ask_contact and contact.enabled(cfg) and contact.step_of(s):
        ask_contact = False               # the details script is already open (a question was answered mid-script): do not start a second one
    elif ask_contact and contact.enabled(cfg):
        # NAME-AT-ACTION-1: a plain answer never triggers the name question. Details are asked only when the visitor
        # takes an action that needs them (book, call back, check out, send a file or voice note, ask for the team).
        ask_contact = False
    ask_email = (answered and _has_contact(s) and s.get("phone_verified") and not s.get("contact_email")
                 and not state.get("email_asked"))
    if ask_email:
        wc.set_state(db, s, email_asked=True)
    if just_answered and not ask_contact and (s.get("state") or {}).get("offer") == "shown":
        # HUMAN-OFFER-1: they took the offer and got an answer: ask once whether that was enough, with the team one tap away
        out.append(wc.append_message(db, s, "bot", "Did that help? If not, I can bring in the team."))
        if not any(c.get("id") == "human" for c in choices):
            choices = choices + [{"id": "human", "label": "Leave a message" if handover.is_away(cfg) else "Talk to the team"}]
        wc.set_state(db, s, offer="answered")
        wc.log_event(db, s["org_id"], s["id"], "tap", s.get("source"), ref="offer_answered")
    res = {"messages": out, "ask_contact": ask_contact, "ask_email": bool(ask_email), "form": form, "human": False, "cards": cards}
    if choices:
        res["choices"] = choices
    return res


def handle_contact(db, s: dict, cfg: dict, *, name, phone, email, consent: bool) -> dict:
    """Validate, create/find the lead, flush earlier messages, and carry on with anything that was waiting."""
    verified = bool(s.get("phone_verified")) and bool(s.get("lead_id"))
    clean, err = wc.validate_contact(name or s.get("contact_name"), phone or (s.get("contact_phone") if verified else None),
                                     email, consent, require_name=not verified)
    if err:
        return {"error": err}
    s = wc.save_contact(db, s, clean)
    after_note = (s.get("state") or {}).get("contact_after")      # read before the step state is cleared
    resume = (s.get("state") or {}).get("contact_resume")
    contact._clear(db, s)                      # WEBCHAT-CONTACT-1: the form (or the in-chat steps) is done, so no step stays open
    out, form, cards = [], None, []
    pending = (s.get("state") or {}).get("pending")
    if resume == "checkout" and webchat_shop_service._cart(s):       # ORDER-CONFIRM-1: they pressed Pay first: carry on to checkout now
        res = webchat_shop_service.checkout(db, s, cfg)
        if not res.get("error"):
            first = wc.append_message(db, s, "bot", "Thank you. We have your details.")
            return {"messages": [first] + list(res.get("messages") or []), "form": None, "cards": [], "cart": res.get("cart"),
                    "human": bool(res.get("human"))}
    if pending == "booking":
        wc.set_state(db, s, pending=None)
        link = _native_booking_link(db, s)
        if link:
            out.append(wc.append_message(db, s, "bot", "Thank you. " + _booking_link_text(link)))
        else:
            out.append(wc.append_message(db, s, "bot", "Thank you. Now tell us what you need and we will confirm."))
            form = "booking"
    else:
        out.append(wc.append_message(db, s, "bot", "Thank you. We have your details."))
        waiting = (s.get("state") or {}).get("pending_question")
        if waiting:
            wc.set_state(db, s, pending_question=None)
            ai = webchat_ai_service.answer(db, s, cfg, waiting)   # WEBCHAT-3: answer what they asked before the form
            if ai:
                out.append(wc.append_message(db, s, "bot", ai["reply"]))
                if cfg.get("shop_enabled") and ai.get("products"):
                    cards = webchat_shop_service.cards_for(db, s["org_id"], ai["products"])
                if ai["handoff"]:
                    wc.set_human(db, s)
                    _notify_human(db, s, cfg, "The assistant could not answer: " + waiting)
            else:
                # WEBCHAT-MENU-1: the AI could not answer now (allowance, limit, error). Never leave the visitor hanging after the
                # form: answer from the catalogue if they are on a product, otherwise say what happens next and tell the team.
                scripted = webchat_shop_service.product_answer(db, s, cfg, waiting)
                if scripted:
                    out.append(wc.append_message(db, s, "bot", scripted))
                else:
                    out.append(wc.append_message(db, s, "bot", "I could not find that to answer right now, so I have passed your question to the team. They will reply here as soon as they can."))
                    _notify_human(db, s, cfg, "Asked before sharing details: " + waiting)
        else:
            after = after_note
            offer = _open_offer_item(cfg, s)
            if offer and not after:
                # OPEN-OFFER-1: they were asked "Want to book a time?" before their details were taken: ask it again, with the button
                first = (s.get("contact_name") or "").split(" ")[0]
                out.append(wc.append_message(db, s, "bot", f"Thank you{', ' + first if first else ''}. Would you like to book a time?"))
                return {"messages": out, "form": form, "cards": cards, "choices": [smart._item_choice(offer)]}
            if after:
                out.append(wc.append_message(db, s, "bot", after))
            elif cfg.get("ai_enabled"):
                tip = " or tap Menu" if cfg.get("menu") else ""
                out.append(wc.append_message(db, s, "bot", "What would you like to know? You can type your question" + tip + "."))
            else:
                # BOT-WORDING-1: nothing reads free questions here, so do not invite them: show what can be tapped
                ov = _overview(cfg)
                out.append(wc.append_message(db, s, "bot", "What would you like to know? Tap one of these."))
                if ov:
                    return {"messages": out, "form": form, "cards": cards, "choices": ov["choices"]}
    return {"messages": out, "form": form, "cards": cards}


def handle_booking(db, s: dict, cfg: dict, fields: dict) -> dict:
    if not _has_contact(s):
        return {"error": "Please share your contact details first."}
    clean: dict = {}
    for f in cfg["booking_fields"]:
        v = wc._clean_text((fields or {}).get(f["key"]), 300)
        if f.get("required", True) and not v:
            return {"error": f"Please fill in: {f['label']}"}
        if v:
            clean[f["key"]] = v
    summary = "; ".join(f"{next((f['label'] for f in cfg['booking_fields'] if f['key'] == k), k)}: {v}" for k, v in clean.items())
    out = [wc.append_message(db, s, "visitor", "Booking request — " + summary)]
    try:
        from app.services import lead_service
        lead_service.write_timeline_event(db, s["org_id"], s["lead_id"], event_type="webchat_booking", actor_id=None,
                                          description="Booking request from web chat: " + summary[:500], metadata=clean)
    except Exception as exc:
        logger.warning("webchat booking timeline failed: %s", exc)
    wc.notify_managers(db, s["org_id"], f"Booking request: {s.get('contact_name') or 'web chat visitor'}", summary[:500],
                       s["lead_id"], "webchat_booking")
    wc.log_event(db, s["org_id"], s["id"], "booked", s.get("source"))
    try:
        from app.services import webchat_followup_service as fu
        fu.send_booking_confirmation(db, s, cfg, summary)       # WEBCHAT-4/4b
    except Exception as exc:
        logger.warning("webchat booking email hook failed: %s", exc)
    out.append(wc.append_message(db, s, "bot", cfg["booking_done"]))
    return {"messages": out}
