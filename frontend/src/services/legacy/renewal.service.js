/**
 * renewal.service.js — Renewal & Subscription API service
 *
 * Covers all 7 subscription endpoints defined in Phase 5A.
 *
 * SECURITY (Technical Spec §11.1):
 *   F1 — JWT from Zustand in-memory store only. Never localStorage.
 *   F2 — org_id is never included in any request payload; derived server-side.
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/** Returns the Authorization header using the in-memory JWT. */
function authHeaders() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

// ── List & Detail ─────────────────────────────────────────────────────────────

/**
 * listSubscriptions
 *
 * Query params (all optional):
 *   status               — one of SUBSCRIPTION_STATUSES
 *   plan_tier            — one of PLAN_TIERS
 *   renewal_window_days  — integer; returns subs expiring within N days
 *   page                 — default 1
 *   page_size            — default 20, max 500
 *
 * Returns paginated envelope:
 *   { success, data: { items, total, page, page_size, has_more } }
 */
export async function listSubscriptions(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/subscriptions`, {
    headers: authHeaders(),
    params,
  })
  return res.data
}

/**
 * getSubscription
 *
 * Returns full subscription record including payment history:
 *   { success, data: { subscription: {...}, payment_history: [...] } }
 */
export async function getSubscription(id) {
  const res = await axios.get(`${BASE}/api/v1/subscriptions/${id}`, {
    headers: authHeaders(),
  })
  return res.data
}

// ── Mutations ─────────────────────────────────────────────────────────────────

/**
 * updateSubscription [Admin]
 *
 * Payload (SubscriptionUpdate — all optional):
 *   plan_tier, billing_cycle, amount, period_start, period_end, notes
 *
 * Returns { success, data: {...updatedSubscription} }
 */
export async function updateSubscription(id, payload) {
  const res = await axios.patch(
    `${BASE}/api/v1/subscriptions/${id}`,
    payload,
    { headers: authHeaders() },
  )
  return res.data
}

/**
 * confirmPayment — Method 2: manual payment confirmation
 *
 * Payload (ConfirmPaymentRequest):
 *   amount_paid         number  — required
 *   payment_channel     string  — required; one of PAYMENT_CHANNELS
 *   payment_reference   string  — optional; used for duplicate-reference check (DRD §6.4)
 *   payment_date        string  — required; ISO date string (YYYY-MM-DD)
 *   notes               string  — optional; max 5,000 chars
 *
 * Returns { success, data: {...updatedSubscription} }
 */
export async function confirmPayment(id, payload) {
  const res = await axios.post(
    `${BASE}/api/v1/subscriptions/${id}/confirm-payment`,
    payload,
    { headers: authHeaders() },
  )
  return res.data
}

/**
 * cancelSubscription [Owner only]
 *
 * Payload (CancelSubscriptionRequest):
 *   reason   string — required; one of CANCELLATION_REASONS
 *   notes    string — optional; max 5,000 chars
 *
 * Returns { success, data: {...updatedSubscription} }
 */
export async function cancelSubscription(id, payload) {
  const res = await axios.post(
    `${BASE}/api/v1/subscriptions/${id}/cancel`,
    payload,
    { headers: authHeaders() },
  )
  return res.data
}

// ── Bulk Confirm ──────────────────────────────────────────────────────────────

/**
 * bulkConfirmUpload — Method 3: CSV/Excel bulk payment confirmation
 *
 * Sends multipart/form-data with a 'file' field (CSV or XLSX).
 * The backend enforces MIME allowlist and 25 MB cap (§11.5).
 *
 * Returns HTTP 202:
 *   { success, data: { job_id }, message }
 *
 * Use pollBulkConfirmJob(job_id) to track progress.
 */
export async function bulkConfirmUpload(file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await axios.post(
    `${BASE}/api/v1/subscriptions/bulk-confirm`,
    formData,
    { headers: { ...authHeaders(), 'Content-Type': 'multipart/form-data' } },
  )
  return res.data
}

/**
 * pollBulkConfirmJob — poll job status until 'done' or 'failed'
 *
 * Returns:
 *   { success, data: { job_id, status, total, confirmed, failed, errors: [{row, message}] } }
 *
 * Statuses: 'pending' | 'processing' | 'done' | 'failed'
 */
export async function pollBulkConfirmJob(jobId) {
  const res = await axios.get(
    `${BASE}/api/v1/subscriptions/bulk-confirm/${jobId}`,
    { headers: authHeaders() },
  )
  return res.data
}
