/**
 * frontend/src/services/digital_campaigns.service.js
 * Digital Campaigns tab API service — REPORTS-DEPT-1 Phase 4d.
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

/**
 * Create or update one campaign's week. Upserts on
 * (campaign_name, week_start) server-side — re-submitting the same
 * campaign+week updates that row instead of creating a duplicate.
 * @param {Object} payload
 * @param {string} payload.campaign_name
 * @param {string} payload.week_start     — any date within the target week (YYYY-MM-DD)
 * @param {number} payload.daily_budget
 * @param {number} payload.spend
 * @param {number} payload.conversations
 * @param {number} payload.ctr_pct
 * @param {number} payload.impressions
 * @param {string} [payload.notes]
 */
export async function upsertCampaignEntry(payload) {
  const r = await axios.post(`${BASE}/api/v1/digital-campaigns`, payload, _h())
  return r.data.data
}

export async function updateCampaignEntry(entryId, payload) {
  const r = await axios.patch(`${BASE}/api/v1/digital-campaigns/${entryId}`, payload, _h())
  return r.data.data
}

export async function deleteCampaignEntry(entryId) {
  const r = await axios.delete(`${BASE}/api/v1/digital-campaigns/${entryId}`, _h())
  return r.data
}

/**
 * List raw weekly entries in a date range (for the editable entries list).
 */
export async function getCampaignEntries(dateFrom, dateTo) {
  const r = await axios.get(`${BASE}/api/v1/digital-campaigns`, {
    ..._h(),
    params: {
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo   ? { date_to:   dateTo   } : {}),
    },
  })
  return r.data.data
}

/**
 * Raw entries + Sales Record revenue for the same range (for ROAS).
 * All aggregation (per-campaign totals, blended CTR, insights) happens
 * client-side from what this returns.
 */
export async function getCampaignSummary(dateFrom, dateTo) {
  const r = await axios.get(`${BASE}/api/v1/digital-campaigns/summary`, {
    ..._h(),
    params: {
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo   ? { date_to:   dateTo   } : {}),
    },
  })
  return r.data.data
}

/**
 * Download the Digital Campaigns PDF report as a Blob.
 * @param {Object} params — date_from, date_to (both optional, default to trailing 30 days)
 * @returns {Blob}
 */
export async function downloadDigitalCampaignsReport(params = {}) {
  const r = await axios.get(`${BASE}/api/v1/digital-campaigns/report/download`, {
    ..._h(),
    params,
    responseType: 'blob',
  })
  return r.data
}
