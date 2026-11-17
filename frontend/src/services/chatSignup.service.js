/**
 * frontend/src/services/chatSignup.service.js
 * WEB-ONLY-1b - public sign-up for web-chat-only businesses (Chioma on the website).
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''
const unwrap = (p) => p.then((r) => r.data?.data ?? r.data)

export const getChatSignupInfo = () => unwrap(axios.get(`${BASE}/api/v1/chat-signup/info`))
export const startChatSignup = (payload) => unwrap(axios.post(`${BASE}/api/v1/chat-signup/start`, payload))
export const verifyChatSignup = (requestId, code, password) => unwrap(axios.post(`${BASE}/api/v1/chat-signup/verify`, { request_id: requestId, code, password }))

export function signupError(err, fallback = 'Something went wrong. Please try again.') {
  const d = err?.response?.data?.detail
  if (!d) return fallback
  if (typeof d === 'string') return d
  if (d.message) return d.message
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return fallback
}
