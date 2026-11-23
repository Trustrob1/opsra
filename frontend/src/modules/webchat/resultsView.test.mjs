import test from 'node:test'
import assert from 'node:assert/strict'
import { biggestDrop, headline, funnelWidths, sourceRows } from './resultsView.js'

const steps = [
  { key: 'visit', label: 'Visits', count: 17, rate: null, of: null },
  { key: 'started', label: 'Started chatting', count: 9, rate: 52.9, of: 'visits' },
  { key: 'contact', label: 'Gave contact', count: 5, rate: 55.6, of: 'started chatting' },
  { key: 'booking', label: 'Booked', count: 0, rate: 0, of: 'gave contact' },
  { key: 'order', label: 'Orders started', count: 2, rate: 40, of: 'gave contact' },
  { key: 'paid', label: 'Paid', count: 0, rate: 0, of: 'orders' },
  { key: 'tap', label: 'Tapped a link', count: 0, rate: 0, of: 'started chatting' },
]

test('headline reads the counts', () => {
  assert.equal(headline(steps), '9 of 17 visitors chatted, 5 left contact, 2 started an order')
  assert.equal(headline([{ key: 'visit', label: 'Visits', count: 0 }]), 'No visitors yet in this period')
  assert.equal(headline(steps.map((s) => (s.key === 'order' ? { ...s, count: 0 } : s.key === 'booking' ? { ...s, count: 3 } : s))), '9 of 17 visitors chatted, 5 left contact, 3 asked to book')
})

test('biggest drop counts the people lost against each step\'s own parent and ignores optional goals', () => {
  // visits to started: 8 of 17 lost. Booked is 0 of 5 (100%) but only 5 people, so it does not win.
  assert.deepEqual(biggestDrop(steps), { from: 'visits', to: 'Started chatting', lost: 47, people: 8, of: 17 })
  const later = steps.map((s) => (s.key === 'started' ? { ...s, count: 16 } : s))
  assert.deepEqual(biggestDrop(later).to, 'Gave contact')                           // 16 chatted, 5 gave contact: 11 lost
  const paid = [
    { key: 'visit', label: 'Visits', count: 10, rate: null, of: null }, { key: 'started', label: 'Started chatting', count: 10, rate: 100, of: 'visits' },
    { key: 'contact', label: 'Gave contact', count: 9, rate: 90, of: 'started chatting' }, { key: 'order', label: 'Orders started', count: 9, rate: 100, of: 'gave contact' },
    { key: 'paid', label: 'Paid', count: 2, rate: 22.2, of: 'orders' },
  ]
  assert.deepEqual(biggestDrop(paid), { from: 'orders', to: 'Paid', lost: 78, people: 7, of: 9 })        // paid is measured against orders, not against the step before it
  assert.equal(biggestDrop([{ key: 'tap', label: 'Tapped a link', count: 0, rate: 0, of: 'started chatting' }]), null)
  assert.equal(biggestDrop([]), null)
  assert.equal(biggestDrop([{ key: 'visit', label: 'Visits', count: 5, rate: null, of: null }, { key: 'started', label: 'Started chatting', count: 5, rate: 100, of: 'visits' }]), null)
})

test('funnel strip never has a zero-width step and fades with depth', () => {
  const w = funnelWidths(steps)
  assert.equal(w.length, steps.length)
  assert.ok(w.every((x) => x.flex >= 0.4))
  assert.ok(w[0].opacity > w[w.length - 1].opacity)
})

test('source rows: ads show their label and product, store page and link are named, unvisited ads appear, sorted by visits', () => {
  const sources = [
    { source: 'link', visit: 1, started: 1, contact: 1, catalog_visit: 0 },
    { source: 'catalog', visit: 13, started: 7, contact: 4, order: 2, catalog_visit: 5 },
    { source: 'elite-cool-sales', visit: 3, started: 1, contact: 0 },
  ]
  const ads = [{ tag: 'elite-cool-sales', label: 'Elite sales', product: 'p1' }, { tag: 'new-ad', label: 'New ad' }]
  const rows = sourceRows(sources, ads, [{ id: 'p1', title: 'Elite Cool mattress' }])
  assert.deepEqual(rows.map((r) => r.source), ['catalog', 'elite-cool-sales', 'link', 'new-ad'])
  assert.equal(rows[0].kind, 'Store page'); assert.equal(rows[0].orders, 2); assert.equal(rows[0].catalog_visit, 5)
  assert.equal(rows[1].name, 'Elite sales'); assert.equal(rows[1].kind, 'Ad · Elite Cool mattress')
  assert.equal(rows[2].kind, 'Shared link')
  assert.equal(rows[3].kind, 'Ad'); assert.equal(rows[3].visit, 0)
  assert.deepEqual(sourceRows(null, null, null), [])
})
