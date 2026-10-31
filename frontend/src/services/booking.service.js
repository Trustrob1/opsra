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
export const getLinkSlots   = (token, from, to, staff) =>
  pub.get(`/api/v1/public/booking/link/${token}/slots`, { params: { from, to, ...(staff ? { staff } : {}) } }).then(unwrap)
export const linkBook       = (token, body) => pub.post(`/api/v1/public/booking/link/${token}/book`, body).then(unwrap)
export const linkReschedule = (token, body) => pub.post(`/api/v1/public/booking/link/${token}/reschedule`, body).then(unwrap)
export const linkVerifyPayment = (token) => pub.post(`/api/v1/public/booking/link/${token}/payment/verify`, {}).then(unwrap)
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

// ── BOOKING-2B: people (per-staff calendars) ──
export const listBookingStaff      = () => api.get('/api/v1/booking/staff').then(unwrap)
export const saveBookingStaff      = (userId, b) => api.put(`/api/v1/booking/staff/${userId}`, b).then(unwrap)
export const saveStaffHours        = (userId, rows) => api.put(`/api/v1/booking/staff/${userId}/hours`, { rows }).then(unwrap)
export const switchToBusinessHours      = (userId) => api.put(`/api/v1/booking/staff/${userId}/use-business-hours`).then(unwrap)
export const listStaffBlocks       = (userId) => api.get(`/api/v1/booking/staff/${userId}/blocks`).then(unwrap)
export const addStaffBlock         = (userId, b) => api.post(`/api/v1/booking/staff/${userId}/blocks`, b).then(unwrap)
export const deleteStaffBlock      = (blockId) => api.delete(`/api/v1/booking/staff/blocks/${blockId}`).then(unwrap)
export const saveServiceStaff      = (serviceId, userIds) => api.put(`/api/v1/booking/services/${serviceId}/staff`, { user_ids: userIds }).then(unwrap)
export const startWaPicker         = (leadId, body) => api.post(`/api/v1/booking/leads/${leadId}/wa-picker`, body || {}).then(unwrap)
export const assignBooking         = (demoId, userId) => api.post(`/api/v1/booking/bookings/${demoId}/assign`, { user_id: userId }).then(unwrap)

export const apiError = (e, fallback = 'Something went wrong. Please try again.') =>
  e?.response?.data?.detail?.message ?? e?.response?.data?.error?.message ?? fallback
export const markDepositPaid     = (demoId) => api.post(`/api/v1/booking/bookings/${demoId}/payment/mark-paid`, {}).then(unwrap)
export const markDepositRefunded = (demoId) => api.post(`/api/v1/booking/bookings/${demoId}/payment/mark-refunded`, {}).then(unwrap)
export const getCalendly        = () => api.get('/api/v1/booking/calendly').then(unwrap)
export const connectCalendly    = (access_token) => api.post('/api/v1/booking/calendly', { access_token }).then(unwrap)
export const disconnectCalendly = () => api.delete('/api/v1/booking/calendly').then(unwrap)
