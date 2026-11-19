import assert from 'node:assert/strict'
import { menuView } from './webchatMenu.js'

const mk = (n, feat = []) => Array.from({ length: n }, (_, i) => ({ id: `m${i}`, label: `M${i}`, ...(feat.includes(i) ? { featured: true } : {}) }))
const ids = (v) => v.shown.map((m) => m.id)

// short menu, nothing featured: all shown, no More
assert.deepEqual(ids(menuView(mk(4), false)), ['m0', 'm1', 'm2', 'm3']); assert.equal(menuView(mk(4), false).hidden, 0)
assert.deepEqual(ids(menuView(mk(6), false)).length, 6)
// long menu, nothing featured: first 5, rest under More
let v = menuView(mk(9), false); assert.deepEqual(ids(v), ['m0', 'm1', 'm2', 'm3', 'm4']); assert.equal(v.hidden, 4)
// featured lead (a campaign can feature two of many)
v = menuView(mk(9, [6, 2]), false); assert.deepEqual(ids(v), ['m2', 'm6']); assert.equal(v.hidden, 7)
// expanded shows everything, featured first, and can collapse
v = menuView(mk(5, [3]), true); assert.deepEqual(ids(v), ['m3', 'm0', 'm1', 'm2', 'm4']); assert.equal(v.hidden, 0); assert.equal(v.canCollapse, true)
// everything featured: no More
v = menuView(mk(3, [0, 1, 2]), false); assert.equal(v.shown.length, 3); assert.equal(v.hidden, 0)
// junk in
assert.deepEqual(menuView(null, false), { shown: [], hidden: 0, canCollapse: false })
console.log('webchatMenu: all tests passed')
