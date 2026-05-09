/**
 * Leads service — all 14 API call functions.
 *
 * Route contracts sourced from Build Status Phase 2A (do not invent new routes).
 * Base URL: /api/v1  ·  Auth: Authorization: Bearer <token>
 * Response envelope: { success, data, message, error }
 * Paginated envelope: { success, data: { items, total, page, page_size, has_more } }
 *
 * SECURITY (Technical Spec §11.1):
 *   - org_id is NEVER sent in any request body — always derived from JWT server-side.
 *   - Authorization header is injected automatically via the request interceptor.
 *   - 401 responses auto-clear the auth store (see interceptor below).
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ─── Axios instance with auth interceptor ────────────────────────────────────

const api = axios.create({ baseURL: BASE })

/** Inject Bearer token on every outgoing request */
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/** On 401 — retry once (handles cold starts / transient pool exhaustion),
 *  then clear auth so the app shows the login screen */
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    if (err.response?.status === 401 && !err.config._retried) {
      err.config._retried = true
      // Wait 4s — gives cold-starting Render instance time to warm up
      await new Promise(r => setTimeout(r, 4000))
      try { return await api(err.config) } catch {}
      useAuthStore.getState().clearAuth()
    }
    return Promise.reject(err)
  },
)

// ─── Helper ──────────────────────────────────────────────────────────────────

/** Strip undefined values so they are not sent as query params */
const clean = (obj) =>
  Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined && v !== ''))

// ─── Lead list ───────────────────────────────────────────────────────────────

/**
 * GET /api/v1/leads
 * Returns paginated envelope.
 * @param {object} params — stage, score, assigned_to, source, from_date, to_date, page, page_size
 */
export async function listLeads(params = {}) {
  const res = await api.get('/api/v1/leads', { params: clean(params) })
  return res.data
}

// ─── Lead CRUD ───────────────────────────────────────────────────────────────

/**
 * POST /api/v1/leads
 * Required: full_name, source.  All other fields optional.
 * org_id is NOT in payload — derived from JWT server-side.
 */
export async function createLead(payload) {
  const res = await api.post('/api/v1/leads', payload)
  return res.data
}

/**
 * GET /api/v1/leads/{id}
 * Returns single lead object inside { success, data }.
 */
export async function getLead(id) {
  const res = await api.get(`/api/v1/leads/${id}`)
  return res.data
}

/**
 * PATCH /api/v1/leads/{id}
 * Partial update — send only changed fields.
 * org_id is NOT in payload.
 */
export async function updateLead(id, payload) {
  const res = await api.patch(`/api/v1/leads/${id}`, payload)
  return res.data
}


/**
 * DELETE /api/v1/leads/{id}
 * Admin only — returns 204 on success.
 */
export async function deleteLead(id) {
  const res = await api.delete(`/api/v1/leads/${id}`)
  return res.data
}

// ─── Lead actions ────────────────────────────────────────────────────────────

/**
 * POST /api/v1/leads/{id}/score
 * Triggers AI scoring via Claude.  Returns { score, score_reason }.
 * Body is empty — all context comes from the lead record server-side.
 */
export async function scoreLead(id) {
  const res = await api.post(`/api/v1/leads/${id}/score`, {})
  return res.data
}

/**
 * POST /api/v1/leads/{id}/move-stage
 * Validates transition against state machine before moving.
 * @param {string} id
 * @param {string} new_stage — one of: new|contacted|demo_done|proposal_sent
 */
export async function moveStage(id, new_stage) {
  const res = await api.post(`/api/v1/leads/${id}/move-stage`, { new_stage })
  return res.data
}

/**
 * POST /api/v1/leads/{id}/convert
 * Terminal transition — creates customer + subscription records.
 * Returns { lead, customer_id }.
 */
export async function convertLead(id) {
  const res = await api.post(`/api/v1/leads/${id}/convert`, {})
  return res.data
}

/**
 * POST /api/v1/leads/{id}/mark-lost
 * @param {string} id
 * @param {{ lost_reason: string, reengagement_date?: string }} payload
 *   lost_reason: not_ready|price|competitor|wrong_size|wrong_contact|other
 *   reengagement_date: ISO date string (optional, typically used with not_ready)
 */
export async function markLost(id, payload) {
  const res = await api.post(`/api/v1/leads/${id}/mark-lost`, payload)
  return res.data
}

/**
 * POST /api/v1/leads/{id}/reactivate
 * Creates a new lead with previous_lead_id set to id.
 * Returns the new lead object.
 */
export async function reactivateLead(id) {
  const res = await api.post(`/api/v1/leads/${id}/reactivate`, {})
  return res.data
}

// ─── Lead sub-resources ──────────────────────────────────────────────────────

/**
 * GET /api/v1/leads/{id}/timeline
 * Returns list of LeadTimelineEntry objects, chronological.
 */
export async function getTimeline(id) {
  const res = await api.get(`/api/v1/leads/${id}/timeline`)
  return res.data
}

/**
 * GET /api/v1/leads/{id}/tasks
 * Returns list of task objects linked to this lead.
 */
export async function getLeadTasks(id) {
  const res = await api.get(`/api/v1/leads/${id}/tasks`)
  return res.data
}

// ─── CSV import ──────────────────────────────────────────────────────────────

/**
 * POST /api/v1/leads/import
 * Multipart form upload.  Returns { job_id, ... }.
 * @param {FormData} formData — must include the CSV file under the 'file' key
 */
export async function importLeads(formData) {
  const res = await api.post('/api/v1/leads/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

/**
 * GET /api/v1/leads/import/{job_id}
 * Poll this until status is 'done' or 'failed'.
 * Returns LeadImportStatus: { job_id, status, total_rows, processed, succeeded, failed, errors }
 */
export async function getImportStatus(jobId) {
  const res = await api.get(`/api/v1/leads/import/${jobId}`)
  return res.data
}

/**
 * POST /api/v1/leads/{id}/score-override
 * Manager/owner manually overrides AI score — Feature 2 (Module 01 gaps).
 * Sets score_source = 'human' on the lead record.
 * @param {string} id       — lead UUID
 * @param {string} score    — 'hot' | 'warm' | 'cold'
 */
export async function overrideLeadScore(id, score) {
  const res = await api.post(`/api/v1/leads/${id}/score-override`, { score })
  return res.data
}

/**
 * GET /api/v1/leads/{id}/messages
 * Returns paginated WhatsApp message history for a lead.
 * @param {string} id         — lead UUID
 * @param {number} page       — page number (default 1)
 * @param {number} pageSize   — page size (default 20)
 */
export async function getLeadMessages(id, page = 1, pageSize = 20) {
  const res = await api.get(`/api/v1/leads/${id}/messages`, {
    params: { page, page_size: pageSize },
  })
  return res.data
}
// ─── M01-7 Demo Scheduling ────────────────────────────────────────────────────

/**
 * POST /api/v1/leads/{id}/demos
 * Create a demo request (status=pending_assignment).
 * Admin is notified to confirm date, time and assign a rep.
 * @param {string} leadId
 * @param {{ lead_preferred_time?: string, medium?: string, notes?: string }} payload
 */
export async function createDemoRequest(leadId, payload) {
  const res = await api.post(`/api/v1/leads/${leadId}/demos`, payload)
  return res.data
}

/**
 * GET /api/v1/leads/{id}/demos
 * List all demos for a lead, newest first.
 * @param {string} leadId
 */
export async function listDemos(leadId) {
  const res = await api.get(`/api/v1/leads/${leadId}/demos`)
  return res.data
}

/**
 * POST /api/v1/leads/{id}/demos/{demoId}/confirm
 * Admin/manager confirms a pending_assignment demo.
 * Auto-sends WA confirmation to lead. Creates rep task. In-app notification to rep.
 * @param {string} leadId
 * @param {string} demoId
 * @param {{ scheduled_at: string, medium: string, assigned_to: string, duration_minutes?: number, notes?: string }} payload
 */
export async function confirmDemo(leadId, demoId, payload) {
  const res = await api.post(`/api/v1/leads/${leadId}/demos/${demoId}/confirm`, payload)
  return res.data
}

/**
 * PATCH /api/v1/leads/{id}/demos/{demoId}
 * Log demo outcome: attended | no_show | rescheduled.
 * attended   → pipeline auto-advances to demo_done.
 * no_show    → follow-up task + WA rescheduling message auto-sent.
 * rescheduled → new pending_assignment demo created for admin to confirm.
 * @param {string} leadId
 * @param {string} demoId
 * @param {{ outcome: string, outcome_notes?: string }} payload
 */
export async function logDemoOutcome(leadId, demoId, payload) {
  const res = await api.patch(`/api/v1/leads/${leadId}/demos/${demoId}`, payload)
  return res.data
}


// ─── M01-7a Demo Queue ────────────────────────────────────────────────────────

/**
 * GET /api/v1/leads/demos/pending
 * Org-wide list of all pending_assignment demos.
 * Admin / owner / ops_manager only.
 * Returns { success, data: [ { id, lead_id, lead_full_name, lead_phone,
 *   lead_preferred_time, medium, notes, created_at, ... } ] }
 */
export async function getPendingDemos() {
  const res = await api.get('/api/v1/leads/demos/pending')
  return res.data
}

// ─── M01-7a Attention Summary ─────────────────────────────────────────────────

/**
 * GET /api/v1/leads/attention-summary
 * Returns { lead_id: { has_attention, unread_messages, pending_demos,
 *                       open_tickets, reasons } }
 * Used by LeadsPipeline to render attention badges on Kanban cards.
 * Scoped roles receive only their assigned leads.
 */
export async function getLeadAttentionSummary() {
  const res = await api.get('/api/v1/leads/attention-summary')
  return res.data
}

export const reactivateFromNurture = async (leadId, reason = null) => {
  const res = await api.patch(`/api/v1/leads/${leadId}/reactivate-from-nurture`, { reason })
  return { success: true, data: res.data?.data ?? res.data }
}

/**
 * GET /api/v1/leads/nurture-queue
 * Paginated list of leads currently on the nurture track.
 * Managers only — returns 403 for other roles.
 *
 * @param {object} params
 * @param {number} [params.page=1]
 * @param {number} [params.page_size=20]
 * @param {boolean} [params.include_opted_out=false] — include opted-out leads
 */
export async function getNurtureQueue(params = {}) {
  const res = await api.get('/api/v1/leads/nurture-queue', {
    params: clean(params),
  })
  return res.data
}

/**
 * PATCH /api/v1/leads/{id}/messages/mark-read
 * Marks all inbound messages for a lead as read — clears the unread badge.
 * @param {string} leadId — lead UUID
 */
export async function markLeadMessagesRead(leadId) {
  const res = await api.patch(`/api/v1/leads/${leadId}/messages/mark-read`, {})
  return res.data
}