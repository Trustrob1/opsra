import test from 'node:test'
import assert from 'node:assert/strict'
import { PRICE_STYLES, priceStyleOf, nextButtonId } from './catalogConfigLogic.js'

test('each price style maps back to itself', () => {
  for (const p of PRICE_STYLES) assert.equal(priceStyleOf(p.template), p.id)
  assert.deepEqual(PRICE_STYLES.map((p) => p.template), ['₦{price}', '₦ {price}', '{price} NGN'])
})

test('a hand-written format is "custom", never silently replaced', () => {
  assert.equal(priceStyleOf('NGN {price} only'), 'custom')
  assert.equal(priceStyleOf(''), 'custom')
  assert.equal(priceStyleOf(undefined), 'custom')
})

test('new button ids are made for the owner and never repeat', () => {
  assert.equal(nextButtonId([]), 'cta_1')
  assert.equal(nextButtonId([{ id: 'cta_1' }, { id: 'cta_2' }]), 'cta_3')
  assert.equal(nextButtonId([{ id: 'cta_3' }, { id: 'showroom' }]), 'cta_4')
  assert.equal(nextButtonId([{ id: 'cta_3' }, { id: 'cta_2' }]), 'cta_4')
  assert.equal(nextButtonId(null), 'cta_1')
})
