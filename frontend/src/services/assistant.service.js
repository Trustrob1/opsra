/**
 * frontend/src/services/assistant.service.js
 * -------------------------------------------
 * API calls for Aria AI Assistant (M01-10b).
 *
 * All calls use axios + _h() helper (Pattern 50).
 * org_id never included in payloads (Pattern 12).
 *
 * Exports:
 *   getBriefing()           — GET /api/v1/briefing
 *   markBriefingSeen()      — POST /api/v1/briefing/seen
 *   getAssistantHistory()   — GET /api/v1/assistant/history
 *   streamAssistantMessage  — POST /api/v1/assistant/message (returns ReadableStream)
 */

import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/** Build Authorization header from Zustand JWT (Pattern 11 — memory only). */
function _h() {
  const token = useAuthStore.getState().token
  return { Authorization: `Bearer ${token}` }
}

// ─── Briefing ─────────────────────────────────────────────────────────────────

/**
 * Check if today's morning briefing should be shown.
 * @returns {{ show: boolean, content: string|null }}
 */
export async function getBriefing() {
  const r = await axios.get(`${BASE}/api/v1/briefing`, { headers: _h() })
  return r.data.data
}

/**
 * Mark today's briefing as seen — suppresses auto-open on refresh.
 */
export async function markBriefingSeen() {
  await axios.post(`${BASE}/api/v1/briefing/seen`, {}, { headers: _h() })
}

// ─── Chat history ─────────────────────────────────────────────────────────────

/**
 * Fetch the last 20 messages for the current user.
 * @returns {Array<{ role: 'user'|'assistant', content: string }>}
 */
export async function getAssistantHistory() {
  const r = await axios.get(`${BASE}/api/v1/assistant/history`, { headers: _h() })
  return r.data.data ?? []
}

// ─── Streaming message send ───────────────────────────────────────────────────

/**
 * Send a message to Aria and stream the response via SSE.
 *
 * Usage:
 *   const { stream, abort } = streamAssistantMessage('How many open leads?')
 *   for await (const chunk of stream) {
 *     // chunk.text — string fragment
 *     // chunk.done — true on final event
 *   }
 *
 * @param {string} message
 * @returns {{ stream: AsyncGenerator, abort: () => void }}
 */
export function streamAssistantMessage(message) {
  const token      = useAuthStore.getState().token
  const controller = new AbortController()

  async function* _stream() {
    const response = await fetch(`${BASE}/api/v1/assistant/message`, {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body:   JSON.stringify({ message }),
      signal: controller.signal,
    })

    if (!response.ok) {
      const errText = await response.text().catch(() => 'Unknown error')
      throw new Error(`Aria request failed (${response.status}): ${errText}`)
    }

    const reader  = response.body.getReader()
    const decoder = new TextDecoder()
    let   buffer  = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // SSE lines are delimited by \n\n
      const lines = buffer.split('\n\n')
      buffer = lines.pop() ?? ''   // keep incomplete last chunk

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6).trim()

        if (payload === '[DONE]') {
          yield { done: true, text: '' }
          return
        }

        try {
          const parsed = JSON.parse(payload)
          if (parsed.text) yield { done: false, text: parsed.text }
        } catch {
          // Malformed chunk — skip
        }
      }
    }

    yield { done: true, text: '' }
  }

  return {
    stream: _stream(),
    abort:  () => controller.abort(),
  }
}
