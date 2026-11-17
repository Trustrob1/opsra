/**
 * frontend/src/services/webchat.service.js
 * WEBCHAT-1 — API client for the public chat page (no login; the chat key in the link names the business,
 * the session token goes in the Authorization header) and for the staff settings screen.
 */
import axios from 'axios'
import api from './api'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

const auth = (token) => (token ? { headers: { Authorization: `Bearer ${token}` } } : {})

// ── Public chat page ─────────────────────────────────────────────────────────

export async function startChat(key, { source, handoff, embedOrigin } = {}) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/session`, { source, handoff, ...(embedOrigin ? { embed_origin: embedOrigin } : {}) })
  return res.data.data
}

// WEBCHAT-CATALOG-1: the chat was opened from a product page; the server checks the id against this business's catalogue
export async function viewingChat(key, token, product) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/viewing`, { product }, auth(token))
  return res.data.data
}

// WEBCHAT-CONTACT-1: a button needs the visitor's details; Chioma asks in the chat ({ form: true } = open the form instead)
export async function startContactChat(key, token, why) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/contact/start`, { why }, auth(token))
  return res.data.data
}

// WEBCHAT-CONTACT-1e: tell the team's inbox the visitor is typing (best effort)
export function pingTyping(key, token) {
  return axios.post(`${BASE}/public/webchat/${key}/typing`, {}, auth(token)).catch(() => null)
}

export async function resumeChat(key, token, embedOrigin) {
  const res = await axios.get(`${BASE}/public/webchat/${key}/session`, { ...auth(token), params: embedOrigin ? { po: embedOrigin } : {} })
  return res.data.data
}

export async function pollChat(key, token, after) {
  const res = await axios.get(`${BASE}/public/webchat/${key}/messages`, { ...auth(token), params: after ? { after } : {} })
  return res.data.data
}

export async function sendChat(key, token, payload) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/message`, payload, auth(token))
  return res.data.data
}

// WEBCHAT-ATTACH-1: a photo, voice note or document. kind: 'image' | 'audio' | 'document'.
export async function uploadChatFile(key, token, file, kind, onProgress) {
  const fd = new FormData()
  fd.append('file', file, file.name || 'file')
  fd.append('kind', kind)
  const res = await axios.post(`${BASE}/public/webchat/${key}/upload`, fd, {
    ...auth(token),
    timeout: 120000,
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total)) },
  })
  return res.data.data
}

export async function sendContact(key, token, payload) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/contact`, payload, auth(token))
  return res.data.data
}

export async function sendBooking(key, token, fields) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/booking`, { fields }, auth(token))
  return res.data.data
}

export async function editChatMessage(key, token, id, text) {
  const res = await axios.patch(`${BASE}/public/webchat/${key}/message/${id}`, { text }, auth(token))
  return res.data.data.message
}

export async function deleteChatMessage(key, token, id) {
  const res = await axios.delete(`${BASE}/public/webchat/${key}/message/${id}`, auth(token))
  return res.data.data.message
}

export async function getChatConfig(key) {
  const res = await axios.get(`${BASE}/public/webchat/${key}/config`)
  return res.data.data
}

export async function requestChatCallback(key, token, phone) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/callback`, { phone: phone || null }, auth(token))
  return res.data.data
}

export function chatErrorMessage(err, fallback = 'Something went wrong. Please try again.') {
  const d = err?.response?.data?.detail
  if (d && typeof d === 'object' && d.message) return d.message
  if (typeof d === 'string') return d
  return fallback
}

// ── Staff ────────────────────────────────────────────────────────────────────

export const sendWebchatReply = (leadId, message) =>
  api.post('/api/v1/conversations/webchat/send', { lead_id: leadId, message })

export async function getWebchatSettings() {
  const r = await api.get('/api/v1/webchat/settings')
  return r.data.data
}

export async function saveWebchatSettings(changes) {
  const r = await api.put('/api/v1/webchat/settings', changes)
  return r.data.data
}

export async function getWebchatEmbedSeen() {
  const r = await api.get('/api/v1/webchat/embed-seen')
  return r.data.data.seen
}

export async function sendWebchatEmbedEmail(to_email, note) {
  const r = await api.post('/api/v1/webchat/embed-email', { to_email, note: note || null })
  return r.data.data
}

export async function applyWebchatTemplate(template) {
  const r = await api.post('/api/v1/webchat/settings/template', { template })
  return r.data.data
}

export async function getWebchatStats() {
  const r = await api.get('/api/v1/webchat/stats')
  return r.data.data
}

// ── Shop (WEBCHAT-3b) ────────────────────────────────────────────────────────

export async function getChatProducts(key, token, q) {
  const res = await axios.get(`${BASE}/public/webchat/${key}/products`, { ...auth(token), params: q ? { q } : {} })
  return res.data.data
}

export async function getChatCart(key, token) {
  const res = await axios.get(`${BASE}/public/webchat/${key}/cart`, auth(token))
  return res.data.data
}

export async function changeChatCart(key, token, payload) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/cart`, payload, auth(token))
  return res.data.data
}

export async function chatCheckout(key, token) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/checkout`, {}, auth(token))
  return res.data.data
}

// ── Email follow-ups (WEBCHAT-4) ────────────────────────────────────────────

export async function saveChatByEmail(key, token, { email, consent }) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/save-chat`, { email, consent }, auth(token))
  return res.data.data
}

/** WEBCHAT-5b: tell the server the visitor tapped a link (counted once per chat). Never throws. */
export async function tapChat(key, token) {
  try { await axios.post(`${BASE}/public/webchat/${key}/tap`, {}, auth(token)) } catch { /* not important */ }
}

export async function stopChatEmails(key, token) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/email-optout`, {}, auth(token))
  return res.data.data
}

export async function testWebchatWhatsapp(phone) {
  const r = await api.post('/api/v1/webchat/settings/test-whatsapp', { phone })
  return r.data
}

// ── Insights, link builder and QR (WEBCHAT-5) ────────────────────────────────

export async function getWebchatAnalytics(days = 30) {
  const r = await api.get('/api/v1/webchat/analytics', { params: { days } })
  return r.data.data
}

/** QR code as SVG text. Fetched with the login header, so it cannot be a plain <img src>. */
export async function getWebchatQr(source, download = false) {
  const r = await api.get('/api/v1/webchat/qr.svg', { params: { s: source, download: download ? 1 : undefined }, responseType: 'text', transformResponse: (d) => d })
  return r.data
}
