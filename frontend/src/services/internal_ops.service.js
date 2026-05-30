/**
 * frontend/src/services/ops.service.js
 * OPS-1 — Internal Ops API client (Issue Tracker + Activity Log)
 *
 * Pattern 11: JWT from Zustand store only — never localStorage
 * Pattern 12: org_id / user_id / team never in any payload — derived server-side from JWT
 *
 * Uses same axios + authHeaders() pattern as tasks.service.js.
 * Does NOT use api.js — no cold-start retry needed for this module.
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

// ── Internal Issues ───────────────────────────────────────────────────────────

/**
 * Get issue counts by status and team.
 * @returns {{ by_status, by_team, overdue }}
 */
export async function getIssuesSummary() {
  const res = await axios.get(`${BASE}/internal-issues/summary`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * List issues — filterable.
 * @param {object} params — team, status_filter, assigned_to, reported_by, priority
 */
export async function listIssues(params = {}) {
  const res = await axios.get(`${BASE}/internal-issues`, {
    headers: authHeaders(),
    params,
  })
  return res.data.data  // { items, total }
}

/**
 * Create a new issue.
 * @param {object} payload — title, description, team, category, priority, assigned_to
 */
export async function createIssue(payload) {
  const res = await axios.post(`${BASE}/internal-issues`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Get a single issue by ID.
 * @param {string} id
 */
export async function getIssue(id) {
  const res = await axios.get(`${BASE}/internal-issues/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Update an issue (status, assignee, resolution notes, etc.)
 * @param {string} id
 * @param {object} payload — any IssueUpdate fields
 */
export async function updateIssue(id, payload) {
  const res = await axios.patch(`${BASE}/internal-issues/${id}`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Soft-delete an issue. Owner/ops_manager only.
 * @param {string} id
 */
export async function deleteIssue(id) {
  const res = await axios.delete(`${BASE}/internal-issues/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

// ── Activity Logs ─────────────────────────────────────────────────────────────

/**
 * Get weekly activity summary for all team members (manager view).
 * @returns {{ week_start, members }}
 */
export async function getActivityLogsSummary() {
  const res = await axios.get(`${BASE}/activity-logs/summary`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Submit (create or update) a daily or weekly activity log.
 * user_id and team are set server-side from JWT — never pass them here.
 * @param {object} payload — log_date, log_type, activities, blockers, plan
 */
export async function submitActivityLog(payload) {
  const res = await axios.post(`${BASE}/activity-logs`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * List activity logs.
 * @param {object} params — user_id_filter, team, log_type, date_from, date_to
 */
export async function listActivityLogs(params = {}) {
  const res = await axios.get(`${BASE}/activity-logs`, {
    headers: authHeaders(),
    params,
  })
  return res.data.data  // { items, total }
}

/**
 * Edit an existing activity log entry. Own logs only.
 * @param {string} id
 * @param {object} payload — activities, blockers, plan
 */
export async function updateActivityLog(id, payload) {
  const res = await axios.patch(`${BASE}/activity-logs/${id}`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Download Internal Ops Issues report as a PDF blob.
 * Owner/ops_manager only. Rate limited to 10/hr per org.
 * @param {object} params — date_from, date_to, team, category,
 *                          status_filter, priority (all optional)
 * @returns {Blob} PDF blob for browser download
 */
export async function downloadInternalOpsReport(params = {}) {
  const res = await axios.get(`${BASE}/internal-issues/report/download`, {
    headers: { ...authHeaders(), Accept: 'application/pdf' },
    params,
    responseType: 'blob',
  })
  return res.data
}