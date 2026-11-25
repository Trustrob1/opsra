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
 * STORE-8: what the small button under a product on the grid does.
 *   'add'    a product with no sizes and a real price: one tap puts it in the cart
 *   'choose' a product with sizes: the button opens the product page to pick one
 *   null     no button (cart off, price on request, no price, sold out)
 */
export function quickAddState(item, { cartOn, config } = {}) {
  if (!cartOn || !item || (config && config.price_on_request) || item.available === false) return null
  if (realVariants(item).length > 0) return 'choose'
  if (!(Number(item.price) > 0)) return null
  const stored = ((item.variants) || []).find((v) => v && (v.id ?? v.variant_id) != null && String(v.id ?? v.variant_id).trim() !== '')
  if (stored && !isVariantAvailable(stored)) return null
  return 'add'
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

// ---------------------------------------------------------------------------
// STORE-3: product list helpers (categories, search, filters, cards)
// ---------------------------------------------------------------------------

export const CATEGORY_KEY = 'category'
const DESCRIPTIVE_KEYS = ['feel', 'firmness', 'health', 'purpose', 'type', 'pillow']

/** Cover image URL of an item; images may be plain strings or { url }. */
export function coverUrl(item) {
  const first = ((item && item.catalog_images) || [])[0]
  if (!first) return ''
  return typeof first === 'string' ? first : first.url || ''
}

/** Value(s) of a tag on an item, always as a list of strings. */
export function tagValues(item, key) {
  const v = item && item.tags && typeof item.tags === 'object' ? item.tags[key] : undefined
  if (v === undefined || v === null || v === '') return []
  return (Array.isArray(v) ? v : [v]).map(String)
}

/** The owner's categories, in their order. */
export function categoryNames(config) {
  const dim = ((config && config.tag_dimensions) || []).find((d) => d && d.key === CATEGORY_KEY)
  return dim && Array.isArray(dim.options) ? dim.options.map(String) : []
}

/**
 * Category buttons for the public page: only categories that really have a product,
 * in the owner's order, with counts. Empty when the owner turned the menu off.
 */
export function categoryChips(items, config, style) {
  if (style && style.show_categories === false) return []
  const counts = {}
  for (const it of items || []) for (const c of tagValues(it, CATEGORY_KEY)) counts[c] = (counts[c] || 0) + 1
  return categoryNames(config).filter((n) => counts[n] > 0).map((n) => ({ name: n, count: counts[n] }))
}

/** Filterable tag groups other than category (these go in the "Filters" panel). */
export function otherFilterDims(config) {
  return ((config && config.tag_dimensions) || []).filter(
    (d) => d && d.filterable && d.key !== CATEGORY_KEY && Array.isArray(d.options) && d.options.length > 0
  )
}

/** Same matching rule as Classic: list tags need an exact member, single tags compare ignoring capitals. */
function matchesFilter(item, key, val) {
  const vals = tagValues(item, key)
  if (!vals.length) return false
  const raw = item.tags[key]
  if (Array.isArray(raw)) return vals.includes(val)
  return vals[0].toLowerCase() === String(val).toLowerCase()
}

/** Search words are matched against the title and description, ignoring capitals. */
export function matchesSearch(item, query) {
  const q = String(query || '').trim().toLowerCase()
  if (!q) return true
  return (item.title || '').toLowerCase().includes(q) || (item.description || '').toLowerCase().includes(q)
}

/** filters is { tagKey: value }; empty values are ignored. */
export function filterItems(items, { search = '', filters = {} } = {}) {
  return (items || []).filter((it) => {
    if (!matchesSearch(it, search)) return false
    return Object.entries(filters).every(([k, v]) => !v || matchesFilter(it, k, v))
  })
}

/** Everything a product card needs. */
export function cardView(item, config) {
  const pv = priceView(item, null, config)
  const note = otherFilterDims(config)
    .filter((d) => DESCRIPTIVE_KEYS.some((k) => d.key.toLowerCase().includes(k) || (d.label || '').toLowerCase().includes(k)))
    .map((d) => tagValues(item, d.key)[0])
    .filter(Boolean)
    .slice(0, 2)
    .join(', ')
  return {
    title: item.title || '',
    cover: coverUrl(item),
    priceText: pv.priceText,
    wasText: pv.wasText,
    pct: pv.pct,
    soldOut: item.available === false,
    note,
  }
}

/** Starting state from the page address: ?category=Pillows&sizes=Queen */
export function readUrlState(search, config) {
  const p = new URLSearchParams(search || '')
  const filters = {}
  const cat = p.get('category')
  if (cat && categoryNames(config).some((n) => n.toLowerCase() === cat.toLowerCase())) {
    filters.category = categoryNames(config).find((n) => n.toLowerCase() === cat.toLowerCase())
  }
  const size = p.get('sizes')
  if (size) filters.sizes = size
  return filters
}

/** Address for the list page with an optional category, keeping other query values such as ?src=. */
export function listUrl(orgSlug, category, currentSearch = '') {
  const p = new URLSearchParams(currentSearch || '')
  p.delete('category')
  p.delete('variant')
  if (category) p.set('category', category)
  const qs = p.toString()
  return `/catalog/${orgSlug}${qs ? '?' + qs : ''}`
}

// ---------------------------------------------------------------------------
// STOREFRONT-2: banner, category tiles and soft accent colours
// ---------------------------------------------------------------------------

/** rgba() of a #RRGGBB colour at the given opacity (falls back to a light grey). */
export function tint(hex, alpha) {
  const m = /^#([0-9a-fA-F]{6})$/.exec(String(hex || ''))
  if (!m) return `rgba(20, 24, 27, ${alpha})`
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/**
 * The banner at the top of the shop. The owner's own words and photo when set; otherwise plain wording and up to
 * three product photos (in-stock ones first). Never invents a promise (no delivery, no discount claims).
 */
export function heroView(style, { orgName = '', plural = 'Products', items = [] } = {}) {
  const st = style || {}
  const covers = (items || [])
    .map((it, i) => ({ url: coverUrl(it), i, sold: it && it.available === false }))
    .filter((c) => c.url)
    .sort((a, b) => Number(a.sold) - Number(b.sold) || a.i - b.i)
    .slice(0, 3)
    .map((c) => c.url)
  return {
    title: (st.hero_title || '').trim() || (orgName ? `Welcome to ${orgName}` : `Our ${plural.toLowerCase()}`),
    text: (st.hero_text || '').trim() || `Browse our ${plural.toLowerCase()} and order in a few taps.`,
    image: st.hero_image_url || '',
    collage: st.hero_image_url ? [] : covers,
  }
}

/** "Shop by category" tiles: each category with its count and the photo of its first product that has one. */
export function categoryTiles(items, chips) {
  return (chips || []).map((c) => {
    const withPhoto = (items || []).find((it) => tagValues(it, CATEGORY_KEY).includes(c.name) && coverUrl(it))
    return { name: c.name, count: c.count, cover: withPhoto ? coverUrl(withPhoto) : '' }
  })
}

// ---------------------------------------------------------------------------
// STOREFRONT-3: menu, trust icons, "Shop by need"
// ---------------------------------------------------------------------------

const NEED_WORDS = ['health', 'purpose', 'need', 'concern', 'use']

/** The tag group shown as "Shop by need" (for example health_purpose), or null. Only options a product really has. */
export function needDim(items, config) {
  const dim = otherFilterDims(config).find((d) => {
    const s = `${d.key} ${d.label || ''}`.toLowerCase()
    return NEED_WORDS.some((w) => s.includes(w))
  })
  if (!dim) return null
  const counts = {}
  for (const it of items || []) for (const v of tagValues(it, dim.key)) counts[v] = (counts[v] || 0) + 1
  const options = dim.options.map(String).filter((o) => counts[o] > 0)
  return options.length ? { key: dim.key, label: dim.label || 'Shop by need', options } : null
}

/**
 * The shop menu: everything, up to five categories, "Shop by need" when there is one, then a help link.
 * Each entry is { id, label, kind } and the page decides what a click does.
 */
export function menuLinks({ plural = 'Products', chips = [], need = null, chioma = false, whatsapp = false } = {}) {
  const out = [{ id: 'all', label: `All ${plural.toLowerCase()}`, kind: 'all' }]
  for (const c of (chips || []).slice(0, 5)) out.push({ id: `cat:${c.name}`, label: c.name, kind: 'category', value: c.name })
  if (need) out.push({ id: 'need', label: 'Shop by need', kind: 'need' })
  if (chioma) out.push({ id: 'chioma', label: 'Ask Chioma', kind: 'chioma' })
  else if (whatsapp) out.push({ id: 'whatsapp', label: 'Chat with us', kind: 'whatsapp' })
  return out
}

/** Which small picture fits a trust point, read from its words. Unknown wording gets a tick. */
export function trustIcon(text) {
  const s = String(text || '').toLowerCase()
  if (/secur|pay|safe|protect/.test(s)) return 'shield'
  if (/deliver|ship|dispatch|nationwide|across/.test(s)) return 'truck'
  if (/talk|person|chat|call|support|whatsapp|help/.test(s)) return 'chat'
  if (/showroom|visit|store|shop in|location/.test(s)) return 'pin'
  if (/return|refund|exchange/.test(s)) return 'return'
  if (/warrant|guarantee|year/.test(s)) return 'badge'
  return 'check'
}

/** WhatsApp link asking about one product (used as the second card button when Chioma is off). */
export function whatsappAskLink(waNumber, title) {
  const n = String(waNumber || '').replace(/[^0-9]/g, '')
  if (!n) return ''
  return `https://wa.me/${n}?text=${encodeURIComponent(`Hello, I have a question about ${title || 'a product'}`)}`
}
