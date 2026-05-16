/**
 * api.js — Central Axios instance with JWT refresh interceptor
 *
 * SECURITY (Technical Spec §11.1 + 9E-H):
 *   - All API calls must go through this instance.
 *   - On 401: silently refresh the Supabase session, update Zustand, retry once.
 *   - If refresh fails: clear Zustand auth state → LoginScreen renders.
 *   - Token read from Zustand at call time — never from browser storage.
 *
 * Usage:
 *   import api from './api'
 *   const res = await api.get('/api/v1/leads')
 *   const res = await api.post('/api/v1/leads', payload)
 *
 * Note: The Authorization header is injected per-request by the request
 * interceptor so it always reflects the latest token in Zustand, even after
 * a silent refresh mid-session.
 */
import axios from 'axios'
import { createClient } from '@supabase/supabase-js'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ── Supabase client (auth only — for session refresh) ──────────────────────
// Uses the same env vars as the rest of the app.
export const _supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)

// ── Axios instance ───────────────────────────────────────────────────────────
const api = axios.create({ baseURL: BASE })

// ── Request interceptor — inject current token ───────────────────────────────
api.interceptors.request.use((config) => {
  // Lazy import to avoid circular dependency at module load time
  const { default: useAuthStore } = require('../store/authStore')
  const token = useAuthStore.getState().getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// ── Response interceptor — silent JWT refresh on 401 ────────────────────────
let _refreshing = false
let _refreshQueue = [] // requests waiting on refresh

const _processQueue = (error, token = null) => {
  _refreshQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  _refreshQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config

    // Only attempt refresh on 401 and only once per request
    if (error?.response?.status !== 401 || original._retried) {
      return Promise.reject(error)
    }

    if (_refreshing) {
      // Another refresh is already in progress — queue this request
      return new Promise((resolve, reject) => {
        _refreshQueue.push({ resolve, reject })
      }).then((token) => {
        original.headers['Authorization'] = `Bearer ${token}`
        return api(original)
      }).catch((err) => Promise.reject(err))
    }

    original._retried = true
    _refreshing = true

    try {
      const { data, error: refreshError } = await _supabase.auth.refreshSession()

      if (refreshError || !data?.session?.access_token) {
        throw refreshError ?? new Error('Refresh returned no token')
      }

      const newToken = data.session.access_token

      // Update Zustand store with the new token
      // Lazy import to avoid circular dependency
      const { default: useAuthStore } = await import('../store/authStore')
      const currentUser = useAuthStore.getState().user
      useAuthStore.getState().setAuth(newToken, currentUser)

      _processQueue(null, newToken)
      original.headers['Authorization'] = `Bearer ${newToken}`
      return api(original)

    } catch (refreshErr) {
      _processQueue(refreshErr)

      // Refresh failed — clear auth and force re-login
      const { default: useAuthStore } = await import('../store/authStore')
      useAuthStore.getState().clearAuth()

      return Promise.reject(refreshErr)

    } finally {
      _refreshing = false
    }
  },
)

export default api

/**
 * Convenience header helper for service files that still use axios directly.
 * Keeps the same _h() pattern used across all service files (Pattern 50).
 *
 * Usage (in service files):
 *   import { _h } from './api'
 *   const r = await axios.get(`${BASE}/api/v1/...`, { headers: _h() })
 *
 * Prefer using `api` directly for new code — this is a bridge for existing files.
 */
export function _h() {
  const { default: useAuthStore } = require('../store/authStore')
  const token = useAuthStore.getState().getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export { BASE }
