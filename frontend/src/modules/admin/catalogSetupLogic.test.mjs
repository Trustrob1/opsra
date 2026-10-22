import test from 'node:test'
import assert from 'node:assert/strict'
import {
  itemWord, showGetStarted, totalViews, setupSteps, doneCount, setupComplete, progressPct, setupHeadline,
  startTab, skipKey, loadSkipped, saveSkipped,
} from './catalogSetupLogic.js'

const photo = { id: 'a', title: 'A', catalog_images: ['x.jpg'] }
const bare = { id: 'b', title: 'B' }
const ids = (s) => s.map((x) => x.id)

test('a brand new catalog starts at step 1', () => {
  const s = setupSteps({})
  assert.deepEqual(ids(s), ['products', 'photos', 'categories', 'look', 'share'])
  assert.equal(doneCount(s), 0)
  assert.equal(s[0].now, true)
  assert.equal(s.filter((x) => x.now).length, 1)
  assert.equal(s.filter((x) => x.next).length, 4)
  assert.equal(progressPct(s), '0%')
  assert.equal(setupHeadline(s), 'Let us get your catalog ready')
})

test('products without a photo: step 1 done, photos is next up and says how many', () => {
  const s = setupSteps({ items: [photo, bare, { id: 'c' }] })
  assert.equal(s[0].done, true)
  assert.equal(s[0].summary, '3 products added')
  assert.equal(s[1].now, true)
  assert.match(s[1].desc, /2 of your 3 products still need a photo/)
  assert.equal(s[1].secondary, 'Show the ones without a photo')
  assert.equal(progressPct(s), '20%')
  assert.equal(setupHeadline(s), 'Good start. Keep going.')
})

test('one missing photo uses the singular', () => {
  const s = setupSteps({ items: [photo, bare] })
  assert.match(s[1].desc, /1 of your 2 products still needs a photo/)
  assert.equal(setupSteps({ items: [bare] })[0].summary, '1 product added')
})

test('photos step is not done with zero products, and is done when all have photos', () => {
  assert.equal(setupSteps({ items: [] })[1].done, false)
  assert.equal(setupSteps({ items: [photo] })[1].done, true)
  assert.equal(setupSteps({ items: [photo] })[1].secondary, '')
})

test('a legacy image_url or extra image counts as a photo', () => {
  assert.equal(setupSteps({ items: [{ id: 'z', image_url: 'u' }] })[1].done, true)
  assert.equal(setupSteps({ items: [{ id: 'z', extra_catalog_images: ['u'] }] })[1].done, true)
})

test('categories are done once there is one, or when skipped', () => {
  assert.equal(setupSteps({ categories: [{ name: 'Beds' }] })[2].done, true)
  assert.equal(setupSteps({ categories: [{ name: 'Beds' }, { name: 'Pillows' }] })[2].summary, '2 categories')
  assert.equal(setupSteps({ categories: [] })[2].done, false)
  const sk = setupSteps({ categories: [], skipped: { categories: true } })[2]
  assert.equal(sk.done, true)
  assert.equal(sk.summary, 'Skipped for now')
})

test('look is done on Storefront, or when skipped; Classic alone is not done', () => {
  assert.equal(setupSteps({ config: { template: 'storefront' } })[3].done, true)
  assert.equal(setupSteps({ config: { template: 'classic' } })[3].done, false)
  assert.equal(setupSteps({ config: {}, skipped: { look: true } })[3].summary, 'Classic look')
})

test('share is done when opened, skipped, or a product page has been viewed', () => {
  assert.equal(setupSteps({})[4].done, false)
  assert.equal(setupSteps({ shared: true })[4].done, true)
  assert.equal(setupSteps({ skipped: { share: true } })[4].done, true)
  assert.equal(setupSteps({ items: [{ catalog_views: 3 }] })[4].done, true)
  assert.equal(totalViews([{ catalog_views: 2 }, { catalog_views: '4' }, {}, null]), 6)
})

test('optional flags: categories and look only', () => {
  assert.deepEqual(setupSteps({}).map((x) => x.optional), [false, false, true, true, false])
})

test('the current step is the first one not done, even when a later one is done', () => {
  const s = setupSteps({ items: [photo], config: { template: 'storefront' } })
  assert.equal(s.find((x) => x.now).id, 'categories')
  assert.equal(s[3].done, true)
})

test('everything done: complete, 100%, ready headline, opens on Products', () => {
  const s = setupSteps({ items: [{ ...photo, catalog_views: 1 }], categories: [{ name: 'A' }], config: { template: 'storefront' } })
  assert.equal(setupComplete(s), true)
  assert.equal(progressPct(s), '100%')
  assert.equal(setupHeadline(s), 'Your catalog is ready to share')
  assert.equal(s.some((x) => x.now), false)
  assert.equal(startTab({}, s), 'catalog-items')
})

test('an incomplete setup opens on Get started; Shopify never does', () => {
  assert.equal(startTab({}, setupSteps({})), 'catalog-start')
  assert.equal(startTab({ external_sync: 'shopify' }, setupSteps({})), 'catalog-items')
  assert.equal(showGetStarted({ external_sync: 'shopify' }), false)
  assert.equal(showGetStarted({ external_sync: 'none' }), true)
  assert.equal(showGetStarted(null), true)
})

test('an empty step list is never "complete"', () => {
  assert.equal(setupComplete([]), false)
})

test("the owner's word for products is used, lower-cased", () => {
  assert.equal(itemWord({ catalog_item_label_plural: ' Mattresses ' }), 'mattresses')
  assert.equal(itemWord({ catalog_item_label_plural: '  ' }), 'products')
  assert.equal(itemWord(null), 'products')
  assert.equal(setupSteps({ config: { catalog_item_label_plural: 'Rooms' } })[0].title, 'Add your rooms')
  assert.match(setupSteps({ items: [bare], config: { catalog_item_label_plural: 'Rooms' } })[1].desc, /1 of your 1 rooms still needs a photo/)
})

function fakeStore(initial) {
  const m = new Map(Object.entries(initial || {}))
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, v) }, m }
}

test('skipped choices are saved per business and read back', () => {
  const st = fakeStore()
  assert.deepEqual(loadSkipped(st, 'o1'), { categories: false, look: false, share: false })
  saveSkipped(st, 'o1', { categories: true })
  assert.equal(loadSkipped(st, 'o1').categories, true)
  assert.equal(loadSkipped(st, 'o2').categories, false)
  assert.equal(skipKey('o1'), 'opsra_catalog_setup_o1')
  assert.equal(skipKey(''), 'opsra_catalog_setup_org')
})

test('broken or missing storage never throws', () => {
  assert.deepEqual(loadSkipped(fakeStore({ [skipKey('o')]: '{nope' }), 'o'), { categories: false, look: false, share: false })
  assert.deepEqual(loadSkipped(undefined, 'o'), { categories: false, look: false, share: false })
  assert.deepEqual(loadSkipped({ getItem() { throw new Error('blocked') } }, 'o'), { categories: false, look: false, share: false })
  assert.doesNotThrow(() => saveSkipped({ setItem() { throw new Error('blocked') } }, 'o', {}))
  assert.doesNotThrow(() => saveSkipped(undefined, 'o', {}))
})
