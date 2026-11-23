/**
 * frontend/src/utils/webchatChoices.js
 * ONLY-1c-DOWN: the buttons the server sends with a "Chioma cannot answer" reply: Open menu, Talk to the team / Leave a message,
 * Call us / Request a call back. Pure functions so they can be tested without a browser.
 */
const KNOWN = new Set(['menu', 'human', 'call', 'item', 'say', 'shop'])     // 'shop' (AD-PRODUCT-1): See other products, opens the shop list     // 'say' (SMART-1): a tap-to-answer option of a guided question; sends its label as the visitor's reply     // 'item' (HUMAN-OFFER-1): one of the business's own chat buttons, by menu_id

/** {mid, items} for the last bot message of a reply that came with choices, else null. Unknown or label-less choices are dropped. */
export function choicesFromReply(res) {
  const items = (Array.isArray(res?.choices) ? res.choices : [])
    .filter((c) => c && KNOWN.has(c.id) && typeof c.label === 'string' && c.label.trim() && (c.id !== 'item' || /^[A-Za-z0-9_-]{1,40}$/.test(c.menu_id || '')))
    .map((c) => (c.id === 'item' ? { id: c.id, label: c.label.trim().slice(0, 40), menu_id: c.menu_id } : { id: c.id, label: c.label.trim().slice(0, 40) }))
  if (!items.length) return null
  const bots = (Array.isArray(res?.messages) ? res.messages : []).filter((m) => m && m.role === 'bot' && m.id)
  const last = bots[bots.length - 1]
  return last ? { mid: last.id, items } : null
}

/**
 * Buttons to show under message `m`: only under the message they came with, and only while it is still the last message
 * (the moment the visitor writes anything, they go). A "Talk to the team" button needs a team item in the menu and is hidden
 * once a person has taken over; a call button needs the business's call feature to be on.
 */
export function visibleChoices(choices, m, isLast, { hasHumanItem, humanActive, callOn }) {
  if (!choices || !isLast || !m || m.id !== choices.mid) return []
  return choices.items.filter((c) => {
    if (c.id === 'human') return !!hasHumanItem && !humanActive
    if (c.id === 'call') return !!callOn
    return true
  })
}
