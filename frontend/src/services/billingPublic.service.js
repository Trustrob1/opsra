/**
 * frontend/src/services/billingPublic.service.js
 * BILL-4 — the invoice-style Billing link. Public calls use plain axios (no login): the token names the business.
 */
import axios from 'axios'
import { BASE } from './api'

const pub = axios.create({ baseURL: BASE })
const unwrap = (res) => res.data.data

export const getPayView = (token) => pub.get(`/api/v1/public/billing/pay/${token}`).then(unwrap)
export const payRenew = (token) => pub.post(`/api/v1/public/billing/pay/${token}/renew`, {}).then(unwrap)
export const payTopup = (token, body) => pub.post(`/api/v1/public/billing/pay/${token}/topup`, body).then(unwrap)
export const payVerify = (token, reference) => pub.post(`/api/v1/public/billing/pay/${token}/verify`, { reference }).then(unwrap)
export const payError = (e, fallback = 'Something went wrong. Please try again.') => {
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}
