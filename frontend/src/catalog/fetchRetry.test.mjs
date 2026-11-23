// LOAD-RETRY-1 tests. Run with: node --test frontend/src/catalog/fetchRetry.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldRetry, withRetry, fetchWithTimeout, REQUEST_TIMEOUT_MS, SLOW_AFTER_MS } from './fetchRetry.js'

const noSleep = () => Promise.resolve()

test('shouldRetry: network errors, 5xx and 429 yes; 404 and other 4xx no', () => {
  assert.equal(shouldRetry(new Error('Failed to fetch')), true)
  assert.equal(shouldRetry(Object.assign(new Error('x'), { status: 503 })), true)
  assert.equal(shouldRetry(Object.assign(new Error('x'), { status: 429 })), true)
  assert.equal(shouldRetry(Object.assign(new Error('x'), { status: 404 })), false)
  assert.equal(shouldRetry(Object.assign(new Error('x'), { status: 401 })), false)
  assert.equal(shouldRetry(null), false)
})

test('withRetry: succeeds on the third try and waits between tries', async () => {
  let n = 0; const waits = []
  const out = await withRetry(async () => { n++; if (n < 3) throw new Error('down'); return 'ok' }, { delays: [5, 9], sleep: (ms) => { waits.push(ms); return Promise.resolve() } })
  assert.equal(out, 'ok'); assert.equal(n, 3); assert.deepEqual(waits, [5, 9])
})

test('withRetry: gives up after the last delay with the last error', async () => {
  let n = 0
  await assert.rejects(withRetry(async () => { n++; throw new Error('still down') }, { delays: [1, 1], sleep: noSleep }), /still down/)
  assert.equal(n, 3)
})

test('withRetry: a 404 is not retried', async () => {
  let n = 0
  await assert.rejects(withRetry(async () => { n++; throw Object.assign(new Error('nf'), { status: 404 }) }, { delays: [1, 1], sleep: noSleep }))
  assert.equal(n, 1)
})

test('fetchWithTimeout: aborts a request that never answers', async () => {
  const never = (url, opts) => new Promise((_, rej) => opts.signal.addEventListener('abort', () => rej(new Error('aborted'))))
  await assert.rejects(fetchWithTimeout('https://x.test', {}, 20, never), /aborted/)
})

test('fetchWithTimeout: passes a fast answer through', async () => {
  const r = await fetchWithTimeout('https://x.test', {}, 50, async () => ({ ok: true, tag: 'fast' }))
  assert.equal(r.tag, 'fast')
})

test('timings: a try gives up before the slow message is far off', () => {
  assert.ok(SLOW_AFTER_MS < REQUEST_TIMEOUT_MS)
})
