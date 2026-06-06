/**
 * frontend/src/services/performance_logs.service.js
 * CPM-1B — Daily Performance Tracking API client
 *
 * Pattern 11: JWT from Zustand store only — never localStorage
 * Pattern 12: org_id / user_id never in any payload — derived server-side from JWT
 *
 * Public routes (getPublicLogForm, submitPublicLog) use no auth headers.
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

function authHeaders() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

// ── Manager routes (JWT-gated) ────────────────────────────────────────────────

/**
 * Generate or regenerate a public log token + PIN for a contractor.
 * @param {string} contractorId
 * @param {object} payload — { pin, log_retention_months, regenerate_token }
 * @returns {{ log_token, log_url, log_retention_months }}
 */
export async function generateLogToken(contractorId, payload) {
  const res = await axios.post(
    `${BASE}/performance-logs/generate-token/${contractorId}`,
    payload,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * List all daily logs for a contractor, optionally filtered by date range.
 * @param {string} contractorId
 * @param {object} params — { date_from, date_to } (optional ISO dates)
 * @returns {{ items, total }}
 */
export async function getPerformanceLogs(contractorId, params = {}) {
  const res = await axios.get(`${BASE}/performance-logs/${contractorId}`, {
    headers: authHeaders(),
    params,
  })
  return res.data.data
}

/**
 * Log a daily entry directly (manager, bypasses PIN).
 * Upserts on (entity_id, kpi_key, log_date).
 * @param {string} contractorId
 * @param {object} payload — { kpi_key, kpi_label, log_date, value, label_value, notes }
 */
export async function logDailyEntry(contractorId, payload) {
  const res = await axios.post(
    `${BASE}/performance-logs/${contractorId}`,
    payload,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * Update an existing daily log entry.
 * @param {string} contractorId
 * @param {string} logId
 * @param {object} payload — { value, label_value, notes }
 */
export async function updateDailyLog(contractorId, logId, payload) {
  const res = await axios.patch(
    `${BASE}/performance-logs/${contractorId}/${logId}`,
    payload,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * Delete a daily log entry.
 * @param {string} contractorId
 * @param {string} logId
 */
export async function deleteDailyLog(contractorId, logId) {
  const res = await axios.delete(
    `${BASE}/performance-logs/${contractorId}/${logId}`,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * Get computed summary for a contractor — running totals, pace, weekly breakdown.
 * @param {string} contractorId
 * @param {object} params — { month } ISO date (optional, defaults to current month)
 * @returns {object} summary with kpi_summaries array
 */
export async function getPerformanceSummary(contractorId, params = {}) {
  const res = await axios.get(
    `${BASE}/performance-logs/${contractorId}/summary`,
    { headers: authHeaders(), params }
  )
  return res.data.data
}

// ── Public routes (no auth headers) ──────────────────────────────────────────

/**
 * Fetch the public log form data for a given token.
 * No auth — used by PublicLogPage before PIN submission.
 * @param {string} token — 64-char hex token from URL
 * @returns {{ contractor_id, full_name, role_title, kpi_targets }}
 */
export async function getPublicLogForm(token) {
  const res = await axios.get(`${BASE}/performance-logs/public/${token}`)
  return res.data.data
}

/**
 * Submit a daily log via the public contractor link (PIN-gated).
 * No auth header — PIN is the only verification.
 * @param {string} token — 64-char hex token from URL
 * @param {object} payload — { pin, log_date, entries: [{ kpi_key, value, ... }] }
 * @returns {{ saved, contractor_name, log_date }}
 */
export async function submitPublicLog(token, payload) {
  const res = await axios.post(
    `${BASE}/performance-logs/public/${token}`,
    payload
  )
  return res.data.data
}

// ── Contractor daily activity logs ────────────────────────────────────────

export async function submitPublicActivities(token, payload) {
  // payload: { pin, log_date, activities: [{activity_description, activity_type, duration_minutes, has_blocker, blocker_note}] }
  const r = await axios.post(`${BASE}/performance-logs/public/${token}/activities`, payload)
  return r.data
}

export async function listActivityLogs(contractorId, params = {}) {
  const r = await axios.get(`${BASE}/performance-logs/${contractorId}/activities`, {
    headers: authHeaders(), params,
  })
  return r.data.data
}

export async function flagActivityLog(contractorId, logId, flagged) {
  const r = await axios.patch(
    `${BASE}/performance-logs/${contractorId}/activities/${logId}/flag`,
    { needs_management_attention: flagged },
    { headers: authHeaders() }
  )
  return r.data.data
}

export async function resolveActivityLog(contractorId, logId, resolutionNote) {
  const r = await axios.patch(
    `${BASE}/performance-logs/${contractorId}/activities/${logId}/resolve`,
    { resolution_note: resolutionNote },
    { headers: authHeaders() }
  )
  return r.data.data
}