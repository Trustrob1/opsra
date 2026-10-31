/**
 * frontend/src/pages/BookingPage.jsx
 * BOOKING-1 — public booking page at /b/:token (no login). The token names one lead and one business.
 * Times show in the visitor's own timezone.
 */
import { useEffect, useState, useCallback } from 'react'
import SlotPicker, { fmtFull } from '../modules/booking/SlotPicker'
import { getLink, getLinkSlots, linkBook, linkReschedule, linkCancel, apiError } from '../services/booking.service'
import '../modules/booking/booking.css'

const MEDIUM = { virtual: 'Online', in_person: 'In person', phone: 'Phone call' }
const ymd = (d) => d.toISOString().slice(0, 10)

export default function BookingPage({ token }) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const [info, setInfo] = useState(null)
  const [slots, setSlots] = useState([])
  const [picked, setPicked] = useState(null)
  const [mode, setMode] = useState('pick')       // pick | reschedule | done | cancelled
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [fatal, setFatal] = useState(null)
  const [confirmCancel, setConfirmCancel] = useState(false)

  useEffect(() => { document.title = 'Book a time'; }, [])

  const loadSlots = useCallback(async () => {
    const from = new Date()
    const to = new Date(Date.now() + 29 * 86400000)
    try {
      const r = await getLinkSlots(token, ymd(from), ymd(to))
      setSlots(r.data?.slots || [])
    } catch (e) { setErr(apiError(e, 'Could not load times.')) }
  }, [token])

  useEffect(() => {
    getLink(token)
      .then((r) => { setInfo(r.data); loadSlots() })
      .catch((e) => setFatal(apiError(e, 'This link is not available.')))
  }, [token, loadSlots])

  if (fatal) return <Shell><h1>Link not available</h1><p className="bk-sub">{fatal}</p></Shell>
  if (!info) return <Shell><p className="bk-sub">Loading…</p></Shell>

  const label = info.label || 'booking'
  const svc = info.service || {}
  const booking = info.booking
  const hasBooking = !!booking && mode !== 'cancelled'

  const doBook = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await (mode === 'reschedule' ? linkReschedule(token, { start: picked }) : linkBook(token, { start: picked, timezone: tz }))
      setInfo({ ...info, booking: r.data.booking })
      setMode('done'); setPicked(null)
    } catch (e) {
      setErr(apiError(e))
      if (e?.response?.status === 409) { setPicked(null); loadSlots() }
    } finally { setBusy(false) }
  }

  const doCancel = async () => {
    setBusy(true); setErr(null)
    try { await linkCancel(token, {}); setInfo({ ...info, booking: null }); setMode('cancelled') }
    catch (e) { setErr(apiError(e)) }
    finally { setBusy(false); setConfirmCancel(false) }
  }

  const head = (
    <>
      <h1>{info.first_name ? `Hi ${info.first_name}, ` : ''}{hasBooking && mode !== 'reschedule' ? `your ${label}` : `book your ${label}`}</h1>
      <p className="bk-sub">{info.business}</p>
      <div className="bk-meta">
        {svc.name && <span className="bk-chip">{svc.name}</span>}
        {svc.duration_minutes && <span className="bk-chip">{svc.duration_minutes} min</span>}
        {svc.medium && <span className="bk-chip">{MEDIUM[svc.medium] || svc.medium}</span>}
      </div>
      {svc.location_text && <p className="bk-sub">{svc.location_text}</p>}
    </>
  )

  if (mode === 'done' && booking) {
    return (
      <Shell>
        <div className="bk-done">
          <div className="bk-tick" aria-hidden="true">✓</div>
          <h1>{booking.status === 'confirmed' ? "You're booked" : 'Request received'}</h1>
          <p className="bk-sub">{fmtFull(booking.scheduled_at, tz)}</p>
          <p className="bk-sub">{booking.status === 'confirmed' ? 'We have sent a confirmation to your WhatsApp.' : "We'll confirm on WhatsApp shortly."}</p>
          <div className="bk-actions"><button className="bk-btn bk-btn-ghost" onClick={() => setMode('pick')}>Change or cancel</button></div>
        </div>
      </Shell>
    )
  }

  if (mode === 'cancelled') {
    return (
      <Shell>
        <div className="bk-done"><h1>Booking cancelled</h1><p className="bk-sub">You can pick a new time any time.</p>
          <div className="bk-actions"><button className="bk-btn" onClick={() => { setMode('pick'); loadSlots() }}>Pick a new time</button></div></div>
      </Shell>
    )
  }

  if (hasBooking && mode === 'pick') {
    return (
      <Shell>
        {head}
        <p className="bk-sec">Your time</p>
        <p style={{ fontSize: 18, fontWeight: 700, margin: '0 0 4px' }}>{fmtFull(booking.scheduled_at, tz)}</p>
        <p className="bk-tz">Shown in your timezone ({tz})</p>
        {err && <p className="bk-err" role="alert">{err}</p>}
        {!confirmCancel ? (
          <div className="bk-actions">
            <button className="bk-btn" onClick={() => { setMode('reschedule'); setErr(null) }}>Change time</button>
            <button className="bk-btn bk-btn-danger" onClick={() => setConfirmCancel(true)}>Cancel booking</button>
          </div>
        ) : (
          <div className="bk-actions">
            <button className="bk-btn bk-btn-danger" disabled={busy} onClick={doCancel}>{busy ? 'Cancelling…' : 'Yes, cancel it'}</button>
            <button className="bk-btn bk-btn-ghost" onClick={() => setConfirmCancel(false)}>Keep it</button>
          </div>
        )}
        {info.cancel_cutoff_hours > 0 && <p className="bk-tz">Changes are allowed up to {info.cancel_cutoff_hours} hours before.</p>}
      </Shell>
    )
  }

  return (
    <Shell>
      {head}
      <p className="bk-sec">{mode === 'reschedule' ? 'Pick a new time' : 'Pick a time'}</p>
      <SlotPicker slots={slots} tz={tz} value={picked} onChange={setPicked} />
      <p className="bk-tz">Times shown in your timezone ({tz})</p>
      {err && <p className="bk-err" role="alert">{err}</p>}
      <div className="bk-actions">
        <button className="bk-btn" disabled={!picked || busy} onClick={doBook}>
          {busy ? 'Saving…' : picked ? `Confirm ${fmtFull(picked, tz)}` : 'Choose a time'}
        </button>
        {mode === 'reschedule' && <button className="bk-btn bk-btn-ghost" onClick={() => { setMode('pick'); setPicked(null) }}>Back</button>}
      </div>
    </Shell>
  )
}

function Shell({ children }) {
  return <main className="bk-page"><div className="bk-card">{children}</div></main>
}
