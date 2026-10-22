import test from 'node:test'
import assert from 'node:assert/strict'
import { normalise, nameCandidates, fileProblem, matchPhotos, photoCount } from './photoMatch.js'

const F = (name, type = 'image/jpeg', size = 1000) => ({ name, type, size })
const items = [
  { id: 'a', slug: 'cloud-9-mattress', title: 'Cloud 9 Mattress' },
  { id: 'b', slug: 'memory-foam-pillow', title: 'Memory Foam Pillow' },
  { id: 'c', slug: 'cloud-9', title: 'Cloud 9' },
  { id: 'd', slug: 'twin-a', title: 'Twin' },
  { id: 'e', slug: 'twin-b', title: 'Twin' },
]

test('normalise: capitals, spaces, accents, symbols', () => {
  assert.equal(normalise('  Café  Chair!! '), 'cafe-chair')
  assert.equal(normalise('Cloud_9 (Mattress)'), 'cloud-9-mattress')
  assert.equal(normalise(''), '')
  assert.equal(normalise(null), '')
})

test('nameCandidates: whole name first, then without the trailing number', () => {
  assert.deepEqual(nameCandidates('cloud-9-mattress-2.jpg'), [{ key: 'cloud-9-mattress-2', index: 1 }, { key: 'cloud-9-mattress', index: 2 }])
  assert.deepEqual(nameCandidates('Pillow (3).PNG').map((c) => c.index), [1, 3])
  assert.deepEqual(nameCandidates('pillow_2.jpeg')[1], { key: 'pillow', index: 2 })
  assert.equal(nameCandidates('nodigits.jpg').length, 1)
  assert.equal(nameCandidates('C:\\pics\\cloud 9.jpg')[0].key, 'cloud-9')
})

test('fileProblem', () => {
  assert.equal(fileProblem(F('a.jpg')), '')
  assert.equal(fileProblem(F('a.png', 'image/png')), '')
  assert.equal(fileProblem(F('a.webp', 'image/webp')), '')
  assert.match(fileProblem(F('IMG_1.HEIC', '')), /HEIC/)
  assert.match(fileProblem(F('a.heic', 'image/heic')), /HEIC/)
  assert.match(fileProblem(F('a.gif', 'image/gif')), /JPEG, PNG and WebP/)
  assert.match(fileProblem(F('a.pdf', 'application/pdf')), /JPEG, PNG and WebP/)
  assert.match(fileProblem(F('a.jpg', 'image/jpeg', 5 * 1024 * 1024 + 1)), /5 MB/)
  assert.equal(fileProblem(F('a.jpg', 'image/jpeg', 5 * 1024 * 1024)), '')
})

test('matches by page address or by name, in photo order', () => {
  const r = matchPhotos([F('cloud-9-mattress-3.jpg'), F('Cloud 9 Mattress.jpg'), F('cloud-9-mattress-2.jpg'), F('memory-foam-pillow.png', 'image/png')], items)
  assert.equal(r.unmatched.length, 0)
  const a = r.matched.find((g) => g.item.id === 'a')
  assert.deepEqual(a.files.map((x) => x.file.name), ['Cloud 9 Mattress.jpg', 'cloud-9-mattress-2.jpg', 'cloud-9-mattress-3.jpg'])
  assert.equal(r.matched.find((g) => g.item.id === 'b').files.length, 1)
  assert.equal(photoCount(r), 4)
})

test('a name that is itself "cloud 9" is not read as "cloud" number 9', () => {
  const r = matchPhotos([F('cloud-9.jpg'), F('cloud-9-2.jpg')], items)
  const c = r.matched.find((g) => g.item.id === 'c')
  assert.deepEqual(c.files.map((x) => x.index), [1, 2])
  assert.equal(r.matched.length, 1)
})

test('no match and more-than-one match are listed, not guessed', () => {
  const r = matchPhotos([F('random.jpg'), F('twin.jpg')], items)
  assert.deepEqual(r.unmatched.map((u) => u.reason), ['none', 'several'])
  assert.equal(r.matched.length, 0)
})

test('the owner can place an unmatched file by hand', () => {
  const files = [F('random.jpg'), F('twin.jpg')]
  const r = matchPhotos(files, items, { 0: 'b', 1: 'e' })
  assert.equal(r.unmatched.length, 0)
  assert.deepEqual(r.matched.map((g) => g.item.id).sort(), ['b', 'e'])
  const bad = matchPhotos([F('x.jpg')], items, { 0: 'nope' })
  assert.equal(bad.unmatched.length, 1)
})

test('unusable files go to problems and are never matched', () => {
  const r = matchPhotos([F('cloud-9-mattress.heic', 'image/heic'), F('cloud-9-mattress.jpg', 'image/jpeg', 6e6), F('cloud-9-mattress.jpg')], items)
  assert.equal(r.problems.length, 2)
  assert.equal(r.matched[0].files.length, 1)
})

test('empty input', () => {
  assert.deepEqual(matchPhotos([], items), { matched: [], unmatched: [], problems: [] })
  assert.deepEqual(matchPhotos(null, null), { matched: [], unmatched: [], problems: [] })
})
