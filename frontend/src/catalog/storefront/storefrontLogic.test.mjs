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

// ---------------------------------------------------------------- STORE-3
import {
  coverUrl, tagValues, categoryNames, categoryChips, otherFilterDims, matchesSearch, filterItems, cardView, readUrlState, listUrl,
} from './storefrontLogic.js'

const DIMS = [
  { key: 'category', label: 'Category', type: 'multi_select', filterable: true, options: ['Mattresses', 'Pillows', 'Empty cat'] },
  { key: 'mattress_feel', label: 'Mattress Feel', type: 'multi_select', filterable: true, options: ['Soft', 'Firm'] },
  { key: 'sizes', label: 'Sizes', type: 'multi_select', filterable: true, options: ['Queen', 'King'] },
  { key: 'hidden', label: 'Hidden', type: 'multi_select', filterable: false, options: ['x'] },
  { key: 'noopts', label: 'No options', type: 'multi_select', filterable: true, options: [] },
]
const LCFG = { ...CFG, tag_dimensions: DIMS, availability_labels: { unavailable: 'Sold out' } }
const ITEMS = [
  { id: 1, slug: 'a', title: 'Cloud 9', description: 'Back support', price: 150000, compare_at_price: 180000, price_label: '₦150,000', available: true,
    catalog_images: ['https://x/a.jpg'], tags: { category: ['Mattresses'], mattress_feel: ['Firm'], sizes: ['Queen', 'King'] } },
  { id: 2, slug: 'b', title: 'Memory Pillow', description: 'Cool', price: 18000, price_label: '₦18,000', available: false,
    catalog_images: [{ url: 'https://x/b.jpg' }], tags: { category: ['Pillows'], mattress_feel: 'Soft' } },
  { id: 3, slug: 'c', title: 'Plain', price: 5000, price_label: '₦5,000', tags: {} },
]

test('coverUrl: string, object, none', () => {
  assert.equal(coverUrl(ITEMS[0]), 'https://x/a.jpg')
  assert.equal(coverUrl(ITEMS[1]), 'https://x/b.jpg')
  assert.equal(coverUrl(ITEMS[2]), '')
  assert.equal(coverUrl(null), '')
})

test('tagValues: list, single, missing, odd', () => {
  assert.deepEqual(tagValues(ITEMS[0], 'sizes'), ['Queen', 'King'])
  assert.deepEqual(tagValues(ITEMS[1], 'mattress_feel'), ['Soft'])
  assert.deepEqual(tagValues(ITEMS[2], 'sizes'), [])
  assert.deepEqual(tagValues({ tags: 'junk' }, 'x'), [])
  assert.deepEqual(tagValues(null, 'x'), [])
})

test('categoryNames in the owner order; none when absent', () => {
  assert.deepEqual(categoryNames(LCFG), ['Mattresses', 'Pillows', 'Empty cat'])
  assert.deepEqual(categoryNames({}), [])
  assert.deepEqual(categoryNames(null), [])
})

test('categoryChips: only categories with products, counts, owner order', () => {
  assert.deepEqual(categoryChips(ITEMS, LCFG, { show_categories: true }), [{ name: 'Mattresses', count: 1 }, { name: 'Pillows', count: 1 }])
})

test('categoryChips: menu switched off or no style object', () => {
  assert.deepEqual(categoryChips(ITEMS, LCFG, { show_categories: false }), [])
  assert.equal(categoryChips(ITEMS, LCFG, null).length, 2)
  assert.deepEqual(categoryChips([], LCFG, null), [])
})

test('otherFilterDims: filterable, not category, with options', () => {
  assert.deepEqual(otherFilterDims(LCFG).map((d) => d.key), ['mattress_feel', 'sizes'])
})

test('matchesSearch: title and description, ignores capitals and blanks', () => {
  assert.equal(matchesSearch(ITEMS[0], 'CLOUD'), true)
  assert.equal(matchesSearch(ITEMS[0], 'support'), true)
  assert.equal(matchesSearch(ITEMS[0], 'pillow'), false)
  assert.equal(matchesSearch(ITEMS[0], '   '), true)
  assert.equal(matchesSearch({}, 'x'), false)
})

test('filterItems: category, list tag, single tag (ignoring capitals), combined, empty filter ignored', () => {
  const ids = (f) => filterItems(ITEMS, f).map((i) => i.id)
  assert.deepEqual(ids({ filters: { category: 'Pillows' } }), [2])
  assert.deepEqual(ids({ filters: { sizes: 'King' } }), [1])
  assert.deepEqual(ids({ filters: { sizes: 'Queen', category: 'Pillows' } }), [])
  assert.deepEqual(ids({ filters: { mattress_feel: 'soft' } }), [2])
  assert.deepEqual(ids({ filters: { mattress_feel: 'soft' }, search: 'pillow' }), [2])
  assert.deepEqual(ids({ filters: { category: '' } }), [1, 2, 3])
  assert.deepEqual(ids({}), [1, 2, 3])
  assert.deepEqual(ids({ search: 'zzz' }), [])
  assert.deepEqual(filterItems(null, {}), [])
})

test('filterItems: a list tag needs an exact member (not a substring)', () => {
  assert.deepEqual(filterItems(ITEMS, { filters: { sizes: 'Quee' } }), [])
})

test('cardView: discount, sold-out, note, cover', () => {
  const a = cardView(ITEMS[0], LCFG)
  assert.equal(a.priceText, '₦150,000'); assert.equal(a.wasText, '₦180,000'); assert.equal(a.pct, 17)
  assert.equal(a.soldOut, false); assert.equal(a.note, 'Firm'); assert.equal(a.cover, 'https://x/a.jpg')
  const b = cardView(ITEMS[1], LCFG)
  assert.equal(b.soldOut, true); assert.equal(b.wasText, ''); assert.equal(b.pct, null); assert.equal(b.note, 'Soft')
  const c = cardView(ITEMS[2], LCFG)
  assert.equal(c.note, ''); assert.equal(c.cover, '')
})

test('cardView: price on request hides price and discount', () => {
  const v = cardView(ITEMS[0], { ...LCFG, price_on_request: true })
  assert.equal(v.priceText, 'Price on request'); assert.equal(v.wasText, ''); assert.equal(v.pct, null)
})

test('readUrlState: valid category (any capitals), size, junk ignored', () => {
  assert.deepEqual(readUrlState('?category=pillows', LCFG), { category: 'Pillows' })
  assert.deepEqual(readUrlState('?category=Nope', LCFG), {})
  assert.deepEqual(readUrlState('?sizes=Queen&src=qr', LCFG), { sizes: 'Queen' })
  assert.deepEqual(readUrlState('', LCFG), {})
  assert.deepEqual(readUrlState(null, LCFG), {})
})

test('listUrl: category added, other query values kept, variant dropped', () => {
  assert.equal(listUrl('royal-rest', 'Pillows', ''), '/catalog/royal-rest?category=Pillows')
  assert.equal(listUrl('royal-rest', null, '?src=qr&category=Old'), '/catalog/royal-rest?src=qr')
  assert.equal(listUrl('royal-rest', 'Back pain care', '?src=qr&variant=9'), '/catalog/royal-rest?src=qr&category=Back+pain+care')
  assert.equal(listUrl('royal-rest', null, ''), '/catalog/royal-rest')
})

// ── STORE-8 quick add ───────────────────────────────────────────────────────
import { quickAddState } from './storefrontLogic.js'

test('quickAddState: add / choose / none', () => {
  const on = { cartOn: true, config: {} }
  const plain = { price: 5000, available: true, variants: [{ id: 9, title: 'Default Title' }] }
  assert.equal(quickAddState(plain, on), 'add')
  assert.equal(quickAddState({ price: 5000 }, on), 'add')                                       // no options stored at all
  assert.equal(quickAddState({ price: 5000, variants: [{ id: 1, title: 'Queen' }] }, on), 'choose')
  assert.equal(quickAddState(plain, { cartOn: false, config: {} }), null)                       // cart off
  assert.equal(quickAddState(plain, { cartOn: true, config: { price_on_request: true } }), null)
  assert.equal(quickAddState({ ...plain, available: false }, on), null)                         // sold out
  assert.equal(quickAddState({ price: 0 }, on), null)
  assert.equal(quickAddState({ price: null }, on), null)
  assert.equal(quickAddState({ price: 5000, variants: [{ id: 9, title: 'Default Title', available: false }] }, on), null)
  assert.equal(quickAddState(null, on), null)
  assert.equal(quickAddState(plain), null)
})
