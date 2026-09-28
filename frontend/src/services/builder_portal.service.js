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

// ── My sites ─────────────────────────────────────────────────────────────
export const listMySites = (token) => unwrap(axios.get(`${BASE}/sites`, authed(token)))
export const getMySite = (token, siteId) => unwrap(axios.get(`${BASE}/sites/${siteId}`, authed(token)))

// ── Editor ───────────────────────────────────────────────────────────────
export const patchMySiteContent = (token, siteId, content) =>
  unwrap(axios.patch(`${BASE}/sites/${siteId}/content`, { content }, authed(token)))
export const patchMySiteRecipe = (token, siteId, recipe) =>
  unwrap(axios.patch(`${BASE}/sites/${siteId}/recipe`, { recipe }, authed(token)))
export const renderMySite = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/render`, null, authed(token)))
export const undoMySite = (token, siteId) =>
  unwrap(axios.post(`${BASE}/sites/${siteId}/undo`, null, authed(token)))
export const uploadMySiteAsset = (token, siteId, slot, file) => {
  const form = new FormData()
  form.append('file', file)
  return unwrap(axios.post(`${BASE}/sites/${siteId}/assets`, form, {
    params: { slot },
    headers: { ...authed(token).headers, 'Content-Type': 'multipart/form-data' },
  }))
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
