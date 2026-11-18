/**
 * frontend/src/utils/webchatTip.js
 * The one-time tip under a visitor's first sent message: "Tap any message to reply, copy, edit or delete it."
 * Stored once per browser (not per chat), so a returning visitor is never shown it again.
 */
export const TIP_KEY = 'wc_msg_tip_seen'

export function tipSeen(storage) {
  try { return storage?.getItem(TIP_KEY) === '1' } catch { return false }
}
export function markTipSeen(storage) {
  try { storage?.setItem(TIP_KEY, '1') } catch { /* storage blocked: the tip may show again next visit */ }
}

/** Id of the visitor's first message that has really been sent (not still sending, not deleted), or null. */
export function firstSentVisitorId(messages) {
  const m = (Array.isArray(messages) ? messages : []).find((x) => x && x.role === 'visitor' && !x.tmp && !x.deleted && x.id && !x.attachment?.uploading)
  return m ? m.id : null
}

/** Show the tip under message `id` only for the first sent visitor message, until it is dismissed or the visitor has opened the options. */
export function showTipFor(id, { messages, seen, menuOpen }) {
  return !seen && !menuOpen && !!id && id === firstSentVisitorId(messages)
}
