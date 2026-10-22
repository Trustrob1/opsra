/**
 * frontend/src/catalog/storefront/storefrontCart.js
 * STORE-4: plain logic for the Storefront cart (no React, no network). The cart itself lives on the web chat
 * session on the server; prices are always re-read there, so nothing here decides a price.
 */
import { coverUrl, formatMoney } from './storefrontLogic.js'

export const MAX_QTY = 10
const TAG_RE = /^[A-Za-z0-9_-]{1,30}$/
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** The tag from ?src= (or ?s=) in the address, if it is a safe 1-30 character tag. */
export function cleanSource(search) {
  const p = new URLSearchParams(search || '')
  const v = (p.get('src') || p.get('s') || '').trim()
  return TAG_RE.test(v) ? v.toLowerCase() : null
}

export const EMPTY_CART = { items: [], total: 0, count: 0 }

/** Whatever the server returned, as a safe {items,total,count}. */
export function normaliseCart(data) {
  const items = Array.isArray(data && data.items)
    ? data.items
        .filter((l) => l && l.pid)
        .map((l) => ({
          pid: String(l.pid), vid: l.vid == null ? null : String(l.vid), name: String(l.name || 'Item'),
          price: Number(l.price) || 0, qty: Math.max(0, Math.min(MAX_QTY, parseInt(l.qty, 10) || 0)),
        }))
        .filter((l) => l.qty > 0)
    : []
  return {
    items,
    total: Number(data && data.total) || items.reduce((n, l) => n + l.price * l.qty, 0),
    count: items.reduce((n, l) => n + l.qty, 0),
  }
}

/**
 * The option id the server needs. A chosen size wins. A product with no real sizes but one stored default option
 * (Shopify "Default Title") still needs that option's id, because the server asks for an option whenever any is stored.
 */
export function cartVariantId(item, selected) {
  const idOf = (v) => (v && (v.id ?? v.variant_id) != null && String(v.id ?? v.variant_id).trim() !== '' ? String(v.id ?? v.variant_id) : null)
  if (selected) return idOf(selected)
  const first = ((item && item.variants) || []).map(idOf).find(Boolean)
  return first || null
}

/** Can this product be added to the cart? Needs a shop key, a real price and no "price on request". */
export function canUseCart(shop, config) {
  return !!(shop && shop.key) && !(config && config.price_on_request)
}

/** Cart lines with the product photo and page name added, for the drawer. */
export function decorateLines(cart, items) {
  const byId = new Map((items || []).map((i) => [String(i.id), i]))
  return (cart && cart.items ? cart.items : []).map((l) => {
    const it = byId.get(l.pid)
    return { ...l, key: `${l.pid}|${l.vid ?? ''}`, image: it ? coverUrl(it) : '', slug: it ? it.slug : null, lineTotal: l.price * l.qty }
  })
}

export const moneyText = (n, template) => formatMoney(n, template) || '₦0'

/** Client-side check before the contact form is sent; the server checks again. Returns {error} or {payload}. */
export function validateContact(f) {
  const name = String((f && f.name) || '').trim()
  const phone = String((f && f.phone) || '').trim()
  const email = String((f && f.email) || '').trim()
  if (name.length < 2) return { error: 'Please tell us your name.' }
  if (!phone && !email) return { error: 'Please give a WhatsApp number or an email so we can reach you.' }
  if (phone && phone.replace(/\D/g, '').length < 7) return { error: 'That WhatsApp number does not look right.' }
  if (email && !EMAIL_RE.test(email)) return { error: 'That email does not look right.' }
  if (!f.consent) return { error: 'Please tick the box so we can contact you.' }
  return { payload: { name, phone: phone || null, email: email || null, consent: true, website: '' } }
}

/** A plain sentence from an API error, never a stack trace. */
export function cartErrorText(err, fallback = 'Something went wrong. Please try again.') {
  const d = err && err.response && err.response.data && err.response.data.detail
  if (d && typeof d === 'object' && d.message) return String(d.message)
  if (typeof d === 'string' && d) return d
  if (err && err.response && err.response.status === 429) return 'Too many tries. Please wait a moment.'
  return fallback
}

export const askedForContact = (err) => !!(err && err.response && err.response.data && err.response.data.detail && err.response.data.detail.ask_contact)
export const isSessionExpired = (err) => !!(err && err.response && err.response.status === 401)

/** Only an https link is followed automatically. */
export const safePayUrl = (u) => (typeof u === 'string' && /^https:\/\/[^\s]+$/i.test(u) ? u : null)

const tokenKey = (shopKey) => `sf_cart_${shopKey}`
export function readToken(shopKey) {
  try { return window.sessionStorage.getItem(tokenKey(shopKey)) || null } catch { return null }
}
export function writeToken(shopKey, token) {
  try { window.sessionStorage.setItem(tokenKey(shopKey), token) } catch { /* private window: the cart just lasts this page */ }
}
export function clearToken(shopKey) {
  try { window.sessionStorage.removeItem(tokenKey(shopKey)) } catch { /* nothing to clear */ }
}

/**
 * STORE-5: the short link /shop/{slug}[/item] opens the same catalog. Returns the /catalog/... path for it,
 * or null when the address is not a short link.
 */
export function catalogPathFromShort(pathname) {
  const parts = String(pathname || '').split('/').filter(Boolean)
  if (parts[0] !== 'shop' || !parts[1]) return null
  return '/catalog/' + parts.slice(1).join('/')
}
