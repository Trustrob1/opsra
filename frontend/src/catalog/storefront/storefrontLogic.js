/**
 * frontend/src/catalog/storefront/storefrontLogic.js
 * STORE-2: Pure helpers for the Storefront catalog look. No React, no network.
 * Kept separate so they can be tested with `node --test` (no test runner needed).
 */

export const DEFAULT_ACCENT = '#0B6E74'
const HEX = /^#[0-9a-fA-F]{6}$/

/** Owner accent colour if it is a valid #rrggbb, otherwise the default teal. */
export function resolveAccent(style) {
  const a = style && style.accent
  return typeof a === 'string' && HEX.test(a) ? a : DEFAULT_ACCENT
}

/** Text colour (white or near-black) that stays readable on the given background. */
export function readableOn(hex) {
  if (!HEX.test(hex || '')) return '#FFFFFF'
  const n = parseInt(hex.slice(1), 16)
  const lin = (c) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }
  const L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255)
  return L > 0.5 ? '#14181B' : '#FFFFFF'
}

/** Same rule as the backend: whole % off, only when compare-at is really higher than price. */
export function discountPercent(price, compareAt) {
  const p = parseFloat(price)
  const c = parseFloat(compareAt)
  if (!Number.isFinite(p) || !Number.isFinite(c)) return null
  if (p <= 0 || c <= p) return null
  const pct = Math.round((1 - p / c) * 100)
  return pct >= 1 ? pct : null
}

/** Money text using the business's price template, for example "₦{price}". */
export function formatMoney(value, template) {
  if (value === null || value === undefined || value === '') return ''
  const n = parseFloat(value)
  if (!Number.isFinite(n)) return ''
  const formatted = n.toLocaleString('en-NG', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return (template || '₦{price}').replace('{price}', formatted)
}

/** Mirror of the Classic page and backend availability rule. */
export function isVariantAvailable(v) {
  if (!v) return false
  if (typeof v.available === 'boolean') return v.available
  return (
    v.inventory_management === null ||
    v.inventory_management === undefined ||
    v.inventory_policy === 'continue' ||
    parseInt(v.inventory_quantity || 0, 10) > 0
  )
}

/** Real options only (drops Shopify's "Default Title"). */
export function realVariants(item) {
  return ((item && item.variants) || []).filter(
    (v) => v && v.title && String(v.title).toLowerCase() !== 'default title'
  )
}

/**
 * What to show for price. Returns
 * { priceText, wasText, pct, rangeNote } and never invents a was-price:
 * wasText and pct are set only when compare-at is higher than the price.
 */
export function priceView(item, variant, config) {
  const template = (config && config.price_label_template) || '₦{price}'
  const onRequest = !!(config && config.price_on_request)
  const empty = { priceText: '', wasText: '', pct: null, rangeNote: '' }
  if (!item) return empty
  if (onRequest) return { ...empty, priceText: 'Price on request' }

  if (variant) {
    const price = variant.price
    const was = variant.compare_at_price
    const pct = discountPercent(price, was)
    return {
      priceText: formatMoney(price, template),
      wasText: pct ? formatMoney(was, template) : '',
      pct,
      rangeNote: '',
    }
  }

  const variants = realVariants(item)
  const prices = variants.map((v) => parseFloat(v.price || 0)).filter((p) => p > 0)
  if (variants.length > 1 && prices.length) {
    const lo = Math.min(...prices)
    const hi = Math.max(...prices)
    if (lo !== hi) {
      return {
        ...empty,
        priceText: `${formatMoney(lo, template)} – ${formatMoney(hi, template)}`,
        rangeNote: 'Pick a size to see the exact price',
      }
    }
  }

  const pct = discountPercent(item.price, item.compare_at_price)
  return {
    priceText: item.price_label || formatMoney(item.price, template),
    wasText: pct ? formatMoney(item.compare_at_price, template) : '',
    pct,
    rangeNote: '',
  }
}

/** WhatsApp order link, or null when the business has no number. */
export function whatsappOrderLink(waNumber, item, variant, qty = 1) {
  if (!waNumber || !item) return null
  const q = qty > 1 ? `${qty} x ` : ''
  const msg = variant
    ? `Hi, I'd like to order ${q}${item.title} (${variant.title})`
    : `Hi, I'd like to order ${q}${item.title}`
  return `https://wa.me/${waNumber}?text=${encodeURIComponent(msg)}`
}

/** "Royal Rest" -> "RR", "Acme" -> "A". */
export function initials(name) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return ''
  return words.slice(0, 2).map((w) => w[0].toUpperCase()).join('')
}

/** Up to `limit` other items: ones sharing a tag value first, then the rest. */
export function relatedItems(items, current, limit = 4) {
  const others = (items || []).filter((i) => i && current && i.slug !== current.slug)
  const vals = (it) =>
    Object.values((it && it.tags) || {}).flatMap((v) => (Array.isArray(v) ? v : [v])).map(String)
  const mine = new Set(vals(current))
  const score = (it) => vals(it).filter((v) => mine.has(v)).length
  return others
    .map((it, idx) => ({ it, idx, s: score(it) }))
    .sort((a, b) => b.s - a.s || a.idx - b.idx)
    .slice(0, limit)
    .map((x) => x.it)
}

/** Safe public trust points: the owner's list, else none (never invented). */
export function trustPoints(style) {
  const list = style && Array.isArray(style.trust_points) ? style.trust_points : []
  return list.filter((t) => typeof t === 'string' && t.trim()).slice(0, 3)
}
