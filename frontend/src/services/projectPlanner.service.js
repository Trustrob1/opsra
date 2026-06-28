/**
 * frontend/src/services/projectPlanner.service.js
 *
 * Conventions matched against the real leads.service.js / api.js:
 *   - import api from './api' (default export, shared Axios instance)
 *   - Every function returns res.data verbatim — the full envelope
 *     { success, data, message } — NOT pre-unwrapped to res.data.data.
 *     Unwrapping is the caller's job, same as every function in
 *     leads.service.js (listLeads, createLead, getLead, etc.)
 *   - Multipart upload sets Content-Type: multipart/form-data explicitly,
 *     matching importLeads()'s exact style — not the "let the browser set
 *     the boundary" assumption I'd guessed at before seeing this file.
 *   - org_id is NEVER sent in any payload — derived from JWT server-side.
 */
import api from './api'

const BASE_PATH = '/api/v1/project-planner'

// ─── Plans ───────────────────────────────────────────────────────────────────

/** GET /api/v1/project-planner/plans */
export async function listPlans() {
  const res = await api.get(`${BASE_PATH}/plans`)
  return res.data
}

/** POST /api/v1/project-planner/plans  Body: { name } */
export async function createPlan(name) {
  const res = await api.post(`${BASE_PATH}/plans`, { name })
  return res.data
}

/** PATCH /api/v1/project-planner/plans/{id} */
export async function updatePlan(planId, payload) {
  const res = await api.patch(`${BASE_PATH}/plans/${planId}`, payload)
  return res.data
}

/** DELETE /api/v1/project-planner/plans/{id} */
export async function deletePlan(planId) {
  const res = await api.delete(`${BASE_PATH}/plans/${planId}`)
  return res.data
}

// ─── Strategies ──────────────────────────────────────────────────────────────

/** GET /api/v1/project-planner/plans/{planId}/strategies */
export async function listStrategies(planId) {
  const res = await api.get(`${BASE_PATH}/plans/${planId}/strategies`)
  return res.data
}

/** POST /api/v1/project-planner/strategies  Body: { plan_id, phase, channel, title, description } */
export async function createStrategy(payload) {
  const res = await api.post(`${BASE_PATH}/strategies`, payload)
  return res.data
}

/** PATCH /api/v1/project-planner/strategies/{id} */
export async function updateStrategy(strategyId, payload) {
  const res = await api.patch(`${BASE_PATH}/strategies/${strategyId}`, payload)
  return res.data
}

/** DELETE /api/v1/project-planner/strategies/{id} */
export async function deleteStrategy(strategyId) {
  const res = await api.delete(`${BASE_PATH}/strategies/${strategyId}`)
  return res.data
}

/** POST /api/v1/project-planner/strategies/{id}/approve — owner + ops_manager only */
export async function approveStrategy(strategyId) {
  const res = await api.post(`${BASE_PATH}/strategies/${strategyId}/approve`, {})
  return res.data
}

/** POST /api/v1/project-planner/strategies/{id}/revert — owner + ops_manager only */
export async function revertStrategy(strategyId) {
  const res = await api.post(`${BASE_PATH}/strategies/${strategyId}/revert`, {})
  return res.data
}

// ─── Phases & Tasks ──────────────────────────────────────────────────────────

/** POST /api/v1/project-planner/strategies/{strategyId}/phases  Body: { title, sub_label, position } */
export async function createPhase(strategyId, payload) {
  const res = await api.post(`${BASE_PATH}/strategies/${strategyId}/phases`, payload)
  return res.data
}

/** PATCH /api/v1/project-planner/phases/{phaseId}  Body: { title?, sub_label? } */
export async function updatePhase(phaseId, payload) {
  const res = await api.patch(`${BASE_PATH}/phases/${phaseId}`, payload)
  return res.data
}

/**
 * POST /api/v1/project-planner/phases/{phaseId}/tasks
 * Body: { title, description, owner_label, due_date } — owner is free text only.
 */
export async function createTask(phaseId, payload) {
  const res = await api.post(`${BASE_PATH}/phases/${phaseId}/tasks`, payload)
  return res.data
}

/** PATCH /api/v1/project-planner/tasks/{id} */
export async function updateTask(taskId, payload) {
  const res = await api.patch(`${BASE_PATH}/tasks/${taskId}`, payload)
  return res.data
}

/** DELETE /api/v1/project-planner/tasks/{id} */
export async function deleteTask(taskId) {
  const res = await api.delete(`${BASE_PATH}/tasks/${taskId}`)
  return res.data
}

// ─── Strategy documents ──────────────────────────────────────────────────────

/**
 * POST /api/v1/project-planner/strategies/{strategyId}/documents
 * Multipart upload. Mirrors importLeads()'s exact header style.
 * @param {string} strategyId
 * @param {FormData} formData — must include the file under the 'file' key
 */
export async function uploadStrategyDocument(strategyId, formData) {
  const res = await api.post(`${BASE_PATH}/strategies/${strategyId}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

/** POST /api/v1/project-planner/strategies/{strategyId}/documents/link  Body: { external_link } */
export async function setStrategyDocumentLink(strategyId, externalLink) {
  const res = await api.post(`${BASE_PATH}/strategies/${strategyId}/documents/link`, {
    external_link: externalLink,
  })
  return res.data
}

/** GET /api/v1/project-planner/documents/{id}/download-url — returns { url } inside data */
export async function getDocumentDownloadUrl(documentId) {
  const res = await api.get(`${BASE_PATH}/documents/${documentId}/download-url`)
  return res.data
}

/** DELETE /api/v1/project-planner/documents/{id} */
export async function deleteDocument(documentId) {
  const res = await api.delete(`${BASE_PATH}/documents/${documentId}`)
  return res.data
}
