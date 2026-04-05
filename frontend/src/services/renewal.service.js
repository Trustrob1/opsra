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

// ── Export ────────────────────────────────────────────────────────────────────

/**
 * fetchAllForExport
 *
 * Fetches all non-cancelled subscriptions for CSV export.
 * Uses page_size=500 (the server cap) to get all rows in one request.
 * Excludes 'cancelled' status — no point asking staff to collect payment
 * for subscriptions that have been deliberately ended.
 *
 * Returns flat array of subscription objects (with customer join).
 */
export async function fetchAllForExport() {
  const statuses = ['trial', 'active', 'grace_period', 'expired', 'suspended']
  const all = []

  for (const s of statuses) {
    const res = await axios.get(`${BASE}/api/v1/subscriptions`, {
      headers: authHeaders(),
      params: { status: s, page: 1, page_size: 500 },
    })
    if (res.data?.success) {
      all.push(...(res.data.data?.items ?? []))
    }
  }

  return all
}

/**
 * generateRenewalExportCSV
 *
 * Converts subscription objects into a CSV string that staff use as a
 * payment reconciliation template. Pre-fills all subscription fields.
 * Leaves payment_channel, payment_date, reference, notes blank — staff
 * fills these from the bank statement / cash register before re-uploading.
 *
 * CSV column design:
 *   subscription_id   — for Method 1 matching on re-upload
 *   customer_name     — human-readable label (NOT used by the importer)
 *   phone             — for Method 2 phone-fallback matching on re-upload
 *   plan_tier         — informational
 *   amount_due        — pre-filled from subscription.amount (what they owe)
 *   period_end        — renewal deadline so staff can prioritise
 *   status            — current status
 *   payment_channel   — BLANK — staff fills from bank statement
 *   payment_date      — BLANK — staff fills from bank statement
 *   reference         — BLANK — staff fills from bank statement
 *   notes             — BLANK — optional staff notes
 *
 * @param {Array} subscriptions — from fetchAllForExport()
 * @returns {string}            — CSV content as a string
 */
export function generateRenewalExportCSV(subscriptions) {
  const headers = [
    'subscription_id',
    'customer_name',
    'phone',
    'plan_tier',
    'amount_due',
    'period_end',
    'status',
    'payment_channel',
    'payment_date',
    'reference',
    'notes',
  ]

  const escape = (val) => {
    if (val == null || val === '') return ''
    const str = String(val)
    // Wrap in quotes if value contains comma, quote, or newline
    if (str.includes(',') || str.includes('"') || str.includes('\n')) {
      return `"${str.replace(/"/g, '""')}"`
    }
    return str
  }

  const rows = subscriptions.map(sub => {
    const customer = sub.customer ?? {}
    return [
      escape(sub.id),
      escape(customer.full_name ?? customer.business_name ?? ''),
      escape(customer.phone ?? ''),
      escape(sub.plan_tier ?? ''),
      escape(sub.amount ?? ''),
      escape(sub.current_period_end?.slice(0, 10) ?? ''),
      escape(sub.status ?? ''),
      '',   // payment_channel — staff fills
      '',   // payment_date    — staff fills
      '',   // reference       — staff fills
      '',   // notes           — staff fills
    ].join(',')
  })

  return [headers.join(','), ...rows].join('\r\n')
}

/**
 * downloadCSV
 *
 * Triggers a browser file download for a CSV string.
 * Uses a temporary anchor element — no server request needed.
 *
 * @param {string} csvContent — CSV string from generateRenewalExportCSV()
 * @param {string} filename   — e.g. 'renewals-2026-03-31.csv'
 */
export function downloadCSV(csvContent, filename) {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url  = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href     = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
