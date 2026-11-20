import assert from 'node:assert/strict'
import { buildCalendar, dayKeyOf, dayTitle } from './bookingCalendar.js'

const tz = 'Africa/Lagos'   // UTC+1
const slots = ['2026-11-21T08:00:00Z', '2026-11-21T08:30:00Z', '2026-11-30T23:30:00Z', '2026-12-02T09:00:00Z']
const c = buildCalendar(slots, tz)

// 23:30Z on 30 Nov is 00:30 on 1 Dec in Lagos
assert.equal(dayKeyOf('2026-11-30T23:30:00Z', tz), '2026-12-01')
assert.deepEqual(c.dayKeys, ['2026-11-21', '2026-12-01', '2026-12-02'])
assert.deepEqual(c.months.map((m) => m.key), ['2026-11', '2026-12'])
assert.equal(c.months[0].label, 'November 2026')

// 1 Nov 2026 is a Sunday, Monday-first grid => 6 blank cells before it
const nov = c.months[0].cells
assert.equal(nov.slice(0, 6).every((x) => x === null), true)
assert.equal(nov[6].n, 1)
assert.equal(nov.length, 6 + 30)
assert.equal(nov.find((x) => x && x.key === '2026-11-21').count, 2)
assert.equal(nov.find((x) => x && x.key === '2026-11-22').count, 0)

// 1 Dec 2026 is a Tuesday => 1 blank
assert.equal(c.months[1].cells.filter((x) => x === null).length, 1)
assert.equal(dayTitle('2026-11-21'), 'Sat 21 Nov')
assert.deepEqual(buildCalendar([], tz).months, [])
console.log('bookingCalendar ok')
