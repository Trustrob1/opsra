import assert from 'node:assert/strict'
import { headerState } from './webchatHeader.js'

const base = { businessName: 'Acme', teamAvailable: false, online: true, reopens: 'tomorrow at 8:00 am' }
// normal chat with Chioma
let h = headerState({ ...base, human: false })
assert.equal(h.withTeam, false); assert.equal(h.subtitle, 'Virtual assistant for Acme')
// handed over after hours, nobody has replied: Chioma stays, subtitle says when the team is back
h = headerState({ ...base, human: true, hasRepReply: false, repTyping: false })
assert.equal(h.withTeam, false); assert.equal(h.subtitle, 'The team is back tomorrow at 8:00 am')
// handed over while the team is online, nobody has replied yet
h = headerState({ ...base, human: true, teamAvailable: true })
assert.equal(h.withTeam, false); assert.equal(h.subtitle, 'The team is online now and will reply here')
// handed over, no business hours set: plain Chioma subtitle
h = headerState({ ...base, human: true, reopens: '' })
assert.equal(h.subtitle, 'Virtual assistant for Acme')
// a team member replied: the team takes the header
h = headerState({ ...base, human: true, hasRepReply: true, teamAvailable: true })
assert.equal(h.withTeam, true); assert.equal(h.subtitle, null); assert.equal(h.dotOn, true)
// a team member is typing
assert.equal(headerState({ ...base, human: true, repTyping: true }).withTeam, true)
// a rep replied earlier but the bot is back (human false): Chioma again
assert.equal(headerState({ ...base, human: false, hasRepReply: true }).withTeam, false)
console.log('webchatHeader: all tests passed')
