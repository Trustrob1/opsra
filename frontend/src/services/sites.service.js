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

// ── Presets (Templates tab) ─────────────────────────────────────────────
export const listPresets = () => unwrap(api.get('/api/v1/sites/presets'))
export const createPreset = (payload) => unwrap(api.post('/api/v1/sites/presets', payload))
export const getPreset = (id) => unwrap(api.get(`/api/v1/sites/presets/${id}`))
export const updatePreset = (id, payload) => unwrap(api.patch(`/api/v1/sites/presets/${id}`, payload))
export const previewPreset = (id, recipe) => unwrap(api.post(`/api/v1/sites/presets/${id}/preview`, recipe))

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
