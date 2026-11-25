/**
 * frontend/src/catalog/catalogBoot.js
 * STOREFRONT-2: open the public catalog without a loading screen.
 *   - index.html asks the server for the catalog while the app itself is still downloading (window.__opsraCatalog).
 *   - The last catalog a browser saw is kept for a day, so a repeat visit shows at once and is then refreshed quietly.
 * Pure helpers (storage, window and clock are passed in) so they can be tested with `node --test`.
 */

export const CACHE_PREFIX = 'opsra_catalog_v1:'
export const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

/** The list response from GET /public/catalog/{slug}, in the shape the pages use. */
export function shapeCatalog(data) {
  const d = data || {}
  return {
    orgName:         d.org_name,
    waNumber:        d.wa_number,
    catalogConfig:   d.catalog_config,
    wizardQuestions: d.wizard_questions || [],
    items:           d.items || [],
    template:        d.template === 'storefront' ? 'storefront' : 'classic',
    shop:            d.shop || null,
    chat:            d.chat || null,
    style:           d.style || null,
  }
}

/** The saved copy for this catalog, or null when there is none, it is too old, or storage is blocked. */
export function readCachedCatalog(storage, slug, now = Date.now()) {
  if (!storage || !slug) return null
  try {
    const raw = storage.getItem(CACHE_PREFIX + slug)
    if (!raw) return null
    const saved = JSON.parse(raw)
    if (!saved || typeof saved.at !== 'number' || !saved.data) return null
    if (now - saved.at > CACHE_MAX_AGE_MS || now < saved.at) return null
    return saved.data
  } catch {
    return null
  }
}

/** Keeps the raw list response for next time. A full or blocked storage is ignored. */
export function writeCachedCatalog(storage, slug, data, now = Date.now()) {
  if (!storage || !slug || !data) return
  try {
    storage.setItem(CACHE_PREFIX + slug, JSON.stringify({ at: now, data }))
  } catch { /* storage full or blocked: the page still works */ }
}

/** Takes the early request started by index.html for this catalog (only once), or null. */
export function takePrefetch(win, slug) {
  const pre = win && win.__opsraCatalog
  if (!pre || pre.slug !== slug || !pre.promise || typeof pre.promise.then !== 'function') return null
  win.__opsraCatalog = null
  return pre.promise
}
