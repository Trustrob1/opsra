/**
 * conversations.service.js — Unified Conversations inbox API calls.
 *
 * CONV-UI additions:
 *   - sendMediaMessage() — POST /api/v1/messages/send-media (multipart)
 *   - pauseAI()          — POST /api/v1/conversations/{type}/{id}/pause-ai
 *
 * Bug fix:
 *   - resumeAI: corrupted [api.post](http://api.post)(...) → api.post(...)
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

/**
 * POST /api/v1/conversations/{contact_type}/{contact_id}/pause-ai
 * Sets ai_paused=true — rep takes over, AI stops responding.
 */
export const pauseAI = (contact_type, contact_id) =>
  api.post(`/api/v1/conversations/${contact_type}/${contact_id}/pause-ai`)

/**
 * POST /api/v1/messages/send-media  (multipart/form-data)
 * Uploads a media file and sends it as a WhatsApp message.
 *
 * FormData fields:
 *   file        — File object (image, video, audio, pdf — max 25 MB)
 *   lead_id     — UUID string (pass if recipient is a lead)
 *   customer_id — UUID string (pass if recipient is a customer)
 *
 * Returns the whatsapp_messages row on success.
 */
export const sendMediaMessage = (formData) =>
  api.post('/api/v1/messages/send-media', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
