/**
 * frontend/src/services/invoicesPublic.service.js
 * INV-3 — the customer's page for a quote or invoice (/i/<token>). No login: plain axios; the token is the key.
 */
import axios from 'axios'
import { BASE } from './api'

const pub = axios.create({ baseURL: BASE })
const unwrap = (res) => res.data.data

export const getPublicDoc = (token) => pub.get(`/api/v1/public/invoices/${token}`).then(unwrap)
export const answerQuote = (token, accept) => pub.post(`/api/v1/public/invoices/${token}/${accept ? 'accept' : 'decline'}`, {}).then(unwrap)
export const publicPdfUrl = (token) => `${BASE}/api/v1/public/invoices/${token}/pdf`
export const publicError = (e, fallback = 'Something went wrong. Please try again.') => {
  const d = e?.response?.data
  return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : fallback)
}
