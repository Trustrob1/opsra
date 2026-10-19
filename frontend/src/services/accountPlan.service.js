/**
 * frontend/src/services/accountPlan.service.js
 * ACCOUNT-PLANS AP-3 — an organisation's own Capture / Convert / Grow plan (login required; owner / ops manager / admin).
 */
import api from './api'

export const getPlan = () => api.get('/api/v1/billing/plan').then((r) => r.data.data)
export const getPlanOrders = () => api.get('/api/v1/billing/plan/orders').then((r) => r.data.data)
export const previewPlan = (key, code) => api.post('/api/v1/billing/plan/preview', { key, code: code || null }).then((r) => r.data.data)
export const startPlanCheckout = (key, code) => api.post('/api/v1/billing/plan/checkout', { key, code: code || null }).then((r) => r.data.data)
export const verifyPlanPayment = (reference) => api.post('/api/v1/billing/plan/verify', { reference }).then((r) => r.data.data)
export const clearPendingPlanChange = () => api.delete('/api/v1/billing/plan/pending-change').then((r) => r.data.data)

export const ngn = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
export const planError = (e, fallback = 'Something went wrong. Please try again.') => {
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}
export const PENDING_PLAN_KEY = 'opsra_pending_plan_ref'
