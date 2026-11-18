import assert from 'node:assert/strict'
import { heldAskIds, withoutHeld, HOLD_MS } from './webchatReveal.js'

const v = { id: 'v', role: 'visitor', text: 'how much' }
const a = { id: 'a', role: 'bot', text: 'answer' }
const q = { id: 'q', role: 'bot', text: 'first name?' }
assert.deepEqual(heldAskIds({ messages: [v, a, q], contact_step: 'name' }), ['q'])          // answer + question: hold the question
assert.deepEqual(heldAskIds({ messages: [v, a, q] }), [])                                    // no details script open
assert.deepEqual(heldAskIds({ messages: [v, q], contact_step: 'name' }), [])                 // the question alone (e.g. a button): nothing to separate it from
assert.deepEqual(heldAskIds({ messages: [v, a, { role: 'bot', text: 'no id' }], contact_step: 'name' }), [])
assert.deepEqual(heldAskIds(null), [])
assert.deepEqual(heldAskIds({}), [])
assert.equal(withoutHeld([v, a, q], new Set(['q'])).length, 2)
assert.equal(withoutHeld([v, a, q], new Set()).length, 3)
assert.equal(withoutHeld([v, a, q], null).length, 3)
assert.ok(HOLD_MS >= 800 && HOLD_MS <= 1500)
console.log('webchatReveal: all tests passed')
