/**
 * frontend/src/services/growth.service.js
 * Growth & Performance Dashboard API service — GPM-1B + GPM-1E (watermark).
 *
 * Pattern 50: axios + _h() only.
 * Pattern 11: JWT in Zustand memory only.
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function _h() {
  const token = useAuthStore.getState().token
  return { headers: { Authorization: `Bearer ${token}` } }
}

function _params(p = {}) {
  const q = {}
  if (p.dateFrom) q.date_from = p.dateFrom
  if (p.dateTo)   q.date_to   = p.dateTo
  if (p.team)     q.team      = p.team
  return q
}

// ---------------------------------------------------------------------------
// Analytics endpoints
// ---------------------------------------------------------------------------

export async function getGrowthOverview(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/overview`, { ..._h(), params: _params(params) })
  return r.data.data
}

export async function getTeamPerformance(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/teams`, { ..._h(), params: _params(params) })
  return r.data.data
}

export async function getFunnelMetrics(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/funnel`, { ..._h(), params: _params(params) })
  return r.data.data
}

export async function getSalesRepMetrics(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/sales-reps`, { ..._h(), params: _params(params) })
  return r.data.data
}

export async function getChannelMetrics(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/channels`, { ..._h(), params: _params(params) })
  return r.data.data
}

export async function getLeadVelocity(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/velocity`, { ..._h(), params: _params(params) })
  return r.data.data
}

export async function getPipelineAtRisk(stuckDays = 7) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/pipeline-at-risk`, { ..._h(), params: { stuck_days: stuckDays } })
  return r.data.data
}

export async function getWinLoss(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/win-loss`, { ..._h(), params: _params(params) })
  return r.data.data
}

// ---------------------------------------------------------------------------
// Growth config — teams
// ---------------------------------------------------------------------------

export async function getGrowthTeams() {
  const r = await axios.get(`${BASE}/api/v1/growth/teams`, _h())
  return r.data.data
}

export async function createGrowthTeam(payload) {
  const r = await axios.post(`${BASE}/api/v1/growth/teams`, payload, _h())
  return r.data.data
}

export async function updateGrowthTeam(teamId, payload) {
  const r = await axios.patch(`${BASE}/api/v1/growth/teams/${teamId}`, payload, _h())
  return r.data.data
}

export async function deleteGrowthTeam(teamId) {
  const r = await axios.delete(`${BASE}/api/v1/growth/teams/${teamId}`, _h())
  return r.data
}

// ---------------------------------------------------------------------------
// Growth config — campaign spend
// ---------------------------------------------------------------------------

export async function getSpendEntries(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/growth/spend`, {
    ..._h(),
    params: {
      ...(params.periodStart ? { period_start: params.periodStart } : {}),
      ...(params.periodEnd   ? { period_end:   params.periodEnd   } : {}),
    },
  })
  return r.data.data
}

export async function createSpendEntry(payload) {
  const r = await axios.post(`${BASE}/api/v1/growth/spend`, payload, _h())
  return r.data.data
}

export async function deleteSpendEntry(spendId) {
  const r = await axios.delete(`${BASE}/api/v1/growth/spend/${spendId}`, _h())
  return r.data
}

// ---------------------------------------------------------------------------
// Growth config — direct sales
// ---------------------------------------------------------------------------

export async function getDirectSales(page = 1, pageSize = 20) {
  const r = await axios.get(`${BASE}/api/v1/growth/direct-sales`, {
    ..._h(), params: { page, page_size: pageSize },
  })
  return r.data.data
}

export async function createDirectSale(payload) {
  const r = await axios.post(`${BASE}/api/v1/growth/direct-sales`, payload, _h())
  return r.data.data
}

export async function updateDirectSale(saleId, payload) {
  const r = await axios.patch(`${BASE}/api/v1/growth/direct-sales/${saleId}`, payload, _h())
  return r.data.data
}

export async function deleteDirectSale(saleId) {
  const r = await axios.delete(`${BASE}/api/v1/growth/direct-sales/${saleId}`, _h())
  return r.data
}

// ---------------------------------------------------------------------------
// Growth config — bulk import  (GPM-1E)
// ---------------------------------------------------------------------------

/**
 * Upload Excel/CSV for bulk sales import.
 * @param {FormData} formData        — must contain field "file"
 * @param {boolean}  confirm         — false = preview, true = insert
 * @param {number[]} selectedIndices — indices of valid_rows to insert (null = all)
 * @param {boolean}  fromBeginning   — ignore watermark
 */
export async function importSalesExcel(formData, confirm = false, selectedIndices = null, fromBeginning = false) {
  const params = new URLSearchParams({ confirm })
  if (fromBeginning) params.append('from_beginning', 'true')
  if (selectedIndices && selectedIndices.length > 0) {
    params.append('selected_indices', selectedIndices.join(','))
  }
  const r = await axios.post(
    `${BASE}/api/v1/growth/direct-sales/import/excel?${params.toString()}`,
    formData,
    {
      headers: {
        ...(_h().headers),
        'Content-Type': 'multipart/form-data',
      },
    }
  )
  return r.data.data
}

/**
 * Pull a publicly shared Google Sheet and import sales.
 * @param {string}   url              — full Google Sheets URL
 * @param {boolean}  confirm          — false = preview, true = insert
 * @param {number[]} selectedIndices  — indices of valid_rows to insert (null = all)
 * @param {boolean}  fromBeginning    — ignore watermark
 */
export async function importSalesSheets(url, confirm = false, selectedIndices = null, fromBeginning = false) {
  const r = await axios.post(
    `${BASE}/api/v1/growth/direct-sales/import/sheets`,
    {
      url,
      confirm,
      from_beginning:   fromBeginning,
      selected_indices: selectedIndices,
    },
    _h()
  )
  return r.data.data
}

/**
 * Reset the import watermark for a source so the next import starts from scratch.
 * @param {string}      sourceType — 'excel' | 'sheets'
 * @param {string|null} sheetUrl   — required for sheets, null for excel
 */
export async function resetImportWatermark(sourceType, sheetUrl = null) {
  const r = await axios.delete(
    `${BASE}/api/v1/growth/direct-sales/import/watermark`,
    { ..._h(), data: { source_type: sourceType, sheet_url: sheetUrl } }
  )
  return r.data
}

// ---------------------------------------------------------------------------
// GPM-2: AI Insight endpoints
// ---------------------------------------------------------------------------

export async function getInsightSections(dateFrom, dateTo) {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/insights/sections`, {
    ..._h(),
    params: {
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo   ? { date_to:   dateTo   } : {}),
    },
  })
  return r.data.data
}

export async function getInsightPanel(dateFrom, dateTo) {
  const r = await axios.post(
    `${BASE}/api/v1/analytics/growth/insights/panel`,
    {},
    {
      ..._h(),
      params: {
        ...(dateFrom ? { date_from: dateFrom } : {}),
        ...(dateTo   ? { date_to:   dateTo   } : {}),
      },
    },
  )
  return r.data.data
}

export async function getInsightAnomalies() {
  const r = await axios.get(`${BASE}/api/v1/analytics/growth/insights/anomalies`, _h())
  return r.data.data
}

export async function clearInsightCache() {
  const r = await axios.delete(`${BASE}/api/v1/analytics/growth/insights/sections/cache`, _h())
  return r.data
}