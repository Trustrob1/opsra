/**
 * frontend/src/services/notifications.service.js
 * Notifications API service — Phase 9
 *
 * Pattern 11: JWT from Zustand only — never localStorage
 * Pattern 12: org_id never in payload — derived from JWT server-side
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function _h() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

/**
 * List notifications for the current user.
 * Returns { items, total, page, page_size, has_more, unread_count }
 * @param {number} page
 * @param {number} pageSize
 */
export async function listNotifications(page = 1, pageSize = 20) {
  const r = await axios.get(`${BASE}/api/v1/notifications`, {
    headers: _h(),
    params: { page, page_size: pageSize },
  })
  return r.data.data
}

/**
 * Mark a single notification as read.
 * @param {string} id — notification UUID
 */
export async function markRead(id) {
  const r = await axios.patch(
    `${BASE}/api/v1/notifications/${id}/read`,
    {},
    { headers: _h() },
  )
  return r.data.data
}

/**
 * Mark all notifications for the current user as read.
 */
export async function markAllRead() {
  const r = await axios.patch(
    `${BASE}/api/v1/notifications/read-all`,
    {},
    { headers: _h() },
  )
  return r.data.data
}
