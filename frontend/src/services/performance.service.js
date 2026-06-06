/**
 * frontend/src/services/performance.service.js
 *
 * All API calls for PERF-1 Performance & Operations Hub.
 * Pattern 50 — axios + _h() only, never fetch.
 * Pattern 12 — org_id never in payloads.
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function _h() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

// ── Scorecard ──────────────────────────────────────────────────────────────

export async function getScorecard(month) {
  const params = month ? { month } : {}
  const r = await axios.get(`${BASE}/api/v1/performance/scorecard`, { headers: _h(), params })
  return r.data.data
}

// ── Staff profile ──────────────────────────────────────────────────────────

export async function getStaffProfile(userId, month) {
  const params = month ? { month } : {}
  const r = await axios.get(`${BASE}/api/v1/performance/staff/${userId}`, { headers: _h(), params })
  return r.data.data
}

// ── KPI templates ──────────────────────────────────────────────────────────

export async function getKpiTemplates() {
  const r = await axios.get(`${BASE}/api/v1/performance/kpi-templates`, { headers: _h() })
  return r.data.data
}

export async function createKpiTemplate(payload) {
  const r = await axios.post(`${BASE}/api/v1/performance/kpi-templates`, payload, { headers: _h() })
  return r.data.data
}

export async function updateKpiTemplate(templateId, updates) {
  const r = await axios.patch(`${BASE}/api/v1/performance/kpi-templates/${templateId}`, updates, { headers: _h() })
  return r.data.data
}

export async function deleteKpiTemplate(templateId) {
  const r = await axios.delete(`${BASE}/api/v1/performance/kpi-templates/${templateId}`, { headers: _h() })
  return r.data.data
}

// ── Targets ────────────────────────────────────────────────────────────────

export async function getTargets(userId, month) {
  const r = await axios.get(`${BASE}/api/v1/performance/targets/${userId}/${month}`, { headers: _h() })
  return r.data.data
}

export async function setTargets(userId, month, targets) {
  const r = await axios.post(`${BASE}/api/v1/performance/targets`, { user_id: userId, month, targets }, { headers: _h() })
  return r.data.data
}

export async function acknowledgeTargets(month) {
  const r = await axios.post(
    `${BASE}/api/v1/performance/targets/acknowledge/acknowledge`,
    {},
    { headers: _h(), params: { month } }
  )
  return r.data.data
}

// ── Staff log ──────────────────────────────────────────────────────────────

export async function createStaffLog(payload) {
  const r = await axios.post(`${BASE}/api/v1/performance/staff-log`, payload, { headers: _h() })
  return r.data.data
}

export async function updateStaffLog(logId, updates) {
  const r = await axios.patch(`${BASE}/api/v1/performance/staff-log/${logId}`, updates, { headers: _h() })
  return r.data.data
}

// ── Health score ───────────────────────────────────────────────────────────

export async function getHealthScore() {
  const r = await axios.get(`${BASE}/api/v1/performance/health-score`, { headers: _h() })
  return r.data.data
}

// ── Owner dashboard setup ──────────────────────────────────────────────────

export async function getOwnerDashboardSetup() {
  const r = await axios.get(`${BASE}/api/v1/performance/owner-dashboard/setup`, { headers: _h() })
  return r.data.data
}

export async function setOwnerDashboardPin(pin) {
  const r = await axios.post(`${BASE}/api/v1/performance/owner-dashboard/setup`, { pin }, { headers: _h() })
  return r.data.data
}

// ── Public owner dashboard (no auth header — PIN session token) ────────────

export async function verifyOwnerDashboardPin(token, pin) {
  const r = await axios.post(`${BASE}/api/v1/public/owner-dashboard/${token}/verify`, { pin })
  return r.data
}

export async function getOwnerDashboardPanels(token, sessionToken) {
  const r = await axios.get(`${BASE}/api/v1/public/owner-dashboard/${token}`, {
    headers: { Authorization: `Bearer ${sessionToken}` },
  })
  return r.data
}

export async function approveOwnerLog(token, logId, sessionToken) {
  const r = await axios.post(
    `${BASE}/api/v1/public/owner-dashboard/${token}/approve`,
    { log_id: logId },
    { headers: { Authorization: `Bearer ${sessionToken}` } }
  )
  return r.data
}

export async function flagOwnerLog(token, logId, note, sessionToken) {
  const r = await axios.post(
    `${BASE}/api/v1/public/owner-dashboard/${token}/flag`,
    { log_id: logId, note },
    { headers: { Authorization: `Bearer ${sessionToken}` } }
  )
  return r.data
}

// ── Business Goals ─────────────────────────────────────────────────────────

export async function getBusinessGoals(periodStart) {
  const r = await axios.get(`${BASE}/api/v1/performance/business-goals`,
    { headers: _h(), params: { period_start: periodStart } })
  return r.data.data
}

export async function upsertBusinessGoal(payload) {
  const r = await axios.post(`${BASE}/api/v1/performance/business-goals`,
    payload, { headers: _h() })
  return r.data.data
}

export async function deleteBusinessGoal(goalId, periodStart) {
  const r = await axios.delete(
    `${BASE}/api/v1/performance/business-goals/${goalId}`,
    { headers: _h(), params: { period_start: periodStart } }
  )
  return r.data.data
}

export async function getOwnerDashboardGoals(token, sessionToken, periodStart) {
  const r = await axios.get(
    `${BASE}/api/v1/public/owner-dashboard/${token}/goals`,
    { headers: { Authorization: `Bearer ${sessionToken}` }, params: { period_start: periodStart } }
  )
  return r.data.data
}


// ── Daily Executive Brief (public) ────────────────────────────────────────

export async function getOwnerBrief(token, sessionToken, date = null) {
  const params = date ? { date } : {}
  const r = await axios.get(
    `${BASE}/api/v1/public/owner-dashboard/${token}/brief`,
    { headers: { Authorization: `Bearer ${sessionToken}` }, params }
  )
  return r.data
}

// ── Toggle owner attention on an issue (authenticated) ────────────────────

export async function toggleOwnerAttention(issueId, flagged) {
  const r = await axios.patch(
    `${BASE}/api/v1/performance/issues/${issueId}/owner-attention`,
    {},
    { headers: _h(), params: { flagged } }
  )
  return r.data.data
}
