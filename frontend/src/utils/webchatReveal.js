/**
 * frontend/src/utils/webchatReveal.js
 * When one reply carries an answer AND the details question ("may I have your first name?"), the question is held back for a moment
 * with Chioma's typing dots, so it reads as a second message instead of part of the first. Only a trailing details question is held:
 * answers always appear at once.
 */
export const HOLD_MS = 1100

/** Ids of the trailing bot message to hold back, or [] (nothing to hold). */
export function heldAskIds(res) {
  if (!res?.contact_step) return []
  const msgs = Array.isArray(res.messages) ? res.messages : []
  const bots = msgs.filter((m) => m && m.role === 'bot' && m.id)
  const last = msgs[msgs.length - 1]
  if (bots.length < 2 || !last || last.role !== 'bot' || !last.id) return []
  return [last.id]
}

/** Messages to show: everything except the ids being held. */
export function withoutHeld(messages, held) {
  return held && held.size ? messages.filter((m) => !held.has(m.id)) : messages
}
