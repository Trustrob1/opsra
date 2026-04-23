/**
 * frontend/src/services/admin.service.js
 * Admin Dashboard API service — Phase 8B
 *
 * Security (Technical Spec §11.1):
 *   - JWT read from Zustand store only — never localStorage (Pattern 11)
 *   - org_id never sent in any payload — derived from JWT server-side (Pattern 12)
 *
 * Covers:
 *   User Management    — listUsers, createUser, updateUser, forceLogout
 *   Role Management    — listRoles, createRole, updateRole
 *   Role Overrides     — listUserOverrides, createUserOverride, deleteUserOverride
 *   Routing Rules      — listRoutingRules, createRoutingRule, updateRoutingRule, deleteRoutingRule
 *   Integration Status — getIntegrationStatus
 *   Commission Settings — getCommissionSettings, updateCommissionSettings
 *   Lead Scoring Rubric — getScoringRubric, updateScoringRubric
 *   Qualification Bot  — getQualificationBot, updateQualificationBot, getQualificationAiRecommendations
 *   Lead SLA Config    — getSlaConfig, updateSlaConfig  (M01-6)
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function _h() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

// ── User Management ──────────────────────────────────────────────────────────

export async function listUsers() {
  const r = await axios.get(`${BASE}/api/v1/admin/users`, { headers: _h() })
  return r.data.data
}

export async function createUser(payload) {
  // payload: { email, full_name, password, role_id }
  const r = await axios.post(`${BASE}/api/v1/admin/users`, payload, { headers: _h() })
  return r.data.data
}

export async function updateUser(id, payload) {
  // payload: any subset of { full_name, role_id, is_active, is_out_of_office }
  const r = await axios.patch(`${BASE}/api/v1/admin/users/${id}`, payload, { headers: _h() })
  return r.data.data
}

export async function forceLogout(id) {
  const r = await axios.post(
    `${BASE}/api/v1/admin/users/${id}/force-logout`,
    {},
    { headers: _h() },
  )
  return r.data.data
}

// ── Role Management ──────────────────────────────────────────────────────────

export async function listRoles() {
  const r = await axios.get(`${BASE}/api/v1/admin/roles`, { headers: _h() })
  return r.data.data
}

export async function createRole(payload) {
  // payload: { name, template, permissions }
  const r = await axios.post(`${BASE}/api/v1/admin/roles`, payload, { headers: _h() })
  return r.data.data
}

export async function updateRole(id, payload) {
  // payload: { name?, permissions? }
  const r = await axios.patch(`${BASE}/api/v1/admin/roles/${id}`, payload, { headers: _h() })
  return r.data.data
}

// ── Role User Overrides ──────────────────────────────────────────────────────

export async function listUserOverrides(roleId) {
  const r = await axios.get(
    `${BASE}/api/v1/admin/roles/${roleId}/overrides`,
    { headers: _h() },
  )
  return r.data.data
}

export async function createUserOverride(roleId, payload) {
  // payload: { user_id, permission_key, granted }
  const r = await axios.post(
    `${BASE}/api/v1/admin/roles/${roleId}/overrides`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

export async function deleteUserOverride(roleId, overrideId) {
  const r = await axios.delete(
    `${BASE}/api/v1/admin/roles/${roleId}/overrides/${overrideId}`,
    { headers: _h() },
  )
  return r.data.data
}

// ── Routing Rules ────────────────────────────────────────────────────────────

export async function listRoutingRules() {
  const r = await axios.get(`${BASE}/api/v1/admin/routing-rules`, { headers: _h() })
  return r.data.data
}

export async function createRoutingRule(payload) {
  const r = await axios.post(`${BASE}/api/v1/admin/routing-rules`, payload, { headers: _h() })
  return r.data.data
}

export async function updateRoutingRule(id, payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/admin/routing-rules/${id}`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

export async function deleteRoutingRule(id) {
  const r = await axios.delete(
    `${BASE}/api/v1/admin/routing-rules/${id}`,
    { headers: _h() },
  )
  return r.data.data
}

// ── Integration Status ───────────────────────────────────────────────────────

export async function getIntegrationStatus() {
  const r = await axios.get(`${BASE}/api/v1/admin/integrations`, { headers: _h() })
  return r.data.data
}

// ── Commission Settings ──────────────────────────────────────────────────────

export async function getCommissionSettings() {
  const r = await axios.get(`${BASE}/api/v1/admin/commission-settings`, { headers: _h() })
  return r.data.data
}

export async function updateCommissionSettings(payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/admin/commission-settings`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

// ── Lead Scoring Rubric — Feature 4 (Module 01 gaps) ────────────────────────

export async function getScoringRubric() {
  const r = await axios.get(`${BASE}/api/v1/admin/scoring-rubric`, { headers: _h() })
  return r.data.data
}

export async function updateScoringRubric(payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/admin/scoring-rubric`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

// ── Qualification Bot — M01-3 ─────────────────────────────────────────────────

export const getQualificationBot = () =>
  axios.get('/api/v1/admin/qualification-bot', { headers: _h() })
    .then(r => r.data.data)

export const updateQualificationBot = (payload) =>
  axios.patch('/api/v1/admin/qualification-bot', payload, { headers: _h() })
    .then(r => r.data.data)

export const getQualificationAiRecommendations = () =>
  axios.post('/api/v1/admin/qualification-bot/ai-recommendations', {}, { headers: _h() })
    .then(r => r.data.data)

// ── Lead SLA Config — M01-6 ──────────────────────────────────────────────────

export async function getSlaConfig() {
  const r = await axios.get(`${BASE}/api/v1/admin/sla-config`, { headers: _h() })
  return r.data.data
}

export async function updateSlaConfig(payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/admin/sla-config`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

// ── Nurture Config — M01-10a ──────────────────────────────────────────────────

export async function getNurtureConfig() {
  const r = await axios.get(`${BASE}/api/v1/admin/nurture-config`, { headers: _h() })
  return r.data.data
}

export async function updateNurtureConfig(payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/admin/nurture-config`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

// ── Triage Config — WH-0 ─────────────────────────────────────────────────────

export async function getTriageConfig() {
  const r = await axios.get(`${BASE}/api/v1/admin/triage-config`, { headers: _h() })
  return r.data.data
}

export async function updateTriageConfig(payload) {
  const r = await axios.patch(
    `${BASE}/api/v1/admin/triage-config`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

// ---------------------------------------------------------------------------
// WH-1b: Add these two functions to frontend/src/services/admin.service.js
// Pattern 50 — axios + _h() only, never fetch.
// ---------------------------------------------------------------------------

export const getQualificationFlow = () =>
  axios.get('/api/v1/admin/qualification-flow', { headers: _h() })
    .then(r => r.data.data)

export const updateQualificationFlow = (payload) =>
  axios.patch('/api/v1/admin/qualification-flow', payload, { headers: _h() })
    .then(r => r.data.data)
// ── Pipeline Stage Config — CONFIG-6 ─────────────────────────────────────────

export async function getPipelineStages() {
  const r = await axios.get(`${BASE}/api/v1/admin/pipeline-stages`, { headers: _h() })
  return r.data.data
}

export async function updatePipelineStages(payload) {
  // payload: { stages: [{ key, label, enabled }] }
  const r = await axios.patch(
    `${BASE}/api/v1/admin/pipeline-stages`,
    payload,
    { headers: _h() },
  )
  return r.data.data
}

// ── Ticket/KB Category Config — CONFIG-1 ─────────────────────────────────────

export const getTicketCategories = () =>
  axios.get('/api/v1/admin/ticket-categories', { headers: _h() })
    .then(r => r.data.data)

export const updateTicketCategories = (payload) =>
  axios.patch('/api/v1/admin/ticket-categories', payload, { headers: _h() })
    .then(r => r.data.data)


// ── Drip Business Types — CONFIG-2 ───────────────────────────────────────────

export const getDripBusinessTypes = () =>
  axios.get('/api/v1/admin/drip-business-types', { headers: _h() })
    .then(r => r.data.data)

export const updateDripBusinessTypes = (payload) =>
  axios.patch('/api/v1/admin/drip-business-types', payload, { headers: _h() })
    .then(r => r.data.data)

// ── SLA Business Hours — CONFIG-3 ────────────────────────────────────────────

export const getSlaBusinessHours = () =>
  axios.get('/api/v1/admin/sla-business-hours', { headers: _h() })
    .then(r => r.data.data)

export const updateSlaBusinessHours = (payload) =>
  axios.patch('/api/v1/admin/sla-business-hours', payload, { headers: _h() })
    .then(r => r.data.data)