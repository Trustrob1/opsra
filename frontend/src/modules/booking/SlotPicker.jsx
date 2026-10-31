/**
 * frontend/src/modules/booking/SlotPicker.jsx
 * BOOKING-1 — day strip + time grid. `slots` are ISO UTC strings; `tz` is the IANA zone to show them in.
 */
import { useMemo, useState, useEffect } from 'react'
import './booking.css'

const dayKey = (iso, tz) => new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso))
const fmtTime = (iso, tz) => new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso)).toLowerCase()
const dayParts = (iso, tz) => {
  const d = new Date(iso)
  return {
    wd: new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short' }).format(d),
    dd: new Intl.DateTimeFormat('en-GB', { timeZone: tz, day: 'numeric' }).format(d),
    mo: new Intl.DateTimeFormat('en-GB', { timeZone: tz, month: 'short' }).format(d),
  }
}

export default function SlotPicker({ slots = [], tz, value, onChange }) {
  const days = useMemo(() => {
    const map = new Map()
    slots.forEach((s) => {
      const k = dayKey(s, tz)
      if (!map.has(k)) map.set(k, { key: k, first: s, times: [] })
      map.get(k).times.push(s)
    })
    return [...map.values()]
  }, [slots, tz])

  const [daySel, setDaySel] = useState(null)
  useEffect(() => {
    if (!days.length) { setDaySel(null); return }
    if (!days.find((d) => d.key === daySel)) setDaySel(days[0].key)
  }, [days]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!days.length) return <p className="bk-empty">No open times in this period. Try again later or contact us.</p>
  const current = days.find((d) => d.key === daySel) || days[0]

  return (
    <div>
      <div className="bk-days" role="group" aria-label="Pick a day">
        {days.map((d) => {
          const p = dayParts(d.first, tz)
          return (
            <button key={d.key} type="button" className="bk-day" aria-pressed={d.key === current.key} onClick={() => setDaySel(d.key)}>
              <b>{p.wd}</b><span>{p.dd}</span><small>{p.mo}</small>
            </button>
          )
        })}
      </div>
      <div className="bk-times" role="group" aria-label="Pick a time">
        {current.times.map((t) => (
          <button key={t} type="button" className="bk-time" aria-pressed={value === t} onClick={() => onChange(t)}>{fmtTime(t, tz)}</button>
        ))}
      </div>
    </div>
  )
}

export { fmtTime, dayKey }
export const fmtFull = (iso, tz) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'long', day: 'numeric', month: 'long', hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso))
