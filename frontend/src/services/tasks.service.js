/**
 * services/tasks.service.js
 * Task Management API functions — Phase 7B (updated M01-9b).
 *
 * Pattern 11: JWT from Zustand store only — never localStorage
 * Pattern 12: org_id never in any payload
 *
 * M01-9b additions:
 *   deleteTask(id)    — soft-delete (archive) a task
 *   restoreTask(id)   — restore an archived task
 *   listTasks now accepts archived param for the Archived tab fetch
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function authHeaders() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

/**
 * List tasks — personal or team view.
 * Backend silently scopes team view to own tasks for non-managers.
 * Pass source_record_id to get all tasks linked to a specific record.
 * Pass archived=true to fetch the Archived tab contents.
 * @param {object} params — team, assigned_to, module, source_record_id,
 *                          priority, status, completed, archived,
 *                          page, page_size, created_from, created_to,
 *                          due_from, due_to
 */
export async function listTasks(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/tasks`, {
    headers: authHeaders(),
    params,
  })
  return res.data.data  // { items, total, page, page_size, has_more }
}

/**
 * Create a task manually.
 * @param {object} payload — title, description, due_at, priority,
 *                           source_module, source_record_id, assigned_to
 */
export async function createTask(payload) {
  const res = await axios.post(`${BASE}/api/v1/tasks`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Get a single task by ID.
 */
export async function getTask(id) {
  const res = await axios.get(`${BASE}/api/v1/tasks/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Partial update on a task.
 */
export async function updateTask(id, payload) {
  const res = await axios.patch(`${BASE}/api/v1/tasks/${id}`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Mark a task as completed.
 * @param {string} id
 * @param {string|null} notes — optional completion notes
 */
export async function completeTask(id, notes = null) {
  const res = await axios.post(
    `${BASE}/api/v1/tasks/${id}/complete`,
    { completion_notes: notes },
    { headers: authHeaders() },
  )
  return res.data.data
}

/**
 * Snooze a task until the specified datetime.
 * @param {string} id
 * @param {string} snoozedUntil — ISO 8601 datetime string
 */
export async function snoozeTask(id, snoozedUntil) {
  const res = await axios.post(
    `${BASE}/api/v1/tasks/${id}/snooze`,
    { snoozed_until: snoozedUntil },
    { headers: authHeaders() },
  )
  return res.data.data
}

/**
 * Soft-delete (archive) a task.
 * Sets deleted_at on the backend. Task moves to the Archived tab.
 * RBAC: own task (created or assigned) or manager.
 * @param {string} id
 */
export async function deleteTask(id) {
  const res = await axios.delete(`${BASE}/api/v1/tasks/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * Restore an archived task.
 * Clears deleted_at. Task returns to its previous status.
 * RBAC: own task (created or assigned) or manager.
 * @param {string} id
 */
export async function restoreTask(id) {
  const res = await axios.post(
    `${BASE}/api/v1/tasks/${id}/restore`,
    {},
    { headers: authHeaders() },
  )
  return res.data.data
}