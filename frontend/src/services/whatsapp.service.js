/**
 * whatsapp.service.js — Module 02 API call functions.
 *
 * Mirrors the API route contracts from Technical Spec §5.3 and Build Status.
 * Axios instance reused from leads.service (same interceptors — Bearer JWT,
 * 401 → clearAuth). We import the same axios instance to avoid duplication.
 *
 * Route contracts (base: /api/v1):
 *   GET    /customers                          listCustomers
 *   GET    /customers/:id                      getCustomer
 *   PATCH  /customers/:id                      updateCustomer
 *   GET    /customers/:id/messages             getCustomerMessages
 *   GET    /customers/:id/tasks                getCustomerTasks
 *   GET    /customers/:id/nps                  getCustomerNps
 *   POST   /messages/send                      sendMessage
 *   GET    /broadcasts                         listBroadcasts
 *   POST   /broadcasts                         createBroadcast
 *   GET    /broadcasts/:id                     getBroadcast
 *   POST   /broadcasts/:id/approve             approveBroadcast
 *   POST   /broadcasts/:id/cancel              cancelBroadcast
 *   GET    /templates                          listTemplates
 *   POST   /templates                          createTemplate
 *   PATCH  /templates/:id                      updateTemplate
 *   GET    /drip-sequences                     getDripSequence
 *   PUT    /drip-sequences                     updateDripSequence   [Admin]
 *
 * Patterns:
 *   - org_id is NEVER sent in the payload (Pattern 12)
 *   - Bearer token injected via request interceptor (Pattern 11)
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

// Re-use one axios instance scoped to the API base URL
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '' })

api.interceptors.request.use(cfg => {
  const token = useAuthStore.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) useAuthStore.getState().clearAuth()
    return Promise.reject(err)
  }
)

// ─────────────────────────────────────────────────────────────────────────────
// Customers
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/v1/customers
 *  @param {object} params — churn_risk, assigned_to, onboarding_complete, page, page_size
 */
export const listCustomers = (params = {}) =>
  api.get('/api/v1/customers', { params })

/** GET /api/v1/customers/:id */
export const getCustomer = id =>
  api.get(`/api/v1/customers/${id}`)

/** PATCH /api/v1/customers/:id — partial update */
export const updateCustomer = (id, payload) =>
  api.patch(`/api/v1/customers/${id}`, payload)

/** GET /api/v1/customers/:id/messages */
export const getCustomerMessages = (id, params = {}) =>
  api.get(`/api/v1/customers/${id}/messages`, { params })

/** GET /api/v1/customers/:id/tasks */
export const getCustomerTasks = id =>
  api.get(`/api/v1/customers/${id}/tasks`)

/** GET /api/v1/customers/:id/nps */
export const getCustomerNps = id =>
  api.get(`/api/v1/customers/${id}/nps`)

// ─────────────────────────────────────────────────────────────────────────────
// Messages
// ─────────────────────────────────────────────────────────────────────────────

/** POST /api/v1/messages/send
 *  @param {object} payload — { customer_id|lead_id, content|template_name }
 */
export const sendMessage = payload =>
  api.post('/api/v1/messages/send', payload)

// ─────────────────────────────────────────────────────────────────────────────
// Broadcasts
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/v1/broadcasts */
export const listBroadcasts = (params = {}) =>
  api.get('/api/v1/broadcasts', { params })

/** POST /api/v1/broadcasts — creates draft */
export const createBroadcast = payload =>
  api.post('/api/v1/broadcasts', payload)

/** GET /api/v1/broadcasts/:id */
export const getBroadcast = id =>
  api.get(`/api/v1/broadcasts/${id}`)

/** POST /api/v1/broadcasts/:id/approve */
export const approveBroadcast = id =>
  api.post(`/api/v1/broadcasts/${id}/approve`)

/** POST /api/v1/broadcasts/:id/cancel */
export const cancelBroadcast = id =>
  api.post(`/api/v1/broadcasts/${id}/cancel`)

// ─────────────────────────────────────────────────────────────────────────────
// Templates
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/v1/templates */
export const listTemplates = () =>
  api.get('/api/v1/templates')

/** POST /api/v1/templates — meta_status starts as "pending" */
export const createTemplate = payload =>
  api.post('/api/v1/templates', payload)

/** PATCH /api/v1/templates/:id — rejected templates only */
export const updateTemplate = (id, payload) =>
  api.patch(`/api/v1/templates/${id}`, payload)

// ─────────────────────────────────────────────────────────────────────────────
// Drip Sequences
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/v1/drip-sequences */
export const getDripSequence = () =>
  api.get('/api/v1/drip-sequences')

/** PUT /api/v1/drip-sequences — Admin (owner role) only
 *  @param {object} payload — { messages: DripMessageConfig[] }
 */
export const updateDripSequence = payload =>
  api.put('/api/v1/drip-sequences', payload)
