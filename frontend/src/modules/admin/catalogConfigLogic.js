/**
 * frontend/src/modules/admin/catalogConfigLogic.js
 * STORE-13: small pure helpers for the Settings screen (tested with node --test).
 */
// the price styles an owner can pick without knowing the format code
export const PRICE_STYLES = [
  { id: 'a', label: '₦150,000', template: '₦{price}' },
  { id: 'b', label: '₦ 150,000', template: '₦ {price}' },
  { id: 'c', label: '150,000 NGN', template: '{price} NGN' },
]

export function priceStyleOf(template) {
  const hit = PRICE_STYLES.find(p => p.template === template)
  return hit ? hit.id : 'custom'
}

/** Next free button ID ("cta_3") so owners never have to invent one. */
export function nextButtonId(buttons) {
  const used = new Set((buttons || []).map(b => b.id))
  let n = (buttons || []).length + 1
  while (used.has(`cta_${n}`)) n += 1
  return `cta_${n}`
}
