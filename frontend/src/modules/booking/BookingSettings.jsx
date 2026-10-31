/**
 * frontend/src/modules/booking/BookingSettings.jsx
 * BOOKING-1 — Admin > Booking: Calendar view + Settings (switch, label, cancel cut-off, services, weekly hours, time off).
 */
import { useCallback, useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { BookingRowActions } from './BookingTools'
import {
  getBookingSettings, saveBookingSettings, listBookingServices, createBookingService, updateBookingService,
  deleteBookingService, getBookingHours, saveBookingHours, listBookingBlocks, addBookingBlock, deleteBookingBlock,
  getBookingsFeed, apiError,
} from '../../services/booking.service'
import './booking.css'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.xl, padding: '20px 24px', marginBottom: 20, boxShadow: ds.cardShadow }
const title = { fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: ds.dark, margin: '0 0 14px', paddingBottom: 10, borderBottom: `1px solid ${ds.border}` }
const lab = { display: 'block', fontSize: 11, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 5 }
const inp = { width: '100%', boxSizing: 'border-box', padding: '9px 12px', border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md, fontSize: 13.5, color: ds.dark, background: '#fff' }
const btnP = { background: ds.teal, color: '#fff', border: 'none', borderRadius: ds.radius.md, padding: '9px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne }
const btnG = { background: '#fff', color: ds.teal, border: `1.5px solid ${ds.teal}`, borderRadius: ds.radius.md, padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }

export default function BookingSettings() {
  const [tab, setTab] = useState('calendar')
  const [cfg, setCfg] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => { getBookingSettings().then((r) => setCfg(r.data)).catch((e) => setErr(e?.response?.data?.detail?.code === 'PLAN_REQUIRED' ? 'Booking is not included in this plan.' : apiError(e, 'Could not load booking settings. Please refresh and try again.'))) }, [])
  if (err) return <p style={{ color: ds.red, padding: 24 }}>⚠ {err}</p>
  if (!cfg) return <p style={{ color: ds.gray, padding: 24 }}>Loading booking…</p>

  const tabBtn = (id, text) => (
    <button key={id} onClick={() => setTab(id)} aria-pressed={tab === id}
      style={{ padding: '8px 18px', borderRadius: 20, border: `1.5px solid ${tab === id ? ds.teal : ds.border}`, background: tab === id ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>{text}</button>
  )
  return (
    <div style={{ maxWidth: 860 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>{tabBtn('calendar', 'Calendar')}{tabBtn('settings', 'Settings')}</div>
      {!cfg.native_enabled && tab === 'calendar' && (
        <p style={{ ...card, color: ds.gray, fontSize: 13.5 }}>Online booking is switched off. Open <b>Settings</b> to turn it on and set your hours.</p>
      )}
      {tab === 'calendar' ? <CalendarView label={cfg.label} /> : <SettingsView cfg={cfg} onCfg={setCfg} />}
    </div>
  )
}

// ───────────────────────────── calendar ─────────────────────────────

const startOfWeek = (d) => { const x = new Date(d); const k = (x.getDay() + 6) % 7; x.setDate(x.getDate() - k); x.setHours(0, 0, 0, 0); return x }
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const STATUS = { pending_assignment: ['Needs approval', '#FFFBEB', '#92400E'], confirmed: ['Confirmed', '#F0FFF4', '#276749'], attended: ['Attended', '#EBF8FF', '#2B6CB0'], no_show: ['No-show', '#FFF5F5', '#C53030'], rescheduled: ['Moved', '#FAF5FF', '#6B46C1'], cancelled: ['Cancelled', '#F3F4F6', '#6B7280'] }

function CalendarView({ label }) {
  const [week, setWeek] = useState(startOfWeek(new Date()))
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  const load = useCallback(() => {
    setRows(null)
    const end = new Date(week); end.setDate(end.getDate() + 6)
    getBookingsFeed(ymd(week), ymd(end)).then((r) => setRows(r.data || [])).catch((e) => { setErr(apiError(e)); setRows([]) })
  }, [week])
  useEffect(() => { load() }, [load])

  const days = [...Array(7)].map((_, i) => { const d = new Date(week); d.setDate(d.getDate() + i); return d })
  const shift = (n) => { const d = new Date(week); d.setDate(d.getDate() + n); setWeek(d) }
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <button style={btnG} onClick={() => shift(-7)} aria-label="Previous week">‹</button>
        <b style={{ fontFamily: ds.fontSyne, color: ds.dark }}>{days[0].toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} – {days[6].toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</b>
        <button style={btnG} onClick={() => shift(7)} aria-label="Next week">›</button>
        <button style={btnG} onClick={() => setWeek(startOfWeek(new Date()))}>This week</button>
      </div>
      {err && <p style={{ color: ds.red }}>⚠ {err}</p>}
      {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {rows && days.map((d) => {
        const key = ymd(d)
        const todays = rows.filter((r) => r.scheduled_at && ymd(new Date(r.scheduled_at)) === key && r.status !== 'rescheduled')
        return (
          <div key={key} style={{ ...card, padding: '12px 18px', marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: todays.length ? 8 : 0 }}>
              {d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}{!todays.length && <span style={{ fontWeight: 500, textTransform: 'none' }}> · nothing booked</span>}
            </div>
            {todays.map((r) => {
              const s = STATUS[r.status] || STATUS.confirmed
              return (
                <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderTop: `1px solid ${ds.border}`, flexWrap: 'wrap' }}>
                  <b style={{ minWidth: 74, fontSize: 14 }}>{new Date(r.scheduled_at).toLocaleTimeString('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase()}</b>
                  <span style={{ flex: 1, fontSize: 14, color: ds.dark }}>{r.leads?.full_name || 'Lead'} <span style={{ color: ds.gray, fontSize: 12 }}>· {label}</span></span>
                  <span style={{ background: s[1], color: s[2], borderRadius: 20, padding: '3px 10px', fontSize: 11.5, fontWeight: 600 }}>{s[0]}</span>
                  <BookingRowActions booking={r} onChanged={load} />
                </div>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

// ───────────────────────────── settings ─────────────────────────────

function SettingsView({ cfg, onCfg }) {
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(cfg)
  const [reps, setReps] = useState([])
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  // BOOKING-2A: people who can own a booking (active, sales / success / manager roles)
  useEffect(() => {
    adminSvc.listUsers().then((res) => setReps((res || []).filter((u) => u.is_active &&
      ['sales_agent', 'customer_success', 'owner', 'ops_manager', 'admin'].includes(u.roles?.template)))).catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true); setMsg(null)
    try {
      const r = await saveBookingSettings({
        native_enabled: !!form.native_enabled, label: form.label,
        cancel_cutoff_hours: Number(form.cancel_cutoff_hours) || 0,
        auto_send_link: !!form.auto_send_link, default_rep_id: form.default_rep_id || null,
      })
      onCfg(r.data); setForm(r.data); setMsg({ ok: true, t: 'Saved.' })
    } catch (e) { setMsg({ ok: false, t: apiError(e) }) } finally { setSaving(false) }
  }

  return (
    <div>
      <div style={card}>
        <p style={title}>Online booking</p>
        <label style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 14, marginBottom: 14, cursor: 'pointer' }}>
          <input type="checkbox" checked={!!form.native_enabled} onChange={(e) => set('native_enabled', e.target.checked)} />
          <span><b>Let people book a time online</b><br /><span style={{ fontSize: 12, color: ds.gray }}>Turns on open slots, instant confirmation and booking links.</span></span>
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 14 }}>
          <div><label style={lab} htmlFor="bk-label">What do you call it?</label>
            <input id="bk-label" style={inp} value={form.label || ''} maxLength={40} onChange={(e) => set('label', e.target.value)} placeholder="consultation" />
            <p style={{ fontSize: 11.5, color: ds.gray, margin: '5px 0 0' }}>Shown to customers, e.g. "your consultation". Use appointment, visit, demo…</p></div>
          <div><label style={lab} htmlFor="bk-cut">Cancel / change up to (hours before)</label>
            <input id="bk-cut" type="number" min={0} max={720} style={inp} value={form.cancel_cutoff_hours ?? 24} onChange={(e) => set('cancel_cutoff_hours', e.target.value)} />
            <p style={{ fontSize: 11.5, color: ds.gray, margin: '5px 0 0' }}>0 means customers can change it any time.</p></div>
          <div><label style={lab} htmlFor="bk-rep">Who takes new bookings?</label>
            <select id="bk-rep" style={inp} value={form.default_rep_id || ''} onChange={(e) => set('default_rep_id', e.target.value)}>
              <option value="">Share between the team</option>
              {reps.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email}</option>)}
            </select>
            <p style={{ fontSize: 11.5, color: ds.gray, margin: '5px 0 0' }}>Pick one person to get every booking, or share them round the team.</p></div>
        </div>
        <label style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 14, marginTop: 16, cursor: 'pointer' }}>
          <input type="checkbox" checked={!!form.auto_send_link} onChange={(e) => set('auto_send_link', e.target.checked)} />
          <span><b>Send the booking link automatically</b><br /><span style={{ fontSize: 12, color: ds.gray }}>Once, on WhatsApp, when a customer finishes the questions. Never sent twice to the same person.</span></span>
        </label>
        <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
          <button style={btnP} disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save'}</button>
          {msg && <span role="status" style={{ fontSize: 13, color: msg.ok ? '#276749' : ds.red }}>{msg.t}</span>}
        </div>
      </div>
      {cfg.native_enabled && (<><Services /><Hours /><TimeOff /></>)}
    </div>
  )
}

function Services() {
  const [list, setList] = useState(null)
  const [err, setErr] = useState(null)
  const load = () => listBookingServices().then((r) => setList(r.data || [])).catch((e) => setErr(apiError(e)))
  useEffect(() => { load() }, [])
  const patch = async (s, p) => { try { await updateBookingService(s.id, p); load() } catch (e) { setErr(apiError(e)) } }
  const add = async () => { try { await createBookingService({ name: 'New service', duration_minutes: 30 }); load() } catch (e) { setErr(apiError(e)) } }
  const del = async (s) => { if (window.confirm(`Remove "${s.name}"? Existing bookings are kept.`)) { try { await deleteBookingService(s.id); load() } catch (e) { setErr(apiError(e)) } } }
  return (
    <div style={card}>
      <p style={title}>Services</p>
      {err && <p className="bk-err">{err}</p>}
      {(list || []).map((s) => <ServiceRow key={s.id} s={s} onSave={(p) => patch(s, p)} onDelete={() => del(s)} />)}
      <button style={btnG} onClick={add}>+ Add service</button>
    </div>
  )
}

function ServiceRow({ s, onSave, onDelete }) {
  const [f, setF] = useState(s)
  const dirty = JSON.stringify(f) !== JSON.stringify(s)
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  return (
    <div style={{ border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 14, marginBottom: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
        <div style={{ gridColumn: 'span 2' }}><label style={lab}>Name</label><input style={inp} value={f.name} onChange={(e) => set('name', e.target.value)} /></div>
        <div><label style={lab}>Length (min)</label><input type="number" style={inp} value={f.duration_minutes} min={5} max={480} onChange={(e) => set('duration_minutes', Number(e.target.value))} /></div>
        <div><label style={lab}>Gap after (min)</label><input type="number" style={inp} value={f.buffer_after_minutes} min={0} max={240} onChange={(e) => set('buffer_after_minutes', Number(e.target.value))} /></div>
        <div><label style={lab}>Where</label>
          <select style={inp} value={f.medium} onChange={(e) => set('medium', e.target.value)}>
            <option value="virtual">Online</option><option value="in_person">In person</option><option value="phone">Phone call</option>
          </select></div>
        <div><label style={lab}>Earliest (hours ahead)</label><input type="number" style={inp} value={f.min_notice_hours} min={0} onChange={(e) => set('min_notice_hours', Number(e.target.value))} /></div>
        <div><label style={lab}>Book up to (days ahead)</label><input type="number" style={inp} value={f.window_days} min={1} max={365} onChange={(e) => set('window_days', Number(e.target.value))} /></div>
        <div style={{ gridColumn: '1 / -1' }}><label style={lab}>Address or details shown to the customer</label><input style={inp} value={f.location_text || ''} onChange={(e) => set('location_text', e.target.value)} /></div>
      </div>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center', marginTop: 10, fontSize: 13 }}>
        <label style={{ cursor: 'pointer' }}><input type="checkbox" checked={!!f.requires_approval} onChange={(e) => set('requires_approval', e.target.checked)} /> A person must approve each booking</label>
        <label style={{ cursor: 'pointer' }}><input type="checkbox" checked={!!f.active} onChange={(e) => set('active', e.target.checked)} /> Open for booking</label>
        <span style={{ flex: 1 }} />
        {dirty && <button style={btnP} onClick={() => onSave({ name: f.name, duration_minutes: f.duration_minutes, buffer_after_minutes: f.buffer_after_minutes, medium: f.medium, min_notice_hours: f.min_notice_hours, window_days: f.window_days, location_text: f.location_text, requires_approval: f.requires_approval, active: f.active })}>Save service</button>}
        <button style={{ ...btnG, color: '#C53030', borderColor: '#F3B5B5' }} onClick={onDelete}>Remove</button>
      </div>
    </div>
  )
}

function Hours() {
  const [rows, setRows] = useState(null)   // [{weekday,start_time,end_time}]
  const [msg, setMsg] = useState(null)
  useEffect(() => { getBookingHours().then((r) => setRows((r.data || []).map((x) => ({ weekday: x.weekday, start_time: String(x.start_time).slice(0, 5), end_time: String(x.end_time).slice(0, 5) })))) .catch((e) => setMsg({ ok: false, t: apiError(e) })) }, [])
  if (!rows) return <div style={card}><p style={title}>Weekly hours</p><p style={{ color: ds.gray }}>Loading…</p></div>
  const upd = (i, k, v) => setRows((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x)))
  const del = (i) => setRows((r) => r.filter((_, j) => j !== i))
  const add = (w) => setRows((r) => [...r, { weekday: w, start_time: '09:00', end_time: '17:00' }])
  const save = async () => {
    setMsg(null)
    try { await saveBookingHours(rows); setMsg({ ok: true, t: 'Hours saved.' }) } catch (e) { setMsg({ ok: false, t: apiError(e) }) }
  }
  return (
    <div style={card}>
      <p style={title}>Weekly hours <span style={{ fontWeight: 400, color: ds.gray }}>(when people can book)</span></p>
      {DAYS.map((name, w) => {
        const mine = rows.map((r, i) => ({ r, i })).filter((x) => x.r.weekday === w)
        return (
          <div key={name} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', flexWrap: 'wrap' }}>
            <span style={{ width: 96, fontSize: 13.5, fontWeight: 600 }}>{name}</span>
            {mine.length === 0 && <span style={{ color: ds.gray, fontSize: 13 }}>Closed</span>}
            {mine.map(({ r, i }) => (
              <span key={i} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <input aria-label={`${name} from`} type="time" value={r.start_time} onChange={(e) => upd(i, 'start_time', e.target.value)} style={{ ...inp, width: 118 }} />
                to
                <input aria-label={`${name} to`} type="time" value={r.end_time} onChange={(e) => upd(i, 'end_time', e.target.value)} style={{ ...inp, width: 118 }} />
                <button onClick={() => del(i)} aria-label={`Remove ${name} hours`} style={{ border: 'none', background: 'none', color: ds.gray, cursor: 'pointer', fontSize: 18 }}>×</button>
              </span>
            ))}
            <button onClick={() => add(w)} style={{ ...btnG, padding: '5px 10px', fontSize: 12 }}>+ Add hours</button>
          </div>
        )
      })}
      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button style={btnP} onClick={save}>Save hours</button>
        {msg && <span role="status" style={{ fontSize: 13, color: msg.ok ? '#276749' : ds.red }}>{msg.t}</span>}
      </div>
    </div>
  )
}

function TimeOff() {
  const [list, setList] = useState([])
  const [f, setF] = useState({ starts: '', ends: '', reason: '' })
  const [err, setErr] = useState(null)
  const load = () => listBookingBlocks().then((r) => setList(r.data || [])).catch((e) => setErr(apiError(e)))
  useEffect(() => { load() }, [])
  const add = async () => {
    setErr(null)
    if (!f.starts || !f.ends) { setErr('Pick a start and an end.'); return }
    try { await addBookingBlock({ starts_at: new Date(f.starts).toISOString(), ends_at: new Date(f.ends).toISOString(), reason: f.reason || undefined }); setF({ starts: '', ends: '', reason: '' }); load() }
    catch (e) { setErr(apiError(e)) }
  }
  const fmt = (iso) => new Date(iso).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true })
  return (
    <div style={card}>
      <p style={title}>Time off <span style={{ fontWeight: 400, color: ds.gray }}>(holidays, leave, closures)</span></p>
      {list.map((b) => (
        <div key={b.id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', fontSize: 13.5 }}>
          <span style={{ flex: 1 }}>{fmt(b.starts_at)} → {fmt(b.ends_at)}{b.reason ? ` · ${b.reason}` : ''}</span>
          <button style={{ ...btnG, padding: '4px 10px', fontSize: 12 }} onClick={() => deleteBookingBlock(b.id).then(load)}>Remove</button>
        </div>
      ))}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginTop: 10 }}>
        <div><label style={lab}>From</label><input type="datetime-local" style={inp} value={f.starts} onChange={(e) => setF({ ...f, starts: e.target.value })} /></div>
        <div><label style={lab}>Until</label><input type="datetime-local" style={inp} value={f.ends} onChange={(e) => setF({ ...f, ends: e.target.value })} /></div>
        <div><label style={lab}>Reason</label><input style={inp} value={f.reason} maxLength={200} onChange={(e) => setF({ ...f, reason: e.target.value })} /></div>
      </div>
      {err && <p className="bk-err">{err}</p>}
      <button style={{ ...btnG, marginTop: 10 }} onClick={add}>+ Add time off</button>
    </div>
  )
}
