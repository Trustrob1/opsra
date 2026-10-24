/**
 * frontend/src/services/waOnboarding.service.js
 * WA-AUTO-3 - the first-login wizard for WhatsApp-automation-only businesses.
 */
import api from './api'

export const getWaOnboarding = () => api.get('/api/v1/wa-onboarding').then((r) => r.data.data)
export const saveWaBasics = (body) => api.put('/api/v1/wa-onboarding/basics', body).then((r) => r.data.data)
export const requestWaSetup = (body) => api.post('/api/v1/wa-onboarding/request-setup', body).then((r) => r.data.data)
export const getWaTestStatus = () => api.get('/api/v1/wa-onboarding/test-status').then((r) => r.data.data)
export const completeWaOnboarding = () => api.post('/api/v1/wa-onboarding/complete').then((r) => r.data.data)

export const waError = (e, fallback = 'Something went wrong. Please try again.') => {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d?.message) return d.message
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return fallback
}
