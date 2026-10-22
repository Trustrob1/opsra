/**
 * frontend/src/modules/admin/catalogSetupLogic.js
 * STORE-13: the "Get started" checklist for a new catalog. Pure helpers (tested with node --test).
 * Five steps: products, photos, categories (optional), look (optional), share.
 */
import { needsPhotoCount } from './catalogImportLogic.js'

export const STEP_TOTAL = 5

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

/** What the owner calls their products, lower case ("mattresses"); "products" when they have not said. */
export function itemWord(config) {
  const w = ((config && config.catalog_item_label_plural) || '').trim().toLowerCase()
  return w || 'products'
}

/** The checklist is only for businesses that add products by hand. Shopify products arrive by sync. */
export function showGetStarted(config) {
  return ((config && config.external_sync) || 'none') !== 'shopify'
}

export function totalViews(items) {
  return (items || []).reduce((n, i) => n + (Number(i && i.catalog_views) || 0), 0)
}

/**
 * The five steps, each with done / now / next.
 * skipped: { categories, look, share } - the owner chose to skip (kept in the browser).
 * shared: the owner opened "Get your link". Someone opening a product page also counts as shared.
 */
export function setupSteps({ items, categories, config, skipped, shared } = {}) {
  const list = items || []
  const cats = categories || []
  const skip = skipped || {}
  const cfg = config || {}
  const word = itemWord(cfg)
  const n = list.length
  const missing = needsPhotoCount(list)
  const storefront = cfg.template === 'storefront'

  const defs = [
    {
      id: 'products', title: `Add your ${word}`, optional: false,
      desc: `Give each one a name, a price and a photo. Got a long list already? Import it from a spreadsheet instead.`,
      primary: 'Add a product', secondary: 'Import a spreadsheet',
      done: n > 0, summary: `${plural(n, 'product', 'products')} added`,
    },
    {
      id: 'photos', title: 'Add photos', optional: false,
      desc: n > 0 && missing > 0
        ? `Shoppers rarely buy what they cannot see. ${missing} of your ${n} ${word} still ${missing === 1 ? 'needs a photo' : 'need a photo'}. Drop many in at once and we match them by file name.`
        : 'Shoppers rarely buy what they cannot see. Drop many photos in at once and we match them by file name.',
      primary: 'Add photos in bulk', secondary: n > 0 && missing > 0 ? 'Show the ones without a photo' : '',
      done: n > 0 && missing === 0, summary: 'Every product has a photo',
    },
    {
      id: 'categories', title: 'Group into categories', optional: true,
      desc: 'Categories become the menu at the top of your store, like Mattresses and Pillows.',
      primary: 'Set up categories', secondary: '',
      done: cats.length > 0 || !!skip.categories, summary: cats.length ? plural(cats.length, 'category', 'categories') : 'Skipped for now',
    },
    {
      id: 'look', title: 'Choose how it looks', optional: true,
      desc: 'Pick Classic or Storefront, and your brand colour.',
      primary: 'Choose a look', secondary: '',
      done: storefront || !!skip.look, summary: storefront ? 'Storefront look' : 'Classic look',
    },
    {
      id: 'share', title: 'Share your catalog', optional: false,
      desc: 'Send the link on WhatsApp, post it on Instagram, or print the QR code for your shop.',
      primary: 'Get your link', secondary: '',
      done: !!shared || !!skip.share || totalViews(list) > 0, summary: 'Link ready to share',
    },
  ]
  let nowSet = false
  return defs.map((d, i) => {
    const now = !d.done && !nowSet
    if (now) nowSet = true
    return { ...d, n: i + 1, now, next: !d.done && !now }
  })
}

export function doneCount(steps) {
  return (steps || []).filter((s) => s.done).length
}

export function setupComplete(steps) {
  return (steps || []).length > 0 && doneCount(steps) === (steps || []).length
}

export function progressPct(steps) {
  return `${Math.round((doneCount(steps) / STEP_TOTAL) * 100)}%`
}

export function setupHeadline(steps) {
  const d = doneCount(steps)
  if (d === 0) return 'Let us get your catalog ready'
  if (d >= STEP_TOTAL) return 'Your catalog is ready to share'
  return 'Good start. Keep going.'
}

/** Which tab opens first: the checklist while it is useful, otherwise the products. */
export function startTab(config, steps) {
  return showGetStarted(config) && !setupComplete(steps) ? 'catalog-start' : 'catalog-items'
}

// ── what the owner skipped, kept in this browser ────────────────────────────
export function skipKey(org) {
  return `opsra_catalog_setup_${org || 'org'}`
}

export function loadSkipped(storage, org) {
  try {
    const v = JSON.parse(storage.getItem(skipKey(org)) || '{}')
    return { categories: !!(v && v.categories), look: !!(v && v.look), share: !!(v && v.share) }
  } catch {
    return { categories: false, look: false, share: false }
  }
}

export function saveSkipped(storage, org, skipped) {
  try { storage.setItem(skipKey(org), JSON.stringify(skipped || {})) } catch { /* private window: it just comes back next time */ }
}
