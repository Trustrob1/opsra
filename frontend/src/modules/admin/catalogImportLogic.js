/**
 * frontend/src/modules/admin/catalogImportLogic.js
 * STORE-10 / STORE-11 / STORE-12: small pure helpers for the import and photo screens (tested with node --test).
 */

/** Does this product have any photo? */
export function hasPhoto(item) {
  return !!(item && ((item.catalog_images || []).length || (item.extra_catalog_images || []).length || item.image_url))
}

export function needsPhotoCount(items) {
  return (items || []).filter((i) => !hasPhoto(i)).length
}

const STATUS = {
  ok: { label: 'Will be added', tone: 'good' },
  exists: { label: 'Already in your catalog', tone: 'muted' },
  duplicate: { label: 'Repeated in this file', tone: 'muted' },
  error: { label: 'Needs fixing', tone: 'bad' },
  example: { label: 'Example row (skipped)', tone: 'muted' },
}
export function statusView(status) {
  return STATUS[status] || STATUS.error
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

/** "12 will be added. 2 already in your catalog. 1 needs fixing." */
export function previewSummary(counts) {
  const c = counts || {}
  const parts = [`${plural(c.ok || 0, 'product', 'products')} will be added`]
  if (c.exists) parts.push(`${c.exists} already in your catalog`)
  if (c.duplicate) parts.push(`${c.duplicate} repeated in this file`)
  if (c.error) parts.push(`${plural(c.error, 'row needs', 'rows need')} fixing`)
  if (c.example) parts.push(`${plural(c.example, 'example row', 'example rows')} skipped`)
  return parts.join('. ') + '.'
}

/** One job per photo link: [{ itemId, title, row, url }] */
export function photoJobs(created) {
  const out = []
  for (const c of created || []) for (const url of c.photos || []) out.push({ itemId: c.id, title: c.title, row: c.row, url })
  return out
}

/**
 * Runs worker(job) for every job, at most `limit` at a time, and returns the results in the same order.
 * The worker is expected to return a value; if it throws, that job's result is { ok: false, error }.
 */
export async function runPool(jobs, limit, worker, onProgress) {
  const results = new Array(jobs.length)
  let next = 0
  let done = 0
  async function lane() {
    while (next < jobs.length) {
      const i = next++
      try { results[i] = await worker(jobs[i], i) } catch (error) { results[i] = { ok: false, error } }
      done += 1
      if (onProgress) onProgress(done, jobs.length)
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, jobs.length || 1)) }, lane))
  return results
}

/** Plain words for the end of an import. */
export function finishedSummary({ created = [], failed = [], photosOk = 0, photosFailed = 0, categoriesAdded = [] }) {
  const lines = [`${plural(created.length, 'product was', 'products were')} added.`]
  if (categoriesAdded.length) lines.push(`New categories: ${categoriesAdded.join(', ')}.`)
  if (photosOk) lines.push(`${plural(photosOk, 'photo was', 'photos were')} added from links.`)
  if (photosFailed) lines.push(`${plural(photosFailed, 'photo link', 'photo links')} could not be used.`)
  if (failed.length) lines.push(`${plural(failed.length, 'product', 'products')} could not be added.`)
  return lines
}

/** How many of the created products still have no photo (no link, or every link failed). */
export function withoutPhotos(created, jobResults) {
  const okFor = new Set()
  photoJobs(created).forEach((j, i) => { if (jobResults[i] && jobResults[i].ok) okFor.add(j.itemId) })
  return (created || []).filter((c) => !okFor.has(c.id))
}
