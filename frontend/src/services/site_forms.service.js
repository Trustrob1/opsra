/**
 * frontend/src/services/site_forms.service.js
 * SITE-1B — public brief-form API client. Prefix: /api/v1/forms/{token}
 *
 * No auth — the token itself is the credential (spec §18). Same "public routes,
 * no headers" pattern as performance_logs.service.js's getPublicLogForm/submitPublicLog.
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

export async function getBriefForm(token) {
  const res = await axios.get(`${BASE}/forms/${token}`)
  return res.data.data
}

/** payload: { answers, preset_id?, website? (honeypot) } — merged server-side, never replaces wholesale. */
export async function autosaveBriefForm(token, payload) {
  const res = await axios.patch(`${BASE}/forms/${token}`, payload)
  return res.data.data
}

export async function uploadBriefFormAsset(token, slot, file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await axios.post(
    `${BASE}/forms/${token}/assets?slot=${encodeURIComponent(slot)}`,
    fd,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return res.data.data
}

/** payload: { answers, client_business_name, website? (honeypot) } */
export async function submitBriefForm(token, payload) {
  const res = await axios.post(`${BASE}/forms/${token}/submit`, payload)
  return res.data.data
}

export function errorMessage(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || 'Something went wrong — please try again.'
}

/** PARTNER-1A — open a partner's permanent link: returns { url } of a fresh single-client brief form. */
export async function openPartnerLink(slug) {
  const res = await axios.post(`${BASE}/partner-links/${encodeURIComponent(slug)}/open`)
  return res.data.data
}
