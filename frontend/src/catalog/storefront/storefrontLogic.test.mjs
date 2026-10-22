// STORE-2 tests. Run with: node --test frontend/src/catalog/storefront/
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFAULT_ACCENT, resolveAccent, readableOn, discountPercent, formatMoney,
  isVariantAvailable, realVariants, priceView, whatsappOrderLink, initials,
  relatedItems, trustPoints,
} from './storefrontLogic.js'

const CFG = { price_label_template: '₦{price}', price_on_request: false }

test('resolveAccent: valid kept, junk falls back', () => {
  assert.equal(resolveAccent({ accent: '#1F4FD8' }), '#1F4FD8')
  assert.equal(resolveAccent({ accent: 'red' }), DEFAULT_ACCENT)
  assert.equal(resolveAccent({ accent: '#12345' }), DEFAULT_ACCENT)
  assert.equal(resolveAccent({ accent: null }), DEFAULT_ACCENT)
  assert.equal(resolveAccent(null), DEFAULT_ACCENT)
  assert.equal(resolveAccent(undefined), DEFAULT_ACCENT)
})

test('readableOn: dark text on light, white on dark', () => {
  assert.equal(readableOn('#FFFFFF'), '#14181B')
  assert.equal(readableOn('#F5D000'), '#14181B')
  assert.equal(readableOn('#0B6E74'), '#FFFFFF')
  assert.equal(readableOn('#14181B'), '#FFFFFF')
  assert.equal(readableOn('nope'), '#FFFFFF')
})

test('discountPercent: only when compare-at is higher', () => {
  assert.equal(discountPercent(150000, 180000), 17)
  assert.equal(discountPercent('150000', '180000'), 17)
  assert.equal(discountPercent(150000, 150000), null)
  assert.equal(discountPercent(150000, 100000), null)
  assert.equal(discountPercent(0, 100), null)
  assert.equal(discountPercent(null, 100), null)
  assert.equal(discountPercent(100, null), null)
  assert.equal(discountPercent(1000, 1001), null) // under 1%
  assert.equal(discountPercent('x', 'y'), null)
})

test('formatMoney: template, no decimals, empty on bad input', () => {
  assert.equal(formatMoney(150000, '₦{price}'), '₦150,000')
  assert.equal(formatMoney('18000', undefined), '₦18,000')
  assert.equal(formatMoney(50, '{price} NGN'), '50 NGN')
  assert.equal(formatMoney(null, '₦{price}'), '')
  assert.equal(formatMoney('abc', '₦{price}'), '')
})

test('isVariantAvailable: explicit flag wins, else Shopify fields', () => {
  assert.equal(isVariantAvailable({ available: false, inventory_quantity: 9 }), false)
  assert.equal(isVariantAvailable({ available: true }), true)
  assert.equal(isVariantAvailable({ inventory_management: 'shopify', inventory_policy: 'deny', inventory_quantity: 0 }), false)
  assert.equal(isVariantAvailable({ inventory_management: 'shopify', inventory_policy: 'deny', inventory_quantity: 3 }), true)
  assert.equal(isVariantAvailable({ inventory_management: 'shopify', inventory_policy: 'continue', inventory_quantity: 0 }), true)
  assert.equal(isVariantAvailable({ inventory_management: null }), true)
  assert.equal(isVariantAvailable(null), false)
})

test('realVariants drops Default Title', () => {
  assert.deepEqual(realVariants({ variants: [{ title: 'Default Title' }] }), [])
  assert.equal(realVariants({ variants: [{ title: 'Queen' }, { title: 'King' }] }).length, 2)
  assert.deepEqual(realVariants({}), [])
  assert.deepEqual(realVariants(null), [])
})

test('priceView: single price with real discount', () => {
  const v = priceView({ price: 150000, compare_at_price: 180000, price_label: '₦150,000' }, null, CFG)
  assert.equal(v.priceText, '₦150,000')
  assert.equal(v.wasText, '₦180,000')
  assert.equal(v.pct, 17)
})

test('priceView: no was-price when compare-at is missing, equal or lower', () => {
  for (const cmp of [undefined, null, 150000, 100000]) {
    const v = priceView({ price: 150000, compare_at_price: cmp, price_label: '₦150,000' }, null, CFG)
    assert.equal(v.wasText, '')
    assert.equal(v.pct, null)
  }
})

test('priceView: range when sizes differ, hint to pick one', () => {
  const item = { variants: [{ title: 'Single', price: 90000 }, { title: 'King', price: 190000 }] }
  const v = priceView(item, null, CFG)
  assert.equal(v.priceText, '₦90,000 – ₦190,000')
  assert.ok(v.rangeNote.length > 0)
  assert.equal(v.wasText, '')
})

test('priceView: same-price variants show a plain price, not a range', () => {
  const item = { price: 5000, price_label: '₦5,000', variants: [{ title: 'A', price: 5000 }, { title: 'B', price: 5000 }] }
  const v = priceView(item, null, CFG)
  assert.equal(v.priceText, '₦5,000')
  assert.equal(v.rangeNote, '')
})

test('priceView: selected variant uses its own price and compare-at', () => {
  const item = { price: 90000, compare_at_price: 999999, variants: [] }
  const v = priceView(item, { title: 'Queen', price: 150000, compare_at_price: 180000 }, CFG)
  assert.equal(v.priceText, '₦150,000')
  assert.equal(v.wasText, '₦180,000')
  assert.equal(v.pct, 17)
})

test('priceView: selected variant without compare-at shows no was-price (does not borrow the item one)', () => {
  const item = { price: 90000, compare_at_price: 120000 }
  const v = priceView(item, { title: 'Queen', price: 150000 }, CFG)
  assert.equal(v.wasText, '')
  assert.equal(v.pct, null)
})

test('priceView: price on request hides every number', () => {
  const v = priceView({ price: 100, compare_at_price: 200 }, null, { ...CFG, price_on_request: true })
  assert.equal(v.priceText, 'Price on request')
  assert.equal(v.wasText, '')
  assert.equal(v.pct, null)
})

test('priceView: item with no price at all', () => {
  const v = priceView({ title: 'X' }, null, CFG)
  assert.equal(v.priceText, '')
  assert.equal(priceView(null, null, CFG).priceText, '')
})

test('whatsappOrderLink: encodes, includes size and quantity, null without number', () => {
  const link = whatsappOrderLink('2348031234567', { title: 'Cloud 9 Mattress' }, { title: 'Queen 5/6 ft' }, 2)
  assert.ok(link.startsWith('https://wa.me/2348031234567?text='))
  const text = decodeURIComponent(link.split('text=')[1])
  assert.equal(text, "Hi, I'd like to order 2 x Cloud 9 Mattress (Queen 5/6 ft)")
  assert.equal(decodeURIComponent(whatsappOrderLink('234', { title: 'Pillow' }, null).split('text=')[1]), "Hi, I'd like to order Pillow")
  assert.equal(whatsappOrderLink(null, { title: 'x' }, null), null)
  assert.equal(whatsappOrderLink('234', null, null), null)
})

test('initials', () => {
  assert.equal(initials('Royal Rest'), 'RR')
  assert.equal(initials('Acme'), 'A')
  assert.equal(initials('  one two three '), 'OT')
  assert.equal(initials(''), '')
  assert.equal(initials(null), '')
})

test('relatedItems: excludes current, shared tags first, capped', () => {
  const cur = { slug: 'a', tags: { type: 'Mattress' } }
  const items = [
    { slug: 'a', tags: { type: 'Mattress' } },
    { slug: 'p1', tags: { type: 'Pillow' } },
    { slug: 'm1', tags: { type: 'Mattress' } },
    { slug: 'p2', tags: { type: ['Pillow'] } },
    { slug: 'm2', tags: { type: ['Mattress'] } },
    { slug: 'x' },
  ]
  const out = relatedItems(items, cur, 4).map((i) => i.slug)
  assert.deepEqual(out, ['m1', 'm2', 'p1', 'p2'])
  assert.ok(!out.includes('a'))
  assert.deepEqual(relatedItems([], cur), [])
  assert.deepEqual(relatedItems(null, cur), [])
  assert.equal(relatedItems(items, cur, 2).length, 2)
})

test('trustPoints: clean, capped at 3, never invented', () => {
  assert.deepEqual(trustPoints({ trust_points: ['A', ' ', 'B', 'C', 'D'] }), ['A', 'B', 'C'])
  assert.deepEqual(trustPoints({}), [])
  assert.deepEqual(trustPoints(null), [])
  assert.deepEqual(trustPoints({ trust_points: 'x' }), [])
})
