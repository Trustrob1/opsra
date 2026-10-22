import test from 'node:test'
import assert from 'node:assert/strict'
import { hasPhoto, needsPhotoCount, statusView, previewSummary, photoJobs, runPool, finishedSummary, withoutPhotos } from './catalogImportLogic.js'

test('hasPhoto / needsPhotoCount', () => {
  assert.equal(hasPhoto({ catalog_images: ['x'] }), true)
  assert.equal(hasPhoto({ catalog_images: [], extra_catalog_images: ['y'] }), true)
  assert.equal(hasPhoto({ image_url: 'z' }), true)
  assert.equal(hasPhoto({ catalog_images: [] }), false)
  assert.equal(hasPhoto(null), false)
  assert.equal(needsPhotoCount([{ catalog_images: ['x'] }, {}, { catalog_images: [] }]), 2)
  assert.equal(needsPhotoCount(null), 0)
})

test('statusView and previewSummary', () => {
  assert.equal(statusView('ok').tone, 'good')
  assert.equal(statusView('exists').tone, 'muted')
  assert.equal(statusView('whatever').tone, 'bad')
  assert.equal(previewSummary({ ok: 1 }), '1 product will be added.')
  assert.equal(previewSummary({ ok: 12, exists: 2, duplicate: 1, error: 3 }), '12 products will be added. 2 already in your catalog. 1 repeated in this file. 3 rows need fixing.')
  assert.equal(previewSummary({ ok: 0, error: 1 }), '0 products will be added. 1 row needs fixing.')
  assert.equal(previewSummary(null), '0 products will be added.')
})

test('photoJobs and withoutPhotos', () => {
  const created = [{ id: 'a', title: 'A', row: 2, photos: ['u1', 'u2'] }, { id: 'b', title: 'B', row: 3, photos: [] }, { id: 'c', title: 'C', row: 4, photos: ['u3'] }]
  const jobs = photoJobs(created)
  assert.deepEqual(jobs.map((j) => [j.itemId, j.url]), [['a', 'u1'], ['a', 'u2'], ['c', 'u3']])
  assert.deepEqual(withoutPhotos(created, [{ ok: false }, { ok: true }, { ok: false }]).map((c) => c.id), ['b', 'c'])
  assert.deepEqual(withoutPhotos(created, []).map((c) => c.id), ['a', 'b', 'c'])
})

test('runPool: order kept, limit respected, errors contained, progress reported', async () => {
  let live = 0, peak = 0
  const progress = []
  const worker = async (n) => { live++; peak = Math.max(peak, live); await new Promise((r) => setTimeout(r, 5)); live--; if (n === 3) throw new Error('boom'); return { ok: true, n } }
  const res = await runPool([1, 2, 3, 4, 5, 6, 7], 3, worker, (d, t) => progress.push([d, t]))
  assert.equal(peak, 3)
  assert.deepEqual(res.map((r) => r.ok), [true, true, false, true, true, true, true])
  assert.equal(res[2].error.message, 'boom')
  assert.deepEqual(res.filter((r) => r.ok).map((r) => r.n), [1, 2, 4, 5, 6, 7])
  assert.deepEqual(progress.at(-1), [7, 7])
  assert.deepEqual(await runPool([], 3, worker), [])
})

test('finishedSummary', () => {
  assert.deepEqual(finishedSummary({ created: [1] }), ['1 product was added.'])
  assert.deepEqual(finishedSummary({ created: [1, 2], failed: [1], photosOk: 3, photosFailed: 1, categoriesAdded: ['Beds', 'Pillows'] }), [
    '2 products were added.', 'New categories: Beds, Pillows.', '3 photos were added from links.', '1 photo link could not be used.', '1 product could not be added.'])
})
