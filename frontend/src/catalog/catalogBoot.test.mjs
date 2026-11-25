import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  shapeCatalog, readCachedCatalog, writeCachedCatalog, takePrefetch, CACHE_PREFIX, CACHE_MAX_AGE_MS,
} from './catalogBoot.js'

function memStorage() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), _m: m }
}

test('shapeCatalog maps the list response and defaults to classic', () => {
  const s = shapeCatalog({ org_name: 'RR', items: [{ id: 1 }], template: 'storefront', style: { accent: '#000000' } })
  assert.equal(s.orgName, 'RR')
  assert.equal(s.template, 'storefront')
  assert.deepEqual(s.items, [{ id: 1 }])
  assert.equal(shapeCatalog({ template: 'odd' }).template, 'classic')
  assert.deepEqual(shapeCatalog(null).wizardQuestions, [])
})

test('a saved copy is read back within a day', () => {
  const st = memStorage()
  writeCachedCatalog(st, 'shop', { org_name: 'A' }, 1000)
  assert.deepEqual(readCachedCatalog(st, 'shop', 2000), { org_name: 'A' })
  assert.equal(readCachedCatalog(st, 'other', 2000), null)
})

test('an old, future-dated or broken copy is ignored', () => {
  const st = memStorage()
  writeCachedCatalog(st, 'shop', { org_name: 'A' }, 1000)
  assert.equal(readCachedCatalog(st, 'shop', 1000 + CACHE_MAX_AGE_MS + 1), null)
  assert.equal(readCachedCatalog(st, 'shop', 10), null)
  st.setItem(CACHE_PREFIX + 'bad', '{not json')
  assert.equal(readCachedCatalog(st, 'bad', 2000), null)
})

test('blocked storage never throws', () => {
  const blocked = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('full') } }
  assert.equal(readCachedCatalog(blocked, 'shop'), null)
  assert.doesNotThrow(() => writeCachedCatalog(blocked, 'shop', { a: 1 }))
  assert.equal(readCachedCatalog(null, 'shop'), null)
})

test('the early request is used once and only for the same catalog', () => {
  const p = Promise.resolve({})
  const win = { __opsraCatalog: { slug: 'shop', promise: p } }
  assert.equal(takePrefetch(win, 'other'), null)
  assert.equal(takePrefetch(win, 'shop'), p)
  assert.equal(takePrefetch(win, 'shop'), null)
  assert.equal(takePrefetch({}, 'shop'), null)
})
