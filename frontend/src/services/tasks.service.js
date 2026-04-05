/**
 * services/tasks.service.js
 * Task Management API functions — Phase 7B.
 *
 * Pattern 11: JWT from Zustand store only — never localStorage
 * Pattern 12: org_id never in any payload
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
 * @param {object} params — team, assigned_to, module, priority, status,
 *                          completed, page, page_size
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
