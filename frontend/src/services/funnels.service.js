/**
 * frontend/src/services/funnels.service.js
 * FUNNEL-1B — Event Funnels API (backend: routers/funnels.py + routers/funnel_tools.py).
 *
 * Uses the central `api` instance (JWT from Zustand + silent refresh on 401).
 * Pattern 12: org_id is never sent — the backend takes it from the JWT.
 * Every function returns the response's `data` payload (the ok() envelope is unwrapped).
 */
import api from './api'

const unwrap = (p) => p.then((r) => r.data?.data ?? r.data)
const F = (id) => `/api/v1/funnels/${id}`

// ── Funnels ───────────────────────────────────────────────────────────────
export const listFunnels     = ()             => unwrap(api.get('/api/v1/funnels'))
export const getFunnelDefaults = ()           => unwrap(api.get('/api/v1/funnels/defaults'))
export const createFunnel    = (payload)      => unwrap(api.post('/api/v1/funnels', payload))
export const getFunnel       = (id)           => unwrap(api.get(F(id)))
export const updateFunnel    = (id, payload)  => unwrap(api.patch(F(id), payload))
export const duplicateAsTest = (id)           => unwrap(api.post(`${F(id)}/duplicate-as-test`))

// ── Overview & spend ─────────────────────────────────────────────────────
export const getOverview  = (id)                 => unwrap(api.get(`${F(id)}/overview`))
export const getAdSpend   = (id, from, to)       => unwrap(api.get(`${F(id)}/ad-spend`, { params: { from, to } }))
export const saveAdSpend  = (id, rows)           => unwrap(api.put(`${F(id)}/ad-spend`, { rows }))

// ── Leads ────────────────────────────────────────────────────────────────
export const listRegistrations = (id, params) => unwrap(api.get(`${F(id)}/registrations`, { params }))
export const getRegistrationEvents = (id, rid) => unwrap(api.get(`${F(id)}/registrations/${rid}/events`))
export const patchRegistration = (id, rid, payload) => unwrap(api.patch(`${F(id)}/registrations/${rid}`, payload))
export const grantEarly    = (id, rid, hours)   => unwrap(api.post(`${F(id)}/registrations/${rid}/grant-early`, { hours }))
export const resendLink    = (id, rid)          => unwrap(api.post(`${F(id)}/registrations/${rid}/resend-link`))
export const markPaid      = (id, rid, payload) => unwrap(api.post(`${F(id)}/registrations/${rid}/mark-paid`, payload))
export const askGmail      = (id, rid)          => unwrap(api.post(`${F(id)}/registrations/${rid}/ask-gmail`))
export const resetTestLead = (id, rid)          => unwrap(api.delete(`${F(id)}/registrations/${rid}`))

// ── Attendees ────────────────────────────────────────────────────────────
export const getGmailList = (id) => unwrap(api.get(`${F(id)}/gmail-list`))
export const exportCsv = async (id, name) => {
  const r = await api.get(`${F(id)}/export.csv`, { responseType: 'blob' })
  const url = URL.createObjectURL(r.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(name || 'attendees').replace(/[^\w\- ]+/g, '').trim() || 'attendees'}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ── Messages ─────────────────────────────────────────────────────────────
export const previewMessage = (id, payload) => unwrap(api.post(`${F(id)}/preview`, payload))

// ── Broadcasts ───────────────────────────────────────────────────────────
export const listBroadcasts  = (id)          => unwrap(api.get(`${F(id)}/broadcasts`))
export const createBroadcast = (id, payload) => unwrap(api.post(`${F(id)}/broadcasts`, payload))
export const cancelBroadcast = (id, bid)     => unwrap(api.post(`${F(id)}/broadcasts/${bid}/cancel`))

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
