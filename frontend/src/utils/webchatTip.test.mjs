import assert from 'node:assert/strict'
import { firstSentVisitorId, showTipFor, tipSeen, markTipSeen, TIP_KEY } from './webchatTip.js'

const bot = { id: 'b1', role: 'bot' }
const sending = { id: 't1', role: 'visitor', tmp: true }
const v1 = { id: 'v1', role: 'visitor' }
const v2 = { id: 'v2', role: 'visitor' }
assert.equal(firstSentVisitorId([]), null)
assert.equal(firstSentVisitorId(null), null)
assert.equal(firstSentVisitorId([bot]), null)
assert.equal(firstSentVisitorId([bot, sending]), null)                       // still sending: no tip yet
assert.equal(firstSentVisitorId([bot, sending, v1, v2]), 'v1')
assert.equal(firstSentVisitorId([{ ...v1, deleted: true }, v2]), 'v2')
assert.equal(firstSentVisitorId([{ ...v1, attachment: { uploading: true } }, v2]), 'v2')
const msgs = [bot, v1, v2]
assert.equal(showTipFor('v1', { messages: msgs, seen: false, menuOpen: false }), true)
assert.equal(showTipFor('v2', { messages: msgs, seen: false, menuOpen: false }), false)    // only under the first one
assert.equal(showTipFor('v1', { messages: msgs, seen: true, menuOpen: false }), false)      // dismissed
assert.equal(showTipFor('v1', { messages: msgs, seen: false, menuOpen: true }), false)      // options already open: they found it
assert.equal(showTipFor(null, { messages: msgs, seen: false, menuOpen: false }), false)
const store = (() => { const d = {}; return { getItem: (k) => d[k] ?? null, setItem: (k, v) => { d[k] = v } } })()
assert.equal(tipSeen(store), false); markTipSeen(store); assert.equal(tipSeen(store), true); assert.equal(store.getItem(TIP_KEY), '1')
assert.equal(tipSeen({ getItem() { throw new Error('blocked') } }), false)                // storage blocked: does not crash
markTipSeen({ setItem() { throw new Error('blocked') } })
console.log('webchatTip: all tests passed')
