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
