/**
 * conversations.service.js — Unified Conversations inbox API calls.
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '' })

api.interceptors.request.use(cfg => {
  const token = useAuthStore.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) useAuthStore.getState().clearAuth()
    return Promise.reject(err)
  }
)

/** GET /api/v1/conversations */
export const getConversations = (params = {}) =>
  api.get('/api/v1/conversations', { params })

/**
 * GET /api/v1/conversations/{contact_type}/{contact_id}/status
 * Returns { window_open: bool, ai_paused: bool }
 */
export const getThreadStatus = (contact_type, contact_id) =>
  api.get(`/api/v1/conversations/${contact_type}/${contact_id}/status`)

/**
 * POST /api/v1/conversations/{contact_type}/{contact_id}/resume-ai
 * Clears ai_paused — hands conversation back to AI.
 */
export const resumeAI = (contact_type, contact_id) =>
  api.post(`/api/v1/conversations/${contact_type}/${contact_id}/resume-ai`)
