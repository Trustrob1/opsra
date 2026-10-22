// STORE-4 tests. Run with: node --test frontend/src/catalog/storefront/storefrontCart.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  cleanSource, normaliseCart, cartVariantId, canUseCart, decorateLines, moneyText, validateContact,
  cartErrorText, askedForContact, isSessionExpired, safePayUrl, EMPTY_CART,
} from './storefrontCart.js'

test('cleanSource: safe tags only, lowercase, ?s= also accepted', () => {
  assert.equal(cleanSource('?src=Instagram'), 'instagram')
  assert.equal(cleanSource('?s=flyer_2'), 'flyer_2')
  assert.equal(cleanSource('?src=a b'), null)
  assert.equal(cleanSource('?src=<x>'), null)
  assert.equal(cleanSource('?src=' + 'a'.repeat(31)), null)
  assert.equal(cleanSource('?src=' + 'a'.repeat(30)), 'a'.repeat(30))
  assert.equal(cleanSource(''), null)
  assert.equal(cleanSource(undefined), null)
  assert.equal(cleanSource('?src=x&s=y'), 'x')
})

test('normaliseCart: tolerates junk, caps quantity, drops empty lines', () => {
  assert.deepEqual(normaliseCart(null), EMPTY_CART)
  assert.deepEqual(normaliseCart({ items: 'x' }), EMPTY_CART)
  const c = normaliseCart({ items: [
    { pid: 1, vid: 'v1', name: 'Bed', price: '150000', qty: 2 },
    { pid: 2, vid: null, name: 'Pillow', price: 18000, qty: 99 },
    { pid: 3, name: 'Gone', price: 5, qty: 0 },
    null, { name: 'no pid', qty: 1 },
  ], total: 336000 })
  assert.equal(c.items.length, 2)
  assert.equal(c.items[1].qty, 10)
  assert.equal(c.count, 12)
  assert.equal(c.total, 336000)
  assert.equal(c.items[0].pid, '1')
  assert.equal(c.items[1].vid, null)
})

test('normaliseCart: total falls back to the lines', () => {
  assert.equal(normaliseCart({ items: [{ pid: 'a', price: 100, qty: 3 }] }).total, 300)
})

test('cartVariantId: chosen option wins; default option is used when no sizes; none when no ids', () => {
  const sized = { variants: [{ id: 11, title: 'Single' }, { id: 12, title: 'Queen' }] }
  assert.equal(cartVariantId(sized, sized.variants[1]), '12')
  const plain = { variants: [{ id: 'dflt', title: 'Default Title' }] }
  assert.equal(cartVariantId(plain, null), 'dflt')
  assert.equal(cartVariantId({ variants: [{ title: 'x' }] }, null), null)
  assert.equal(cartVariantId({ variants: [] }, null), null)
  assert.equal(cartVariantId({}, null), null)
  assert.equal(cartVariantId(sized, { variant_id: 'z' }), 'z')
  assert.equal(cartVariantId(sized, { title: 'no id' }), null)
})

test('canUseCart: needs shop key and a visible price', () => {
  assert.equal(canUseCart({ key: 'wc_x' }, {}), true)
  assert.equal(canUseCart(null, {}), false)
  assert.equal(canUseCart({}, {}), false)
  assert.equal(canUseCart({ key: 'wc_x' }, { price_on_request: true }), false)
})

test('decorateLines: adds photo, slug and line total', () => {
  const items = [{ id: 'p1', slug: 'cloud', catalog_images: ['https://i/x.jpg'] }]
  const lines = decorateLines({ items: [{ pid: 'p1', vid: 'v', name: 'Cloud', price: 100, qty: 3 }, { pid: 'p9', vid: null, name: 'Other', price: 5, qty: 1 }] }, items)
  assert.equal(lines[0].image, 'https://i/x.jpg')
  assert.equal(lines[0].slug, 'cloud')
  assert.equal(lines[0].lineTotal, 300)
  assert.equal(lines[1].image, '')
  assert.equal(lines[1].slug, null)
  assert.notEqual(lines[0].key, lines[1].key)
  assert.deepEqual(decorateLines(null, null), [])
})

test('moneyText', () => {
  assert.equal(moneyText(168000, '₦{price}'), '₦168,000')
  assert.equal(moneyText(0, '₦{price}'), '₦0')
  assert.equal(moneyText(NaN, null), '₦0')
})

test('validateContact', () => {
  const ok = { name: ' Ada Obi ', phone: '0803 123 4567', email: '', consent: true }
  const r = validateContact(ok)
  assert.deepEqual(r.payload, { name: 'Ada Obi', phone: '0803 123 4567', email: null, consent: true, website: '' })
  assert.match(validateContact({ ...ok, name: 'A' }).error, /name/)
  assert.match(validateContact({ ...ok, phone: '', email: '' }).error, /WhatsApp number or an email/)
  assert.match(validateContact({ ...ok, phone: '12' }).error, /number/)
  assert.match(validateContact({ ...ok, phone: '', email: 'nope' }).error, /email/)
  assert.match(validateContact({ ...ok, consent: false }).error, /tick the box/)
  assert.ok(validateContact({ name: 'Ada', phone: '', email: 'a@b.co', consent: true }).payload)
  assert.equal(validateContact(null).error.length > 0, true)
})

test('error helpers', () => {
  assert.equal(cartErrorText({ response: { data: { detail: { message: 'Out of stock' } } } }), 'Out of stock')
  assert.equal(cartErrorText({ response: { data: { detail: 'Plain' } } }), 'Plain')
  assert.match(cartErrorText({ response: { status: 429, data: {} } }), /Too many/)
  assert.equal(cartErrorText(new Error('boom'), 'fallback'), 'fallback')
  assert.equal(askedForContact({ response: { data: { detail: { ask_contact: true } } } }), true)
  assert.equal(askedForContact({ response: { data: { detail: { message: 'x' } } } }), false)
  assert.equal(askedForContact(null), false)
  assert.equal(isSessionExpired({ response: { status: 401 } }), true)
  assert.equal(isSessionExpired({ response: { status: 422 } }), false)
})

test('safePayUrl: https only', () => {
  assert.equal(safePayUrl('https://checkout.paystack.com/abc'), 'https://checkout.paystack.com/abc')
  assert.equal(safePayUrl('http://x.com'), null)
  assert.equal(safePayUrl('javascript:alert(1)'), null)
  assert.equal(safePayUrl(''), null)
  assert.equal(safePayUrl(null), null)
  assert.equal(safePayUrl('https://a b'), null)
})

test('catalogPathFromShort: /shop/ becomes /catalog/, anything else is left alone', async () => {
  const { catalogPathFromShort } = await import('./storefrontCart.js')
  assert.equal(catalogPathFromShort('/shop/royal-rest'), '/catalog/royal-rest')
  assert.equal(catalogPathFromShort('/shop/royal-rest/cloud-9'), '/catalog/royal-rest/cloud-9')
  assert.equal(catalogPathFromShort('/shop/royal-rest/'), '/catalog/royal-rest')
  assert.equal(catalogPathFromShort('/shop'), null)
  assert.equal(catalogPathFromShort('/shop/'), null)
  assert.equal(catalogPathFromShort('/catalog/royal-rest'), null)
  assert.equal(catalogPathFromShort('/shopping/x'), null)
  assert.equal(catalogPathFromShort(''), null)
  assert.equal(catalogPathFromShort(undefined), null)
})
