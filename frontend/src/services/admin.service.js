/**
 * frontend/src/services/admin.service.js
 * Admin Dashboard API service — Phase 8B
 *
 * Security (Technical Spec §11.1):
 *   - JWT read from Zustand store only — never localStorage (Pattern 11)
 *   - org_id never sent in any payload — derived from JWT server-side (Pattern 12)
 *
 * MIGRATION (Session 72.5):
 *   Migrated from raw axios + manual _h() header injection to the central api.js
 *   instance. This gives every admin call the full Supabase session refresh,
 *   the 4-second cold-start retry, and the request queue — matching all other
 *   service files. The _h() helper and BASE constant are no longer needed.
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
import api from './api'

// ── User Management ──────────────────────────────────────────────────────────

export async function listUsers() {
  const r = await api.get('/api/v1/admin/users')
  return r.data.data
}

export async function createUser(payload) {
  // payload: { email, full_name, password, role_id }
  const r = await api.post('/api/v1/admin/users', payload)
  return r.data.data
}

export async function updateUser(id, payload) {
  // payload: any subset of { full_name, role_id, is_active, is_out_of_office }
  const r = await api.patch(`/api/v1/admin/users/${id}`, payload)
  return r.data.data
}

export async function forceLogout(id) {
  const r = await api.post(`/api/v1/admin/users/${id}/force-logout`, {})
  return r.data.data
}

// ── Role Management ──────────────────────────────────────────────────────────

export async function listRoles() {
  const r = await api.get('/api/v1/admin/roles')
  return r.data.data
}

export async function createRole(payload) {
  // payload: { name, template, permissions }
  const r = await api.post('/api/v1/admin/roles', payload)
  return r.data.data
}

export async function updateRole(id, payload) {
  // payload: { name?, permissions? }
  const r = await api.patch(`/api/v1/admin/roles/${id}`, payload)
  return r.data.data
}

// ── Role User Overrides ──────────────────────────────────────────────────────

export async function listUserOverrides(roleId) {
  const r = await api.get(`/api/v1/admin/roles/${roleId}/overrides`)
  return r.data.data
}

export async function createUserOverride(roleId, payload) {
  // payload: { user_id, permission_key, granted }
  const r = await api.post(`/api/v1/admin/roles/${roleId}/overrides`, payload)
  return r.data.data
}

export async function deleteUserOverride(roleId, overrideId) {
  const r = await api.delete(`/api/v1/admin/roles/${roleId}/overrides/${overrideId}`)
  return r.data.data
}

// ── Routing Rules ────────────────────────────────────────────────────────────

export async function listRoutingRules() {
  const r = await api.get('/api/v1/admin/routing-rules')
  return r.data.data
}

export async function createRoutingRule(payload) {
  const r = await api.post('/api/v1/admin/routing-rules', payload)
  return r.data.data
}

export async function updateRoutingRule(id, payload) {
  const r = await api.patch(`/api/v1/admin/routing-rules/${id}`, payload)
  return r.data.data
}

export async function deleteRoutingRule(id) {
  const r = await api.delete(`/api/v1/admin/routing-rules/${id}`)
  return r.data.data
}

// ── Integration Status ───────────────────────────────────────────────────────

export async function getIntegrationStatus() {
  const r = await api.get('/api/v1/admin/integrations')
  return r.data.data
}

// ── Commission Settings ──────────────────────────────────────────────────────

export async function getCommissionSettings() {
  const r = await api.get('/api/v1/admin/commission-settings')
  return r.data.data
}

export async function updateCommissionSettings(payload) {
  const r = await api.patch('/api/v1/admin/commission-settings', payload)
  return r.data.data
}

// ── Lead Scoring Rubric — Feature 4 (Module 01 gaps) ────────────────────────

export async function getScoringRubric() {
  const r = await api.get('/api/v1/admin/scoring-rubric')
  return r.data.data
}

export async function updateScoringRubric(payload) {
  const r = await api.patch('/api/v1/admin/scoring-rubric', payload)
  return r.data.data
}

// ── Qualification Bot — M01-3 ─────────────────────────────────────────────────

export const getQualificationBot = () =>
  api.get('/api/v1/admin/qualification-bot')
    .then(r => r.data.data)

export const updateQualificationBot = (payload) =>
  api.patch('/api/v1/admin/qualification-bot', payload)
    .then(r => r.data.data)

export const getQualificationAiRecommendations = () =>
  api.post('/api/v1/admin/qualification-bot/ai-recommendations', {})
    .then(r => r.data.data)

// ── Lead SLA Config — M01-6 ──────────────────────────────────────────────────

export async function getSlaConfig() {
  const r = await api.get('/api/v1/admin/sla-config')
  return r.data.data
}

export async function updateSlaConfig(payload) {
  const r = await api.patch('/api/v1/admin/sla-config', payload)
  return r.data.data
}

// ── Nurture Config — M01-10a ──────────────────────────────────────────────────

export async function getNurtureConfig() {
  const r = await api.get('/api/v1/admin/nurture-config')
  return r.data.data
}

export async function updateNurtureConfig(payload) {
  const r = await api.patch('/api/v1/admin/nurture-config', payload)
  return r.data.data
}

// ── Triage Config — WH-0 ─────────────────────────────────────────────────────

export async function getTriageConfig() {
  const r = await api.get('/api/v1/admin/triage-config')
  return r.data.data
}

export async function updateTriageConfig(payload) {
  const r = await api.patch('/api/v1/admin/triage-config', payload)
  return r.data.data
}

// ── WH-1b: Qualification Flow ─────────────────────────────────────────────────

export const getQualificationFlow = () =>
  api.get('/api/v1/admin/qualification-flow')
    .then(r => r.data.data)

export const updateQualificationFlow = (payload) =>
  api.patch('/api/v1/admin/qualification-flow', payload)
    .then(r => r.data.data)

// ── Pipeline Stage Config — CONFIG-6 ─────────────────────────────────────────

export async function getPipelineStages() {
  const r = await api.get('/api/v1/admin/pipeline-stages')
  return r.data.data
}

export async function updatePipelineStages(payload) {
  // payload: { stages: [{ key, label, enabled }] }
  const r = await api.patch('/api/v1/admin/pipeline-stages', payload)
  return r.data.data
}

// ── Ticket/KB Category Config — CONFIG-1 ─────────────────────────────────────

export const getTicketCategories = () =>
  api.get('/api/v1/admin/ticket-categories')
    .then(r => r.data.data)

export const updateTicketCategories = (payload) =>
  api.patch('/api/v1/admin/ticket-categories', payload)
    .then(r => r.data.data)

// ── Drip Business Types — CONFIG-2 ───────────────────────────────────────────

export const getDripBusinessTypes = () =>
  api.get('/api/v1/admin/drip-business-types')
    .then(r => r.data.data)

export const updateDripBusinessTypes = (payload) =>
  api.patch('/api/v1/admin/drip-business-types', payload)
    .then(r => r.data.data)

// ── SLA Business Hours — CONFIG-3 ────────────────────────────────────────────

export const getSlaBusinessHours = () =>
  api.get('/api/v1/admin/sla-business-hours')
    .then(r => r.data.data)

export const updateSlaBusinessHours = (payload) =>
  api.patch('/api/v1/admin/sla-business-hours', payload)
    .then(r => r.data.data)

// ── SM-1: Sales Mode + Contact Menus ─────────────────────────────────────────

export const getSalesMode = () =>
  api.get('/api/v1/admin/sales-mode')
    .then(r => r.data)

export const updateSalesMode = (mode) =>
  api.patch('/api/v1/admin/sales-mode', { mode })
    .then(r => r.data)

export const getContactMenus = () =>
  api.get('/api/v1/admin/contact-menus')
    .then(r => r.data)

export const updateContactMenus = (payload) =>
  api.patch('/api/v1/admin/contact-menus', payload)
    .then(r => r.data)

// ── SHOP-1B: Shopify Integration ──────────────────────────────────────────────

export const getShopifyStatus = () =>
  api.get('/api/v1/admin/shopify/status')
    .then(r => r.data)

export const connectShopify = (payload) =>
  // payload: { shop_domain, client_id, client_secret, webhook_secret? }
  api.post('/api/v1/admin/shopify/connect', payload)
    .then(r => r.data)

export const disconnectShopify = () =>
  api.delete('/api/v1/admin/shopify/disconnect')
    .then(r => r.data)

export const triggerShopifySync = () =>
  api.post('/api/v1/admin/shopify/sync', {})
    .then(r => r.data)

// ── MULTI-ORG-WA-1: WhatsApp connection management ───────────────────────────

export const getWhatsAppStatus = () =>
  api.get('/api/v1/admin/whatsapp/status')
    .then(r => r.data.data)

export const connectWhatsApp = (payload) =>
  // payload: { whatsapp_phone_id, whatsapp_access_token, whatsapp_waba_id? }
  api.post('/api/v1/admin/whatsapp/connect', payload)
    .then(r => r.data.data)

export const disconnectWhatsApp = () =>
  api.delete('/api/v1/admin/whatsapp/disconnect')
    .then(r => r.data.data)

// ── COMM-1: Commerce Settings ─────────────────────────────────────────────────

export const getCommerceSettings = () =>
  api.get('/api/v1/admin/commerce/settings')
    .then(r => r.data.data)

export const updateCommerceSettings = (payload) =>
  // payload: { enabled?: boolean, checkout_message?: string }
  api.patch('/api/v1/admin/commerce/settings', payload)
    .then(r => r.data.data)

// ── 9E-D: Messaging Limits ───────────────────────────────────────────────────

export const getMessagingLimits = () =>
  api.get('/api/v1/admin/messaging-limits')
    .then(r => r.data.data)

export const updateMessagingLimits = (payload) =>
  // payload: { daily_customer_message_limit?, quiet_hours_start?,
  //            quiet_hours_end?, timezone? }
  api.patch('/api/v1/admin/messaging-limits', payload)
    .then(r => r.data.data)

// ── SHOP-3: Meta Commerce Catalog ID ─────────────────────────────────────────

export const updateMetaCatalogId = (payload) =>
  // payload: { meta_catalog_id: string | null }
  api.patch('/api/v1/admin/shopify/connect', payload)
    .then(r => r.data)

// ── ASSIGN-1: Lead Assignment Engine ─────────────────────────────────────────

export const getLeadAssignment = () =>
  api.get('/api/v1/admin/lead-assignment')
    .then(r => r.data.data)

export const updateAssignmentMode = (mode) =>
  api.put('/api/v1/admin/lead-assignment/mode', { mode })
    .then(r => r.data.data)

export const getAssignmentShifts = () =>
  api.get('/api/v1/admin/lead-assignment/shifts')
    .then(r => r.data.data)

export const createShift = (payload) =>
  api.post('/api/v1/admin/lead-assignment/shifts', payload)
    .then(r => r.data.data)

export const updateShift = (id, payload) =>
  api.patch(`/api/v1/admin/lead-assignment/shifts/${id}`, payload)
    .then(r => r.data.data)

export const deleteShift = (id) =>
  api.delete(`/api/v1/admin/lead-assignment/shifts/${id}`)
    .then(r => r.data.data)


export const getLeadFormConfig = () =>
  api.get('/api/v1/admin/lead-form-config')
    .then(r => r.data?.data)

export const updateLeadFormConfig = (payload) =>
  api.patch('/api/v1/admin/lead-form-config', payload)
    .then(r => r.data?.data)

export const getGrowthDashboardConfig = () =>
  api.get('/api/v1/admin/growth-dashboard-config')
    .then(r => r.data?.data)

export const updateGrowthDashboardConfig = (payload) =>
  api.patch('/api/v1/admin/growth-dashboard-config', payload)
    .then(r => r.data?.data)

export const getWASalesMode = () =>
  api.get('/api/v1/admin/whatsapp-sales-mode')
    .then(r => r.data.data)
 
export const updateWASalesMode = (mode) =>
  // mode: 'human' | 'bot' | 'ai_agent'
  api.patch('/api/v1/admin/whatsapp-sales-mode', { mode })
    .then(r => r.data.data)

// ── AUTH-RESET-1: Admin password reset + email update ────────────────────────

export async function adminResetPassword(userId) {
  // Sends reset link to user's registered email.
  // Also returns reset_link as a fallback the admin can share directly.
  const r = await api.post(`/api/v1/admin/users/${userId}/reset-password`, {})
  return r.data.data  // { sent, email, reset_link }
}

export async function adminUpdateEmail(userId, newEmail) {
  // Force-updates a staff member's email — bypasses confirmation.
  const r = await api.patch(`/api/v1/admin/users/${userId}/email`, { new_email: newEmail })
  return r.data.data  // { updated, email }
}