// WEBCHAT-CATALOG-1 tests. Run with: node --test frontend/src/catalog/storefront/storefrontChat.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { canShowChat, cleanProductId, chatSrc, viewingMessage } from './storefrontChat.js'

test('canShowChat: only a real chat key', () => {
  assert.equal(canShowChat({ key: 'wc_abcdefgh12' }), true)
  assert.equal(canShowChat({ key: 'abc' }), false)
  assert.equal(canShowChat({ key: 'wc_../evil' }), false)
  assert.equal(canShowChat({}), false)
  assert.equal(canShowChat(null), false)
})

test('cleanProductId: uuids pass, odd values are dropped', () => {
  assert.equal(cleanProductId('3f2b8c1e-9d4a-4b7e-8c21-5a6d7e8f9a0b'), '3f2b8c1e-9d4a-4b7e-8c21-5a6d7e8f9a0b')
  assert.equal(cleanProductId(' abc '), 'abc')
  assert.equal(cleanProductId('a b'), '')
  assert.equal(cleanProductId('x&y=1'), '')
  assert.equal(cleanProductId('x'.repeat(61)), '')
  assert.equal(cleanProductId(null), '')
})

test('chatSrc: embedded, tagged as catalog, product only when valid', () => {
  assert.equal(chatSrc('wc_abcdefgh12', null), '/c/wc_abcdefgh12?embed=1&s=catalog')
  assert.equal(chatSrc('wc_abcdefgh12', 'p-1'), '/c/wc_abcdefgh12?embed=1&s=catalog&p=p-1')
  assert.equal(chatSrc('wc_abcdefgh12', 'bad id'), '/c/wc_abcdefgh12?embed=1&s=catalog')
})

test('viewingMessage: only for a valid product', () => {
  assert.deepEqual(viewingMessage('p-1'), { source: 'opsra-catalog', type: 'viewing', product: 'p-1' })
  assert.equal(viewingMessage(''), null)
  assert.equal(viewingMessage('a b'), null)
})

import { greetingText, greetedKey, helloWord } from './storefrontChat.js'

test('greetingText (CHIOMA-VOICE-1): a warm, time-aware welcome that fits any business', () => {
  assert.equal(greetingText('Royal Rest', 'Holiday Sleep Mattress'), 'Any questions about the Holiday Sleep Mattress? I’m happy to help.')
  assert.equal(greetingText('Royal Rest', 'The Big Bed'), 'Any questions about the Big Bed? I’m happy to help.')
  assert.equal(greetingText('Royal Rest', '', { hour: 9, goal: 'a new mattress' }), 'Good morning, welcome to Royal Rest! Looking for a new mattress, or just browsing?')
  assert.equal(greetingText('Glow Salon', '', { hour: 14 }), 'Good afternoon, welcome to Glow Salon! Looking for something, or just browsing?')
  assert.equal(greetingText('', null, { hour: 20 }), 'Good evening, welcome! Looking for something, or just browsing?')
  assert.equal(greetingText('Glow Salon', '', { hour: 2 }), 'Hello, welcome to Glow Salon! Looking for something, or just browsing?')
  assert.equal(greetingText('Glow Salon', '', { returning: true }), 'Welcome back to Glow Salon! 😊 Anything I can help you with today?')
  assert.ok(greetingText('X', 'A'.repeat(80)).includes('…'))
  assert.equal(greetingText('X', '  Big   Bed  '), 'Any questions about the Big Bed? I’m happy to help.')
  for (const w of ['Chioma. Ask me anything', 'virtual assistant']) assert.ok(!greetingText('X', '', { hour: 9 }).includes(w))
})

test('helloWord: morning, afternoon, evening, and a plain hello in the small hours', () => {
  assert.deepEqual([4, 5, 11, 12, 16, 17, 23, 0].map(helloWord), ['Hello', 'Good morning', 'Good morning', 'Good afternoon', 'Good afternoon', 'Good evening', 'Good evening', 'Hello'])
})

test('widget.js chiomaGreeting matches the storefront greeting', async () => {
  const fs = await import('node:fs')
  const src = fs.readFileSync(new URL('../../../public/widget.js', import.meta.url), 'utf8')
  const body = src.slice(src.indexOf('function chiomaGreeting'), src.indexOf('\n  }\n', src.indexOf('function chiomaGreeting')) + 4)
  const fn = new Function(`${body}; return chiomaGreeting`)()
  for (const [o, title, opts] of [['Royal Rest', '', { hour: 9, goal: 'a new mattress' }], ['Glow Salon', '', { hour: 15 }], ['Glow Salon', 'The Gel Polish', {}], ['Glow Salon', '', { returning: true }]]) {
    assert.equal(fn({ name: o, product: title, goal: opts.goal, hour: opts.hour, returning: opts.returning }), greetingText(o, title, opts))
  }
  assert.equal(fn({ name: 'X', hint: 'cart', hour: 9 }), 'Need a hand with your order? I’m right here.')
  assert.ok(!src.includes('online now'))
})

test('greetedKey: one per product per chat', () => {
  assert.equal(greetedKey('wc_abcdefgh12', 'p1'), 'opsra_chioma_greeted_wc_abcdefgh12_p1')
  assert.equal(greetedKey('wc_abcdefgh12', ''), 'opsra_chioma_greeted_wc_abcdefgh12_home')
})

// STORE-CHIOMA-1
import { cleanVariantId, buyMessage, CHIOMA_EVENT, askChioma } from './storefrontChat.js'

test('chatSrc: carries a buy request only with a clean product id', () => {
  assert.equal(chatSrc('wc_abcdefgh12', 'p1', { product: 'p1', variant: 'v-2' }), '/c/wc_abcdefgh12?embed=1&s=catalog&p=p1&b=p1&bv=v-2')
  assert.equal(chatSrc('wc_abcdefgh12', 'p1', { product: 'p1' }), '/c/wc_abcdefgh12?embed=1&s=catalog&p=p1&b=p1')
  assert.equal(chatSrc('wc_abcdefgh12', 'p1', { product: 'bad id&x=1', variant: 'v' }), '/c/wc_abcdefgh12?embed=1&s=catalog&p=p1')
  assert.equal(chatSrc('wc_abcdefgh12', 'p1', { product: 'p1', variant: 'a&b=c' }), '/c/wc_abcdefgh12?embed=1&s=catalog&p=p1&b=p1')
})

test('cleanVariantId and buyMessage', () => {
  assert.equal(cleanVariantId('abc-1_2'), 'abc-1_2')
  assert.equal(cleanVariantId('a b'), '')
  assert.equal(cleanVariantId(null), '')
  assert.deepEqual(buyMessage('p1', 'v1'), { source: 'opsra-catalog', type: 'buy', product: 'p1', variant: 'v1' })
  assert.deepEqual(buyMessage('p1', '<x>'), { source: 'opsra-catalog', type: 'buy', product: 'p1', variant: '' })
  assert.equal(buyMessage('', 'v1'), null)
})

test('askChioma sends one window event, and never throws without a window', () => {
  assert.equal(CHIOMA_EVENT, 'opsra-chioma')
  assert.doesNotThrow(() => askChioma({ action: 'open' }))
  const seen = []
  globalThis.window = { dispatchEvent: (e) => { seen.push(e); return true } }
  globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o.detail } }
  askChioma({ action: 'buy', product: 'p1' })
  delete globalThis.window; delete globalThis.CustomEvent
  assert.equal(seen.length, 1)
  assert.equal(seen[0].type, 'opsra-chioma')
  assert.deepEqual(seen[0].detail, { action: 'buy', product: 'p1' })
})
