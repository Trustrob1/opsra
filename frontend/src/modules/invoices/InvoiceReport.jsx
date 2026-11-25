/**
 * frontend/src/modules/invoices/InvoiceReport.jsx
 * INV-5 — the Report tab: what was invoiced and collected in a period, money owed now by how late it is, payment
 * methods, quote win rate, the best-paying customers, and 12 months of invoiced vs collected (chart or table).
 * Download CSV gives the period's receipts for the accountant.
 */
import { useEffect, useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getInvoiceReport, downloadReceiptsCsv, apiError } from '../../services/invoices.service'
import { naira, nairaShort, METHOD_LABEL, card, btnG, disabled } from './invoiceUi'

// Validated pair (dataviz validator, light surface): both pass lightness, chroma, CVD and 3:1 contrast.
const C_INVOICED = '#D97A2B'
const C_COLLECTED = ds.teal
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monthLabel = (k) => `${MONTHS[Number(k.slice(5, 7)) - 1]} ${k.slice(2, 4)}`

function periods() {
  const t = new Date()
  const y = t.getFullYear(), m = t.getMonth()
  return [
    ['this_month', 'This month', ymd(new Date(y, m, 1)), ymd(t)],
    ['last_month', 'Last month', ymd(new Date(y, m - 1, 1)), ymd(new Date(y, m, 0))],
    ['this_year', 'This year', ymd(new Date(y, 0, 1)), ymd(t)],
    ['last_12', 'Last 12 months', ymd(new Date(y, m - 11, 1)), ymd(t)],
  ]
}

export default function InvoiceReport() {
  const isMobile = useIsMobile()
  const opts = useMemo(periods, [])
  const [pick, setPick] = useState('this_month')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [view, setView] = useState('chart')
  const [busy, setBusy] = useState(false)
  const [, , start, end] = opts.find((o) => o[0] === pick)

  useEffect(() => {
    let live = true
    getInvoiceReport(start, end).then((d) => { if (live) { setData(d); setErr('') } })
      .catch((e) => { if (live) setErr(apiError(e, 'Could not load the report. Please refresh.')) })
    return () => { live = false }
  }, [start, end])

  const csv = async () => {
    setBusy(true)
    try { await downloadReceiptsCsv(start, end) } catch (e) { setErr(apiError(e, 'Could not make the file.')) } finally { setBusy(false) }
  }

  const tile = (label, value, sub, tone) => (
    <div style={{ ...card, padding: '14px 16px', flex: '1 1 160px' }}>
      <div style={{ fontSize: 12.5, color: ds.gray, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone || ds.dark, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12.5, color: ds.gray, marginTop: 2 }}>{sub}</div>}
    </div>
  )
  const chip = (active, text, onClick) => (
    <button key={text} type="button" onClick={onClick} aria-pressed={active}
      style={{ padding: '0 14px', minHeight: 36, borderRadius: 999, border: `1.5px solid ${active ? ds.teal : ds.border}`, background: active ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13.5, cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: ds.fontDm }}>{text}</button>
  )
  const h = { margin: '0 0 12px', fontSize: 15, color: ds.dark }

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', flex: 1 }}>{opts.map(([k, label]) => chip(pick === k, label, () => setPick(k)))}</div>
        <button type="button" style={disabled(btnG, busy)} disabled={busy} onClick={csv}><Download size={16} />{busy ? 'Preparing…' : 'Receipts CSV'}</button>
      </div>
      {err && <p role="alert" style={{ color: ds.red, margin: 0 }}>{err}</p>}
      {!data && !err && <p style={{ color: ds.gray }}>Loading…</p>}
      {data && (
        <>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {tile('Invoiced', nairaShort(data.invoiced.amount), `${data.invoiced.count} invoice${data.invoiced.count === 1 ? '' : 's'}`)}
            {tile('Collected', nairaShort(data.collected.amount), `${data.collected.count} receipt${data.collected.count === 1 ? '' : 's'}`, ds.green)}
            {tile('Owed to you now', nairaShort(data.owed_now.amount), `${nairaShort(data.owed_now.overdue)} of it overdue`, data.owed_now.overdue ? ds.red : undefined)}
            {tile('Quotes won', data.quotes.win_rate == null ? '—' : `${data.quotes.win_rate}%`, `${data.quotes.accepted} of ${data.quotes.issued} quotes accepted`)}
          </div>

          <section style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
              <h3 style={{ ...h, margin: 0, flex: 1 }}>Invoiced and collected, last 12 months</h3>
              <div role="group" aria-label="View" style={{ display: 'flex', gap: 6 }}>
                {chip(view === 'chart', 'Chart', () => setView('chart'))}
                {chip(view === 'table', 'Table', () => setView('table'))}
              </div>
            </div>
            {view === 'chart' ? (
              <>
                <div style={{ display: 'flex', gap: 16, fontSize: 12.5, color: ds.gray, marginBottom: 8 }}>
                  <Key color={C_INVOICED} label="Invoiced" />
                  <Key color={C_COLLECTED} label="Collected" />
                </div>
                <div style={{ width: '100%', height: isMobile ? 220 : 280 }}>
                  <ResponsiveContainer>
                    <BarChart data={data.months.map((m) => ({ ...m, label: monthLabel(m.month) }))} margin={{ top: 8, right: 8, bottom: 0, left: 4 }} barGap={2} barCategoryGap="22%">
                      <CartesianGrid vertical={false} stroke="#EEF1F5" />
                      <XAxis dataKey="label" tick={{ fontSize: 11, fill: ds.gray }} axisLine={{ stroke: ds.border }} tickLine={false} interval={isMobile ? 1 : 0} />
                      <YAxis tickFormatter={short} tick={{ fontSize: 11, fill: ds.gray }} axisLine={false} tickLine={false} width={52} />
                      <Tooltip content={<Tip />} cursor={{ fill: 'rgba(36,103,227,0.06)' }} />
                      <Bar dataKey="invoiced" name="Invoiced" fill={C_INVOICED} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
                      <Bar dataKey="collected" name="Collected" fill={C_COLLECTED} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                  <thead><tr style={{ color: ds.gray, fontSize: 12.5, textAlign: 'left' }}><th style={{ padding: 6 }}>Month</th><th style={{ padding: 6, textAlign: 'right' }}>Invoiced</th><th style={{ padding: 6, textAlign: 'right' }}>Collected</th></tr></thead>
                  <tbody>{data.months.map((m) => (
                    <tr key={m.month} style={{ borderTop: `1px solid ${ds.border}` }}>
                      <td style={{ padding: 6 }}>{monthLabel(m.month)}</td>
                      <td style={{ padding: 6, textAlign: 'right', whiteSpace: 'nowrap' }}>{naira(m.invoiced)}</td>
                      <td style={{ padding: 6, textAlign: 'right', whiteSpace: 'nowrap' }}>{naira(m.collected)}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}
          </section>

          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, 1fr)', gap: 12, alignItems: 'start' }}>
            <section style={card}>
              <h3 style={h}>Owed now, by how late</h3>
              {data.owed_now.aging.map((a) => (
                <Line2 key={a.key} k={<>{a.label} <span style={{ color: ds.gray }}>({a.count})</span></>} v={naira(a.amount)} red={a.key !== 'not_due' && a.amount > 0} />
              ))}
            </section>
            <section style={card}>
              <h3 style={h}>How customers paid</h3>
              {data.collected.by_method.length === 0 ? <p style={{ color: ds.gray, margin: 0 }}>No payments in this period.</p>
                : data.collected.by_method.map((m) => <Line2 key={m.method} k={METHOD_LABEL[m.method] || m.method} v={naira(m.amount)} />)}
            </section>
            <section style={card}>
              <h3 style={h}>Customers who paid the most</h3>
              {data.top_customers.length === 0 ? <p style={{ color: ds.gray, margin: 0 }}>No payments in this period.</p>
                : data.top_customers.map((c, i) => <Line2 key={`${c.name}-${i}`} k={c.name} v={naira(c.amount)} />)}
            </section>
          </div>
        </>
      )}
    </div>
  )
}

const short = (n) => (n >= 1e6 ? `₦${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}m` : n >= 1e3 ? `₦${Math.round(n / 1e3)}k` : `₦${n}`)

function Key({ color, label }) {
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: color }} />{label}</span>
}
function Line2({ k, v, red }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '6px 0', borderTop: `1px solid ${ds.border}`, fontSize: 14 }}><span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{k}</span><b style={{ whiteSpace: 'nowrap', color: red ? ds.red : ds.dark }}>{v}</b></div>
}
function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 8, padding: '8px 10px', fontSize: 12.5, boxShadow: ds.cardShadow }}>
      <div style={{ fontWeight: 700, color: ds.dark, marginBottom: 4 }}>{label}</div>
      {payload.map((p) => <div key={p.dataKey} style={{ display: 'flex', gap: 8, alignItems: 'center', color: ds.dark }}><Key color={p.color} label={p.name} /><b style={{ marginLeft: 'auto' }}>{naira(p.value)}</b></div>)}
    </div>
  )
}
