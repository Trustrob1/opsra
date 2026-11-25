/**
 * frontend/src/modules/reports/ReportBits.jsx
 * REPORT-1 — pieces shared by the Sales report and the Inventory report: the period picker (quick ranges + dates),
 * the PDF / CSV download buttons, the number tiles and a plain table.
 */
import { useState } from 'react'
import { Download } from 'lucide-react'
import { ds } from '../../utils/ds'
import { card, inp, lab, btnG, disabled } from '../invoices/invoiceUi'

const pad = (n) => String(n).padStart(2, '0')
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const lagosNow = () => {   // Africa/Lagos is UTC+1 all year
  const n = new Date()
  return new Date(n.getTime() + (n.getTimezoneOffset() + 60) * 60000)
}
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }

function ranges() {
  const t = lagosNow()
  const monday = addDays(t, -((t.getDay() + 6) % 7))
  const firstThis = new Date(t.getFullYear(), t.getMonth(), 1)
  const firstLast = new Date(t.getFullYear(), t.getMonth() - 1, 1)
  return [
    ['today', 'Today', ymd(t), ymd(t)],
    ['yesterday', 'Yesterday', ymd(addDays(t, -1)), ymd(addDays(t, -1))],
    ['week', 'This week', ymd(monday), ymd(t)],
    ['lastweek', 'Last week', ymd(addDays(monday, -7)), ymd(addDays(monday, -1))],
    ['month', 'This month', ymd(firstThis), ymd(t)],
    ['lastmonth', 'Last month', ymd(firstLast), ymd(addDays(firstThis, -1))],
  ]
}

/** value: { start, end } (YYYY-MM-DD). Starts on This month when empty. */
export function PeriodPicker({ value, onChange }) {
  const list = ranges()
  const active = list.find(([, , s, e]) => s === value.start && e === value.end)?.[0]
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {list.map(([id, label, s, e]) => (
          <button key={id} type="button" aria-pressed={active === id} onClick={() => onChange({ start: s, end: e })}
            style={{ ...btnG, minHeight: 36, background: active === id ? ds.mint : '#fff', borderColor: active === id ? ds.teal : ds.border }}>
            {label}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <label style={{ minWidth: 150 }}><span style={lab}>From</span>
          <input type="date" style={inp} value={value.start} max={value.end} onChange={(e) => e.target.value && onChange({ ...value, start: e.target.value })} />
        </label>
        <label style={{ minWidth: 150 }}><span style={lab}>To</span>
          <input type="date" style={inp} value={value.end} min={value.start} onChange={(e) => e.target.value && onChange({ ...value, end: e.target.value })} />
        </label>
      </div>
    </div>
  )
}

/** onDownload(format) returns a promise. */
export function DownloadButtons({ onDownload }) {
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const go = (format) => {
    setBusy(format)
    setErr('')
    onDownload(format).catch(() => setErr('The download did not work. Please try again.')).finally(() => setBusy(''))
  }
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      {[['pdf', 'Download PDF'], ['csv', 'Download CSV']].map(([f, label]) => (
        <button key={f} type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => go(f)}>
          <Download size={16} />{busy === f ? 'Preparing…' : label}
        </button>
      ))}
      {err && <span role="alert" style={{ color: ds.red, fontSize: 13.5 }}>{err}</span>}
    </div>
  )
}

/** tiles: [[label, value]] */
export function Tiles({ tiles }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
      {tiles.map(([k, v]) => (
        <div key={k} style={{ ...card, padding: '12px 14px' }}>
          <div style={{ fontSize: 12, color: ds.gray, fontWeight: 600 }}>{k}</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: ds.dark, marginTop: 4 }}>{v}</div>
        </div>
      ))}
    </div>
  )
}

/** head: [label]; rows: [[cell]]; right: indexes of number columns. */
export function ReportTable({ title, head, rows, right = [], empty = 'Nothing in this period.' }) {
  const cell = (i) => ({ padding: '8px 10px', borderBottom: `1px solid ${ds.border}`, textAlign: right.includes(i) ? 'right' : 'left',
    whiteSpace: right.includes(i) ? 'nowrap' : 'normal', fontSize: 14 })
  return (
    <section style={{ ...card, padding: '14px 16px' }}>
      <h2 style={{ margin: '0 0 8px', fontSize: 16, color: ds.dark }}>{title}</h2>
      {rows.length === 0 ? <p style={{ margin: 0, color: ds.gray, fontSize: 14 }}>{empty}</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: ds.fontDm }}>
            <thead><tr>{head.map((h, i) => <th key={h || i} scope="col" style={{ ...cell(i), fontSize: 12, color: ds.gray, fontWeight: 600 }}>{h}</th>)}</tr></thead>
            <tbody>{rows.map((r, n) => <tr key={n}>{r.map((c, i) => <td key={i} style={cell(i)}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </section>
  )
}
