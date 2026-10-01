/**
 * frontend/src/services/sites.service.js
 * SITE-1A part 2 — Site Engine API (backend: routers/sites.py, prefix /api/v1/sites).
 *
 * Uses the central `api` instance (JWT from Zustand + silent refresh on 401).
 * Pattern 12: org_id is never sent — the backend takes it from the JWT.
 * Every function returns the response's `data` payload (the ok() envelope is unwrapped).
 */
import api from './api'

const unwrap = (p) => p.then((r) => r.data?.data ?? r.data)

// ── Overview ─────────────────────────────────────────────────────────────
export const getSitesOverview = () => unwrap(api.get('/api/v1/sites/overview'))

// ── Settings ─────────────────────────────────────────────────────────────
export const getSiteSettings = () => unwrap(api.get('/api/v1/sites/settings'))
export const updateSiteSettings = (payload) => unwrap(api.patch('/api/v1/sites/settings', payload))

// ── Discount codes (SITE-DISCOUNT) ─────────────────────────────────────────
export const listDiscountCodes = () => unwrap(api.get('/api/v1/sites/discount-codes'))
export const createDiscountCode = (payload) => unwrap(api.post('/api/v1/sites/discount-codes', payload))
export const updateDiscountCode = (id, payload) => unwrap(api.patch(`/api/v1/sites/discount-codes/${id}`, payload))
export const deleteDiscountCode = (id) => unwrap(api.delete(`/api/v1/sites/discount-codes/${id}`))

// ── Presets (Templates tab) ─────────────────────────────────────────────
export const listPresets = () => unwrap(api.get('/api/v1/sites/presets'))
export const suggestDesigns = (siteId) => unwrap(api.post(`/api/v1/sites/${siteId}/design/suggest`))
export const presetLookStats = () => unwrap(api.get('/api/v1/sites/presets/look-stats'))
export const createPreset = (payload) => unwrap(api.post('/api/v1/sites/presets', payload))
export const getPreset = (id) => unwrap(api.get(`/api/v1/sites/presets/${id}`))
export const updatePreset = (id, payload) => unwrap(api.patch(`/api/v1/sites/presets/${id}`, payload))
// `seed` (SITE-1C-1): let the server pick the look with the same seeded picker new sites use — returns { html, recipe }.
export const previewPreset = (id, recipe, seed) =>
  unwrap(api.post(`/api/v1/sites/presets/${id}/preview`, recipe, seed ? { params: { seed } } : undefined))

// ── Builders ─────────────────────────────────────────────────────────────
export const listBuilders = () => unwrap(api.get('/api/v1/sites/builders'))
export const createBuilder = (payload) => unwrap(api.post('/api/v1/sites/builders', payload))
export const updateBuilder = (id, payload) => unwrap(api.patch(`/api/v1/sites/builders/${id}`, payload))
export const importBuilders = (file) => {
  const form = new FormData()
  form.append('file', file)
  return unwrap(api.post('/api/v1/sites/builders/import', form, { headers: { 'Content-Type': 'multipart/form-data' } }))
}

// ── Brief forms (SITE-1B — by-hand link creation) ───────────────────────────
export const listBriefForms = (params) => unwrap(api.get('/api/v1/sites/forms', { params }))
/** payload: { builder_id, audience: 'builder'|'client', preset_id?, client_label? } */
export const createBriefForm = (payload) => unwrap(api.post('/api/v1/sites/forms', payload))
export const revokeBriefForm = (id) => unwrap(api.post(`/api/v1/sites/forms/${id}/revoke`))

// ── Editor magic links (SITE-2B — by-hand link creation, stand-in for the
// WhatsApp EDIT command until D4's site_builder number is supplied) ────────
export const createEditorLink = (builderId) => unwrap(api.post(`/api/v1/sites/builders/${builderId}/edit-link`))

// ── Sites ────────────────────────────────────────────────────────────────
export const listSites = (params) => unwrap(api.get('/api/v1/sites', { params }))
export const createSite = (payload) => unwrap(api.post('/api/v1/sites', payload))
export const getSite = (id) => unwrap(api.get(`/api/v1/sites/${id}`))
export const patchSiteContent = (id, content) => unwrap(api.patch(`/api/v1/sites/${id}/content`, { content }))
export const patchSiteRecipe = (id, recipe) => unwrap(api.patch(`/api/v1/sites/${id}/recipe`, { recipe }))
export const renderSite = (id) => unwrap(api.post(`/api/v1/sites/${id}/render`))
export const uploadSiteAsset = (id, slot, file) => {
  const form = new FormData()
  form.append('file', file)
  return unwrap(api.post(`/api/v1/sites/${id}/assets`, form, {
    params: { slot }, headers: { 'Content-Type': 'multipart/form-data' },
  }))
}

// ── SITE-3: Orders, Hosting queue, Domains & renewals (spec §13/§17) ─────────
export const listOrders = (params) => unwrap(api.get('/api/v1/sites/orders', { params }))
export const approveOrder = (id) => unwrap(api.post(`/api/v1/sites/orders/${id}/approve`))
export const rejectOrder = (id, reason) => unwrap(api.post(`/api/v1/sites/orders/${id}/reject`, { reason }))
/** amount is optional — the server defaults to the computed refund (amount paid − service fee). */
export const recordRefund = (id, amount) => unwrap(api.post(`/api/v1/sites/orders/${id}/refund-recorded`, amount ? { amount } : {}))
export const setOrderDomain = (id, domain) => unwrap(api.post(`/api/v1/sites/orders/${id}/set-domain`, { domain }))

export const listHostingJobs = (params) => unwrap(api.get('/api/v1/sites/hosting-jobs', { params }))
/** Only the keys you send change. assigned_to: user id | null · status · notes · step + step_done. */
export const patchHostingJob = (id, payload) => unwrap(api.patch(`/api/v1/sites/hosting-jobs/${id}`, payload))
export const recheckJobDomain = (id) => unwrap(api.post(`/api/v1/sites/hosting-jobs/${id}/recheck-domain`))
export const switchToBackupDomain = (id) => unwrap(api.post(`/api/v1/sites/hosting-jobs/${id}/use-backup`))
export const markJobLive = (id, liveUrl) => unwrap(api.post(`/api/v1/sites/hosting-jobs/${id}/mark-live`, { live_url: liveUrl }))

/** SITE-4 — finishes a renewal job (both registrar steps must be ticked). */
export const markJobRenewed = (id) => unwrap(api.post(`/api/v1/sites/hosting-jobs/${id}/mark-renewed`))
/** SITE-4 — (re)creates the renewal payment link for a domain and WhatsApps it to the builder. */
export const sendRenewalLink = (domainId) => unwrap(api.post(`/api/v1/sites/domains/${domainId}/renewal-link`))

/** SITE-4B — staff: what = 'plan' | 'pack'. → { checkout_url, amount, kind, sent } */
export const sendCareLink = (siteId, what) => unwrap(api.post(`/api/v1/sites/${siteId}/care-link`, { what }))

export const listSiteDomains = (params) => unwrap(api.get('/api/v1/sites/domains', { params }))

/** spec §8.6 — built in memory on the server; saved through a temporary link. */
export const downloadSiteExport = async (siteId, slug) => {
  const r = await api.get(`/api/v1/sites/${siteId}/export.zip`, { responseType: 'blob' })
  const url = URL.createObjectURL(r.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(slug || 'site').replace(/[^\w-]+/g, '') || 'site'}-export.zip`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** SITE-PUBLISH — uploads the site to Cloudflare under the client's domain. Returns {domain, files, bytes, removed, urls}. */
/** opts.dns_mode: 'cloudflare_zone' (we manage the domain's DNS on Cloudflare) | 'client_cname' (client adds a CNAME). Omitted = auto. */
export const publishSite = (siteId, opts) => unwrap(api.post(`/api/v1/sites/${siteId}/publish`, opts || {}))

/** SITE-HOSTNAMES — DNS records the client must add + whether Cloudflare has connected the domain. */
export const getSiteHostnames = (siteId) => unwrap(api.get(`/api/v1/sites/${siteId}/hostnames`))

/** Pull a readable message out of an axios error ({detail:{message}} or FastAPI 422 list). */
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
