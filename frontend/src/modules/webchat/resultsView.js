/**
 * frontend/src/modules/webchat/resultsView.js — WEBCHAT-RESULTS-1
 * Pure helpers for the Web chat Results page (no React, so they can be tested with node --test).
 * `steps` are the funnel steps the server sends: [{key, label, count, rate, of}], rate = % of the step before (null for the first).
 */

const DROP_KEYS = new Set(['started', 'contact', 'booking', 'order', 'paid'])         // not the optional goals (moved to WhatsApp, tapped a link): a low rate there is normal

/** The parent step's count: the server names it by label in `of` ("visits", "started chatting", "gave contact", "orders"). */
function parentCount(steps, s) {
  const key = String(s.of || '').toLowerCase()
  const hit = key === 'orders' ? steps.find((x) => x.key === 'order') : steps.find((x) => String(x.label || '').toLowerCase() === key)
  return hit ? Number(hit.count) || 0 : 0
}

/**
 * Where the most PEOPLE were lost between a step and its own parent, among the main funnel steps (small percentages mislead when the numbers are small:
 * 0 of 5 booked reads as 100% but only 5 people). Ties keep the earlier step. null when nobody was lost.
 * Returns { from, to, lost: percent, people, of } (people = how many did not go on, of = how many were on the step before).
 */
export function biggestDrop(steps) {
  let best = null
  for (const s of steps || []) {
    if (!s || !DROP_KEYS.has(s.key)) continue
    const parent = parentCount(steps, s)
    const people = parent - (Number(s.count) || 0)
    if (parent > 0 && people > 0 && (!best || people > best.people)) best = { from: String(s.of || ''), to: s.label, lost: Math.round((100 * people) / parent), people, of: parent }
  }
  return best
}

/** One sentence for the top of the page, from the steps' own counts: "9 of 17 visitors chatted, 5 left contact, 2 started an order". */
export function headline(steps) {
  const by = Object.fromEntries((steps || []).map((s) => [s.key, s]))
  const visits = by.visit ? by.visit.count : 0
  if (!visits) return 'No visitors yet in this period'
  const parts = []
  if (by.started) parts.push(`${by.started.count} of ${visits} visitors chatted`)
  if (by.contact) parts.push(`${by.contact.count} left contact`)
  if (by.order && by.order.count) parts.push(`${by.order.count} started an order`)
  else if (by.booking && by.booking.count) parts.push(`${by.booking.count} asked to book`)
  return parts.join(', ') || `${visits} visitors`
}

/** Bar flex and opacity for the thin funnel strip: each step's count (at least a sliver) fading with depth. */
export function funnelWidths(steps) {
  const n = (steps || []).length
  return (steps || []).map((s, i) => ({ flex: Math.max(Number(s.count) || 0, 0.4), opacity: Math.max(0.2, 0.9 - (i * 0.7) / Math.max(n - 1, 1)) }))
}

/**
 * The by-source list: every source the server counted plus every ad the owner made (even with no visits yet), sorted by visits.
 * `ads` = the owner's campaigns [{tag, label, product}], `products` = [{id, title}].
 */
export function sourceRows(sources, ads, products) {
  const adBy = Object.fromEntries((Array.isArray(ads) ? ads : []).filter((a) => a && a.tag).map((a) => [a.tag, a]))
  const prodBy = Object.fromEntries((Array.isArray(products) ? products : []).map((p) => [p.id, p.title]))
  const have = new Set((sources || []).map((s) => s.source))
  const all = [...(sources || []), ...Object.keys(adBy).filter((t) => !have.has(t)).map((t) => ({ source: t }))]
  const rows = all.map((s) => {
    const ad = adBy[s.source]
    const prod = ad && ad.product ? prodBy[ad.product] : ''
    const kind = ad ? `Ad${prod ? ` · ${prod}` : ''}` : s.source === 'catalog' ? 'Store page' : s.source === 'link' ? 'Shared link' : ''
    const orders = Number(s.order) || 0
    return {
      source: s.source, name: ad ? (ad.label || s.source) : s.source, kind,
      visit: Number(s.visit) || 0, started: Number(s.started) || 0, contact: Number(s.contact) || 0, catalog_visit: Number(s.catalog_visit) || 0,
      orders, revenue_kobo: s.revenue_kobo || 0,
      goalCounts: { booking: Number(s.booked) || 0, order: orders, paid: Number(s.paid) || 0, whatsapp: Number(s.redirect_sent) || 0, tap: Number(s.tap) || 0 },
    }
  })
  return rows.sort((a, b) => b.visit - a.visit || b.orders - a.orders || b.catalog_visit - a.catalog_visit)
}
