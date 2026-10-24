/**
 * frontend/src/services/waSignup.service.js
 * WA-AUTO-5 - public sign-up for WhatsApp-automation-only businesses, plus the Superadmin switches.
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''
const unwrap = (p) => p.then((r) => r.data?.data ?? r.data)

export const getSignupInfo = () => unwrap(axios.get(`${BASE}/api/v1/wa-signup/info`))
export const startWaSignup = (payload) => unwrap(axios.post(`${BASE}/api/v1/wa-signup/start`, payload))
export const verifyWaSignup = (requestId, code, password) => unwrap(axios.post(`${BASE}/api/v1/wa-signup/verify`, { request_id: requestId, code, password }))

export function signupError(err, fallback = 'Something went wrong. Please try again.') {
  const d = err?.response?.data?.detail
  if (!d) return fallback
  if (typeof d === 'string') return d
  if (d.message) return d.message
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return fallback
}
