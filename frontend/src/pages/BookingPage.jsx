/**
 * frontend/src/pages/BookingPage.jsx
 * BOOKING-1 — public booking page at /b/:token (no login). The token names one lead and one business.
 * Times show in the visitor's own timezone.
 */
import { useEffect, useState, useCallback } from 'react'
import SlotPicker, { fmtFull } from '../modules/booking/SlotPicker'
import { getLink, getLinkSlots, linkBook, linkReschedule, linkCancel, linkVerifyPayment, apiError } from '../services/booking.service'
import '../modules/booking/booking.css'

const MEDIUM = { virtual: 'Online', in_person: 'In person', phone: 'Phone call' }
const ymd = (d) => d.toISOString().slice(0, 10)
const money = (amt, cur) => { try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur || 'NGN' }).format(Number(amt) || 0) } catch { return `${cur || ''} ${amt}` } }

export default function BookingPage({ token }) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const [info, setInfo] = useState(null)
  const [slots, setSlots] = useState([])
  const [picked, setPicked] = useState(null)
  const [staffId, setStaffId] = useState('')      // BOOKING-2D: person chosen by the visitor ('' = anyone)
  const [mode, setMode] = useState('pick')       // pick | reschedule | done | cancelled
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [fatal, setFatal] = useState(null)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [payment, setPayment] = useState(null)    // BOOKING-3A: deposit hold, if the service asks for one
  const [payMsg, setPayMsg] = useState(null)

  useEffect(() => { document.title = 'Book a time'; }, [])

  const loadSlots = useCallback(async (who = staffId) => {
    const from = new Date()
    const to = new Date(Date.now() + 29 * 86400000)
    try {
      const r = await getLinkSlots(token, ymd(from), ymd(to), who)
      setSlots(r.data?.slots || [])
    } catch (e) { setErr(apiError(e, 'Could not load times.')) }
  }, [token, staffId])

  useEffect(() => {
    getLink(token)
      .then(async (r) => {
        setInfo(r.data); setPayment(r.data.payment || null); loadSlots()
        if (r.data.booking && r.data.payment?.status === 'pending' && new URLSearchParams(window.location.search).get('paid')) {
          try { const v = await linkVerifyPayment(token); setInfo((i) => ({ ...i, booking: v.data.booking })); setPayment(v.data.payment || null) } catch { /* the page still shows the pay button */ }
        }
      })
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
      const r = await (mode === 'reschedule' ? linkReschedule(token, { start: picked }) : linkBook(token, { start: picked, timezone: tz, ...(staffId ? { staff_id: staffId } : {}) }))
      setInfo({ ...info, booking: r.data.booking }); setPayment(r.data.payment || null)
      setMode('done'); setPicked(null)
    } catch (e) {
      setErr(apiError(e))
      if (e?.response?.status === 409) { setPicked(null); loadSlots() }
    } finally { setBusy(false) }
  }

  const checkPayment = async () => {
    setBusy(true); setPayMsg(null)
    try {
      const v = await linkVerifyPayment(token)
      setInfo((i) => ({ ...i, booking: v.data.booking })); setPayment(v.data.payment || null)
      if (v.data.payment?.status === 'pending') setPayMsg('We have not seen your payment yet. If you just paid, give it a minute and check again.')
    } catch (e) { setPayMsg(apiError(e)) } finally { setBusy(false) }
  }

  const payPending = !!payment && payment.status === 'pending' && booking?.status === 'pending_assignment'
  const payBox = payPending && (
    <div role="status" style={{ background: '#FFF8E6', border: '1px solid #F6D58A', borderRadius: 10, padding: 14, margin: '0 0 16px' }}>
      <p style={{ margin: '0 0 6px', fontWeight: 700 }}>Pay the {money(payment.amount, payment.currency)} deposit to secure this time</p>
      <p className="bk-tz" style={{ margin: '0 0 10px' }}>We are holding it until {fmtFull(payment.hold_expires_at, tz)}.</p>
      <div className="bk-actions">
        <a className="bk-btn" href={payment.pay_url} target={payment.method === 'external' ? '_blank' : '_self'} rel="noopener noreferrer">Pay now</a>
        <button className="bk-btn bk-btn-ghost" disabled={busy} onClick={checkPayment}>{busy ? 'Checking…' : "I've paid"}</button>
      </div>
      {payMsg && <p className="bk-tz" style={{ marginTop: 8 }}>{payMsg}</p>}
    </div>
  )

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
          <div className="bk-tick" aria-hidden="true">{payPending ? '…' : '✓'}</div>
          <h1>{booking.status === 'confirmed' ? "You're booked" : payPending ? 'Almost there' : 'Request received'}</h1>
          <p className="bk-sub">{fmtFull(booking.scheduled_at, tz)}</p>
          {payBox}
          {!payPending && <p className="bk-sub">{booking.status === 'confirmed' ? 'We have sent a confirmation to your WhatsApp.' : "We'll confirm on WhatsApp shortly."}</p>}
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
        {payBox}
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
      {mode !== 'reschedule' && (info.staff || []).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <label className="bk-tz" htmlFor="bk-who" style={{ display: 'block', marginBottom: 4 }}>Who would you like to see?</label>
          <select id="bk-who" value={staffId} style={{ padding: '9px 12px', fontSize: 14, borderRadius: 8, border: '1.5px solid #cbd5e0', maxWidth: '100%' }}
            onChange={(e) => { setStaffId(e.target.value); setPicked(null); loadSlots(e.target.value) }}>
            <option value="">Anyone available</option>
            {info.staff.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </div>
      )}
      <SlotPicker slots={slots} tz={tz} value={picked} onChange={setPicked} />
      <p className="bk-tz">Times shown in your timezone ({tz})</p>
      {info.deposit && mode !== 'reschedule' && <p className="bk-tz" style={{ fontWeight: 600 }}>A {money(info.deposit.amount, info.deposit.currency)} deposit secures your time. You will pay on the next step.</p>}
      {err && <p className="bk-err" role="alert">{err}</p>}
      <div className="bk-actions">
        <button className="bk-btn" disabled={!picked || busy} onClick={doBook}>
          {busy ? 'Saving…' : picked ? `${info.deposit && mode !== 'reschedule' ? 'Continue with' : 'Confirm'} ${fmtFull(picked, tz)}` : 'Choose a time'}
        </button>
        {mode === 'reschedule' && <button className="bk-btn bk-btn-ghost" onClick={() => { setMode('pick'); setPicked(null) }}>Back</button>}
      </div>
    </Shell>
  )
}

function Shell({ children }) {
  return <main className="bk-page"><div className="bk-card">{children}</div></main>
}
