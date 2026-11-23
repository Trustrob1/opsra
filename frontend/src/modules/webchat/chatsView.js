/**
 * frontend/src/modules/webchat/chatsView.js — WEBCHAT-CHATS-1
 * Pure helpers for the Chats tab (no React), so they can be tested with `node --test`.
 */

export const FILTERS = [
  ['all', 'All'],
  ['asked', 'Asked questions'],
  ['no_contact', 'No contact left'],
  ['gap', "Chioma couldn't answer"],
  ['ordered', 'Ordered'],
  ['human', 'Handed to team'],
]

/** Who the chat was: the visitor's name when they left contact, else the short code ("Visitor 4F2A"). */
export function chatTitle(c) {
  if (!c) return ''
  return (c.has_contact && c.name) ? c.name : c.has_contact ? 'Contact left' : (c.code || 'Visitor')
}

/** Where the chat came from, in words: an ad by its name, the store page, a shared link, else the tag. */
export function sourceLabel(source, ads) {
  const ad = (Array.isArray(ads) ? ads : []).find((a) => a && a.tag === source)
  if (ad) return `Ad · ${ad.label || ad.tag}`
  if (source === 'catalog') return 'Store page'
  if (source === 'link' || !source) return 'Shared link'
  return source
}

/** Short tags shown on each row, most useful first. */
export function chatFacts(c) {
  if (!c) return []
  const out = []
  if (c.paid) out.push({ key: 'paid', text: 'Paid', tone: 'good' })
  else if (c.ordered) out.push({ key: 'ordered', text: 'Started an order', tone: 'good' })
  else if (c.cart_items > 0) out.push({ key: 'cart', text: `${c.cart_items} in cart`, tone: 'info' })
  if (c.handed) out.push({ key: 'handed', text: 'Handed to team', tone: 'info' })
  if (c.gap) out.push({ key: 'gap', text: "Couldn't answer", tone: 'warn' })
  if (!c.has_contact) out.push({ key: 'nocontact', text: 'No contact', tone: 'muted' })
  if (c.messages === 0) out.push({ key: 'silent', text: 'Said nothing', tone: 'muted' })
  else out.push({ key: 'msgs', text: c.messages === 1 ? '1 message' : `${c.messages} messages`, tone: 'muted' })
  return out
}

/** "5 min ago", "3 h ago", "2 days ago", else the date. */
export function ago(iso, now = Date.now()) {
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return ''
  const m = Math.max(0, Math.round((now - t) / 60000))
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.round(h / 24)
  if (d < 8) return d === 1 ? '1 day ago' : `${d} days ago`
  return new Date(t).toLocaleDateString('en-NG', { day: 'numeric', month: 'short' })
}
