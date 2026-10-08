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

/** GIVEAWAY-1 — public giveaway: slots left, and opening a form (needs the consent tick). */
export async function getGiveaway(slug) {
  const res = await axios.get(`${BASE}/giveaways/${encodeURIComponent(slug)}`)
  return res.data.data
}
/** contact: { name, phone, email } — one slot per WhatsApp number. */
export async function openGiveaway(slug, consent, contact = {}) {
  const res = await axios.post(`${BASE}/giveaways/${encodeURIComponent(slug)}/open`, {
    consent: consent === true, name: contact.name, phone: contact.phone, email: contact.email,
  })
  return res.data.data
}

/** GIVEAWAY-3 — a winner who lost their private link asks for a new one with their WhatsApp number. */
export async function requestLostLink(slug, phone) {
  const res = await axios.post(`${BASE}/giveaways/${encodeURIComponent(slug)}/lost-link`, { phone })
  return res.data
}

/** GIVEAWAY-1 — the winner's private page (the token in the link is the credential). */
export async function getGiveawayWinner(token) {
  const res = await axios.get(`${BASE}/giveaway-winner/${encodeURIComponent(token)}`)
  return res.data.data
}
export async function checkWinnerDomain(token, domain) {
  const res = await axios.post(`${BASE}/giveaway-winner/${encodeURIComponent(token)}/domain-check`, { domain })
  return res.data.data
}
/** Buy a pack of extra catalog items once the site is paid for → { checkout_url, amount, items } */
export async function buyWinnerItems(token) {
  const res = await axios.post(`${BASE}/giveaway-winner/${encodeURIComponent(token)}/catalog-checkout`)
  return res.data.data
}
/** body: { domain, backup_domain, legal_owner:{full_name,email,phone,address}, accepted_terms } — the amount is set by the server. */
export async function payGiveawayWinner(token, body) {
  const res = await axios.post(`${BASE}/giveaway-winner/${encodeURIComponent(token)}/checkout`, body)
  return res.data.data
}
