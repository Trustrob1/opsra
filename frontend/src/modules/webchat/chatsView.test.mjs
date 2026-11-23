import test from 'node:test'
import assert from 'node:assert/strict'
import { chatTitle, sourceLabel, chatFacts, ago, FILTERS } from './chatsView.js'

test('visitor without contact shows the code, with contact shows the name', () => {
  assert.equal(chatTitle({ has_contact: false, code: 'Visitor 4F2A' }), 'Visitor 4F2A')
  assert.equal(chatTitle({ has_contact: true, name: 'Ada' }), 'Ada')
  assert.equal(chatTitle({ has_contact: true, name: null }), 'Contact left')
})

test('source names', () => {
  const ads = [{ tag: 'elite-cool-sales', label: 'Elite Cool ad' }]
  assert.equal(sourceLabel('elite-cool-sales', ads), 'Ad · Elite Cool ad')
  assert.equal(sourceLabel('catalog', ads), 'Store page')
  assert.equal(sourceLabel('link', ads), 'Shared link')
  assert.equal(sourceLabel('flyer', ads), 'flyer')
})

test('facts: paid beats ordered beats cart, silent visitors are marked', () => {
  const k = (c) => chatFacts(c).map((f) => f.key)
  assert.deepEqual(k({ paid: true, ordered: true, has_contact: true, messages: 4 }), ['paid', 'msgs'])
  assert.deepEqual(k({ ordered: true, has_contact: true, messages: 1 }), ['ordered', 'msgs'])
  assert.deepEqual(k({ cart_items: 2, has_contact: false, messages: 0 }), ['cart', 'nocontact', 'silent'])
  assert.deepEqual(k({ gap: true, handed: true, has_contact: true, messages: 2 }), ['handed', 'gap', 'msgs'])
})

test('ago', () => {
  const now = Date.parse('2026-11-23T12:00:00Z')
  assert.equal(ago('2026-11-23T11:55:00Z', now), '5 min ago')
  assert.equal(ago('2026-11-23T09:00:00Z', now), '3 h ago')
  assert.equal(ago('2026-11-21T12:00:00Z', now), '2 days ago')
  assert.equal(ago('nope', now), '')
})

test('filters match the server list', () => {
  assert.deepEqual(FILTERS.map((f) => f[0]), ['all', 'asked', 'no_contact', 'gap', 'ordered', 'human'])
})
