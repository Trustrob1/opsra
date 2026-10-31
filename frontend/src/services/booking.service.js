/**
 * frontend/src/services/booking.service.js
 * BOOKING-1 — native booking API.
 * Staff calls use the shared api instance (JWT). Public calls use plain axios (no login).
 * org_id is never sent: staff = JWT, public = the signed link token.
 */
import axios from 'axios'
import api, { BASE } from './api'

const pub = axios.create({ baseURL: BASE })
const unwrap = (res) => res.data

// ── Public (booking link) ────────────────────────────────────────────────────
export const getLink        = (token) => pub.get(`/api/v1/public/booking/link/${token}`).then(unwrap)
export const getLinkSlots   = (token, from, to) =>
  pub.get(`/api/v1/public/booking/link/${token}/slots`, { params: { from, to } }).then(unwrap)
export const linkBook       = (token, body) => pub.post(`/api/v1/public/booking/link/${token}/book`, body).then(unwrap)
export const linkReschedule = (token, body) => pub.post(`/api/v1/public/booking/link/${token}/reschedule`, body).then(unwrap)
export const linkCancel     = (token, body) => pub.post(`/api/v1/public/booking/link/${token}/cancel`, body).then(unwrap)

// ── Staff ────────────────────────────────────────────────────────────────────
export const getBookingSettings    = () => api.get('/api/v1/booking/settings').then(unwrap)
export const saveBookingSettings   = (b) => api.patch('/api/v1/booking/settings', b).then(unwrap)
export const listBookingServices   = () => api.get('/api/v1/booking/services').then(unwrap)
export const createBookingService  = (b) => api.post('/api/v1/booking/services', b).then(unwrap)
export const updateBookingService  = (id, b) => api.patch(`/api/v1/booking/services/${id}`, b).then(unwrap)
export const deleteBookingService  = (id) => api.delete(`/api/v1/booking/services/${id}`).then(unwrap)
export const getBookingHours       = () => api.get('/api/v1/booking/availability').then(unwrap)
export const saveBookingHours      = (rows) => api.put('/api/v1/booking/availability', { rows }).then(unwrap)
export const listBookingBlocks     = () => api.get('/api/v1/booking/blocks').then(unwrap)
export const addBookingBlock       = (b) => api.post('/api/v1/booking/blocks', b).then(unwrap)
export const deleteBookingBlock    = (id) => api.delete(`/api/v1/booking/blocks/${id}`).then(unwrap)
export const getStaffSlots         = (service, from, to) =>
  api.get('/api/v1/booking/slots', { params: { service, from, to } }).then(unwrap)
export const getBookingsFeed       = (from, to) => api.get('/api/v1/booking/bookings', { params: { from, to } }).then(unwrap)
export const staffBookLead         = (leadId, body) => api.post(`/api/v1/booking/leads/${leadId}/book`, body).then(unwrap)
export const makeBookingLink       = (leadId, body) => api.post(`/api/v1/booking/leads/${leadId}/link`, body).then(unwrap)
export const staffCancelBooking    = (demoId, body) => api.post(`/api/v1/booking/bookings/${demoId}/cancel`, body).then(unwrap)
export const staffRescheduleBooking = (demoId, body) => api.post(`/api/v1/booking/bookings/${demoId}/reschedule`, body).then(unwrap)

export const apiError = (e, fallback = 'Something went wrong. Please try again.') =>
  e?.response?.data?.detail?.message ?? e?.response?.data?.error?.message ?? fallback
