/**
 * frontend/src/modules/admin/catalogStorefrontLogic.js
 * STORE-6: pure helpers for the owner screens "Look" and "Categories" and the product drawer's Categories field.
 * No React, no network - tested with `node --test`.
 * The rules mirror the backend (catalog.py / catalog_storefront_service.py / catalog_category_service.py);
 * the backend is still the final check.
 */

export const ACCENT_PRESETS = [
  { name: 'Teal', hex: '#0B6E74' },
  { name: 'Blue', hex: '#1F4FD8' },
  { name: 'Rust', hex: '#B4452B' },
  { name: 'Black', hex: '#14181B' },
]
export const DEFAULT_ACCENT = '#0B6E74'
export const ANNOUNCEMENT_MAX = 120
export const TRUST_POINTS_MAX = 3
export const TRUST_POINT_CHARS = 40
export const LOGO_URL_MAX = 300
export const CATEGORY_MAX = 20
export const CATEGORY_NAME_MAX = 40

const HEX = /^#[0-9a-fA-F]{6}$/
const squash = (s) => String(s ?? '').split(/\s+/).filter(Boolean).join(' ')

export const isHex = (v) => HEX.test(String(v ?? ''))

// ---------------------------------------------------------------- Look

/** Starting values for the Look form from a saved catalog config. */
export function lookFromConfig(config) {
  const c = config || {}
  const pts = Array.isArray(c.trust_points) ? c.trust_points.map(String) : []
  return {
    template: c.template === 'storefront' ? 'storefront' : 'classic',
    accent: isHex(c.accent) ? c.accent : '',
    announcement: String(c.announcement || ''),
    trust_points: [0, 1, 2].map((i) => pts[i] || ''),
    logo_url: String(c.logo_url || ''),
  }
}

/** The accent shown as selected: the saved one, or the default teal when none is saved. */
export const effectiveAccent = (look) => (isHex(look?.accent) ? look.accent : DEFAULT_ACCENT)

/**
 * What to send to PATCH /catalog/config. Only the Storefront fields, so saving the Look
 * can never overwrite the other catalog settings (and the other way round).
 * Returns { payload } or { error } with a message an owner can act on.
 */
export function lookPayload(look) {
  const announcement = squash(look.announcement)
  if (announcement.length > ANNOUNCEMENT_MAX) return { error: `The announcement can be up to ${ANNOUNCEMENT_MAX} characters.` }
  const points = (look.trust_points || []).map(squash).filter(Boolean)
  if (points.length > TRUST_POINTS_MAX) return { error: `You can add up to ${TRUST_POINTS_MAX} trust points.` }
  const long = points.find((p) => p.length > TRUST_POINT_CHARS)
  if (long) return { error: `Each trust point can be up to ${TRUST_POINT_CHARS} characters. "${long.slice(0, 20)}..." is too long.` }
  const accent = String(look.accent || '').trim()
  if (accent && !isHex(accent)) return { error: 'Type the colour as a code like #0B6E74, or pick one of the four.' }
  const logo = String(look.logo_url || '').trim()
  if (logo && (!/^https:\/\//i.test(logo) || /\s/.test(logo) || logo.length > LOGO_URL_MAX)) {
    return { error: 'The logo link must start with https:// and have no spaces.' }
  }
  return {
    payload: {
      template: look.template === 'storefront' ? 'storefront' : 'classic',
      announcement,
      trust_points: points,
      accent,
      logo_url: logo,
    },
  }
}

/** True when the form differs from what is saved. */
export function lookChanged(look, config) {
  const a = lookPayload(look).payload
  const b = lookPayload(lookFromConfig(config)).payload
  return !a || JSON.stringify(a) !== JSON.stringify(b)
}

/** The Storefront card is locked when the plan does not include it (a saved Storefront choice still shows as chosen). */
export function storefrontLocked(allowed) {
  return allowed === false
}

// ---------------------------------------------------------------- Categories (owner screen)

let _seq = 0
const nextId = () => `c${++_seq}`

/** Draft list from GET /catalog/categories: each row remembers its saved name (`was`) so a rename can be told to the server. */
export function draftFromSnapshot(snap) {
  return ((snap && snap.categories) || []).map((c) => ({ id: nextId(), name: c.name, was: c.name }))
}

/** Same rules as the server: 1-40 characters, no / or \, not already used (ignoring capitals), at most 20. */
export function validateCategoryName(raw, draft, exceptId = null) {
  const name = squash(raw)
  if (!name) return { error: 'Type a name for the category.' }
  if (name.length > CATEGORY_NAME_MAX) return { error: `A category name can be up to ${CATEGORY_NAME_MAX} characters.` }
  if (/[\\/]/.test(name)) return { error: 'A category name cannot contain / or \\.' }
  const clash = (draft || []).find((c) => c.id !== exceptId && c.name.toLowerCase() === name.toLowerCase())
  if (clash) return { error: `You already have a category called ${clash.name}.` }
  if (exceptId === null && (draft || []).length >= CATEGORY_MAX) return { error: `You can have up to ${CATEGORY_MAX} categories.` }
  return { name }
}

export function addDraftCategory(draft, raw) {
  const v = validateCategoryName(raw, draft)
  if (v.error) return { error: v.error, draft }
  const row = { id: nextId(), name: v.name, was: null }
  return { draft: [...draft, row], id: row.id, name: v.name }
}

export function renameDraftCategory(draft, id, raw) {
  const v = validateCategoryName(raw, draft, id)
  if (v.error) return { error: v.error, draft }
  return { draft: draft.map((c) => (c.id === id ? { ...c, name: v.name } : c)) }
}

export const removeDraftCategory = (draft, id) => draft.filter((c) => c.id !== id)

export function moveDraftCategory(draft, id, dir) {
  const i = draft.findIndex((c) => c.id === id)
  const j = i + dir
  if (i < 0 || j < 0 || j >= draft.length) return draft
  const next = draft.slice()
  ;[next[i], next[j]] = [next[j], next[i]]
  return next
}

/** Body for PUT /catalog/categories: names in order, `was` only where a saved category was renamed. */
export function entriesFromDraft(draft) {
  return draft.map((c) => (c.was && c.was !== c.name ? { name: c.name, was: c.was } : { name: c.name }))
}

/** { savedName: [item ids] } from the products' category tags. */
export function assignmentsFromItems(items, savedNames) {
  const out = {}
  for (const n of savedNames) out[n] = []
  for (const it of items || []) {
    const raw = it && it.tags && it.tags.category
    const vals = Array.isArray(raw) ? raw : raw ? [raw] : []
    for (const v of vals) if (out[v] && !out[v].includes(String(it.id))) out[v].push(String(it.id))
  }
  return out
}

/** Draft assignments keyed by draft id, seeded from the saved ones (new categories start empty). */
export function draftAssignments(draft, saved) {
  const out = {}
  for (const c of draft) out[c.id] = c.was && saved[c.was] ? saved[c.was].slice() : []
  return out
}

export function toggleAssignment(assign, id, itemId) {
  const cur = assign[id] || []
  const has = cur.includes(itemId)
  return { ...assign, [id]: has ? cur.filter((x) => x !== itemId) : [...cur, itemId] }
}

/**
 * After the categories are saved, which categories need their product list sent?
 * New categories with products, and saved ones whose product set changed. Uses the final names.
 * Returns [{ name, item_ids }].
 */
export function assignmentCalls(draft, assign, saved) {
  const same = (a, b) => a.length === b.length && a.every((x) => b.includes(x))
  const calls = []
  for (const c of draft) {
    const now = assign[c.id] || []
    // a brand-new row that re-uses a saved name keeps the server's old products until we send ours
    const before = (c.was ? saved[c.was] : saved[c.name]) || []
    if (!same(now, before)) calls.push({ name: c.name, item_ids: now })
  }
  return calls
}

/** True when the owner changed anything on the Categories screen. */
export function categoriesChanged(draft, assign, saved, snap, showInMenu) {
  const names = (snap?.categories || []).map((c) => c.name)
  const sameNames = names.length === draft.length && draft.every((c, i) => c.name === names[i] && c.was === names[i])
  return !sameNames || assignmentCalls(draft, assign, saved).length > 0 || (snap?.show_in_menu !== false) !== !!showInMenu
}

// ---------------------------------------------------------------- Product drawer: Categories field

export const chosenCategories = (tags) => {
  const raw = tags && tags.category
  return (Array.isArray(raw) ? raw : raw ? [raw] : []).map(String)
}

export const withCategory = (chosen, name) => (chosen.includes(name) ? chosen : [...chosen, name])
export const withoutCategory = (chosen, name) => chosen.filter((c) => c !== name)

/** Categories not yet on this product (the outlined chips). */
export const remainingCategories = (all, chosen) => all.filter((n) => !chosen.includes(n))
