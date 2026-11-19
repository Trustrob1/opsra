/**
 * frontend/src/utils/webchatMenu.js
 * MENU-MORE: which chat buttons the Menu panel shows first. The owner marks buttons as featured; those lead and the rest sit under
 * "More options" (a campaign can feature just one or two). With nothing featured, a long menu (more than 6) shows its first 5.
 * "Talk to the team" is handled separately by the page (always shown). Pure, so it can be tested without a browser.
 */
export const LONG_MENU = 6
export const FIRST_SHOWN = 5

/** { shown, hidden } for the menu items (human item already removed). expanded = the visitor tapped More options. */
export function menuView(items, expanded) {
  const list = Array.isArray(items) ? items : []
  const featured = list.filter((m) => m && m.featured)
  let lead
  if (featured.length && featured.length < list.length) lead = featured
  else if (!featured.length && list.length > LONG_MENU) lead = list.slice(0, FIRST_SHOWN)
  else lead = list
  const rest = list.filter((m) => !lead.includes(m))
  return expanded ? { shown: [...lead, ...rest], hidden: 0, canCollapse: rest.length > 0 } : { shown: lead, hidden: rest.length, canCollapse: false }
}
