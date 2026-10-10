/**
 * frontend/src/modules/sites/siteAddonsKit.js
 * SITE-ADDONS A0-3 - non-component helpers for the plan screens (kept apart from the components for Fast Refresh).
 */
export const money = (n) => `₦${Number(n || 0).toLocaleString('en-NG')}`

export const STATUS = {
  active: { tone: 'good', label: 'Active' },
  grace: { tone: 'warn', label: 'Payment overdue' },
  pending: { tone: 'info', label: 'Waiting for payment' },
  paused: { tone: 'neutral', label: 'Paused' },
  cancelled: { tone: 'bad', label: 'Cancelled' },
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true } catch { return false }
}
