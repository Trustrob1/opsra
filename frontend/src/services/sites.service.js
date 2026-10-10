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

// ── SITE-PREMIUM P2b: Premium designs (Claude designs a bespoke page; staff review, switch, go back) ──
/** { tier, current_design_id, designs: [{ id, version, status, cost_usd, duration_ms, checks, created_by, created_at, ... }] } */
export const getPremiumDesigns = (siteId) => unwrap(api.get(`/api/v1/sites/${siteId}/premium/designs`))
/** Queues a design (202). Poll getPremiumDesigns: the new version goes generating -> checking -> ready | failed. */
/** Staff: charge the whole Premium price at go-live for a Premium site made before payment existed. */
export const setPremiumChargeAtGoLive = (siteId, enabled) => unwrap(api.post(`/api/v1/sites/${siteId}/premium/charge-at-golive`, { enabled }))
export const generatePremiumDesign = (siteId) => unwrap(api.post(`/api/v1/sites/${siteId}/premium/generate`))
/** { design_id, html } - the page for one finished version; changes nothing. */
export const previewPremiumDesign = (siteId, designId) => unwrap(api.get(`/api/v1/sites/${siteId}/premium/designs/${designId}/preview`))
export const switchPremiumDesign = (siteId, designId) => unwrap(api.post(`/api/v1/sites/${siteId}/premium/use-design`, { design_id: designId }))
export const premiumBackToStandard = (siteId) => unwrap(api.post(`/api/v1/sites/${siteId}/premium/standard`))

// ── SITE-IMPORT 1b: import a finished single-page site made outside Opsra (staff) ──
/** { tier, current_design_id, designs: [{ id, version, active, staged, counts, warnings, scripts, external_unknown, missing_files, ... }] } */
export const getImportDesigns = (siteId) => unwrap(api.get(`/api/v1/sites/${siteId}/import/designs`))
/** opts: { dryRun, accepted: { 'js/app.js': ['eval'] } }. 422 carries detail.errors and detail.report. */
export const importSiteFile = (siteId, file, opts = {}) => {
  const form = new FormData()
  form.append('file', file)
  form.append('dry_run', opts.dryRun ? 'true' : 'false')
  if (opts.accepted && Object.keys(opts.accepted).length) form.append('accepted', JSON.stringify(opts.accepted))
  return unwrap(api.post(`/api/v1/sites/${siteId}/import`, form, { headers: { 'Content-Type': 'multipart/form-data' } }))
}
/** { html } - show ONLY inside <iframe sandbox="allow-scripts" srcDoc>. */
export const previewImportDesign = (siteId, designId) => unwrap(api.get(`/api/v1/sites/${siteId}/import/designs/${designId}/preview`))
/** { resolved, failed, remaining } - copies files the page loads from unlisted websites. */
export const resolveImportDesign = (siteId, designId) => unwrap(api.post(`/api/v1/sites/${siteId}/import/resolve`, { design_id: designId }))
export const activateImportDesign = (siteId, designId, adoptContent = false) => unwrap(api.post(`/api/v1/sites/${siteId}/import/activate`, { design_id: designId, adopt_content: !!adoptContent }))
export const makeImportEditable = (siteId, designId) => unwrap(api.post(`/api/v1/sites/${siteId}/import/make-editable`, { design_id: designId }))

// ── SITE-IMPORT 3: design library (staff) ──
/** { designs: [{ id, name, niche, source_kind, status, uses_count, has_scripts, note, ... }], niches: [{ niche, active, warning }] } */
export const getLibraryDesigns = (niche) => unwrap(api.get('/api/v1/site-library', { params: niche ? { niche } : {} }))
/** payload: { site_id, design_id, name, niche, note } -> { id, warnings, fixed_text }. 409 duplicate name, 422 failed fit checks. */
export const saveLibraryDesign = (payload) => unwrap(api.post('/api/v1/site-library/save', payload))
/** { html } - show ONLY inside <iframe sandbox="allow-scripts allow-popups" srcDoc>. */
export const previewLibraryDesign = (libraryId) => unwrap(api.get(`/api/v1/site-library/${libraryId}/preview`))
export const setLibraryDesignStatus = (libraryId, action) => unwrap(api.post(`/api/v1/site-library/${libraryId}/${action === 'retire' ? 'retire' : 'restore'}`))
/** libraryId null = the rotation picks one. */
export const attachLibraryDesign = (siteId, libraryId) => unwrap(api.post(`/api/v1/sites/${siteId}/library/attach`, libraryId ? { library_id: libraryId } : {}))

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

// ── PARTNER-1B — Launch Partners (staff) ────────────────────────────────────
export const listPartners = () => unwrap(api.get('/api/v1/partners'))
export const listPartnerApplications = (status = 'applied') =>
  unwrap(api.get('/api/v1/partners/applications', { params: { status } }))
export const approvePartnerApplication = (id) => unwrap(api.post(`/api/v1/partners/applications/${id}/approve`))
export const declinePartnerApplication = (id) => unwrap(api.post(`/api/v1/partners/applications/${id}/decline`))
export const suspendPartner = (id) => unwrap(api.post(`/api/v1/partners/${id}/suspend`))
export const reactivatePartner = (id) => unwrap(api.post(`/api/v1/partners/${id}/reactivate`))

// ── GIVEAWAY-1 — group giveaways (staff) ────────────────────────────────────
export const listGiveaways = () => unwrap(api.get('/api/v1/giveaways'))
export const createGiveaway = (payload) => unwrap(api.post('/api/v1/giveaways', payload))
export const closeGiveaway = (id) => unwrap(api.post(`/api/v1/giveaways/${id}/close`))
export const reopenGiveaway = (id) => unwrap(api.post(`/api/v1/giveaways/${id}/reopen`))
export const listGiveawayEntries = (id) => unwrap(api.get(`/api/v1/giveaways/${id}/entries`))
export const resendGiveawayLink = (id, position) => unwrap(api.post(`/api/v1/giveaways/${id}/entries/${position}/resend-link`))
export const voidGiveawaySlot = (id, position) => unwrap(api.post(`/api/v1/giveaways/${id}/entries/${position}/void`))

// ── SITE-ADDONS A0-3 — tiers and add-ons (staff) ──────────────────────────────
export const getSiteAddonsCatalog = () => unwrap(api.get('/api/v1/site-addons/catalog'))
export const getSiteAddons = (siteId) => unwrap(api.get(`/api/v1/sites/${siteId}/addons`))
/** payload: { kind: 'tier'|'addon', key, until?, picks?, payer? } — free access, nothing is charged. */
export const grantSiteAddon = (siteId, payload) => unwrap(api.put(`/api/v1/sites/${siteId}/addons`, payload))
/** payload: { kind, key, picks?, payer?: {name, phone, email}, send? } — returns { addon_id, pay_url, scheduled, quote, sent? }. */
export const startSiteAddonCheckout = (siteId, payload) => unwrap(api.post(`/api/v1/sites/${siteId}/addons/checkout`, payload))
export const sendSiteAddonLink = (siteId, addonId) => unwrap(api.post(`/api/v1/sites/${siteId}/addons/${addonId}/send-link`))
/** action: 'pause' | 'resume' | 'cancel'; `until` (ISO) only for resume. */
export const changeSiteAddon = (siteId, addonId, action, until) =>
  unwrap(api.post(`/api/v1/sites/${siteId}/addons/${addonId}/${action}`, until ? { until } : {}))

// ── SITE-ADDONS A1-2 — lead capture (staff) ──────────────────────────────────
export const getSiteCapture = (siteId) => unwrap(api.get(`/api/v1/sites/${siteId}/capture`))
export const rotateSiteCaptureKey = (siteId) => unwrap(api.post(`/api/v1/sites/${siteId}/capture/rotate-key`))
