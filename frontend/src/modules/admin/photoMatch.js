/**
 * frontend/src/modules/admin/photoMatch.js
 * STORE-12: match a pile of photo files to products by file name. Pure functions, tested with node --test.
 *
 *   cloud-9-mattress.jpg      -> the product whose page address or name is "cloud-9-mattress" (first photo)
 *   cloud-9-mattress-2.jpg    -> the same product, second photo  (also _2, " 2", "(2)")
 *   Cloud 9 Mattress.PNG      -> capitals, spaces and accents do not matter
 * A file that matches no product, or matches two, is listed for the owner to place by hand. Nothing is guessed.
 */
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export function normalise(s) {
  return String(s || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

/** File name without its extension. */
export function stem(fileName) {
  return String(fileName || '').replace(/^.*[\\/]/, '').replace(/\.[A-Za-z0-9]{1,5}$/, '')
}

/** Names to try for a file, best first: the whole name (photo 1), then the name without a trailing number (photo N). */
export function nameCandidates(fileName) {
  const whole = normalise(stem(fileName))
  const out = [{ key: whole, index: 1 }]
  const m = stem(fileName).match(/^(.*?)[\s_-]*\(?(\d{1,2})\)?$/)
  if (m && normalise(m[1])) out.push({ key: normalise(m[1]), index: Number(m[2]) })
  return out
}

function indexItems(items) {
  const map = new Map()
  for (const it of items || []) {
    for (const k of new Set([normalise(it.slug), normalise(it.title)].filter(Boolean))) {
      if (!map.has(k)) map.set(k, new Set())
      map.get(k).add(it.id)
    }
  }
  return map
}

/** Why a file cannot be used at all, or '' when it is fine. `file` needs name, type and size. */
export function fileProblem(file) {
  const name = String(file && file.name || '')
  const type = String(file && file.type || '').toLowerCase()
  if (/\.(heic|heif)$/i.test(name) || /hei[cf]/.test(type)) {
    return 'iPhone HEIC photos are not supported. Send or save them as JPEG, then add them again.'
  }
  if (!PHOTO_TYPES.includes(type)) return 'Only JPEG, PNG and WebP pictures can be added.'
  if ((file.size || 0) > MAX_PHOTO_BYTES) return 'This picture is bigger than 5 MB.'
  return ''
}

/**
 * files: [{name, type, size, ...}], items: [{id, slug, title}]
 * -> { matched: [{ item, files: [{file, index}] }]  (photos in order, 1 first),
 *      unmatched: [{ file, reason }]  (reason: 'none' | 'several'),
 *      problems: [{ file, message }] }
 * `placed` (optional) maps a file's position in `files` to an item id the owner chose by hand.
 */
export function matchPhotos(files, items, placed = {}) {
  const index = indexItems(items)
  const byId = new Map((items || []).map((i) => [i.id, i]))
  const groups = new Map()
  const unmatched = []
  const problems = []
  ;(files || []).forEach((file, pos) => {
    const message = fileProblem(file)
    if (message) { problems.push({ file, message }); return }
    let hit = null
    let several = false
    if (placed[pos] && byId.has(placed[pos])) {
      hit = { id: placed[pos], index: nameCandidates(file.name)[0].index }
      const cand = nameCandidates(file.name).find((c) => (index.get(c.key) || new Set()).has(placed[pos]))
      if (cand) hit.index = cand.index
    } else {
      for (const c of nameCandidates(file.name)) {
        const ids = index.get(c.key)
        if (!ids) continue
        if (ids.size === 1) { hit = { id: [...ids][0], index: c.index }; break }
        several = true
        break
      }
    }
    if (!hit) { unmatched.push({ file, pos, reason: several ? 'several' : 'none' }); return }
    if (!groups.has(hit.id)) groups.set(hit.id, [])
    groups.get(hit.id).push({ file, index: hit.index, pos })
  })
  const matched = [...groups.entries()].map(([id, list]) => ({
    item: byId.get(id),
    files: list.sort((a, b) => a.index - b.index || a.pos - b.pos),
  }))
  return { matched, unmatched, problems }
}

/** Pictures the owner has already placed or matched, as a count. */
export function photoCount(result) {
  return (result.matched || []).reduce((n, g) => n + g.files.length, 0)
}
