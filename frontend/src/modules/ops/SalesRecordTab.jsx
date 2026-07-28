/**
 * frontend/src/modules/ops/SalesRecordTab.jsx
 * REPORTS-DEPT-1 Phase 4c — Sales Record dashboard inside Business Activities.
 *
 * Filtering changes from Phase 4c:
 *   - Rep filter is now a dropdown of distinct rep_name values actually
 *     present in direct_sales (the literal text typed in the sheet) —
 *     NOT Opsra's registered users. A rep who never matched an Opsra
 *     user still filters and displays correctly.
 *   - Model filter is a dropdown sourced from the Commission Rates list
 *     (configured in the Commissions tab) — exact match, not free text.
 *   - Variant is a new, separate dropdown/column (e.g. "6x6"), split out
 *     from what used to be one combined "Model" string.
 *   - Date filtering is now the shared DateRangePresets control
 *     (Today/Yesterday/Last 30 days/Last Month/Last Year/Custom),
 *     defaulting to Today, rather than raw from/to inputs with no default.
 *
 * Two data sources, deliberately separate:
 *   - getDirectSalesSummary(): UNPAGINATED, drives every KPI/breakdown/
 *     chart on this page.
 *   - getDirectSales(): the existing paginated detail table underneath.
 *
 * Chart is hand-rolled SVG, matching GrowthDashboard.jsx's VelocitySection
 * pattern — no new charting library dependency.
 *
 * Owner/ops_manager only, matching backend RBAC.
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { ds } from '../../utils/ds'
import { getDirectSales, getDirectSalesSummary, getDirectSalesFilterOptions, getCommissionRates } from '../../services/growth.service'
import DateRangePresets from './DateRangePresets'

const INP = {
  padding:      '8px 10px',
  border:       '1px solid #D1D5DB',
  borderRadius: 8,
  fontSize:     13,
  outline:      'none',
  background:   'white',
  fontFamily:   'inherit',
}

const CARD = {
  background: 'white', border: '1px solid #E4EEF2', borderRadius: 12,
  padding: '16px 18px',
}

function Badge({ text, tone }) {
  const colours = {
    rec:  { bg: '#ECFDF5', text: '#059669' },
    pen:  { bg: '#FDF4E3', text: '#92601A' },
    none: { bg: '#F3F4F6', text: '#6B7280' },
  }[tone]
  return (
    <span style={{ background: colours.bg, color: colours.text, fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 20, whiteSpace: 'nowrap' }}>
      {text}
    </span>
  )
}

function Kpi({ label, value, accent }) {
  return (
    <div style={{ ...CARD, flex: 1 }}>
      <p style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.6px', margin: '0 0 6px' }}>{label}</p>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 24, color: accent ?? '#0a1a24', margin: 0 }}>{value}</p>
    </div>
  )
}

function BreakdownCard({ title, rows, formatValue }) {
  const max = Math.max(...rows.map(r => r.value), 1)
  return (
    <div style={{ ...CARD, flex: 1 }}>
      <p style={{ fontSize: 12.5, fontWeight: 700, color: '#0a1a24', margin: '0 0 12px' }}>{title}</p>
      {rows.length === 0 ? (
        <p style={{ fontSize: 12.5, color: '#9CA3AF', margin: 0 }}>No data yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map(r => (
            <div key={r.label}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 4 }}>
                <span style={{ color: '#0a1a24', fontWeight: 500 }}>{r.label}</span>
                <span style={{ color: '#7A9BAD' }}>{formatValue(r.value)}</span>
              </div>
              <div style={{ height: 6, borderRadius: 4, background: '#F0F7FA', overflow: 'hidden' }}>
                <div style={{ width: `${(r.value / max) * 100}%`, height: '100%', background: r.color ?? ds.teal, borderRadius: 4 }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RevenueChart({ points }) {
  if (!points || points.length === 0) {
    return <div style={{ color: '#9CA3AF', fontSize: 13, padding: '24px 0' }}>No data for this period.</div>
  }
  const max = Math.max(...points.map(p => p.amount), 1)
  const svgW = 700, svgH = 160, pad = 36

  const pts = points.map((p, i) => {
    const x = pad + (i / Math.max(points.length - 1, 1)) * (svgW - pad * 2)
    const y = svgH - pad - (p.amount / max) * (svgH - pad * 2)
    return { x, y, ...p }
  })

  const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${svgW} ${svgH}`} style={{ width: '100%', maxWidth: svgW, display: 'block' }}>
        {[0, 0.25, 0.5, 0.75, 1].map(f => {
          const y = svgH - pad - f * (svgH - pad * 2)
          return (
            <g key={f}>
              <line x1={pad} y1={y} x2={svgW - pad} y2={y} stroke="#f1f5f8" strokeWidth={1} />
              <text x={pad - 6} y={y + 4} fontSize={9} fill="#94a3b8" textAnchor="end" fontFamily={ds.fontDm}>
                {Math.round((f * max) / 1000)}k
              </text>
            </g>
          )
        })}
        <path d={`${pathD} L ${pts[pts.length - 1].x} ${svgH - pad} L ${pts[0].x} ${svgH - pad} Z`} fill={`${ds.teal}18`} />
        <path d={pathD} fill="none" stroke={ds.teal} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
        {pts.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={3.5} fill={ds.teal} stroke="white" strokeWidth={1.5} />
            {(i === 0 || i === pts.length - 1 || i % Math.ceil(pts.length / 8) === 0) && (
              <text x={p.x} y={svgH - 8} fontSize={9} fill="#94a3b8" textAnchor="middle" fontFamily={ds.fontDm}>{p.label}</text>
            )}
          </g>
        ))}
      </svg>
    </div>
  )
}

export default function SalesRecordTab({ isActive }) {
  const [summary, setSummary]   = useState([])
  const [sales, setSales]       = useState([])
  const [reps, setReps]         = useState([])
  const [variants, setVariants] = useState([])
  const [models, setModels]     = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [page, setPage]         = useState(1)
  const [total, setTotal]       = useState(0)
  const [hasMore, setHasMore]   = useState(false)
  const pageSize = 25

  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [repName, setRepName]   = useState('')
  const [model, setModel]       = useState('')
  const [variant, setVariant]   = useState('')

  const filters = useMemo(() => {
    const f = {}
    if (dateFrom) f.date_from = dateFrom
    if (dateTo)   f.date_to   = dateTo
    if (repName)  f.rep_name  = repName
    if (model)    f.model     = model
    if (variant)  f.variant   = variant
    return f
  }, [dateFrom, dateTo, repName, model, variant])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [summaryData, salesData] = await Promise.all([
        getDirectSalesSummary(filters),
        getDirectSales(page, pageSize, filters),
      ])
      setSummary(summaryData?.items ?? [])
      setSales(salesData?.items ?? [])
      setTotal(salesData?.total ?? 0)
      setHasMore(!!salesData?.has_more)
    } catch {
      setError('Failed to load sales records.')
    } finally {
      setLoading(false)
    }
  }, [page, filters])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive])

  // Filter dropdown options — fetched once, independent of current filters
  useEffect(() => {
    getDirectSalesFilterOptions().then(data => {
      setReps(data?.reps ?? [])
      setVariants(data?.variants ?? [])
    }).catch(() => {})
    getCommissionRates().then(data => {
      setModels((data?.commission_rates ?? []).map(r => r.product_name))
    }).catch(() => {})
  }, [])

  const resetPage = () => setPage(1)

  const kpis = useMemo(() => {
    const totalRevenue = summary.reduce((s, r) => s + (Number(r.amount) || 0), 0)
    const totalUnits   = summary.reduce((s, r) => s + (Number(r.units) || 0), 0)
    const totalTxns    = summary.length
    const avgSale      = totalTxns > 0 ? totalRevenue / totalTxns : 0
    return { totalRevenue, totalUnits, totalTxns, avgSale }
  }, [summary])

  const regionBreakdown = useMemo(() => {
    const byRegion = {}
    for (const r of summary) {
      const key = r.region || 'Not recorded'
      byRegion[key] = (byRegion[key] || 0) + (Number(r.amount) || 0)
    }
    return Object.entries(byRegion).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
  }, [summary])

  const statusBreakdown = useMemo(() => {
    const byStatus = { Reconciled: 0, Pending: 0 }
    for (const r of summary) {
      const key = r.reconciliation_status === 'Reconciled' ? 'Reconciled' : 'Pending'
      byStatus[key] += Number(r.amount) || 0
    }
    return [
      { label: 'Reconciled', value: byStatus.Reconciled, color: '#059669' },
      { label: 'Pending',    value: byStatus.Pending,    color: '#92601A' },
    ]
  }, [summary])

  const topModels = useMemo(() => {
    const byModel = {}
    for (const r of summary) {
      const key = r.model || 'Not recorded'
      byModel[key] = (byModel[key] || 0) + (Number(r.units) || 0)
    }
    return Object.entries(byModel).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value).slice(0, 5)
  }, [summary])

  const chartPoints = useMemo(() => {
    if (summary.length === 0) return []
    const dates = summary.map(r => r.sale_date).filter(Boolean).sort()
    const spanDays = (new Date(dates[dates.length - 1]) - new Date(dates[0])) / 86400000
    const byWeek = spanDays > 60
    const buckets = {}
    for (const r of summary) {
      if (!r.sale_date) continue
      let key = r.sale_date
      if (byWeek) {
        const d = new Date(r.sale_date)
        const day = d.getUTCDay() || 7
        d.setUTCDate(d.getUTCDate() - day + 1)
        key = d.toISOString().slice(0, 10)
      }
      buckets[key] = (buckets[key] || 0) + (Number(r.amount) || 0)
    }
    return Object.entries(buckets).sort(([a], [b]) => a.localeCompare(b)).map(([date, amount]) => ({ amount, label: date.slice(5) }))
  }, [summary])

  const fmtCurrency = (v) => `₦${Math.round(v).toLocaleString()}`

  return (
    <div style={{ padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Sales Record</h2>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>{total} sale{total !== 1 ? 's' : ''}</p>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <DateRangePresets onChange={({ dateFrom: f, dateTo: t }) => { setDateFrom(f); setDateTo(t); resetPage() }} />
        <select value={repName} onChange={e => { setRepName(e.target.value); resetPage() }} style={{ ...INP, width: 'auto' }}>
          <option value="">All reps</option>
          {reps.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={model} onChange={e => { setModel(e.target.value); resetPage() }} style={{ ...INP, width: 'auto' }}>
          <option value="">All models</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select value={variant} onChange={e => { setVariant(e.target.value); resetPage() }} style={{ ...INP, width: 'auto' }}>
          <option value="">All variants</option>
          {variants.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      {error && <p style={{ color: '#DC2626', fontSize: 13, marginBottom: 14 }}>{error}</p>}

      {loading && summary.length === 0 ? (
        <p style={{ color: '#7A9BAD', fontSize: 14 }}>Loading…</p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            <Kpi label="Total Revenue" value={fmtCurrency(kpis.totalRevenue)} accent={ds.teal} />
            <Kpi label="Total Units Sold" value={kpis.totalUnits.toLocaleString()} />
            <Kpi label="Total Transactions" value={kpis.totalTxns.toLocaleString()} />
            <Kpi label="Average Sale Value" value={fmtCurrency(kpis.avgSale)} />
          </div>

          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            <BreakdownCard title="Revenue by Region" rows={regionBreakdown} formatValue={fmtCurrency} />
            <BreakdownCard title="Reconciled vs. Pending" rows={statusBreakdown} formatValue={fmtCurrency} />
            <BreakdownCard title="Top-Selling Models (units)" rows={topModels} formatValue={v => v.toLocaleString()} />
          </div>

          <div style={{ ...CARD, marginBottom: 24 }}>
            <p style={{ fontSize: 12.5, fontWeight: 700, color: '#0a1a24', margin: '0 0 12px' }}>Revenue Over Time</p>
            <RevenueChart points={chartPoints} />
          </div>

          {sales.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '48px 32px', color: '#7A9BAD' }}>
              <p style={{ fontSize: 14 }}>No sales match these filters.</p>
            </div>
          ) : (
            <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#F8FBFC' }}>
                    {['Date', 'Rep', 'Customer', 'Region', 'Model', 'Variant', 'Units', 'Amount', 'Status'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '10px 14px', fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.6px' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sales.map((s, i) => (
                    <tr key={s.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none' }}>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.sale_date}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.rep_name ?? 'Not recorded'}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.customer_name ?? '—'}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#7A9BAD' }}>{s.region ?? '—'}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.model ?? '—'}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.variant ?? '—'}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.units ?? '—'}</td>
                      <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24', fontWeight: 500 }}>
                        {s.amount != null ? fmtCurrency(s.amount) : '—'}
                      </td>
                      <td style={{ padding: '10px 14px' }}>
                        {s.reconciliation_status
                          ? <Badge text={s.reconciliation_status} tone={s.reconciliation_status === 'Reconciled' ? 'rec' : 'pen'} />
                          : <Badge text="—" tone="none" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 16 }}>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} style={{ ...INP, cursor: page === 1 ? 'not-allowed' : 'pointer', opacity: page === 1 ? 0.5 : 1 }}>Previous</button>
            <span style={{ fontSize: 13, color: '#7A9BAD' }}>Page {page}</span>
            <button onClick={() => setPage(p => p + 1)} disabled={!hasMore} style={{ ...INP, cursor: !hasMore ? 'not-allowed' : 'pointer', opacity: !hasMore ? 0.5 : 1 }}>Next</button>
          </div>
        </>
      )}
    </div>
  )
}
