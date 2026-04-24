/**
 * frontend/src/services/growth.service.js
 * Growth & Performance Dashboard API service — GPM-1B.
 *
 * Pattern 50: axios + _h() only, relative paths — never fetch, never absolute URL.
 * Pattern 11: JWT in Zustand memory only — _h() pulls token from authStore.
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

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
  const r = await axios.get('/api/v1/analytics/growth/overview', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

export async function getTeamPerformance(params = {}) {
  const r = await axios.get('/api/v1/analytics/growth/teams', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

export async function getFunnelMetrics(params = {}) {
  const r = await axios.get('/api/v1/analytics/growth/funnel', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

export async function getSalesRepMetrics(params = {}) {
  const r = await axios.get('/api/v1/analytics/growth/sales-reps', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

export async function getChannelMetrics(params = {}) {
  const r = await axios.get('/api/v1/analytics/growth/channels', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

export async function getLeadVelocity(params = {}) {
  const r = await axios.get('/api/v1/analytics/growth/velocity', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

export async function getPipelineAtRisk(stuckDays = 7) {
  const r = await axios.get('/api/v1/analytics/growth/pipeline-at-risk', {
    ..._h(), params: { stuck_days: stuckDays },
  })
  return r.data.data
}

export async function getWinLoss(params = {}) {
  const r = await axios.get('/api/v1/analytics/growth/win-loss', {
    ..._h(), params: _params(params),
  })
  return r.data.data
}

// ---------------------------------------------------------------------------
// Growth config — teams
// ---------------------------------------------------------------------------

export async function getGrowthTeams() {
  const r = await axios.get('/api/v1/growth/teams', _h())
  return r.data.data
}

export async function createGrowthTeam(payload) {
  const r = await axios.post('/api/v1/growth/teams', payload, _h())
  return r.data.data
}

export async function updateGrowthTeam(teamId, payload) {
  const r = await axios.patch(`/api/v1/growth/teams/${teamId}`, payload, _h())
  return r.data.data
}

export async function deleteGrowthTeam(teamId) {
  const r = await axios.delete(`/api/v1/growth/teams/${teamId}`, _h())
  return r.data
}

// ---------------------------------------------------------------------------
// Growth config — campaign spend
// ---------------------------------------------------------------------------

export async function getSpendEntries(params = {}) {
  const r = await axios.get('/api/v1/growth/spend', {
    ..._h(),
    params: {
      ...(params.periodStart ? { period_start: params.periodStart } : {}),
      ...(params.periodEnd   ? { period_end:   params.periodEnd   } : {}),
    },
  })
  return r.data.data
}

export async function createSpendEntry(payload) {
  const r = await axios.post('/api/v1/growth/spend', payload, _h())
  return r.data.data
}

export async function deleteSpendEntry(spendId) {
  const r = await axios.delete(`/api/v1/growth/spend/${spendId}`, _h())
  return r.data
}

// ---------------------------------------------------------------------------
// Growth config — direct sales
// ---------------------------------------------------------------------------

export async function getDirectSales(page = 1, pageSize = 20) {
  const r = await axios.get('/api/v1/growth/direct-sales', {
    ..._h(), params: { page, page_size: pageSize },
  })
  return r.data.data
}

export async function createDirectSale(payload) {
  const r = await axios.post('/api/v1/growth/direct-sales', payload, _h())
  return r.data.data
}

export async function updateDirectSale(saleId, payload) {
  const r = await axios.patch(`/api/v1/growth/direct-sales/${saleId}`, payload, _h())
  return r.data.data
}

export async function deleteDirectSale(saleId) {
  const r = await axios.delete(`/api/v1/growth/direct-sales/${saleId}`, _h())
  return r.data
}
