/**
 * frontend/src/catalog/storefront/storefrontChat.js
 * WEBCHAT-CATALOG-1: pure helpers for the "Chat with Chioma" button on the Storefront. No React, no network.
 * The backend decides whether the button may show (catalog_storefront_service.chat_info); these only make sure what the
 * browser does with that answer is safe.
 */

const KEY = /^wc_[A-Za-z0-9_-]{8,40}$/
const PID = /^[A-Za-z0-9_-]{1,60}$/

/** The button shows only for a well-formed chat key from the server. */
export function canShowChat(chat) {
  return !!(chat && typeof chat.key === 'string' && KEY.test(chat.key))
}

/** A product id we are willing to pass to the chat, or '' (ids are UUIDs; anything odd is dropped). */
export function cleanProductId(v) {
  const s = String(v ?? '').trim()
  return PID.test(s) ? s : ''
}

/** The chat page shown inside the panel (same site). The product id is optional. */
export function chatSrc(key, productId, buy) {
  const pid = cleanProductId(productId)
  const b = buy ? cleanProductId(buy.product) : ''
  const bv = b ? cleanVariantId(buy.variant) : ''
  return `/c/${key}?embed=1&s=catalog${pid ? `&p=${encodeURIComponent(pid)}` : ''}${b ? `&b=${encodeURIComponent(b)}${bv ? `&bv=${encodeURIComponent(bv)}` : ''}` : ''}`
}

const VID = /^[A-Za-z0-9_.:-]{1,80}$/

/** A product option (size) id we are willing to pass to the chat, or ''. The server checks it against the product. */
export function cleanVariantId(v) {
  const s = String(v ?? '').trim()
  return VID.test(s) ? s : ''
}

/** STORE-CHIOMA-1: "Buy now": the chat puts this product (and size) in its cart and opens the cart, ready to check out. */
export function buyMessage(productId, variantId) {
  const pid = cleanProductId(productId)
  return pid ? { source: 'opsra-catalog', type: 'buy', product: pid, variant: cleanVariantId(variantId) } : null
}

/** The storefront's buttons ask the Chioma panel to open (or to buy) through this one window event. */
export const CHIOMA_EVENT = 'opsra-chioma'
export function askChioma(detail) {
  try { window.dispatchEvent(new CustomEvent(CHIOMA_EVENT, { detail })) } catch { /* no window: nothing to open */ }
}

/** The message sent to the chat page when the visitor moves to another product while the panel is open. */
export function viewingMessage(productId) {
  const pid = cleanProductId(productId)
  return pid ? { source: 'opsra-catalog', type: 'viewing', product: pid } : null
}

/** CHIOMA-VOICE-1: how a person in the shop would say hello at this hour (the visitor's own clock). */
export function helloWord(hour) {
  const h = Number(hour)
  if (h >= 5 && h < 12) return 'Good morning'
  if (h >= 12 && h < 17) return 'Good afternoon'
  if (h >= 17 && h < 24) return 'Good evening'
  return 'Hello'
}

/** WEBCHAT-CATALOG-1c / CHIOMA-VOICE-1: the one-line greeting above the button, in a friendly shop-floor voice.
 * Works for any business: its own name, what its visitors usually come for (`goal`, set in Settings), the time of day,
 * a returning visitor, and the product on a product page. Fixed copy, no AI. Keep in step with chiomaGreeting() in public/widget.js. */
export function greetingText(orgName, productTitle, opts = {}) {
  const t = String(productTitle ?? '').replace(/\s+/g, ' ').trim().replace(/^the\s+/i, '')
  if (t) return `Any questions about the ${t.length > 40 ? `${t.slice(0, 39).trimEnd()}…` : t}? I’m happy to help.`
  const n = String(orgName ?? '').replace(/\s+/g, ' ').trim().slice(0, 60)
  const to = n ? ` to ${n}` : ''
  if (opts.returning) return `Welcome back${to}! 😊 Anything I can help you with today?`
  const goal = String(opts.goal ?? '').replace(/\s+/g, ' ').trim().slice(0, 40)
  const hour = opts.hour ?? new Date().getHours()
  return `${helloWord(hour)}, welcome${to}! Looking for ${goal || 'something'}, or just browsing?`
}

/** CHIOMA-VOICE-1: remembered across visits, so a second visit gets "Welcome back". */
export function seenKey(chatKey) {
  return `opsra_chioma_seen_${chatKey}`
}

/** Once per browser tab for each product (or the shop home), so the card is useful and never nags. */
export function greetedKey(chatKey, productId) {
  return `opsra_chioma_greeted_${chatKey}_${cleanProductId(productId) || 'home'}`
}
