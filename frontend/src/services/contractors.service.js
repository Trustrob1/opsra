/**
 * frontend/src/services/contractors.service.js
 * CPM-1 + CPM-1A — Contractor Performance Management API client
 *
 * Pattern 11: JWT from Zustand store only — never localStorage
 * Pattern 12: org_id / user_id never in any payload — derived server-side from JWT
 *
 * Uses same axios + authHeaders() pattern as internal_ops.service.js.
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

// ── Contractors ───────────────────────────────────────────────────────────────

/**
 * Get scorecard summary for all contractors (manager view).
 * Includes kpi_months and risk_summary per contractor.
 * @returns {{ items, total }}
 */
export async function getContractorScorecard() {
  const res = await axios.get(`${BASE}/contractors/scorecard`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * List all contractors for the org (no enrichment — lightweight).
 * @returns {{ items, total }}
 */
export async function listContractors() {
  const res = await axios.get(`${BASE}/contractors`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Create a new contractor profile.
 * @param {object} payload — ContractorCreate fields
 */
export async function createContractor(payload) {
  const res = await axios.post(`${BASE}/contractors`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Get a single contractor with full detail, kpi_months and risk_summary.
 * @param {string} id
 */
export async function getContractor(id) {
  const res = await axios.get(`${BASE}/contractors/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Update a contractor profile.
 * @param {string} id
 * @param {object} payload — ContractorUpdate fields
 */
export async function updateContractor(id, payload) {
  const res = await axios.patch(`${BASE}/contractors/${id}`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Soft-delete a contractor. Owner only.
 * @param {string} id
 */
export async function deleteContractor(id) {
  const res = await axios.delete(`${BASE}/contractors/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

// ── KPI Actuals ───────────────────────────────────────────────────────────────

/**
 * Get all KPI actuals for a contractor.
 * @param {string} contractorId
 * @returns {{ items, total }}
 */
export async function getKpiActuals(contractorId) {
  const res = await axios.get(`${BASE}/contractors/${contractorId}/kpi-actuals`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Log or update a monthly KPI actual (upsert).
 * Unique on (contractor_id, month_label, kpi_key).
 * @param {string} contractorId
 * @param {object} payload — { month_label, month_start, kpi_key, actual_value, actual_label, notes }
 */
export async function logKpiActual(contractorId, payload) {
  const res = await axios.post(
    `${BASE}/contractors/${contractorId}/kpi-actuals`,
    payload,
    { headers: authHeaders() }
  )
  return res.data.data
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

/**
 * Get all tasks for a contractor.
 * @param {string} contractorId
 * @param {object} params — { status_filter } (optional)
 * @returns {{ items, total }}
 */
export async function getContractorTasks(contractorId, params = {}) {
  const res = await axios.get(`${BASE}/contractors/${contractorId}/tasks`, {
    headers: authHeaders(),
    params,
  })
  return res.data.data
}

/**
 * Manually create a single task for a contractor.
 * @param {string} contractorId
 * @param {object} payload — TaskCreate fields
 */
export async function createContractorTask(contractorId, payload) {
  const res = await axios.post(
    `${BASE}/contractors/${contractorId}/tasks`,
    payload,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * Update a task status.
 * @param {string} contractorId
 * @param {string} taskId
 * @param {object} payload — { status, done_date, notes }
 */
export async function updateContractorTask(contractorId, taskId, payload) {
  const res = await axios.patch(
    `${BASE}/contractors/${contractorId}/tasks/${taskId}`,
    payload,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * Generate tasks from the contractor's task_template JSONB.
 * Computes due_dates from contract_start + due_day.
 * Skips tasks that already exist.
 * @param {string} contractorId
 * @returns {{ created: number }}
 */
export async function generateContractorTasks(contractorId) {
  const res = await axios.post(
    `${BASE}/contractors/${contractorId}/tasks/generate`,
    {},
    { headers: authHeaders() }
  )
  return res.data.data
}

// ── CPM-1A: AI Contract Parser ────────────────────────────────────────────────

/**
 * Upload a PDF or DOCX contract and extract KPI targets + risk clauses
 * using Claude Sonnet. Returns structured data to pre-fill Steps 3 + 4
 * of ContractorCreateModal.
 *
 * No DB writes — pure parsing endpoint.
 * Fails gracefully — always returns { kpis, risk_clauses, raw_summary }
 * even on extraction failure (empty arrays).
 *
 * @param {File} file — PDF or DOCX File object from input
 * @returns {{ kpis, risk_clauses, raw_summary }}
 */
export async function parseContractKpis(file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await axios.post(
    `${BASE}/contractors/parse-contract-kpis`,
    formData,
    {
      headers: {
        ...authHeaders(),
        'Content-Type': 'multipart/form-data',
      },
    }
  )
  return res.data.data
}
