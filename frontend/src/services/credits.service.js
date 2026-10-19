/**
 * frontend/src/services/credits.service.js
 * CREDITS-2 — a business's own credit wallet (login required).
 */
import api from './api'

export const getCreditSummary = () => api.get('/api/v1/credits/summary').then((r) => r.data.data)
export const getCreditUsage = (days = 30) => api.get('/api/v1/credits/usage', { params: { days } }).then((r) => r.data.data)
export const getCreditLedger = (before) => api.get('/api/v1/credits/ledger', { params: before ? { before } : {} }).then((r) => r.data.data)
export const getCreditPacks = () => api.get('/api/v1/credits/packs').then((r) => r.data.data)
export const getCreditOrders = () => api.get('/api/v1/credits/orders').then((r) => r.data.data)
export const startCreditCheckout = (body) => api.post('/api/v1/credits/checkout', body).then((r) => r.data.data)
export const verifyCreditPayment = (reference) => api.post('/api/v1/credits/verify', { reference }).then((r) => r.data.data)

export const naira = (kobo) => `₦${(Number(kobo || 0) / 100).toLocaleString('en-NG', { maximumFractionDigits: 2 })}`
export const creditError = (e, fallback = 'Something went wrong. Please try again.') => {
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}
