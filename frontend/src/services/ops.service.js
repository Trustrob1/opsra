/**
 * services/ops.service.js
 * Operations Intelligence API functions — Phase 6B.
 *
 * Functions:
 *   getDashboardMetrics()   GET  /api/v1/dashboard/metrics
 *   askData(question)       POST /api/v1/ask
 *
 * Security (Technical Spec §11.1):
 *   - JWT from Zustand store only — never localStorage (Pattern 11)
 *   - org_id never sent in any payload (Pattern 12)
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function authHeaders() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

/**
 * Fetch aggregated executive dashboard metrics.
 * Revenue fields (mrr_ngn, revenue_at_risk_ngn) are null for agents — scoped server-side.
 * @returns {Promise<object>} DashboardMetrics dict
 */
export async function getDashboardMetrics() {
  const res = await axios.get(`${BASE}/api/v1/dashboard/metrics`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Send a natural-language question to the ask-your-data assistant.
 * Rate limited to 30 calls per hour per user (S15).
 * @param {string} question — 1–1000 characters
 * @returns {Promise<string>} Plain-English answer
 * @throws axios error — caller handles 429 (rate limited) separately
 */
export async function askData(question) {
  const res = await axios.post(
    `${BASE}/api/v1/ask`,
    { question },
    { headers: authHeaders() },
  )
  return res.data.data.answer
}
