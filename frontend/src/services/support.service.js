/**
 * frontend/src/services/support.service.js
 * API client for Module 03 — Support.
 * Covers all 18 Phase 4A routes:
 *   tickets, ticket messages, attachments,
 *   knowledge base articles, interaction logs.
 *
 * Conventions:
 *   - org_id NEVER sent in any payload — derived server-side from JWT (Pattern 12)
 *   - JWT stored in Zustand only, read via useAuthStore.getState() (Pattern 11)
 *   - All responses unwrap resp.data (the ok() envelope data field)
 */

import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : "/api/v1";

function headers() {
  const token = useAuthStore.getState().token
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }
}

async function request(method, path, body = null) {
  const opts = { method, headers: headers() }
  if (body !== null) opts.body = JSON.stringify(body)
  const resp = await fetch(`${BASE}${path}`, opts)
  const json = await resp.json()
  if (!resp.ok) throw new Error(json.detail || json.message || `HTTP ${resp.status}`)
  return json.data
}

// ---------------------------------------------------------------------------
// Tickets
// ---------------------------------------------------------------------------

export async function listTickets({
  status, category, urgency, assigned_to, sla_breached,
  customer_id, lead_id,
  page = 1, page_size = 20,
} = {}) {
  const params = new URLSearchParams()
  if (status)       params.set('status', status)
  if (category)     params.set('category', category)
  if (urgency)      params.set('urgency', urgency)
  if (assigned_to)  params.set('assigned_to', assigned_to)
  if (sla_breached !== undefined && sla_breached !== null)
    params.set('sla_breached', sla_breached)
  if (customer_id)  params.set('customer_id', customer_id)
  if (lead_id)      params.set('lead_id', lead_id)
  params.set('page', page)
  params.set('page_size', page_size)
  return request('GET', `/api/v1/tickets?${params}`)
}

export async function createTicket(data) {
  return request('POST', '/api/v1/tickets', data)
}

export async function getTicket(ticketId) {
  return request('GET', `/api/v1/tickets/${ticketId}`)
}

export async function updateTicket(ticketId, data) {
  return request('PATCH', `/api/v1/tickets/${ticketId}`, data)
}

// ---------------------------------------------------------------------------
// Ticket messages & status transitions
// ---------------------------------------------------------------------------

export async function addMessage(ticketId, data) {
  return request('POST', `/api/v1/tickets/${ticketId}/messages`, data)
}

export async function resolveTicket(ticketId, resolution_notes) {
  return request('POST', `/api/v1/tickets/${ticketId}/resolve`, { resolution_notes })
}

export async function closeTicket(ticketId) {
  return request('POST', `/api/v1/tickets/${ticketId}/close`)
}

export async function reopenTicket(ticketId) {
  return request('POST', `/api/v1/tickets/${ticketId}/reopen`)
}

export async function escalateTicket(ticketId) {
  return request('POST', `/api/v1/tickets/${ticketId}/escalate`)
}

// ---------------------------------------------------------------------------
// Attachments
// ---------------------------------------------------------------------------

export async function listAttachments(ticketId) {
  return request('GET', `/api/v1/tickets/${ticketId}/attachments`)
}

export async function uploadAttachment(ticketId, file) {
  const token = useAuthStore.getState().token
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(`${BASE}/api/v1/tickets/${ticketId}/attachments`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  const json = await resp.json()
  if (!resp.ok) throw new Error(json.detail || json.message || `HTTP ${resp.status}`)
  return json.data
}

// ---------------------------------------------------------------------------
// Knowledge base
// ---------------------------------------------------------------------------

export async function listKBArticles({ category, page = 1, page_size = 20 } = {}) {
  const params = new URLSearchParams()
  if (category) params.set('category', category)
  params.set('page', page)
  params.set('page_size', page_size)
  return request('GET', `/api/v1/knowledge-base?${params}`)
}

export async function createKBArticle(data) {
  return request('POST', '/api/v1/knowledge-base', data)
}

export async function getKBArticle(articleId) {
  return request('GET', `/api/v1/knowledge-base/${articleId}`)
}

export async function updateKBArticle(articleId, data) {
  return request('PATCH', `/api/v1/knowledge-base/${articleId}`, data)
}

export async function unpublishKBArticle(articleId) {
  return request('DELETE', `/api/v1/knowledge-base/${articleId}`)
}

export async function suggestKBArticle(ticketId) {
  return request('POST', `/api/v1/tickets/${ticketId}/suggest-kb-article`)
}

// ---------------------------------------------------------------------------
// Interaction logs
// ---------------------------------------------------------------------------

export async function createInteractionLog(data) {
  return request('POST', '/api/v1/interaction-logs', data)
}

export async function listInteractionLogs({
  customer_id, lead_id, logged_by,
  page = 1, page_size = 20,
} = {}) {
  const params = new URLSearchParams()
  if (customer_id) params.set('customer_id', customer_id)
  if (lead_id)     params.set('lead_id', lead_id)
  if (logged_by)   params.set('logged_by', logged_by)
  params.set('page', page)
  params.set('page_size', page_size)
  return request('GET', `/api/v1/interaction-logs?${params}`)
}