/**
 * frontend/src/modules/admin/catalogErrors.js
 * STORE-6: turn an API error into one plain sentence for the owner.
 */
export function catalogErrorText(err, fallback) {
  const data = err && err.response && err.response.data
  const detail = data && data.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    if (detail.code === 'PLAN_REQUIRED') return 'Your plan does not include this. Ask your Opsra contact to add it.'
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message
  }
  if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === 'string') {
    return detail[0].msg.replace(/^Value error, /, '')
  }
  return fallback
}
