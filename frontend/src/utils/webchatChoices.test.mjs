import assert from 'node:assert/strict'
import { choicesFromReply, visibleChoices } from './webchatChoices.js'

const msgs = [{ id: 'v1', role: 'visitor', text: 'hi' }, { id: 'b1', role: 'bot', text: 'unable' }]
const items = [{ id: 'menu', label: 'Open menu' }, { id: 'human', label: 'Leave a message' }, { id: 'call', label: 'Request a call back' }]

// choicesFromReply
assert.equal(choicesFromReply(null), null)
assert.equal(choicesFromReply({}), null)
assert.equal(choicesFromReply({ messages: msgs }), null)
assert.equal(choicesFromReply({ messages: msgs, choices: [] }), null)
assert.equal(choicesFromReply({ messages: [msgs[0]], choices: items }), null)                 // no bot message to attach to
assert.deepEqual(choicesFromReply({ messages: msgs, choices: items }), { mid: 'b1', items })
assert.deepEqual(choicesFromReply({ messages: [...msgs, { id: 'b2', role: 'bot', text: 'x' }], choices: items }).mid, 'b2')   // the last bot message
assert.deepEqual(choicesFromReply({ messages: msgs, choices: [{ id: 'evil', label: 'x' }, { id: 'menu', label: '  ' }, null, { id: 'menu', label: ' Open menu ' }] }).items,
  [{ id: 'menu', label: 'Open menu' }])
assert.equal(choicesFromReply({ messages: msgs, choices: [{ id: 'menu', label: 'A'.repeat(100) }] }).items[0].label.length, 40)

// visibleChoices
const ch = { mid: 'b1', items }
const on = { hasHumanItem: true, humanActive: false, callOn: true }
const ids = (x) => x.map((c) => c.id)
assert.deepEqual(ids(visibleChoices(ch, msgs[1], true, on)), ['menu', 'human', 'call'])
assert.deepEqual(visibleChoices(ch, msgs[1], false, on), [])                                       // not the last message any more
assert.deepEqual(visibleChoices(ch, { id: 'b9', role: 'bot' }, true, on), [])                      // a different message
assert.deepEqual(visibleChoices(null, msgs[1], true, on), [])
assert.deepEqual(ids(visibleChoices(ch, msgs[1], true, { ...on, humanActive: true })), ['menu', 'call'])      // a person already took over
assert.deepEqual(ids(visibleChoices(ch, msgs[1], true, { ...on, hasHumanItem: false })), ['menu', 'call'])
assert.deepEqual(ids(visibleChoices(ch, msgs[1], true, { ...on, callOn: false })), ['menu', 'human'])
console.log('webchatChoices: all tests passed')

// HUMAN-OFFER-1: topic buttons carry a menu_id; bad ids are dropped
const offer = choicesFromReply({ messages: msgs, choices: [{ id: 'item', menu_id: 'hours', label: 'Opening hours' }, { id: 'item', menu_id: '../x', label: 'Bad' }, { id: 'item', label: 'None' }, { id: 'human', label: 'No, connect me to the team' }] })
assert.deepEqual(offer.items, [{ id: 'item', label: 'Opening hours', menu_id: 'hours' }, { id: 'human', label: 'No, connect me to the team' }])
console.log('ok')
