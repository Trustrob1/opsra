/**
 * conversations.service.js — Unified Conversations inbox API calls.
 *
 * Route: GET /api/v1/conversations
 * Returns one entry per lead/customer sorted by most recent message.
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

/**
 * GET /api/v1/conversations
 * @param {object} params — { channel, contact_type }
 */
export const getConversations = (params = {}) =>
  api.get('/api/v1/conversations', { params })
