/**
 * frontend/src/modules/booking/BookingTools.jsx
 * BOOKING-1 — staff tools used on the lead's booking tab and the calendar:
 *   <BookingActions>   "Book a time" + "Send booking link" (only when native booking is on)
 *   <BookingRowActions> Reschedule / Cancel for one booking
 * Times are shown in the organisation's timezone.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import SlotPicker, { fmtFull } from './SlotPicker'
import {
  getBookingSettings, listBookingServices, getStaffSlots, staffBookLead, makeBookingLink,
  staffCancelBooking, staffRescheduleBooking, startWaPicker, markDepositPaid, markDepositRefunded, apiError,
} from '../../services/booking.service'
import './booking.css'

const ymd = (d) => d.toISOString().slice(0, 10)

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const h = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div role="dialog" aria-modal="true" aria-label={title} onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(13,27,42,.45)', zIndex: ds.z.modal, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: '#fff', borderRadius: 16, padding: 22, width: '100%', maxWidth: 520, maxHeight: '90vh', overflow: 'auto', boxShadow: ds.modalShadow }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontFamily: ds.fontSyne, fontSize: 16, color: ds.dark }}>{title}</h3>
          <button onClick={onClose} aria-label="Close" style={{ border: 'none', background: 'none', fontSize: 22, cursor: 'pointer', color: ds.gray }}>×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

/** Pick an open slot and call onPick(isoUtc). */
export function SlotModal({ title, serviceId, tz, confirmLabel, onPick, onClose }) {
  const [slots, setSlots] = useState(null)
  const [zone, setZone] = useState(tz || 'Africa/Lagos')
  const [picked, setPicked] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getStaffSlots(serviceId, ymd(new Date()), ymd(new Date(Date.now() + 29 * 86400000)))
      .then((r) => { setSlots(r.data.slots); setZone(r.data.timezone) })
      .catch((e) => { setErr(apiError(e, 'Could not load open times.')); setSlots([]) })
  }, [serviceId])

  const go = async () => {
    setBusy(true); setErr(null)
    try { await onPick(picked) } catch (e) { setErr(apiError(e)); setBusy(false) }
  }

  return (
    <Modal title={title} onClose={onClose}>
      {slots === null ? <p style={{ color: ds.gray }}>Loading open times…</p> : <SlotPicker slots={slots} tz={zone} value={picked} onChange={setPicked} />}
      <p className="bk-tz">Times shown in {zone}</p>
      {err && <p className="bk-err" role="alert">{err}</p>}
      <div className="bk-actions">
        <button className="bk-btn" disabled={!picked || busy} onClick={go}>{busy ? 'Saving…' : picked ? `${confirmLabel} ${fmtFull(picked, zone)}` : 'Choose a time'}</button>
      </div>
    </Modal>
  )
}

export function BookingActions({ leadId, meetingLabel = 'Meeting', onChanged }) {
  const [cfg, setCfg] = useState(null)
  const [services, setServices] = useState([])
  const [serviceId, setServiceId] = useState('')
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getBookingSettings().then(async (r) => {
      setCfg(r.data)
      if (r.data?.native_enabled) {
        const s = await listBookingServices()
        const act = (s.data || []).filter((x) => x.active)
        setServices(act)
        if (act[0]) setServiceId(act[0].id)
      }
    }).catch(() => setCfg({ native_enabled: false }))
  }, [])

  if (!cfg?.native_enabled || !services.length) return null
  const label = (cfg.label || meetingLabel).toLowerCase()

  const sendLink = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await makeBookingLink(leadId, { service: serviceId || undefined, send_whatsapp: true })
      const d = r.data
      const why = {
        window_closed: "Not sent: this person hasn't messaged in 24 hours. Copy the link and send it yourself.",
        template_failed: "Not sent: the WhatsApp message template isn't approved yet. Copy the link and send it yourself.",
        no_whatsapp: 'Not sent: WhatsApp is not connected for this business.',
        no_number: 'Not sent: this lead has no phone number.',
      }
      setMsg(d.sent_whatsapp
        ? { ok: true, text: 'Booking link sent on WhatsApp.', url: d.url }
        : { ok: false, text: why[d.whatsapp_reason] || 'The message could not be sent. Copy the link and send it yourself.', url: d.url })
    } catch (e) { setMsg({ ok: false, text: apiError(e) }) }
    finally { setBusy(false) }
  }
  const sendTimes = async () => {
    setBusy(true); setMsg(null)
    try {
      const d = (await startWaPicker(leadId, { service: serviceId || undefined })).data
      if (d.started) setMsg({ ok: true, text: 'Times sent on WhatsApp. The customer picks a day, then a time.' })
      else if (d.fallback === 'link') setMsg({ ok: !!d.sent, text: d.sent ? "This customer hasn't messaged in 24 hours, so the booking link was sent instead." : "Not sent: this customer hasn't messaged in 24 hours and the message template isn't approved yet. Copy the link and send it yourself.", url: d.url })
      else {
        const why = { too_many: 'Already offered times to this customer 5 times today.', no_slots: 'No open times right now, so nothing was sent.', no_service: 'Add a service first.', not_enabled: 'Turn on online booking first.', send_failed: 'WhatsApp could not send the message.' }
        setMsg({ ok: false, text: why[d.reason] || 'Could not send the times.' })
      }
    } catch (e) { setMsg({ ok: false, text: apiError(e) }) }
    finally { setBusy(false) }
  }
  const copyLink = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await makeBookingLink(leadId, { service: serviceId || undefined, send_whatsapp: false })
      try { await navigator.clipboard.writeText(r.data.url) } catch { /* shown below instead */ }
      setMsg({ ok: true, text: 'Link copied.', url: r.data.url })
    } catch (e) { setMsg({ ok: false, text: apiError(e) }) }
    finally { setBusy(false) }
  }

  const btn = { border: `1.5px solid ${ds.teal}`, background: '#fff', color: ds.teal, borderRadius: ds.radius.md, padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne }
  return (
    <div style={{ background: ds.light, border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 14, marginBottom: 16 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {services.length > 1 && (
          <select aria-label="Service" value={serviceId} onChange={(e) => setServiceId(e.target.value)} style={{ padding: '8px 10px', borderRadius: ds.radius.md, border: `1.5px solid ${ds.border}`, fontSize: 13 }}>
            {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        <button style={{ ...btn, background: ds.teal, color: '#fff' }} onClick={() => setOpen(true)}>Book a {label}</button>
        <button style={btn} disabled={busy} onClick={sendTimes}>Send times on WhatsApp</button>
        <button style={btn} disabled={busy} onClick={sendLink}>Send booking link</button>
        <button style={btn} disabled={busy} onClick={copyLink}>Copy link</button>
      </div>
      {msg && <p role="status" style={{ margin: '10px 0 0', fontSize: 13, color: msg.ok ? '#276749' : ds.red, wordBreak: 'break-all' }}>{msg.text}{msg.url ? ` ${msg.url}` : ''}</p>}
      {open && (
        <SlotModal title={`Book a ${label}`} serviceId={serviceId} confirmLabel="Book"
          onClose={() => setOpen(false)}
          onPick={async (start) => { await staffBookLead(leadId, { service: serviceId, start }); setOpen(false); onChanged && onChanged() }} />
      )}
    </div>
  )
}

export function BookingRowActions({ booking, onChanged }) {
  const [modal, setModal] = useState(null)   // 'resched' | 'cancel'
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const live = ['pending_assignment', 'confirmed'].includes(booking.status)
  const ps = booking.payment_status          // BOOKING-3A: pending | paid | refund_due | refunded | expired | ...
  const PAY_LABEL = { pending: 'Deposit unpaid', paid: 'Deposit paid', refund_due: 'Refund due', refunded: 'Deposit refunded', waived: 'Deposit waived' }
  const payAct = async (fn) => {
    setBusy(true); setErr(null)
    try { await fn(booking.id); onChanged && onChanged() } catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }
  const btnS = { border: `1.5px solid ${ds.border}`, background: '#fff', borderRadius: ds.radius.md, padding: '4px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer', color: ds.dark }
  const payBits = ps && PAY_LABEL[ps] && (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', marginRight: 6 }}>
      <span style={{ fontSize: 11.5, fontWeight: 700, padding: '3px 8px', borderRadius: 99, background: ps === 'paid' || ps === 'refunded' ? '#E6F4EA' : '#FFF4D6', color: ps === 'paid' || ps === 'refunded' ? '#276749' : '#8A5A00' }}>{PAY_LABEL[ps]}</span>
      {ps === 'pending' && <button style={btnS} disabled={busy} onClick={() => payAct(markDepositPaid)}>Mark as paid</button>}
      {ps === 'refund_due' && <button style={btnS} disabled={busy} onClick={() => payAct(markDepositRefunded)}>Mark refunded</button>}
      {err && <span role="alert" style={{ fontSize: 11.5, color: '#C53030' }}>{err}</span>}
    </span>
  )
  if (!live) return payBits || null
  const btn = { border: `1.5px solid ${ds.border}`, background: '#fff', borderRadius: ds.radius.md, padding: '6px 12px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', color: ds.dark }
  const doCancel = async () => {
    setBusy(true); setErr(null)
    try { await staffCancelBooking(booking.id, { reason: reason || undefined }); setModal(null); onChanged && onChanged() }
    catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }
  return (
    <>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        {payBits}
        {booking.service_id && <button style={btn} onClick={() => setModal('resched')}>Reschedule</button>}
        <button style={{ ...btn, color: '#C53030', borderColor: '#F3B5B5' }} onClick={() => setModal('cancel')}>Cancel</button>
      </span>
      {modal === 'resched' && (
        <SlotModal title="Move booking" serviceId={booking.service_id} confirmLabel="Move to"
          onClose={() => setModal(null)}
          onPick={async (start) => { await staffRescheduleBooking(booking.id, { start }); setModal(null); onChanged && onChanged() }} />
      )}
      {modal === 'cancel' && (
        <Modal title="Cancel this booking?" onClose={() => setModal(null)}>
          <p style={{ fontSize: 13, color: ds.gray, marginTop: 0 }}>The person is told on WhatsApp and the time opens up again.</p>
          <label style={{ fontSize: 12, fontWeight: 600, color: ds.gray }}>Reason (optional)
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} style={{ display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 4, padding: '9px 12px', border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md }} />
          </label>
          {err && <p className="bk-err" role="alert">{err}</p>}
          <div className="bk-actions">
            <button className="bk-btn bk-btn-danger" disabled={busy} onClick={doCancel}>{busy ? 'Cancelling…' : 'Cancel booking'}</button>
            <button className="bk-btn bk-btn-ghost" onClick={() => setModal(null)}>Keep it</button>
          </div>
        </Modal>
      )}
    </>
  )
}
