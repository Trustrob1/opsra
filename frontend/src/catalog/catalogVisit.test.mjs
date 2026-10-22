import test from 'node:test'
import assert from 'node:assert/strict'
import { trackVisitOnce, visitKey } from './catalogVisit.js'

const mem = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) } }

test('sends once per store and tag per session', () => {
  const storage = mem(), sent = []
  const send = (s, t) => { sent.push([s, t]); return Promise.resolve() }
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: 'instagram', storage, send }), true)
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: 'instagram', storage, send }), false)
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: 'flyer', storage, send }), true)
  assert.equal(trackVisitOnce({ orgSlug: 'other', tag: 'instagram', storage, send }), true)
  assert.deepEqual(sent, [['rr', 'instagram'], ['rr', 'flyer'], ['other', 'instagram']])
  assert.equal(visitKey('rr', 'flyer'), 'cv_rr_flyer')
})

test('no tag or no store sends nothing', () => {
  const sent = []
  const send = () => { sent.push(1) }
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: null, storage: mem(), send }), false)
  assert.equal(trackVisitOnce({ orgSlug: '', tag: 'ig', storage: mem(), send }), false)
  assert.equal(sent.length, 0)
})

test('blocked storage and a failing sender never throw', () => {
  const blocked = { getItem() { throw new Error('no') }, setItem() { throw new Error('no') } }
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: 'ig', storage: blocked, send: () => Promise.reject(new Error('x')) }), true)
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: 'ig', storage: mem(), send: () => { throw new Error('x') } }), true)
  assert.equal(trackVisitOnce({ orgSlug: 'rr', tag: 'ig', storage: null, send: () => {} }), true)
})
