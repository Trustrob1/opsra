/**
 * frontend/src/utils/bookingCalendar.js
 * BOOKING-CAL-1 — pure helpers for the month calendar on the public booking page.
 * `slots` are ISO UTC strings; `tz` is the IANA zone the visitor sees. No React here so it can be tested in node.
 */
export const dayKeyOf = (iso, tz) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso))

const utcDate = (key) => { const [y, m, d] = key.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)) }

/** Group slots by local day, then lay the days out as Monday-first month grids. */
export function buildCalendar(slots, tz) {
  const byDay = new Map()
  ;(slots || []).forEach((s) => {
    const k = dayKeyOf(s, tz)
    if (!byDay.has(k)) byDay.set(k, [])
    byDay.get(k).push(s)
  })
  byDay.forEach((list) => list.sort())
  const dayKeys = [...byDay.keys()].sort()
  const monthKeys = [...new Set(dayKeys.map((k) => k.slice(0, 7)))]
  const months = monthKeys.map((mk) => {
    const [y, m] = mk.split('-').map(Number)
    const first = new Date(Date.UTC(y, m - 1, 1))
    const lead = (first.getUTCDay() + 6) % 7            // Monday = 0
    const total = new Date(Date.UTC(y, m, 0)).getUTCDate()
    const cells = Array.from({ length: lead }, () => null)
    for (let d = 1; d <= total; d++) {
      const key = `${mk}-${String(d).padStart(2, '0')}`
      cells.push({ key, n: d, count: (byDay.get(key) || []).length })
    }
    return { key: mk, label: new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', month: 'long', year: 'numeric' }).format(first), cells }
  })
  return { byDay, dayKeys, months }
}

export const dayTitle = (key) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).format(utcDate(key))

export const dayLong = (key) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long' }).format(utcDate(key))
