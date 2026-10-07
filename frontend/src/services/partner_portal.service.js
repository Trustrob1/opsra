/**
 * frontend/src/services/partner_portal.service.js
 * PARTNER-1B — Launch Partner apply / sign-in / portal API. Prefix: /api/v1/partner-portal.
 * The session is the builder session issued by /api/v1/builder/auth/exchange; like the builder
 * portal it lives in memory only (React state), never localStorage/sessionStorage.
 */
import axios from 'axios'
import { exchangeBuilderToken, errorMessage } from './builder_portal.service'

const BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/v1/partner-portal` : '/api/v1/partner-portal'
const authed = (token) => ({ headers: { Authorization: `Bearer ${token}` } })
const unwrap = (p) => p.then((r) => r.data?.data ?? r.data)

export { exchangeBuilderToken, errorMessage }
/** payload: { full_name, email, phone, agency_name, accept_terms, website (honeypot) } → { request_id, email_hint } */
export const startApplication = (payload) => unwrap(axios.post(`${BASE}/apply/start`, payload))
export const verifyApplication = (requestId, code) => unwrap(axios.post(`${BASE}/apply/verify`, { request_id: requestId, code }))
/** identifier: an email or a WhatsApp number. The reply never says whether it is registered. */
export const requestPartnerLink = (identifier) => unwrap(axios.post(`${BASE}/auth/request-link`, { identifier }))
export const getPartnerMe = (token) => unwrap(axios.get(`${BASE}/me`, authed(token)))
export const getPartnerReferrals = (token) => unwrap(axios.get(`${BASE}/referrals`, authed(token)))
export const previewUrl = (path) => `${import.meta.env.VITE_API_URL || ''}${path}`
