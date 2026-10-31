/**
 * frontend/src/modules/booking/BookingTeam.jsx
 * BOOKING-2B — Admin > Booking > Team (only when the calendar mode is "each person has their own calendar"):
 *   <TeamView>        who takes bookings, their weekly hours and time off, and which services each person serves
 *   <ReassignButton>  manager action on a calendar row: hand a booking to another person
 */
import { useCallback, useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import { Modal } from './BookingTools'
import {
  listBookingStaff, saveBookingStaff, saveStaffHours, switchToBusinessHours, listStaffBlocks, addStaffBlock, deleteStaffBlock,
  listBookingServices, updateBookingService, saveServiceStaff, assignBooking, apiError,
} from '../../services/booking.service'
import './booking.css'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.xl, padding: '20px 24px', marginBottom: 20, boxShadow: ds.cardShadow }
const title = { fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: ds.dark, margin: '0 0 14px', paddingBottom: 10, borderBottom: `1px solid ${ds.border}` }
const lab = { display: 'block', fontSize: 11, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 5 }
const inp = { width: '100%', boxSizing: 'border-box', padding: '9px 12px', border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md, fontSize: 13.5, color: ds.dark, background: '#fff' }
const btnP = { background: ds.teal, color: '#fff', border: 'none', borderRadius: ds.radius.md, padding: '9px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const btnG = { background: '#fff', color: ds.teal, border: `1.5px solid ${ds.teal}`, borderRadius: ds.radius.md, padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const hhmm = (v) => String(v).slice(0, 5)

export default function TeamView() {
  const [staff, setStaff] = useState(null)
  const [services, setServices] = useState([])
  const [err, setErr] = useState(null)
  const load = useCallback(() => {
    Promise.all([listBookingStaff(), listBookingServices()])
      .then(([a, b]) => { setStaff(a.data || []); setServices(b.data || []) })
      .catch((e) => { setErr(apiError(e)); setStaff([]) })
  }, [])
  useEffect(() => { load() }, [load])
  if (staff === null) return <p style={{ color: ds.gray }}>Loading team…</p>
  const accepting = staff.filter((s) => s.accepts_bookings).length
  return (
    <div>
      {err && <p role="alert" style={{ color: ds.red }}>⚠ {err}</p>}
      <div style={card}>
        <p style={title}>Who takes bookings</p>
        <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 12px' }}>
          Each person has their own calendar. A time is offered when at least one of them is free, and the booking goes to the lead's owner (if the service says so), otherwise to whoever has had the fewest recent bookings.
        </p>
        {accepting === 0 && <p role="alert" style={{ color: ds.red, fontSize: 13.5 }}>⚠ Nobody is switched on yet, so no times will be offered. Turn on at least one person below.</p>}
        {staff.length === 0 && <p style={{ color: ds.gray }}>No team members found.</p>}
        {staff.map((p) => <StaffCard key={p.user_id} person={p} onChanged={load} />)}
      </div>
      {services.length > 0 && <ServiceAssignment services={services} staff={staff} onChanged={load} />}
    </div>
  )
}

function StaffCard({ person, onChanged }) {
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState(null)
  const toggle = async (accepts) => {
    setMsg(null)
    try { await saveBookingStaff(person.user_id, { accepts_bookings: accepts }); onChanged() } catch (e) { setMsg({ ok: false, t: apiError(e) }) }
  }
  return (
    <div style={{ borderTop: `1px solid ${ds.border}`, padding: '12px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, cursor: 'pointer', fontSize: 14 }}>
          <input type="checkbox" checked={person.accepts_bookings} onChange={(e) => toggle(e.target.checked)} />
          <span><b>{person.full_name}</b><br /><span style={{ fontSize: 12, color: ds.gray }}>{person.accepts_bookings ? (person.uses_org_hours ? 'Follows business hours' : 'Own hours') : 'Not taking bookings'}</span></span>
        </label>
        {person.accepts_bookings && <button style={btnG} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close' : 'Hours & time off'}</button>}
      </div>
      {msg && <p role="alert" style={{ color: ds.red, fontSize: 13 }}>⚠ {msg.t}</p>}
      {open && person.accepts_bookings && <PersonSchedule person={person} onChanged={onChanged} />}
    </div>
  )
}

function PersonSchedule({ person, onChanged }) {
  const [rows, setRows] = useState((person.hours || []).map((x) => ({ ...x, start_time: hhmm(x.start_time), end_time: hhmm(x.end_time) })))
  const [custom, setCustom] = useState(!person.uses_org_hours)
  const [msg, setMsg] = useState(null)
  const upd = (i, k, v) => setRows((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x)))
  const del = (i) => setRows((r) => r.filter((_, j) => j !== i))
  const add = (w) => setRows((r) => [...r, { weekday: w, start_time: '09:00', end_time: '17:00' }])
  const save = async () => {
    setMsg(null)
    try { await saveStaffHours(person.user_id, rows); setMsg({ ok: true, t: 'Hours saved.' }); onChanged() } catch (e) { setMsg({ ok: false, t: apiError(e) }) }
  }
  const useBusiness = async () => {
    setMsg(null)
    try { await switchToBusinessHours(person.user_id); setCustom(false); setRows([]); setMsg({ ok: true, t: 'Now following the business hours.' }); onChanged() } catch (e) { setMsg({ ok: false, t: apiError(e) }) }
  }
  return (
    <div style={{ background: ds.mint, borderRadius: ds.radius.lg, padding: 14, marginTop: 10 }}>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, cursor: 'pointer', marginBottom: 10 }}>
        <input type="radio" name={`hrs-${person.user_id}`} checked={!custom} onChange={useBusiness} /> Same hours as the business
      </label>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, cursor: 'pointer', marginBottom: 8 }}>
        <input type="radio" name={`hrs-${person.user_id}`} checked={custom} onChange={() => { setCustom(true); if (!rows.length) setRows([0, 1, 2, 3, 4].map((w) => ({ weekday: w, start_time: '09:00', end_time: '17:00' }))) }} /> Their own hours
      </label>
      {custom && (
        <div>
          {DAYS.map((name, w) => {
            const mine = rows.map((r, i) => ({ r, i })).filter((x) => x.r.weekday === w)
            return (
              <div key={name} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '5px 0', flexWrap: 'wrap' }}>
                <span style={{ width: 96, fontSize: 13, fontWeight: 600 }}>{name}</span>
                {mine.length === 0 && <span style={{ color: ds.gray, fontSize: 13 }}>Off</span>}
                {mine.map(({ r, i }) => (
                  <span key={i} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                    <input aria-label={`${name} from`} type="time" value={r.start_time} onChange={(e) => upd(i, 'start_time', e.target.value)} style={{ ...inp, width: 118 }} />
                    to
                    <input aria-label={`${name} to`} type="time" value={r.end_time} onChange={(e) => upd(i, 'end_time', e.target.value)} style={{ ...inp, width: 118 }} />
                    <button onClick={() => del(i)} aria-label={`Remove ${name} hours`} style={{ border: 'none', background: 'none', color: ds.gray, cursor: 'pointer', fontSize: 18 }}>×</button>
                  </span>
                ))}
                <button onClick={() => add(w)} style={{ ...btnG, padding: '4px 10px', fontSize: 12 }}>+ Add hours</button>
              </div>
            )
          })}
          <button style={{ ...btnP, marginTop: 10 }} onClick={save}>Save hours</button>
        </div>
      )}
      {msg && <p role="status" style={{ fontSize: 13, color: msg.ok ? '#276749' : ds.red, margin: '8px 0 0' }}>{msg.t}</p>}
      <PersonTimeOff userId={person.user_id} />
    </div>
  )
}

function PersonTimeOff({ userId }) {
  const [list, setList] = useState([])
  const [f, setF] = useState({ starts: '', ends: '', reason: '' })
  const [err, setErr] = useState(null)
  const load = useCallback(() => listStaffBlocks(userId).then((r) => setList(r.data || [])).catch((e) => setErr(apiError(e))), [userId])
  useEffect(() => { load() }, [load])
  const add = async () => {
    setErr(null)
    if (!f.starts || !f.ends) { setErr('Pick a start and an end.'); return }
    try { await addStaffBlock(userId, { starts_at: new Date(f.starts).toISOString(), ends_at: new Date(f.ends).toISOString(), reason: f.reason || undefined }); setF({ starts: '', ends: '', reason: '' }); load() }
    catch (e) { setErr(apiError(e)) }
  }
  const fmt = (iso) => new Date(iso).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true })
  return (
    <div style={{ marginTop: 14 }}>
      <span style={lab}>Time off</span>
      {list.map((b) => (
        <div key={b.id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '4px 0', fontSize: 13 }}>
          <span style={{ flex: 1 }}>{fmt(b.starts_at)} → {fmt(b.ends_at)}{b.reason ? ` · ${b.reason}` : ''}</span>
          <button style={{ ...btnG, padding: '3px 9px', fontSize: 12 }} onClick={() => deleteStaffBlock(b.id).then(load).catch((e) => setErr(apiError(e)))}>Remove</button>
        </div>
      ))}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 8, marginTop: 6 }}>
        <input aria-label="Time off from" type="datetime-local" style={inp} value={f.starts} onChange={(e) => setF({ ...f, starts: e.target.value })} />
        <input aria-label="Time off until" type="datetime-local" style={inp} value={f.ends} onChange={(e) => setF({ ...f, ends: e.target.value })} />
        <input aria-label="Reason" placeholder="Reason (optional)" style={inp} value={f.reason} maxLength={200} onChange={(e) => setF({ ...f, reason: e.target.value })} />
      </div>
      {err && <p role="alert" style={{ color: ds.red, fontSize: 13 }}>⚠ {err}</p>}
      <button style={{ ...btnG, marginTop: 8 }} onClick={add}>+ Add time off</button>
    </div>
  )
}

const MODES = [
  ['anyone', 'Anyone who is free'],
  ['lead_owner_first', "The lead's owner first, then anyone free"],
  ['specific', 'Only the people I pick'],
]

function ServiceAssignment({ services, staff, onChanged }) {
  const [msg, setMsg] = useState(null)
  const setMode = async (svc, mode) => {
    setMsg(null)
    try { await updateBookingService(svc.id, { assignment_mode: mode }); onChanged() } catch (e) { setMsg(apiError(e)) }
  }
  const toggle = async (svc, userId, on) => {
    setMsg(null)
    const cur = staff.filter((p) => (p.service_ids || []).includes(svc.id)).map((p) => p.user_id)
    const next = on ? [...new Set([...cur, userId])] : cur.filter((u) => u !== userId)
    try { await saveServiceStaff(svc.id, next); onChanged() } catch (e) { setMsg(apiError(e)) }
  }
  return (
    <div style={card}>
      <p style={title}>Who serves each service</p>
      {msg && <p role="alert" style={{ color: ds.red, fontSize: 13 }}>⚠ {msg}</p>}
      {services.map((svc) => (
        <div key={svc.id} style={{ borderTop: `1px solid ${ds.border}`, padding: '12px 0' }}>
          <label style={lab} htmlFor={`am-${svc.id}`}>{svc.name}</label>
          <select id={`am-${svc.id}`} style={inp} value={svc.assignment_mode || 'anyone'} onChange={(e) => setMode(svc, e.target.value)}>
            {MODES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
          {svc.assignment_mode === 'specific' && (
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 8 }}>
              {staff.filter((p) => p.accepts_bookings).map((p) => (
                <label key={p.user_id} style={{ fontSize: 13.5, cursor: 'pointer' }}>
                  <input type="checkbox" checked={(p.service_ids || []).includes(svc.id)} onChange={(e) => toggle(svc, p.user_id, e.target.checked)} /> {p.full_name}
                </label>
              ))}
              {staff.every((p) => !(p.service_ids || []).includes(svc.id)) && <span style={{ color: ds.red, fontSize: 13 }}>⚠ Pick at least one person or no times will be offered.</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function ReassignButton({ booking, staff, onChanged }) {
  const [open, setOpen] = useState(false)
  const [to, setTo] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const options = (staff || []).filter((p) => p.accepts_bookings && p.user_id !== booking.assigned_to)
  const go = async () => {
    setBusy(true); setErr(null)
    try { await assignBooking(booking.id, to); setOpen(false); onChanged() } catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }
  if (!['confirmed', 'pending_assignment'].includes(booking.status) || !options.length) return null
  return (
    <>
      <button style={{ ...btnG, padding: '4px 10px', fontSize: 12 }} onClick={() => { setOpen(true); setTo(options[0].user_id) }}>Reassign</button>
      {open && (
        <Modal title="Reassign booking" onClose={() => setOpen(false)}>
          <label style={lab} htmlFor="bk-assign">Give this booking to</label>
          <select id="bk-assign" style={inp} value={to} onChange={(e) => setTo(e.target.value)}>
            {options.map((p) => <option key={p.user_id} value={p.user_id}>{p.full_name}</option>)}
          </select>
          {err && <p role="alert" style={{ color: ds.red, fontSize: 13 }}>⚠ {err}</p>}
          <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
            <button style={btnP} disabled={busy || !to} onClick={go}>{busy ? 'Reassigning…' : 'Reassign'}</button>
            <button style={btnG} onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </Modal>
      )}
    </>
  )
}
