/**
 * frontend/src/services/commissions.service.js
 * Commission tracking API service — Phase 9C
 *
 * Pattern 11: JWT from Zustand only
 * Pattern 12: org_id never in payload
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function _h() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

/**
 * List commissions.
 * Affiliates see own records; managers can pass affiliateUserId to filter.
 * @param {object} params — { affiliateUserId, status, eventType, page, pageSize }
 */
export async function listCommissions(params = {}) {
  const query = {}
  if (params.affiliateUserId) query.affiliate_user_id = params.affiliateUserId
  if (params.status)          query.status            = params.status
  if (params.eventType)       query.event_type        = params.eventType
  if (params.page)            query.page              = params.page
  if (params.pageSize)        query.page_size         = params.pageSize
  const r = await axios.get(`${BASE}/api/v1/commissions`, {
    headers: _h(), params: query,
  })
  return r.data.data
}

/**
 * Get commission summary totals by status.
 * Returns { total_count, total_amount_ngn, by_status }
 */
export async function getCommissionSummary() {
  const r = await axios.get(`${BASE}/api/v1/commissions/summary`, { headers: _h() })
  return r.data.data
}

/**
 * Update a commission (manager only).
 * @param {string} id
 * @param {object} payload — { amount_ngn?, status?, notes? }
 */
export async function updateCommission(id, payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/commissions/${id}`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}
