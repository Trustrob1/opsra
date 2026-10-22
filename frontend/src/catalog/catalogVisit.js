/**
 * frontend/src/catalog/catalogVisit.js
 * STORE-7: tell the server once per browser session that a tagged catalog link was opened.
 * Pure helper: storage and the sender are passed in, so it is tested without a browser. Never throws.
 */
export function visitKey(orgSlug, tag) {
  return `cv_${orgSlug}_${tag}`
}

/** Sends one visit for this store and tag per browser session. Returns true when it sent one. */
export function trackVisitOnce({ orgSlug, tag, storage, send }) {
  if (!orgSlug || !tag) return false
  const key = visitKey(orgSlug, tag)
  try {
    if (storage && storage.getItem(key)) return false
  } catch { /* storage blocked: still count once per page load below */ }
  try {
    if (storage) storage.setItem(key, '1')
  } catch { /* ignore */ }
  try {
    const p = send(orgSlug, tag)
    if (p && typeof p.catch === 'function') p.catch(() => {})
  } catch { /* a visit that cannot be sent is not worth a broken page */ }
  return true
}
