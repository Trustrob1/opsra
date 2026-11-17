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
export function chatSrc(key, productId) {
  const pid = cleanProductId(productId)
  return `/c/${key}?embed=1&s=catalog${pid ? `&p=${encodeURIComponent(pid)}` : ''}`
}

/** The message sent to the chat page when the visitor moves to another product while the panel is open. */
export function viewingMessage(productId) {
  const pid = cleanProductId(productId)
  return pid ? { source: 'opsra-catalog', type: 'viewing', product: pid } : null
}

/** WEBCHAT-CATALOG-1c (BUBBLE-3): the one-line greeting above the button. On a product page it names the product. Fixed copy, no AI. */
export function greetingText(orgName, productTitle) {
  const t = String(productTitle ?? '').replace(/\s+/g, ' ').trim()
  if (t) return `Questions about ${t.length > 40 ? `${t.slice(0, 39).trimEnd()}…` : t}? I can help.`
  const n = String(orgName ?? '').replace(/\s+/g, ' ').trim().slice(0, 60)
  return n ? `Hi, I’m Chioma. Ask me anything about ${n}.` : 'Hi, I’m Chioma. Ask me anything.'
}

/** Once per browser tab for each product (or the shop home), so the card is useful and never nags. */
export function greetedKey(chatKey, productId) {
  return `opsra_chioma_greeted_${chatKey}_${cleanProductId(productId) || 'home'}`
}
