"""
app/models/sites.py
--------------------
SITE-1A — Pydantic models for the Site Engine (Trust's own org, site_builder mode).

Used by:
  • routers/sites.py (internal CRUD, content/recipe edits, presets, builders)
  • routers/public_sites.py (the public preview route reads validated `content`
    already stored on the row — it does not re-validate here)
  • services/site_renderer.py (SiteContentV1 / Recipe are what it renders)

Per SITE-0 spec §8.2/§8.3. Every string has a maximum length; prices are positive with
at most 2 decimal places; reviews are never generated here (they only ever come from the
builder — see spec §8.2 and services/site_copy_service.py, SITE-2).
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_KEY_RE = re.compile(r"^[a-z0-9_]{1,50}$")
_SLUG_RE = re.compile(r"^[a-z0-9-]{3,60}$")

PriceStyle = Literal["exact", "from", "on_request"]
SiteStatus = Literal[
    "brief_in_progress", "brief_complete", "generating", "preview_ready", "revising",
    "hosting_checkout", "awaiting_payment", "paid", "publishing", "live",
    "renewal_due", "lapsed", "cancelled",
]
ContentSource = Literal["ai", "builder_words", "manual"]


# ───────────────────────────── Content JSON (SiteContentV1) ─────────────────────────────

class SiteBusiness(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=120)
    city: str = Field("", max_length=80)
    tagline: str = Field("", max_length=160)
    whatsapp_e164: str = Field(..., min_length=8, max_length=20)
    phone_display: str = Field("", max_length=30)
    instagram: str = Field("", max_length=60)
    delivery_note: str = Field("", max_length=200)

    @field_validator("whatsapp_e164")
    @classmethod
    def _e164(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\+?[0-9]{8,18}$", v):
            raise ValueError("whatsapp_e164 must be digits, optionally prefixed with +")
        return v if v.startswith("+") else "+" + v


class SiteHero(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    headline: str = Field(..., min_length=1, max_length=140)
    subhead: str = Field("", max_length=240)
    image_asset_id: Optional[str] = None


class SiteAbout(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field("", max_length=140)
    body: list[str] = Field(default_factory=list, max_length=6)
    owner: str = Field("", max_length=100)
    pull_quote: str = Field("", max_length=240)
    image_asset_id: Optional[str] = None

    @field_validator("body")
    @classmethod
    def _body_len(cls, v: list[str]) -> list[str]:
        for p in v:
            if len(p) > 600:
                raise ValueError("about.body paragraphs are limited to 600 characters")
        return v


class SiteItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=100)
    desc: str = Field("", max_length=300)
    price_ngn: float = Field(0, ge=0, le=100_000_000)
    price_style: PriceStyle = "exact"
    tag: Optional[str] = Field(None, max_length=30)
    image_asset_id: Optional[str] = None

    @field_validator("price_ngn")
    @classmethod
    def _two_dp(cls, v: float) -> float:
        if round(v, 2) != v:
            raise ValueError("price_ngn allows at most 2 decimal places")
        return v


class SiteCategory(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=60)
    teaser: str = Field("", max_length=140)
    image_asset_id: Optional[str] = None


class SiteReview(BaseModel):
    """Reviews only ever come from the builder — the AI never invents them (spec §8.2)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field(..., min_length=1, max_length=400)
    who: str = Field("", max_length=80)


class SiteHours(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    days: str = Field(..., min_length=1, max_length=40)
    time: str = Field(..., min_length=1, max_length=40)


class SiteLocation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    address: str = Field("", max_length=200)
    landmark: str = Field("", max_length=120)


class SiteOrderSection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field("", max_length=100)
    steps: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("steps")
    @classmethod
    def _step_len(cls, v: list[str]) -> list[str]:
        for s in v:
            if len(s) > 160:
                raise ValueError("order_section.steps entries are limited to 160 characters")
        return v


class SiteAnnouncement(BaseModel):
    """SITE-1C-3: one short line shown in a bar above the menu (a promo, a delivery cut-off)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field("", max_length=140)


class SiteBanner(BaseModel):
    """SITE-1C-3f: a closing full-width photo banner (headline, a line of text, a WhatsApp button)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    eyebrow: str = Field("", max_length=60)
    headline: str = Field("", max_length=100)
    text: str = Field("", max_length=300)
    button_text: str = Field("", max_length=40)
    image_asset_id: Optional[str] = None


class SiteFaq(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    q: str = Field(..., min_length=1, max_length=140)
    a: str = Field(..., min_length=1, max_length=600)


class SiteMenuLine(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=100)
    desc: str = Field("", max_length=200)
    price_ngn: float = Field(0, ge=0, le=100_000_000)
    price_style: PriceStyle = "exact"

    @field_validator("price_ngn")
    @classmethod
    def _two_dp(cls, v: float) -> float:
        if round(v, 2) != v:
            raise ValueError("price_ngn allows at most 2 decimal places")
        return v


class SiteMenuGroup(BaseModel):
    """A heading with its priced lines: a price list or a menu (SITE-1C-3)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=60)
    lines: list[SiteMenuLine] = Field(default_factory=list, max_length=15)


class SiteProcessStep(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(..., min_length=1, max_length=80)
    text: str = Field("", max_length=300)


class SiteProcess(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field("", max_length=100)
    steps: list[SiteProcessStep] = Field(default_factory=list, max_length=6)


class SiteTeamMember(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=80)
    role: str = Field("", max_length=80)
    bio: str = Field("", max_length=300)
    image_asset_id: Optional[str] = None


class SiteGalleryImage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    caption: str = Field("", max_length=100)
    image_asset_id: Optional[str] = None


class SiteSeo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field("", max_length=70)
    description: str = Field("", max_length=200)


class SiteContentV1(BaseModel):
    """
    The generic content JSON every niche renders from. The preset's `labels`
    decide what `items` are called on the page (spec §8.2) — this model does
    not know about niches at all.
    """
    model_config = ConfigDict(str_strip_whitespace=True)
    business: SiteBusiness
    hero: SiteHero
    about: SiteAbout = Field(default_factory=lambda: SiteAbout(title="", body=[], owner="", pull_quote=""))
    items: list[SiteItem] = Field(default_factory=list, max_length=60)
    categories: list[SiteCategory] = Field(default_factory=list, max_length=20)
    reviews: list[SiteReview] = Field(default_factory=list, max_length=20)
    hours: list[SiteHours] = Field(default_factory=list, max_length=7)
    location: SiteLocation = Field(default_factory=SiteLocation)
    order_section: SiteOrderSection = Field(default_factory=SiteOrderSection)
    # SITE-1C-3: optional extra sections. Every field has an empty default, so content saved
    # before this phase stays valid and renders exactly as before. Hours and location (already
    # above) feed the new "visit" section.
    announcement: SiteAnnouncement = Field(default_factory=SiteAnnouncement)
    faqs: list[SiteFaq] = Field(default_factory=list, max_length=12)
    menu: list[SiteMenuGroup] = Field(default_factory=list, max_length=8)
    process: SiteProcess = Field(default_factory=SiteProcess)
    team: list[SiteTeamMember] = Field(default_factory=list, max_length=6)
    gallery: list[SiteGalleryImage] = Field(default_factory=list, max_length=9)
    banner: SiteBanner = Field(default_factory=SiteBanner)   # SITE-1C-3f
    seo: SiteSeo = Field(default_factory=SiteSeo)


# ───────────────────────────────── Recipe (design choice) ─────────────────────────────────

class SectionVariants(BaseModel):
    """Only the keys for sections actually used matter; unknown keys are ignored by the renderer."""
    model_config = ConfigDict(extra="allow")
    hero: Optional[str] = None
    items: Optional[str] = None
    about: Optional[str] = None
    reviews: Optional[str] = None
    categories: Optional[str] = None
    order: Optional[str] = None
    # SITE-1C-3
    announcement: Optional[str] = None
    faq: Optional[str] = None
    menu: Optional[str] = None
    visit: Optional[str] = None
    process: Optional[str] = None
    team: Optional[str] = None
    gallery: Optional[str] = None
    banner: Optional[str] = None   # SITE-1C-3f


class RecipeTokens(BaseModel):
    """SITE-1C-1 design tokens. Values are checked against site_design_registry.TOKENS by
    site_renderer.validate_recipe (so the option lists live in one place). Unknown keys -> 422."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    radius: Optional[str] = Field(None, max_length=20)
    density: Optional[str] = Field(None, max_length=20)
    button: Optional[str] = Field(None, max_length=20)
    heading_case: Optional[str] = Field(None, max_length=20)
    image_style: Optional[str] = Field(None, max_length=20)
    divider: Optional[str] = Field(None, max_length=20)
    background: Optional[str] = Field(None, max_length=20)
    bands: Optional[str] = Field(None, max_length=20)
    cards: Optional[str] = Field(None, max_length=20)
    finish: Optional[str] = Field(None, max_length=20)   # SITE-1C-3d: "standard" | "refined"
    hero_height: Optional[str] = Field(None, max_length=20)   # SITE-1C-3e: "standard" | "tall"
    mobile_cols: Optional[str] = Field(None, max_length=20)   # SITE-1C-3f: "two" | "one"
    image_fit: Optional[str] = Field(None, max_length=20)     # SITE-1C-3g: "center" | "top" | "whole"


class Recipe(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    theme: str = Field(..., max_length=40)
    palette: Optional[str] = Field(None, max_length=40)
    custom_colour: Optional[str] = Field(None, max_length=20)
    fonts: Optional[str] = Field(None, max_length=60)
    tokens: Optional[RecipeTokens] = None
    variants: SectionVariants = Field(default_factory=SectionVariants)
    order: list[str] = Field(..., min_length=1, max_length=16)
    hidden: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _palette_or_custom(self):
        if not self.palette and not self.custom_colour:
            raise ValueError("recipe needs either a named palette or a custom_colour")
        return self

    @field_validator("custom_colour")
    @classmethod
    def _hex(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("custom_colour must be a 6-digit hex colour, e.g. #7A2E4A")
        return v.upper()


# ───────────────────────────────── Presets (site_presets) ─────────────────────────────────

class PresetLabels(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)
    items: str = Field("Shop", max_length=40)
    item: str = Field("Item", max_length=40)
    price_style: PriceStyle = "exact"
    cta: str = Field("Order on WhatsApp", max_length=40)


class SitePresetCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    key: str = Field(..., max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    sections: list[str] = Field(..., min_length=1, max_length=16)
    labels: PresetLabels = Field(default_factory=PresetLabels)
    brief_questions: list[dict] = Field(default_factory=list, max_length=40)
    wa_messages: dict[str, str] = Field(default_factory=dict)
    allowed_themes: list[str] = Field(..., min_length=1, max_length=10)
    default_palettes: list[str] = Field(default_factory=list, max_length=30)
    allowed_fonts: list[str] = Field(default_factory=list, max_length=20)
    token_options: dict[str, list[str]] = Field(default_factory=dict)
    allowed_variants: dict[str, list[str]] = Field(default_factory=dict)
    ai_tone: str = Field("", max_length=300)
    max_items: int = Field(20, ge=1, le=60)
    is_active: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("preset key must be lowercase letters, digits, underscore")
        return v


class SitePresetUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    sections: Optional[list[str]] = Field(None, min_length=1, max_length=16)
    labels: Optional[PresetLabels] = None
    brief_questions: Optional[list[dict]] = Field(None, max_length=40)
    wa_messages: Optional[dict[str, str]] = None
    allowed_themes: Optional[list[str]] = Field(None, min_length=1, max_length=10)
    default_palettes: Optional[list[str]] = Field(None, max_length=30)
    allowed_fonts: Optional[list[str]] = Field(None, max_length=20)
    token_options: Optional[dict[str, list[str]]] = None
    allowed_variants: Optional[dict[str, list[str]]] = None
    ai_tone: Optional[str] = Field(None, max_length=300)
    max_items: Optional[int] = Field(None, ge=1, le=60)
    is_active: Optional[bool] = None


# ───────────────────────────────── Sites (internal CRUD, SITE-1A) ─────────────────────────

class SiteCreate(BaseModel):
    """Internal, by-hand creation (Trust building a site directly, ahead of SITE-1B chat/form)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    builder_id: Optional[str] = None
    preset_id: str
    client_business_name: str = Field(..., min_length=1, max_length=255)
    content: SiteContentV1
    recipe: Recipe
    content_source: ContentSource = "manual"


class SiteContentPatch(BaseModel):
    content: SiteContentV1


class SiteRecipePatch(BaseModel):
    recipe: Recipe


class SiteAssetCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slot: str = Field(..., min_length=1, max_length=40)

    @field_validator("slot")
    @classmethod
    def _slot(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9_]{1,40}$", v):
            raise ValueError("slot must be lowercase letters, digits, underscore")
        return v


def slugify_business_name(name: str) -> str:
    """`{business-name}-{6 random chars}` per spec §5.3 — the random suffix is appended
    by the caller (services/site_renderer.generate_slug) after this normalises the name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)
    return (base or "site")[:40]


# ─────────────────────────── Brief forms (site_brief_forms, SITE-1B) ──────────────────────

import hashlib
import secrets as _secrets

FormAudience = Literal["builder", "client"]
FormStatus = Literal["open", "submitted", "expired", "revoked"]


def generate_form_token() -> tuple[str, str]:
    """
    Spec §18: form tokens are random, hashed, never stored raw.
    Returns (raw_token, token_hash) — the raw token is only ever handed back to the
    caller once (to build the `/f/{token}` link); only the SHA-256 hex digest is
    persisted in site_brief_forms.token_hash.
    """
    raw = _secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_form_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class SiteBriefFormCreate(BaseModel):
    """Internal, by-hand form creation (routers/sites.py) — the WhatsApp-driven creation
    in site_chat_service builds the same row shape directly."""
    model_config = ConfigDict(str_strip_whitespace=True)
    builder_id: str
    audience: FormAudience = "builder"
    preset_id: Optional[str] = None
    client_label: Optional[str] = Field(None, max_length=120)


class SiteBriefFormAnswersPatch(BaseModel):
    """PATCH /api/v1/forms/{token} — autosave. Merged into answers, never replaced wholesale,
    so an interrupted autosave never wipes earlier progress."""
    answers: dict = Field(default_factory=dict)
    preset_id: Optional[str] = None
    # Honeypot — spec §18. Real users never see or fill this field; the public frontend
    # renders it visually hidden. Any non-empty value here is treated as a bot and the
    # request is accepted (200) but silently dropped server-side.
    website: Optional[str] = Field(None, max_length=200)


class SiteBriefFormSubmit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    answers: dict = Field(default_factory=dict)
    client_business_name: str = Field(..., min_length=1, max_length=255)
    website: Optional[str] = Field(None, max_length=200)  # honeypot, see above


# ─────────────────────────── Hosting checkout (SITE-3, spec §11/§12/§17) ──────────────────

RouteChoice = Literal["standard", "express"]
QuoteKind = Literal["initial", "renewal"]


class DomainCheckRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    domain: str = Field(..., min_length=3, max_length=253)


class QuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    domain: str = Field(..., min_length=3, max_length=253)
    kind: QuoteKind = "initial"
    discount_code: Optional[str] = Field(None, max_length=40)


class LegalOwnerDetails(BaseModel):
    """spec §11.3 — the client's legal-owner details, used only for domain
    registration (spec §18, NDPR: never used for anything else)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=200)
    phone: str = Field(..., min_length=8, max_length=20)
    address: str = Field(..., min_length=1, max_length=300)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("legal_owner.email must be a valid email address")
        return v


class CheckoutRequest(BaseModel):
    """spec §11.3 — the builder chooses a route, confirms domain + backup,
    confirms the client's legal-owner details, and accepts the terms."""
    model_config = ConfigDict(str_strip_whitespace=True)
    site_id: str
    route: RouteChoice
    domain: str = Field(..., min_length=3, max_length=253)
    backup_domain: str = Field(..., min_length=3, max_length=253)
    legal_owner: LegalOwnerDetails
    accepted_terms: bool
    discount_code: Optional[str] = Field(None, max_length=40)   # SITE-DISCOUNT — re-validated server-side

    @field_validator("accepted_terms")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("The refund rule and renewal contact clause must be accepted to check out.")
        return v

    @model_validator(mode="after")
    def _backup_differs(self):
        if self.domain.strip().lower() == self.backup_domain.strip().lower():
            raise ValueError("The backup domain must be different from the main domain.")
        return self


# ─────────────────── Staff dashboard actions (SITE-3 part 3, spec §13 / §17) ───────────────────

class OrderRejectRequest(BaseModel):
    """Reject an awaiting_approval order, or refund a needs_builder_choice one."""
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(..., min_length=3, max_length=1000)


class RefundRecordedRequest(BaseModel):
    """The refund was already sent by hand in Paystack (v1, spec §11.8). Amount defaults to the computed refund."""
    amount: Optional[float] = Field(None, gt=0, le=100_000_000)


class OrderDomainChoice(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    domain: str = Field(..., min_length=3, max_length=253)


class HostingJobPatch(BaseModel):
    """Only the fields the caller sends are changed (model_dump(exclude_unset=True))."""
    model_config = ConfigDict(str_strip_whitespace=True)
    assigned_to: Optional[str] = Field(None, max_length=64)
    status: Optional[Literal["queued", "in_progress", "blocked"]] = None
    notes: Optional[str] = Field(None, max_length=5000)
    step: Optional[str] = Field(None, max_length=40)
    step_done: bool = True


class MarkLiveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    live_url: str = Field(..., min_length=8, max_length=500)


# ───────────────────────────── SITE-PREMIUM P1 ─────────────────────────────

class PremiumImportRequest(BaseModel):
    """Staff import of a hand-written Premium skeleton (HTML with an optional <style> block).
    Fonts must come from the Premium font registry; omitted = a safe default pair."""
    model_config = ConfigDict(str_strip_whitespace=True)
    html: str = Field(..., min_length=20, max_length=400_000)
    headline_font: Optional[str] = Field(None, max_length=60)
    body_font: Optional[str] = Field(None, max_length=60)


class PremiumUseDesign(BaseModel):
    design_id: str = Field(..., min_length=36, max_length=36)
