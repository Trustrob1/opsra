/**
 * frontend/src/services/reports.service.js
 * Management Reports API service — RPT-1B.
 *
 * Pattern 50: axios + _h() only, never fetch. Relative paths via BASE.
 * Pattern 11: JWT in Zustand memory only — never localStorage.
 * Pattern 12: org_id never sent in frontend payloads.
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function _h() {
  const token = useAuthStore.getState().token
  return { headers: { Authorization: `Bearer ${token}` } }
}

// ---------------------------------------------------------------------------
// Report endpoints
// ---------------------------------------------------------------------------

/**
 * Fetch the full report JSON for preview.
 * @param {Object} params
 * @param {string} [params.period_preset]   — e.g. "last_30d"
 * @param {string} [params.date_from]       — ISO date (custom range)
 * @param {string} [params.date_to]         — ISO date (custom range)
 * @param {string} [params.sections]        — comma-separated section keys
 * @param {string} [params.team]            — team filter
 * @param {string} [params.rep_id]          — rep UUID filter
 * @param {string} [params.compare]         — "previous_period"|"year_on_year"|"none"
 */
export async function getFullReport(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/reports/full`, {
    ..._h(),
    params,
  })
  return r.data.data
}

/**
 * Download the report as a PDF blob.
 * Returns a Blob — caller is responsible for triggering browser download.
 * @param {Object} params — same shape as getFullReport
 */
export async function downloadReport(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/reports/download`, {
    ..._h(),
    params,
    responseType: 'blob',
  })
  return r.data
}

/**
 * Fetch the list of available section keys with labels and descriptions.
 */
export async function getReportSections() {
  const r = await axios.get(`${BASE}/api/v1/reports/sections`, _h())
  return r.data.data
}

// ---------------------------------------------------------------------------
// Scheduled reports
// ---------------------------------------------------------------------------

export async function getScheduledReports() {
  const r = await axios.get(`${BASE}/api/v1/reports/scheduled`, _h())
  return r.data.data
}

/**
 * @param {Object} payload — ScheduledReportCreate shape
 * @param {string}   payload.label
 * @param {string}   payload.frequency         — "weekly"|"monthly"
 * @param {number}   [payload.day_of_week]     — 0=Mon…6=Sun (required if weekly)
 * @param {number}   [payload.day_of_month]    — 1–28 (required if monthly)
 * @param {number}   payload.send_hour         — 0–23 UTC
 * @param {string[]} payload.sections          — section key array
 * @param {string}   payload.period_preset
 * @param {string}   payload.delivery_channel  — "email"|"whatsapp"
 * @param {string[]} payload.recipients        — email addresses or E.164 phone numbers
 */
export async function createScheduledReport(payload) {
  const r = await axios.post(`${BASE}/api/v1/reports/scheduled`, payload, _h())
  return r.data.data
}

export async function updateScheduledReport(id, payload) {
  const r = await axios.patch(`${BASE}/api/v1/reports/scheduled/${id}`, payload, _h())
  return r.data.data
}

export async function deleteScheduledReport(id) {
  const r = await axios.delete(`${BASE}/api/v1/reports/scheduled/${id}`, _h())
  return r.data
}

// ---------------------------------------------------------------------------
// Supporting data for filters
// ---------------------------------------------------------------------------

/**
 * Fetch org users for the staff/rep filter dropdown.
 * Uses /api/v1/admin/users — filtered client-side to sales_agent and
 * customer_success roles for the rep filter dropdown.
 * S14: returns [] on any failure.
 */
export async function getOrgUsers() {
  try {
    const r = await axios.get(`${BASE}/api/v1/admin/users`, _h())
    return r.data?.data?.items ?? r.data?.data ?? []
  } catch {
    return []
  }
}
