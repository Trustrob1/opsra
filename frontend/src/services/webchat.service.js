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

export async function startChat(key, { source, handoff } = {}) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/session`, { source, handoff })
  return res.data.data
}

export async function resumeChat(key, token) {
  const res = await axios.get(`${BASE}/public/webchat/${key}/session`, auth(token))
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

export async function sendContact(key, token, payload) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/contact`, payload, auth(token))
  return res.data.data
}

export async function sendBooking(key, token, fields) {
  const res = await axios.post(`${BASE}/public/webchat/${key}/booking`, { fields }, auth(token))
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

export async function applyWebchatTemplate(template) {
  const r = await api.post('/api/v1/webchat/settings/template', { template })
  return r.data.data
}

export async function getWebchatStats() {
  const r = await api.get('/api/v1/webchat/stats')
  return r.data.data
}
