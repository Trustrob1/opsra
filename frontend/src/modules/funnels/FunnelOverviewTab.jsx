/**
 * frontend/src/modules/funnels/FunnelOverviewTab.jsx
 * FUNNEL-1B — Overview: KPIs, template budget meter, leads-vs-payments by day,
 * per-ad-code performance with the pause flag, daily ad spend entry, referrals.
 *
 * Chart (dataviz method): change over time → line chart; 2 series of the same unit
 * (count) on ONE axis; series colours validated (CVD ΔE 17.3, normal ΔE 27.2, ≥3:1);
 * legend + end-of-line direct labels; crosshair tooltip; table view toggle.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { AlertTriangle, Users, Wallet, Ticket, Tag, CircleAlert, Mail, Save, TrendingUp } from 'lucide-react'
import { getOverview, getAdSpend, saveAdSpend, errorMessage } from '../../services/funnels.service'
import { Card, Kpi, SectionTitle, Button, Badge, Notice, Spinner, Empty, Segmented } from './funnelUi'
import { T, INPUT, money, num, pct, dateOnly, todayLagos } from './funnelKit'

export default function FunnelOverviewTab({ funnel, isActive, canEdit, isMobile, overview: parentOverview, reloadOverview, showToast, tick, goTo }) {
  const [ov, setOv] = useState(parentOverview)
  const [loading, setLoading] = useState(!parentOverview)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setOv(await getOverview(funnel.id))
    } catch (e) {
      setError(errorMessage(e, 'Could not load the numbers.'))
    } finally {
      setLoading(false)
    }
  }, [funnel.id])

  useEffect(() => { if (isActive) load() }, [isActive, load, tick])
  useEffect(() => { if (parentOverview) setOv(parentOverview) }, [parentOverview])

  if (loading) return <Spinner />
  if (error) return <Notice tone="bad">{error}</Notice>
  if (!ov) return null

  const windowLabel = funnel.pricing_mode === 'deadline' ? 'Paid before deadline' : `Paid within ${funnel.window_hours}h`
  const kpiGrid = { display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? 145 : 165}px, 1fr))`, gap: 12 }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={kpiGrid}>
        <Kpi label="Leads" icon={Users} value={num(ov.leads)} sub={`${pct(ov.conversion)} paid`} />
        <Kpi label="Paid seats" icon={Ticket} value={num(ov.seats)} sub={`${num(ov.paid)} buyers`} />
        <Kpi label="Revenue" icon={Wallet} value={money(ov.revenue)} sub={ov.roas ? `${ov.roas}× return on spend` : 'No spend entered yet'} />
        <Kpi label="Cost per payment" icon={TrendingUp} value={money(ov.cost_per_payment)} sub={`Ad spend ${money(ov.ad_spend)}`} />
        <Kpi label={windowLabel} icon={Tag} value={pct(ov.conversion_in_window)} sub="of all leads" />
        <Kpi label="Need you" icon={CircleAlert} value={num(ov.needs_human)} tone={ov.needs_human ? 'bad' : undefined}
          sub={ov.needs_human ? 'Open Leads → Needs you' : 'All handled'} />
        <Kpi label="Missing Gmail" icon={Mail} value={num(ov.missing_email)} tone={ov.missing_email ? 'warn' : undefined} sub="paid, no Meet email" />
      </div>

      {ov.template_budget?.active && <BudgetMeter b={ov.template_budget} onSetup={() => goTo('setup')} />}

      <DailyChart rows={ov.by_day} isMobile={isMobile} />

      <AdCodeTable rows={ov.by_ad_code} threshold={ov.pause_threshold} isMobile={isMobile} />

      <SpendEntry funnel={funnel} canEdit={canEdit} isMobile={isMobile} showToast={showToast} isActive={isActive}
        onSaved={() => { load(); reloadOverview?.() }} />

      <Card>
        <SectionTitle title="Referrals" hint="Buyers whose code brought in paying friends. 1 paid friend → priority question. 3 → ticket refund (paid by hand)." />
        {ov.referrers?.length ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr>{['Referrer', 'Code', 'Paid friends', 'Reward'].map((h, i) => <Th key={h} right={i === 2}>{h}</Th>)}</tr></thead>
            <tbody>
              {ov.referrers.slice(0, 20).map((r) => (
                <tr key={r.registration_id} style={{ borderTop: `1px solid ${T.line}` }}>
                  <Td>{r.name || '—'}</Td>
                  <Td><code style={{ fontSize: 12 }}>{r.ref_code}</code></Td>
                  <Td right className="tnum">{r.paid_referrals}</Td>
                  <Td>{r.paid_referrals >= 3 ? <Badge tone="good">Refund due</Badge> : r.paid_referrals >= 1 ? <Badge tone="info">Priority Q&amp;A</Badge> : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No paid referrals yet.</p>}
      </Card>
    </div>
  )
}

function Th({ children, right }) {
  return <th style={{ textAlign: right ? 'right' : 'left', fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px', padding: '8px 10px', whiteSpace: 'nowrap' }}>{children}</th>
}
function Td({ children, right, className, style }) {
  return <td className={className} style={{ textAlign: right ? 'right' : 'left', padding: '10px', color: T.ink, verticalAlign: 'middle', ...style }}>{children}</td>
}

function BudgetMeter({ b, onSetup }) {
  const used = b.cap ? Math.min(1, b.spent / b.cap) : 0
  const tone = used >= 1 ? 'bad' : used >= 0.8 ? 'warn' : 'good'
  const bar = tone === 'bad' ? T.bad : tone === 'warn' ? '#C98A00' : T.teal
  return (
    <Card>
      <SectionTitle title="Template message budget"
        hint="Meta charges for template messages (reminders outside the 24-hour window and broadcasts). Free replies inside the window don’t count."
        right={<Button size="sm" variant="ghost" onClick={onSetup}>Change cap</Button>} />
      <div role="meter" aria-valuemin={0} aria-valuemax={b.cap} aria-valuenow={b.spent} aria-label="Template budget used"
        style={{ height: 10, background: '#EEF4F6', borderRadius: 6, overflow: 'hidden' }}>
        <div style={{ width: `${used * 100}%`, height: '100%', background: bar, borderRadius: 6 }} />
      </div>
      <div className="tnum" style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 8, fontSize: 12.5, color: T.soft, flexWrap: 'wrap' }}>
        <span>{money(b.spent)} of {money(b.cap)} · {num(b.messages_used)} messages at ~{money(b.cost_per_message)}</span>
        <span>{tone === 'bad'
          ? <Badge tone="bad" icon={AlertTriangle}>Cap reached: templates paused</Badge>
          : <>{num(b.remaining_messages)} messages left</>}</span>
      </div>
    </Card>
  )
}

function DailyChart({ rows, isMobile }) {
  const [view, setView] = useState('chart')
  const data = useMemo(() => (rows || []).map((r) => ({ ...r, label: dateOnly(`${r.date}T12:00:00+01:00`) })), [rows])
  const last = data[data.length - 1]
  return (
    <Card>
      <SectionTitle title="Leads and payments by day"
        right={<Segmented ariaLabel="View" value={view} onChange={setView} options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} />} />
      {data.length === 0 ? (
        <Empty title="No leads yet" text="The first WhatsApp message to your funnel number shows up here." />
      ) : view === 'chart' ? (
        <>
          <div style={{ display: 'flex', gap: 16, fontSize: 12.5, color: T.soft, marginBottom: 8 }} aria-hidden="true">
            <LegendKey color={T.seriesLeads} label="Leads" />
            <LegendKey color={T.seriesPaid} label="Payments" dashed />
          </div>
          <div style={{ width: '100%', height: isMobile ? 220 : 260 }}>
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 8, right: isMobile ? 16 : 70, bottom: 0, left: -18 }}>
                <CartesianGrid vertical={false} stroke="#EEF3F5" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: T.muted }} axisLine={{ stroke: '#DCE6EA' }} tickLine={false} minTickGap={16} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: T.muted }} axisLine={false} tickLine={false} width={48} />
                <Tooltip content={<ChartTip />} cursor={{ stroke: '#B9CDD5', strokeWidth: 1 }} />
                <Line type="monotone" dataKey="leads" name="Leads" stroke={T.seriesLeads} strokeWidth={2}
                  dot={data.length <= 14 ? { r: 4, strokeWidth: 2, stroke: '#fff', fill: T.seriesLeads } : false} activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }}
                  label={isMobile ? false : endLabel(data.length, 'Leads')} isAnimationActive={false} />
                <Line type="monotone" dataKey="paid" name="Payments" stroke={T.seriesPaid} strokeWidth={2} strokeDasharray="5 3"
                  dot={data.length <= 14 ? { r: 4, strokeWidth: 2, stroke: '#fff', fill: T.seriesPaid, strokeDasharray: '0' } : false} activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }}
                  label={isMobile ? false : endLabel(data.length, 'Payments')} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {last && <p className="tnum" style={{ margin: '6px 0 0', fontSize: 12, color: T.muted }}>Latest day ({last.label}): {last.leads} leads, {last.paid} payments, {money(last.revenue)}.</p>}
        </>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr><Th>Day</Th><Th right>Leads</Th><Th right>Payments</Th><Th right>Revenue</Th></tr></thead>
            <tbody className="tnum">
              {[...data].reverse().map((r) => (
                <tr key={r.date} style={{ borderTop: `1px solid ${T.line}` }}>
                  <Td>{r.label}</Td><Td right>{r.leads}</Td><Td right>{r.paid}</Td><Td right>{money(r.revenue)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

// End-of-line direct label (selective: only the last point, never every point).
const endLabel = (len, text) => (props) => {
  const { x, y, index } = props
  if (index !== len - 1) return null
  return <text x={x + 10} y={y + 4} fontSize={11.5} fill={T.soft} fontWeight={600}>{text}</text>
}

function LegendKey({ color, label, dashed }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <svg width="20" height="8" aria-hidden="true"><line x1="0" y1="4" x2="20" y2="4" stroke={color} strokeWidth="2" strokeDasharray={dashed ? '5 3' : undefined} /></svg>
      {label}
    </span>
  )
}

function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="tnum" style={{ background: '#fff', border: `1px solid ${T.line}`, borderRadius: 8, padding: '9px 11px', fontSize: 12, boxShadow: '0 2px 10px rgba(10,26,36,.12)' }}>
      <div style={{ fontWeight: 700, color: T.ink, marginBottom: 4 }}>{label}</div>
      <div style={{ color: T.soft }}>Leads: <strong style={{ color: T.ink }}>{row.leads}</strong></div>
      <div style={{ color: T.soft }}>Payments: <strong style={{ color: T.ink }}>{row.paid}</strong></div>
      <div style={{ color: T.soft }}>Revenue: <strong style={{ color: T.ink }}>{money(row.revenue)}</strong></div>
    </div>
  )
}

function AdCodeTable({ rows, threshold, isMobile }) {
  return (
    <Card>
      <SectionTitle title="Ad codes"
        hint={`Best cost per payment first. Flagged: ${money(threshold)}+ spent with no payment yet — consider pausing that ad.`} />
      {!rows?.length ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No leads or spend yet.</p> : isMobile ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r) => (
            <div key={r.code} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <strong style={{ fontSize: 14 }}>{r.code}</strong>
                {r.label && <span style={{ fontSize: 12, color: T.muted }}>{r.label}</span>}
                <span style={{ marginLeft: 'auto' }}>{r.pause_flag && <Badge tone="bad" icon={AlertTriangle}>Pause?</Badge>}</span>
              </div>
              <div className="tnum" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 12.5, color: T.soft }}>
                <span>Leads {num(r.leads)}</span><span>Paid {num(r.paid)}</span>
                <span>Spend {money(r.spend)}</span><span>Revenue {money(r.revenue)}</span>
                <span>Cost/lead {money(r.cost_per_lead)}</span><span>Cost/payment {money(r.cost_per_payment)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr>
              <Th>Code</Th><Th right>Leads</Th><Th right>Paid</Th><Th right>Conv.</Th><Th right>Revenue</Th>
              <Th right>Spend</Th><Th right>Cost / lead</Th><Th right>Cost / payment</Th><Th> </Th>
            </tr></thead>
            <tbody className="tnum">
              {rows.map((r) => (
                <tr key={r.code} style={{ borderTop: `1px solid ${T.line}` }}>
                  <Td><strong>{r.code}</strong>{r.label && <span style={{ color: T.muted, marginLeft: 6, fontSize: 12 }}>{r.label}</span>}</Td>
                  <Td right>{num(r.leads)}</Td>
                  <Td right>{num(r.paid)}</Td>
                  <Td right>{r.leads ? pct(r.paid / r.leads) : '—'}</Td>
                  <Td right>{money(r.revenue)}</Td>
                  <Td right>{money(r.spend)}</Td>
                  <Td right>{money(r.cost_per_lead)}</Td>
                  <Td right><strong>{money(r.cost_per_payment)}</strong></Td>
                  <Td>{r.pause_flag && <Badge tone="bad" icon={AlertTriangle} title="Spend passed the pause threshold with no payment">Pause?</Badge>}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function SpendEntry({ funnel, canEdit, isMobile, showToast, isActive, onSaved }) {
  const codes = (funnel.ad_codes || []).map((c) => c.code)
  const [day, setDay] = useState(todayLagos())
  const [values, setValues] = useState({})
  const [recent, setRecent] = useState([])
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const rows = await getAdSpend(funnel.id)
      setRecent(rows)
    } catch { setRecent([]) }
  }, [funnel.id])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  // Pre-fill the inputs with whatever was already saved for the chosen day.
  useEffect(() => {
    const v = {}
    recent.filter((r) => String(r.spend_date).slice(0, 10) === day).forEach((r) => { v[r.ad_code] = String(Number(r.amount)) })
    setValues(v)
  }, [day, recent])

  const save = async () => {
    const rows = codes.filter((c) => values[c] !== undefined && values[c] !== '')
      .map((c) => ({ date: day, ad_code: c, amount: Number(values[c]) }))
    if (!rows.length) { showToast('Enter at least one amount', 'bad'); return }
    if (rows.some((r) => Number.isNaN(r.amount) || r.amount < 0)) { showToast('Amounts must be 0 or more', 'bad'); return }
    setSaving(true)
    try {
      await saveAdSpend(funnel.id, rows)
      showToast(`Spend saved for ${dateOnly(`${day}T12:00:00+01:00`)}`)
      await load()
      onSaved?.()
    } catch (e) {
      showToast(errorMessage(e, 'Could not save spend'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const byDay = useMemo(() => {
    const m = {}
    recent.forEach((r) => { const d = String(r.spend_date).slice(0, 10); m[d] = (m[d] || 0) + Number(r.amount || 0) })
    return Object.entries(m).sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, 7)
  }, [recent])

  if (!codes.length) {
    return <Card><SectionTitle title="Daily ad spend" hint="Add ad codes in Setup to record spend per ad." /></Card>
  }

  return (
    <Card>
      <SectionTitle title="Daily ad spend" hint="Each evening, copy spend per ad from Ads Manager. Re-entering a day replaces it." />
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 2fr) minmax(0, 1fr)', gap: 20 }}>
        <div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 12 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>Day</span>
              <input type="date" style={{ ...INPUT, width: 170 }} value={day} max={todayLagos()} onChange={(e) => setDay(e.target.value)} />
            </label>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10 }}>
            {codes.map((c) => (
              <label key={c} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: T.ink }}>{c}</span>
                <input type="number" min={0} inputMode="decimal" disabled={!canEdit} className="tnum" placeholder="₦0"
                  style={INPUT} value={values[c] ?? ''} onChange={(e) => setValues((p) => ({ ...p, [c]: e.target.value }))} />
              </label>
            ))}
          </div>
          {canEdit && <div style={{ marginTop: 12 }}><Button variant="primary" icon={Save} loading={saving} onClick={save}>Save spend</Button></div>}
        </div>
        <div>
          <p style={{ fontSize: 12, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px', margin: '0 0 8px' }}>Last 7 days entered</p>
          {byDay.length ? (
            <ul className="tnum" style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 13 }}>
              {byDay.map(([d, v]) => (
                <li key={d} style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderTop: `1px solid ${T.line}` }}>
                  <button type="button" onClick={() => setDay(d)} style={{ border: 'none', background: 'none', padding: 0, color: T.teal, cursor: 'pointer', fontFamily: 'inherit', fontSize: 13 }}>
                    {dateOnly(`${d}T12:00:00+01:00`)}
                  </button>
                  <span>{money(v)}</span>
                </li>
              ))}
            </ul>
          ) : <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>Nothing entered yet.</p>}
        </div>
      </div>
    </Card>
  )
}
