/**
 * UpcomingBookings.jsx - BOOKINGS-VIEW-1
 *
 * A quick list of booked calls and visits inside Lead Center, so a booking made from WhatsApp, a booking link or by staff can be found
 * without going to Admin > Booking > Calendar. Reads the same feed as that calendar (GET /api/v1/booking/bookings), next 60 days,
 * grouped Today / This week / Later, with Past 7 days below. Each row opens the lead.
 * Read-only: changing, cancelling or moving a booking is still done from the lead or the Admin > Booking calendar.
 */
import { useState, useEffect, useCallback } from 'react'
import { getBookingsFeed, listBookingServices, apiError } from '../../services/booking.service'
import { ds } from '../../utils/ds'

const STATUS = {
  pending_assignment: ['Needs approval', '#FFFBEB', '#92400E'], confirmed: ['Confirmed', '#F0FFF4', '#276749'],
  attended: ['Attended', '#EBF8FF', '#2B6CB0'], no_show: ['No-show', '#FFF5F5', '#C53030'],
}
const SHOW = new Set(Object.keys(STATUS))
const MEDIUM = { virtual: 'Online', in_person: 'In person', phone: 'Phone' }
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const dayStart = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
const timeOf = (iso) => new Date(iso).toLocaleTimeString('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase()
const dateOf = (iso) => new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

export default function UpcomingBookings({ onOpenLead }) {
  const [rows, setRows] = useState(null)
  const [services, setServices] = useState({})
  const [err, setErr] = useState(null)

  const load = useCallback(() => {
    setRows(null); setErr(null)
    const today = dayStart(new Date())
    getBookingsFeed(ymd(addDays(today, -7)), ymd(addDays(today, 60)))
      .then((r) => setRows(r.data || []))
      .catch((e) => { setErr(apiError(e)); setRows([]) })
    listBookingServices().then((r) => {
      const m = {}; (r.data || []).forEach((s) => { m[s.id] = s.name }); setServices(m)
    }).catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])

  const today = dayStart(new Date())
  const tomorrow = addDays(today, 1)
  const weekEnd = addDays(today, 7)
  const live = (rows || []).filter((r) => r.scheduled_at && SHOW.has(r.status))
  const upcoming = live.filter((r) => new Date(r.scheduled_at) >= today)
  const past = live.filter((r) => new Date(r.scheduled_at) < today).reverse()
  const groups = [
    ['Today', upcoming.filter((r) => new Date(r.scheduled_at) < tomorrow)],
    ['Next 7 days', upcoming.filter((r) => { const t = new Date(r.scheduled_at); return t >= tomorrow && t < weekEnd })],
    ['Later', upcoming.filter((r) => new Date(r.scheduled_at) >= weekEnd)],
  ]

  const row = (r, muted) => {
    const s = STATUS[r.status] || STATUS.confirmed
    return (
      <div key={r.id} onClick={() => r.lead_id && onOpenLead && onOpenLead(r.lead_id)}
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 4px', borderTop: `1px solid ${ds.border}`, flexWrap: 'wrap', cursor: r.lead_id ? 'pointer' : 'default', opacity: muted ? 0.7 : 1 }}>
        <div style={{ minWidth: 118 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: ds.dark }}>{timeOf(r.scheduled_at)}</div>
          <div style={{ fontSize: 12, color: ds.gray }}>{dateOf(r.scheduled_at)}</div>
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: ds.dark }}>{r.leads?.full_name || 'Lead'}</div>
          <div style={{ fontSize: 12, color: ds.gray }}>
            {services[r.service_id] || 'Booking'}{r.medium ? ` · ${MEDIUM[r.medium] || r.medium}` : ''}{r.duration_minutes ? ` · ${r.duration_minutes} min` : ''}{r.leads?.whatsapp ? ` · ${r.leads.whatsapp}` : ''}
          </div>
        </div>
        <span style={{ background: s[1], color: s[2], borderRadius: 20, padding: '3px 10px', fontSize: 11.5, fontWeight: 600 }}>{s[0]}</span>
        {r.lead_id && <button type="button" onClick={(e) => { e.stopPropagation(); onOpenLead && onOpenLead(r.lead_id) }}
          style={{ background: '#fff', color: ds.teal, border: `1.5px solid ${ds.teal}`, borderRadius: ds.radius.md, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>Open lead</button>}
      </div>
    )
  }

  const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 14, padding: '14px 18px', marginBottom: 14 }
  const head = { fontSize: 12, fontWeight: 700, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <b style={{ fontFamily: ds.fontSyne, color: ds.dark, fontSize: 16 }}>Upcoming bookings</b>
        <span style={{ fontSize: 12, color: ds.gray }}>{rows === null ? '' : `${upcoming.length} coming up`}</span>
        <button type="button" onClick={load} style={{ marginLeft: 'auto', background: '#fff', color: ds.teal, border: `1.5px solid ${ds.teal}`, borderRadius: ds.radius.md, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>Refresh</button>
      </div>
      {err && <p style={{ color: ds.red }}>⚠ {err}</p>}
      {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {rows && !err && upcoming.length === 0 && (
        <div style={{ ...card, color: ds.gray, fontSize: 14 }}>Nothing booked in the next 60 days. Bookings made from WhatsApp, a booking link or by your team appear here.</div>
      )}
      {rows && groups.map(([title, list]) => list.length > 0 && (
        <div key={title} style={card}><div style={head}>{title} · {list.length}</div>{list.map((r) => row(r, false))}</div>
      ))}
      {rows && past.length > 0 && (
        <div style={card}><div style={head}>Past 7 days · {past.length}</div>{past.map((r) => row(r, true))}</div>
      )}
    </div>
  )
}
