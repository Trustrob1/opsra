/**
 * frontend/src/modules/booking/CalendarPicker.jsx
 * BOOKING-CAL-1 — month calendar with the day's times beside it (stacked on a phone).
 * Same props as SlotPicker: `slots` are ISO UTC strings, `tz` is the IANA zone to show them in.
 * The staff-side SlotModal still uses SlotPicker; only the public booking page uses this.
 */
import { useMemo, useState } from 'react'
import { buildCalendar, dayTitle } from '../../utils/bookingCalendar'
import { fmtTime } from './SlotPicker'
import './booking.css'

const WEEK = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function CalendarPicker({ slots = [], tz, value, onChange }) {
  const cal = useMemo(() => buildCalendar(slots, tz), [slots, tz])
  const [daySel, setDaySel] = useState(null)
  const [monthSel, setMonthSel] = useState(null)

  if (!cal.dayKeys.length) return <p className="bk-empty">No open times in this period. Try again later or contact us.</p>
  // derived, so a reload of the slots never leaves a stale day or month selected
  const day = cal.byDay.has(daySel) ? daySel : cal.dayKeys[0]
  const monthKey = cal.months.some((m) => m.key === monthSel) ? monthSel : day.slice(0, 7)
  const monthIdx = cal.months.findIndex((m) => m.key === monthKey)
  const month = cal.months[monthIdx]
  const go = (n) => setMonthSel(cal.months[monthIdx + n].key)
  const times = cal.byDay.get(day) || []

  return (
    <div className="bk-cal">
      <div className="bk-cal-month">
        <div className="bk-cal-head">
          <h2>{month.label}</h2>
          <div className="bk-cal-nav">
            <button type="button" aria-label="Previous month" disabled={monthIdx <= 0} onClick={() => go(-1)}>‹</button>
            <button type="button" aria-label="Next month" disabled={monthIdx >= cal.months.length - 1} onClick={() => go(1)}>›</button>
          </div>
        </div>
        <div className="bk-cal-week" aria-hidden="true">{WEEK.map((w) => <span key={w}>{w}</span>)}</div>
        <div className="bk-cal-grid" role="group" aria-label="Pick a day">
          {month.cells.map((c, i) => c ? (
            <button key={c.key} type="button" className="bk-cal-day" disabled={!c.count} aria-pressed={c.key === day}
              aria-label={`${dayTitle(c.key)}${c.count ? '' : ', no times'}`} onClick={() => { setDaySel(c.key); setMonthSel(null) }}>{c.n}</button>
          ) : <span key={`b${i}`} />)}
        </div>
      </div>
      <div className="bk-cal-times">
        <h2>{dayTitle(day)}</h2>
        <p className="bk-cal-count">{times.length} {times.length === 1 ? 'time' : 'times'} available</p>
        <div className="bk-cal-slots" role="group" aria-label="Pick a time">
          {times.map((t) => (
            <button key={t} type="button" className="bk-time" aria-pressed={value === t} onClick={() => onChange(t)}>{fmtTime(t, tz)}</button>
          ))}
        </div>
      </div>
    </div>
  )
}
