// STORE-6 tests. Run with: node --test frontend/src/modules/admin/catalogStorefrontLogic.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import * as L from './catalogStorefrontLogic.js'

// ---------------------------------------------------------------- Look
test('lookFromConfig: defaults for an empty or junk config', () => {
  assert.deepEqual(L.lookFromConfig(null), { template: 'classic', accent: '', announcement: '', trust_points: ['', '', ''], logo_url: '' })
  assert.equal(L.lookFromConfig({ template: 'weird' }).template, 'classic')
  assert.equal(L.lookFromConfig({ accent: 'red' }).accent, '')
  assert.deepEqual(L.lookFromConfig({ trust_points: 'x' }).trust_points, ['', '', ''])
})

test('lookFromConfig: reads saved values', () => {
  const l = L.lookFromConfig({ template: 'storefront', accent: '#1F4FD8', announcement: 'Hi', trust_points: ['A', 'B'], logo_url: 'https://x/y.png' })
  assert.deepEqual(l, { template: 'storefront', accent: '#1F4FD8', announcement: 'Hi', trust_points: ['A', 'B', ''], logo_url: 'https://x/y.png' })
})

test('effectiveAccent falls back to teal', () => {
  assert.equal(L.effectiveAccent({ accent: '' }), '#0B6E74')
  assert.equal(L.effectiveAccent({ accent: '#B4452B' }), '#B4452B')
  assert.equal(L.effectiveAccent(null), '#0B6E74')
})

test('lookPayload: cleans and sends only the Storefront keys', () => {
  const r = L.lookPayload({ template: 'storefront', accent: ' #1F4FD8 ', announcement: '  Free   delivery ', trust_points: [' Pay  safely ', '', 'Fast'], logo_url: ' https://x/y.png ' })
  assert.deepEqual(r.payload, { template: 'storefront', announcement: 'Free delivery', trust_points: ['Pay safely', 'Fast'], accent: '#1F4FD8', logo_url: 'https://x/y.png' })
  assert.deepEqual(Object.keys(r.payload).sort(), ['accent', 'announcement', 'logo_url', 'template', 'trust_points'])
})

test('lookPayload: empty values are sent as empty so they clear', () => {
  const r = L.lookPayload({ template: 'classic', accent: '', announcement: '', trust_points: ['', '', ''], logo_url: '' })
  assert.deepEqual(r.payload, { template: 'classic', announcement: '', trust_points: [], accent: '', logo_url: '' })
})

test('lookPayload: owner-fixable errors', () => {
  const base = { template: 'storefront', accent: '', announcement: '', trust_points: ['', '', ''], logo_url: '' }
  assert.match(L.lookPayload({ ...base, announcement: 'x'.repeat(121) }).error, /120/)
  assert.match(L.lookPayload({ ...base, trust_points: ['x'.repeat(41), '', ''] }).error, /40/)
  assert.match(L.lookPayload({ ...base, trust_points: ['a', 'b', 'c', 'd'] }).error, /up to 3/)
  assert.match(L.lookPayload({ ...base, accent: 'blue' }).error, /colour/)
  assert.match(L.lookPayload({ ...base, accent: '#12345' }).error, /colour/)
  assert.match(L.lookPayload({ ...base, logo_url: 'http://x/y.png' }).error, /https/)
  assert.match(L.lookPayload({ ...base, logo_url: 'https://x/a b.png' }).error, /https/)
  assert.equal(L.lookPayload({ ...base, announcement: 'x'.repeat(120) }).error, undefined)
})

test('lookChanged', () => {
  const cfg = { template: 'storefront', accent: '#1F4FD8', announcement: 'Hi', trust_points: ['A'], logo_url: '' }
  assert.equal(L.lookChanged(L.lookFromConfig(cfg), cfg), false)
  assert.equal(L.lookChanged({ ...L.lookFromConfig(cfg), announcement: 'Hi there' }, cfg), true)
  assert.equal(L.lookChanged({ ...L.lookFromConfig(cfg), template: 'classic' }, cfg), true)
  assert.equal(L.lookChanged({ ...L.lookFromConfig(cfg), announcement: ' Hi ' }, cfg), false)
  assert.equal(L.lookChanged({ ...L.lookFromConfig(cfg), accent: 'bad' }, cfg), true)
})

test('storefrontLocked only when the plan says no', () => {
  assert.equal(L.storefrontLocked(false), true)
  assert.equal(L.storefrontLocked(true), false)
  assert.equal(L.storefrontLocked(undefined), false)
})

// ---------------------------------------------------------------- Categories
const snap = { categories: [{ name: 'Mattresses', count: 2 }, { name: 'Pillows', count: 1 }], show_in_menu: true }

test('draftFromSnapshot: ids, was = saved name', () => {
  const d = L.draftFromSnapshot(snap)
  assert.deepEqual(d.map((c) => [c.name, c.was]), [['Mattresses', 'Mattresses'], ['Pillows', 'Pillows']])
  assert.equal(new Set(d.map((c) => c.id)).size, 2)
  assert.deepEqual(L.draftFromSnapshot(null), [])
})

test('validateCategoryName', () => {
  const d = L.draftFromSnapshot(snap)
  assert.equal(L.validateCategoryName('  Back   pain ', d).name, 'Back pain')
  assert.match(L.validateCategoryName('', d).error, /Type a name/)
  assert.match(L.validateCategoryName('x'.repeat(41), d).error, /40/)
  assert.match(L.validateCategoryName('a/b', d).error, /cannot contain/)
  assert.match(L.validateCategoryName('a\\b', d).error, /cannot contain/)
  assert.match(L.validateCategoryName('PILLOWS', d).error, /already have a category called Pillows/)
  assert.equal(L.validateCategoryName('Pillows', d, d[1].id).name, 'Pillows') // renaming to itself is fine
  const full = Array.from({ length: 20 }, (_, i) => ({ id: 'x' + i, name: 'n' + i, was: null }))
  assert.match(L.validateCategoryName('one more', full).error, /up to 20/)
  assert.equal(L.validateCategoryName('n3', full, 'x3').name, 'n3')
})

test('add / rename / remove / move', () => {
  let d = L.draftFromSnapshot(snap)
  let r = L.addDraftCategory(d, 'Toppers'); assert.equal(r.error, undefined); d = r.draft
  assert.deepEqual(d.map((c) => c.name), ['Mattresses', 'Pillows', 'Toppers']); assert.equal(d[2].was, null); assert.equal(r.id, d[2].id)
  r = L.addDraftCategory(d, 'toppers'); assert.ok(r.error); assert.equal(r.draft, d)
  r = L.renameDraftCategory(d, d[1].id, 'Cushions'); d = r.draft; assert.equal(d[1].name, 'Cushions'); assert.equal(d[1].was, 'Pillows')
  r = L.renameDraftCategory(d, d[1].id, 'Mattresses'); assert.ok(r.error)
  d = L.moveDraftCategory(d, d[2].id, -1); assert.deepEqual(d.map((c) => c.name), ['Mattresses', 'Toppers', 'Cushions'])
  assert.equal(L.moveDraftCategory(d, d[0].id, -1), d)
  assert.equal(L.moveDraftCategory(d, d[2].id, 1), d)
  assert.equal(L.moveDraftCategory(d, 'nope', 1), d)
  d = L.removeDraftCategory(d, d[1].id); assert.deepEqual(d.map((c) => c.name), ['Mattresses', 'Cushions'])
})

test('entriesFromDraft: was only on real renames', () => {
  let d = L.draftFromSnapshot(snap)
  d = L.renameDraftCategory(d, d[1].id, 'Cushions').draft
  d = L.addDraftCategory(d, 'Toppers').draft
  assert.deepEqual(L.entriesFromDraft(d), [{ name: 'Mattresses' }, { name: 'Cushions', was: 'Pillows' }, { name: 'Toppers' }])
})

const ITEMS = [
  { id: 1, tags: { category: ['Mattresses', 'Pillows'] } },
  { id: 2, tags: { category: 'Mattresses' } },
  { id: 3, tags: {} },
  { id: 4 },
  { id: 5, tags: { category: ['Ghost'] } },
]

test('assignmentsFromItems: ids as strings, unknown categories ignored, no duplicates', () => {
  const a = L.assignmentsFromItems([...ITEMS, { id: 1, tags: { category: ['Mattresses'] } }], ['Mattresses', 'Pillows'])
  assert.deepEqual(a, { Mattresses: ['1', '2'], Pillows: ['1'] })
})

test('assignmentCalls: only changed categories, final names, new categories with products', () => {
  const saved = L.assignmentsFromItems(ITEMS, ['Mattresses', 'Pillows'])
  let d = L.draftFromSnapshot(snap)
  let a = L.draftAssignments(d, saved)
  assert.deepEqual(L.assignmentCalls(d, a, saved), [])
  a = L.toggleAssignment(a, d[1].id, '3')
  assert.deepEqual(L.assignmentCalls(d, a, saved), [{ name: 'Pillows', item_ids: ['1', '3'] }])
  d = L.renameDraftCategory(d, d[1].id, 'Cushions').draft
  assert.deepEqual(L.assignmentCalls(d, a, saved), [{ name: 'Cushions', item_ids: ['1', '3'] }])
  const added = L.addDraftCategory(d, 'Toppers')
  d = added.draft
  a = { ...a, [added.id]: [] }
  assert.equal(L.assignmentCalls(d, a, saved).some((c) => c.name === 'Toppers'), false)
  a = L.toggleAssignment(a, added.id, '4')
  assert.deepEqual(L.assignmentCalls(d, a, saved).find((c) => c.name === 'Toppers'), { name: 'Toppers', item_ids: ['4'] })
})

test('toggleAssignment adds then removes', () => {
  let a = {}
  a = L.toggleAssignment(a, 'c1', '9'); assert.deepEqual(a, { c1: ['9'] })
  a = L.toggleAssignment(a, 'c1', '9'); assert.deepEqual(a, { c1: [] })
})

test('delete then re-add the same name: the empty list is sent so the UI and server agree', () => {
  const saved = L.assignmentsFromItems(ITEMS, ['Mattresses', 'Pillows'])
  let d = L.draftFromSnapshot(snap)
  d = L.removeDraftCategory(d, d[1].id)
  const added = L.addDraftCategory(d, 'Pillows'); d = added.draft
  const a = { ...L.draftAssignments(L.draftFromSnapshot(snap).slice(0, 1), saved), [added.id]: [] }
  const calls = L.assignmentCalls(d, { ...a, [d[0].id]: saved.Mattresses }, saved)
  assert.deepEqual(calls, [{ name: 'Pillows', item_ids: [] }])
})

test('categoriesChanged', () => {
  const saved = L.assignmentsFromItems(ITEMS, ['Mattresses', 'Pillows'])
  const d = L.draftFromSnapshot(snap)
  const a = L.draftAssignments(d, saved)
  assert.equal(L.categoriesChanged(d, a, saved, snap, true), false)
  assert.equal(L.categoriesChanged(d, a, saved, snap, false), true)
  assert.equal(L.categoriesChanged(L.addDraftCategory(d, 'X').draft, a, saved, snap, true), true)
  assert.equal(L.categoriesChanged(L.moveDraftCategory(d, d[1].id, -1), a, saved, snap, true), true)
  assert.equal(L.categoriesChanged(d, L.toggleAssignment(a, d[0].id, '4'), saved, snap, true), true)
  assert.equal(L.categoriesChanged(d, a, saved, { ...snap, show_in_menu: undefined }, true), false)
})

// ---------------------------------------------------------------- drawer field
test('drawer helpers', () => {
  assert.deepEqual(L.chosenCategories({ category: ['A', 'B'] }), ['A', 'B'])
  assert.deepEqual(L.chosenCategories({ category: 'A' }), ['A'])
  assert.deepEqual(L.chosenCategories({}), [])
  assert.deepEqual(L.chosenCategories(null), [])
  assert.deepEqual(L.withCategory(['A'], 'B'), ['A', 'B'])
  assert.deepEqual(L.withCategory(['A'], 'A'), ['A'])
  assert.deepEqual(L.withoutCategory(['A', 'B'], 'A'), ['B'])
  assert.deepEqual(L.remainingCategories(['A', 'B', 'C'], ['B']), ['A', 'C'])
})

// ---------------------------------------------------------------- error text
import { catalogErrorText } from './catalogErrors.js'
test('catalogErrorText', () => {
  const e = (detail) => ({ response: { data: { detail } } })
  assert.equal(catalogErrorText(e('You already have a category called Pillows.'), 'x'), 'You already have a category called Pillows.')
  assert.match(catalogErrorText(e({ code: 'PLAN_REQUIRED' }), 'x'), /plan does not include/)
  assert.equal(catalogErrorText(e({ message: 'Nope' }), 'x'), 'Nope')
  assert.equal(catalogErrorText(e([{ msg: 'Value error, Logo link must start with https://' }]), 'x'), 'Logo link must start with https://')
  assert.equal(catalogErrorText(e('  '), 'fallback'), 'fallback')
  assert.equal(catalogErrorText(new Error('net'), 'fallback'), 'fallback')
  assert.equal(catalogErrorText(null, 'fallback'), 'fallback')
})
