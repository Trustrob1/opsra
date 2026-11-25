/**
 * frontend/src/services/inventory.service.js
 * STOCK-1 — stock per product + size + location (backend: routers/inventory.py).
 * Uses the shared api instance (JWT). org_id is never sent; the server takes it from the token.
 */
import api from './api'

const d = (res) => res.data?.data

export const isPlanBlocked = (e) => e?.response?.data?.detail?.code === 'PLAN_REQUIRED'
export const stockError = (e, fallback = 'Something went wrong. Please try again.') =>
  isPlanBlocked(e)
    ? 'Inventory is not included in your plan. Open Billing to see the plans.'
    : (e?.response?.data?.error?.message ?? e?.response?.data?.detail?.message
      ?? (typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : null) ?? fallback)
export const errorField = (e) => e?.response?.data?.error?.field || null

export const getStock          = (params = {}) => api.get('/api/v1/inventory', { params }).then(d)
export const getStockSettings  = () => api.get('/api/v1/inventory/settings').then(d)
export const saveStockSettings = (body) => api.put('/api/v1/inventory/settings', body).then(d)
export const getLocations      = () => api.get('/api/v1/inventory/locations').then(d)
export const createLocation    = (body) => api.post('/api/v1/inventory/locations', body).then(d)
export const updateLocation    = (id, body) => api.patch(`/api/v1/inventory/locations/${id}`, body).then(d)
export const pickStockProducts = (q) => api.get('/api/v1/inventory/products', { params: q ? { q } : {} }).then(d)
export const getStockHistory   = (params = {}) => api.get('/api/v1/inventory/history', { params }).then(d)
export const receiveStock      = (body) => api.post('/api/v1/inventory/receive', body).then(d)
export const adjustStock       = (body) => api.post('/api/v1/inventory/adjust', body).then(d)
export const updateStockItem   = (body) => api.patch('/api/v1/inventory/items', body).then(d)

// STOCK-2: invoices holding stock, paid invoices still to deliver, and what is left per size at one location
export const getHeld         = (params = {}) => api.get('/api/v1/inventory/held', { params }).then(d)
export const getApprovals     = () => api.get('/api/v1/inventory/approvals').then(d)   // STOCK-2b
export const getToDeliver    = (params = {}) => api.get('/api/v1/inventory/to-deliver', { params }).then(d)
export const getAvailability = (locationId, productIds) =>
  api.get('/api/v1/inventory/availability', { params: { location_id: locationId, product_ids: productIds.join(',') } }).then(d)

// STOCK-3: moving stock between locations
export const getTransfers     = (status) => api.get('/api/v1/inventory/transfers', { params: status ? { status } : {} }).then(d)
export const sendTransfer     = (body) => api.post('/api/v1/inventory/transfers', body).then(d)
export const receiveTransfer  = (id, body) => api.post(`/api/v1/inventory/transfers/${id}/receive`, body).then(d)
export const cancelTransfer   = (id) => api.post(`/api/v1/inventory/transfers/${id}/cancel`).then(d)
