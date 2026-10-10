/**
 * frontend/src/services/builder_portal.service.js
 * SITE-2B — builder-portal API client. Prefix: /api/v1/builder.
 *
 * Deliberately separate from services/api.js (the staff client): the builder
 * portal is a standalone public page (pages/BuilderPortalPage.jsx, matched in
 * App.jsx via `/b/*`, outside AppShell/authStore entirely) and its JWT is a
 * completely different credential — a staff session must never be sent here
 * and vice versa (spec §10 / backend routers/builder_portal.py).
 *
 * Same security rule as the staff app (Technical Spec §11.1): the builder JWT
 * lives in memory only (React state in BuilderPortalPage), never localStorage
 * / sessionStorage. Every function below takes the token as an explicit first
 * argument rather than reading a shared store, so that rule is structural,
 * not just a convention someone has to remember.
 *
 * Every function returns the response's `data` payload (the ok() envelope is
 * unwrapped), matching sites.service.js's `unwrap` convention.
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1/builder`
  : '/api/v1/builder'

const authed = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const unwrap = (p) => p.then((r) => r.data?.data ?? r.data)

// ── Auth ─────────────────────────────────────────────────────────────────
/** Exchanges a magic-link token (the `t=` value from /b/login?t=...) for a
 * builder session. Returns { access_token, expires_at, builder }. */
export const exchangeBuilderToken = (rawToken) =>
  unwrap(axios.post(`${BASE}/auth/exchange`, { token: rawToken }))

// ── Account ──────────────────────────────────────────────────────────────
export const getMyAccount = (token) => unwrap(axios.get(`${BASE}/me`, authed(token)))
/** payload: any of { full_name, business_name, email } */
export const updateMyAccount = (token, payload) => unwrap(axios.patch(`${BASE}/me`, payload, authed(token)))

/** SITE-WEB-2: change the WhatsApp number. A code is emailed to the address on the account; then confirm it. */
export const startPhoneChange = (token, phone) => unwrap(axios.post(`${BASE}/me/phone/start`, { phone }, authed(token)))
export const verifyPhoneChange = (token, requestId, code) =>
  unwrap(axios.post(`${BASE}/me/phone/verify`, { request_id: requestId, code }, authed(token)))

/** SITE-WEB-2: a wa.me link to the Site Builder WhatsApp with `text` already typed. The builder presses send, which is
 * their first message, so WhatsApp lets us reply (a sign-in link, order updates) with no approved template.
 * Built from VITE_BUILDER_JOIN_URL; returns '' when that isn't set. */
export function whatsappLink(text) {
  const base = import.meta.env.VITE_BUILDER_JOIN_URL || ''
  if (!base) return ''
  try {
    const u = new URL(base)
    u.searchParams.set('text', text)
    return u.toString()
  } catch {
    return base
  }
}

// ── My sites ─────────────────────────────────────────────────────────────
export const listMySites = (token) => unwrap(axios.get(`${BASE}/sites`, authed(token)))
export const getMySite = (token, siteId) => unwrap(axios.get(`${BASE}/sites/${siteId}`, authed(token)))

// ── Editor ───────────────────────────────────────────────────────────────
export const patchMySiteContent = (token, siteId, content) =>
  unwrap(axios.patch(`${BASE}/sites/${siteId}/content`, { content }, authed(token)))
export const patchMySiteRecipe = (token, siteId, recipe) =>
  unwrap(axios.patch(`${BASE}/sites/${siteId}/recipe`, { recipe }, authed(token)))
export const suggestMyDesigns = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/design/suggest`, null, authed(token)))
export const applyMyDesign = (token, siteId, recipe) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/design/apply`, { recipe }, authed(token)))
// SITE-PREMIUM P4-2: the customer's colour and font look for a Premium site
export const getPremiumLook = (token, siteId) =>
  unwrap(axios.get(`${BASE}/sites/${siteId}/premium/look`, authed(token)))
export const previewPremiumLook = (token, siteId, look) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/look/preview`, look, authed(token)))
export const applyPremiumLook = (token, siteId, look) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/look`, look, authed(token)))
export const undoPremiumLook = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/look/undo`, null, authed(token)))
export const getPremiumHistory = (token, siteId) =>
  unwrap(axios.get(`${BASE}/sites/${siteId}/premium/history`, authed(token)))
export const getPremiumHistoryPreview = (token, siteId, designId) =>
  unwrap(axios.get(`${BASE}/sites/${siteId}/premium/history/${designId}/preview`, authed(token)))
export const restorePremiumVersion = (token, siteId, designId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/history/${designId}/restore`, null, authed(token)))
// ── Buying Premium (P5) ─────────────────────────────────────────────────────
/** → { offer: { available, state, design_fee, total, golive_balance, ... }, tier } */
export const getPremiumOffer = (token, siteId) =>
  unwrap(axios.get(`${BASE}/sites/${siteId}/premium/offer`, authed(token)))
/** what: 'design' | 'redesign' → { checkout_url, amount, kind, reused } */
export const premiumCheckout = (token, siteId, what) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/checkout`, { what }, authed(token)))
export const retryPremiumDesign = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/retry`, null, authed(token)))
export const refundPremiumFee = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/refund`, null, authed(token)))
export const getPremiumRedesign = (token, siteId) =>
  unwrap(axios.get(`${BASE}/sites/${siteId}/premium/redesign`, authed(token)))
export const startPremiumRedesign = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/redesign`, null, authed(token)))
export const getPremiumRedesignPreview = (token, siteId) =>
  unwrap(axios.get(`${BASE}/sites/${siteId}/premium/redesign/preview`, authed(token)))
export const keepPremiumRedesign = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/redesign/keep`, null, authed(token)))
export const discardPremiumRedesign = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/premium/redesign/discard`, null, authed(token)))
export const renderMySite = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/render`, null, authed(token)))
export const undoMySite = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/undo`, null, authed(token)))
export const uploadMySiteAsset = (token, siteId, slot, file) => {
  const form = new FormData()
  form.append('file', file)
  // Deliberately NOT setting Content-Type ourselves: axios/the browser needs
  // to generate it (multipart/form-data; boundary=...) from the FormData
  // object itself. Hard-coding 'multipart/form-data' here would send that
  // header with no boundary, which the browser then honours as explicitly
  // set rather than filling in — the request leaves with a body FastAPI
  // can't parse as multipart, and fails before any response detail comes
  // back (surfacing as the generic "Could not upload this photo" fallback
  // rather than a real server error message).
  return unwrap(axios.post(`${BASE}/sites/${siteId}/assets`, form, {
    params: { slot },
    headers: authed(token).headers,
  }))
}

// ── Hosting checkout (SITE-3) ───────────────────────────────────────────────
/** { domain } → { domain, status, available, alternatives } */
export const checkDomain = (token, domain) =>
  unwrap(axios.post(`${BASE}/domains/check`, { domain }, authed(token)))
/** { domain, kind } → { standard: {...}|{error}, express: {...}|null|{error} } */
export const getQuote = (token, domain, kind = 'initial', discountCode, siteId) =>
  unwrap(axios.post(`${BASE}/quotes`, { domain, kind, ...(discountCode ? { discount_code: discountCode } : {}), ...(siteId && kind === 'initial' ? { site_id: siteId } : {}) }, authed(token)))
/** payload: { site_id, route, domain, backup_domain, legal_owner, accepted_terms }
 * → { checkout_url, reference, order_id, amount } */
export const checkout = (token, payload) =>
  unwrap(axios.post(`${BASE}/checkout`, payload, authed(token)))

// ── Renewals (SITE-4) ───────────────────────────────────────────────────────
/** → { checkout_url, amount, domain, expires_on, reused } (422 when it is too early to renew) */
export const renewalCheckout = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/renewal-checkout`, {}, authed(token)))

// ── Care plans & extra edits (SITE-4B) ──────────────────────────────────────
/** what = 'plan' | 'pack' → { checkout_url, amount, kind } */
export const careCheckout = (token, siteId, what) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/care-plan/checkout`, { what }, authed(token)))
/** cancel = true keeps the plan until the end of the paid month; false takes it back. */
export const cancelCarePlan = (token, siteId, cancel = true) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/care-plan/cancel`, { cancel }, authed(token)))
/** GIVEAWAY-2 — buy a pack of extra catalog items for one site → { checkout_url, amount, items } */
export const catalogCheckout = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/catalog/checkout`, {}, authed(token)))
/** The offer a 402 CATALOG_LIMIT response carries (the item limit and the pack on sale), or null for any other error. */
export const catalogLimitOffer = (err) => {
  const d = err?.response?.data?.detail
  return err?.response?.status === 402 && d?.code === 'CATALOG_LIMIT' ? { ...(d.offer || {}), message: d.message } : null
}
/** The offer a 402 EDIT_LIMIT_REACHED response carries, or null for any other error. */
export const editLimitOffer = (err) => {
  const d = err?.response?.data?.detail
  return err?.response?.status === 402 && d?.code === 'EDIT_LIMIT_REACHED' ? (d.offer || {}) : null
}

/** Pull a readable message out of an axios error — same shape as sites.service.js's helper. */
export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  const d = err?.response?.data?.detail
  if (!d) return fallback
  if (typeof d === 'string') return d
  if (d.message) return d.message
  if (Array.isArray(d) && d.length) {
    const first = d[0]
    const field = Array.isArray(first.loc) ? first.loc.filter((x) => x !== 'body').join(' › ') : ''
    return field ? `${field}: ${first.msg}` : first.msg
  }
  return fallback
}

/** Landing-page sign-in: asks the server to send a magic link to the builder's own
 * WhatsApp/email. The reply never says whether the number exists. */
export const requestBuilderLink = (phone) =>
  unwrap(axios.post(`${BASE}/auth/request-link`, { phone }))

// ── Web sign-up (SITE-WEB-1) ────────────────────────────────────────────────
/** payload: { full_name, email, phone, account_type: 'builder'|'owner', accept_terms, website (honeypot) }
 * → { request_id, email_hint }. A code is emailed; nothing is created yet. */
export const startSignup = (payload) => unwrap(axios.post(`${BASE}/auth/signup/start`, payload))
/** → { token, builder }. Open `/b/login?t=<token>` to start the session. */
export const verifySignup = (requestId, code) =>
  unwrap(axios.post(`${BASE}/auth/signup/verify`, { request_id: requestId, code }))

// ── Free sites and the builder subscription (SITE-ACCESS-1) ─────────────────
/** → { used, free_sites, free_left, subscribed, subscribed_until, can_create, price_ngn, days } */
export const getAccess = (token) => unwrap(axios.get(`${BASE}/access`, authed(token)))
/** → { checkout_url, amount, days, reused } */
export const accessCheckout = (token) => unwrap(axios.post(`${BASE}/access/checkout`, null, authed(token)))
/** The detail a 403 ACCESS_LIMIT response carries ({ message, access }), or null for any other error. */
export const accessLimit = (err) => {
  const d = err?.response?.data?.detail
  return err?.response?.status === 403 && d?.code === 'ACCESS_LIMIT' ? d : null
}

// ── Start a site from the web (SITE-WEB-1) ──────────────────────────────────
export const listPresets = (token) => unwrap(axios.get(`${BASE}/presets`, authed(token)))
export const listMyForms = (token) => unwrap(axios.get(`${BASE}/forms`, authed(token)))
/** payload: { audience: 'builder'|'client', preset_id?, client_label? } → { id, url, expires_at, ... } (link shown once) */
export const createMyForm = (token, payload) => unwrap(axios.post(`${BASE}/forms`, payload, authed(token)))
export const revokeMyForm = (token, formId) => unwrap(axios.post(`${BASE}/forms/${formId}/revoke`, null, authed(token)))

// ── SITE-ADDONS A0-3 — plans for a client's site ──────────────────────────────
export const getSiteAddonPlans = (token, siteId) => unwrap(axios.get(`${BASE}/sites/${siteId}/addons`, authed(token)))
/** payload: { kind, key, picks?, payer?: {name, phone, email}, send? } — returns { addon_id, pay_url, scheduled, quote, sent? }. */
export const startSiteAddonPlan = (token, siteId, payload) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/addons/checkout`, payload, authed(token)))
