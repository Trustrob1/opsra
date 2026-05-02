/**
 * customers.service.js — Module 02 customer API calls.
 *
 * M01-7a additions:
 *   getCustomerAttentionSummary() — multi-signal badge data for CustomerList
 *
 * Base URL: /api/v1  ·  Auth: Authorization: Bearer <token>
 * Response envelope: { success, data, message, error }
 *
 * SECURITY:
 *   - org_id is NEVER sent in any request body — derived from JWT server-side.
 *   - Uses the same axios instance + interceptor pattern as leads.service.js.
 *   - Pattern 50: axios + _h() pattern — consistent with admin.service.js.
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : 'http://localhost:8000/api/v1'

const api = axios.create({ baseURL: BASE })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().clearAuth()
    }
    return Promise.reject(err)
  },
)

// ─── M01-7a Attention Summary ─────────────────────────────────────────────────

/**
 * GET /api/v1/customers/attention-summary
 * Returns { customer_id: { has_attention, unread_messages, open_tickets,
 *                           churn_risk, reasons } }
 * Used by CustomerList to render attention badges on each customer row.
 * Scoped roles receive only their assigned customers.
 */
export async function getCustomerAttentionSummary() {
  const res = await api.get('/customers/attention-summary')
  return res.data
}

// ── Customer Contacts — WH-0 ──────────────────────────────────────────────────

export async function getCustomerContacts(customerId) {
  const res = await api.get(`/customers/${customerId}/contacts`)
  return res.data
}

export async function addCustomerContact(customerId, payload) {
  // payload: { phone_number, name?, contact_role? }
  const res = await api.post(`/customers/${customerId}/contacts`, payload)
  return res.data
}

export async function approveContact(contactId) {
  const res = await api.patch(`/customers/contacts/${contactId}/approve`)
  return res.data
}

export async function removeContact(contactId) {
  const res = await api.delete(`/customers/contacts/${contactId}`)
  return res.data
}