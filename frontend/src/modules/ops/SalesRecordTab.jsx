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
 * REPORTS-DEPT-1 Phase 4c — Revenue Over Time chart history:
 *   v1: hand-rolled SVG, single blended line, no region breakdown, date
 *       labels truncated the year (bug — two different weeks/years could
 *       render an identical label).
 *   v2: rebuilt on recharts (pinned >=2.15.0 in package.json — earlier
 *       2.x had a confirmed React 19 rendering bug) as a stacked bar
 *       chart, one segment per region, year-inclusive labels, custom
 *       tooltip with per-region + total, weekly/daily bucketing
 *       threshold tuned to 14 days after feedback that a ~month view
 *       still looked jagged at day-level granularity.
 *   v3 (this update): replaced the stacked bars with a MULTI-LINE chart
 *       — one line per region, plus a dashed "Average" benchmark line
 *       (the mean of all regions' values at that bucket). Stacked bars
 *       made it hard to read one specific region's trend in isolation,
 *       since each region's segment sits on a shifting baseline stacked
 *       on top of whatever's below it; separate lines give every region
 *       its own flat, directly comparable baseline. The average line
 *       lets you see at a glance whether a given region is over- or
 *       under-performing the typical region that period.
 * Deliberate, discussed departure from the "no new charting library"
 * convention used elsewhere (e.g. GrowthDashboard.jsx, which was NOT
 * touched and still uses its own hand-rolled SVG charts).
 *
 * Owner/ops_manager only, matching backend RBAC.
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
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

// Fixed palette so a given region keeps the same colour across renders
// (rather than reassigning colours as the region list changes shape).
const REGION_COLORS = ['#0F6E7C', '#F59E0B', '#7C3AED', '#059669', '#DC2626', '#2563EB', '#B45309', '#0E7490']
const AVERAGE_COLOR = '#94A3B8'
const AVERAGE_KEY = '__average'

// Buckets by week once the filtered range exceeds this many days,
// otherwise by day. (Tuned to 14 after feedback that a ~month view
// still looked jagged/noisy at day-level granularity.)
const WEEKLY_BUCKET_THRESHOLD_DAYS = 14

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

// Custom tooltip: lists each region's amount (in full ₦, not the
// abbreviated axis units), the Average benchmark, and a Total line
// (sum of actual regions — excludes the average itself from that sum).
function RevenueTooltip({ active, payload, label, fmtCurrency }) {
  if (!active || !payload || payload.length === 0) return null
  const regionEntries  = payload.filter(p => p.dataKey !== AVERAGE_KEY)
  const averageEntry   = payload.find(p => p.dataKey === AVERAGE_KEY)
  const total = regionEntries.reduce((s, p) => s + (Number(p.value) || 0), 0)
  return (
    <div style={{ background: 'white', border: '1px solid #E4EEF2', borderRadius: 8, padding: '10px 12px', fontSize: 12, boxShadow: '0 2px 10px rgba(10,26,36,0.12)', minWidth: 190 }}>
      <p style={{ margin: '0 0 8px', fontWeight: 700, color: '#0a1a24' }}>{label}</p>
      {regionEntries.slice().reverse().map(p => (
        <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, color: '#4a7a8a', padding: '2px 0' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color, display: 'inline-block', flexShrink: 0 }} />
            {p.dataKey}
          </span>
          <span style={{ color: '#0a1a24', fontWeight: 500 }}>{fmtCurrency(p.value)}</span>
        </div>
      ))}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginTop: 6, paddingTop: 6, borderTop: '1px solid #F0F7FA', fontWeight: 700, color: '#0a1a24' }}>
        <span>Total</span>
        <span>{fmtCurrency(total)}</span>
      </div>
      {averageEntry && (
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginTop: 4, color: '#7A9BAD' }}>
          <span>Average (per region)</span>
          <span>{fmtCurrency(averageEntry.value)}</span>
        </div>
      )}
    </div>
  )
}

// Small dashed-line swatch for the "Average" legend entry, to visually
// distinguish it from the solid-square region swatches (it's a
// benchmark, not a real series).
function DashSwatch() {
  return (
    <svg width="14" height="9" style={{ flexShrink: 0 }}>
      <line x1="0" y1="4.5" x2="14" y2="4.5" stroke={AVERAGE_COLOR} strokeWidth="2" strokeDasharray="4 3" />
    </svg>
  )
}

// Multi-line chart: one line per region, plus a dashed Average benchmark
// line (mean of all regions' values at that bucket). Replaces the
// earlier stacked-bar version.
function RevenueChart({ rows, regions, byWeek, fmtCurrency }) {
  if (!rows || rows.length === 0) {
    return <div style={{ color: '#9CA3AF', fontSize: 13, padding: '24px 0' }}>No data for this period.</div>
  }
  // Avoid a cluttered axis when there are many points — show every
  // label up to ~14 points, otherwise thin them out evenly.
  const tickInterval = rows.length <= 14 ? 0 : Math.ceil(rows.length / 10) - 1

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8, marginBottom: 4 }}>
        <p style={{ fontSize: 11.5, color: '#7A9BAD', margin: 0 }}>
          Revenue in Naira (₦), {byWeek ? 'grouped by week' : 'grouped by day'}, one line per region. Dashed line = average across regions. Hover a point for exact figures.
        </p>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          {regions.map((region, i) => (
            <span key={region} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#4a7a8a' }}>
              <span style={{ width: 9, height: 9, borderRadius: 2, background: REGION_COLORS[i % REGION_COLORS.length], display: 'inline-block' }} />
              {region}
            </span>
          ))}
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#4a7a8a' }}>
            <DashSwatch />
            Average
          </span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows} margin={{ top: 8, right: 12, left: 4, bottom: byWeek ? 40 : 30 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f8" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: '#94a3b8' }}
            interval={tickInterval}
            angle={-30}
            textAnchor="end"
            height={byWeek ? 46 : 36}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#94a3b8' }}
            tickFormatter={(v) => `₦${Math.round(v / 1000)}k`}
            width={56}
            label={{ value: 'Revenue (₦, thousands)', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#94a3b8' }}
          />
          <Tooltip content={<RevenueTooltip fmtCurrency={fmtCurrency} />} cursor={{ stroke: '#CBD5E1', strokeDasharray: '3 3' }} />
          {regions.map((region, i) => (
            <Line
              key={region}
              type="monotone"
              dataKey={region}
              name={region}
              stroke={REGION_COLORS[i % REGION_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          ))}
          <Line
            type="monotone"
            dataKey={AVERAGE_KEY}
            name="Average"
            stroke={AVERAGE_COLOR}
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
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

  useEffect(() => { if (isActive) load() }, [isActive, load])

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

  // Buckets by week when the filtered range spans more than
  // WEEKLY_BUCKET_THRESHOLD_DAYS, otherwise by day. Every bucket key
  // carries its own per-region amounts, and every label is built from
  // the FULL date (day, month, AND year) — never truncated — so two
  // different weeks/days can never render an identical label regardless
  // of how wide the date range is. Also computes an __average field per
  // row (mean of that row's region values) for the benchmark line.
  const chartData = useMemo(() => {
    if (summary.length === 0) return { rows: [], regions: [], byWeek: false }

    const dates = summary.map(r => r.sale_date).filter(Boolean).sort()
    const spanDays = (new Date(dates[dates.length - 1]) - new Date(dates[0])) / 86400000
    const byWeek = spanDays > WEEKLY_BUCKET_THRESHOLD_DAYS

    const regionSet = new Set()
    const buckets = {} // bucket key (YYYY-MM-DD) -> { [region]: amount }

    for (const r of summary) {
      if (!r.sale_date) continue
      let key = r.sale_date
      if (byWeek) {
        const d = new Date(r.sale_date)
        const day = d.getUTCDay() || 7
        d.setUTCDate(d.getUTCDate() - day + 1)
        key = d.toISOString().slice(0, 10)
      }
      const region = r.region || 'Not recorded'
      regionSet.add(region)
      if (!buckets[key]) buckets[key] = {}
      buckets[key][region] = (buckets[key][region] || 0) + (Number(r.amount) || 0)
    }

    const regions = Array.from(regionSet).sort()
    const sortedKeys = Object.keys(buckets).sort()

    const rows = sortedKeys.map(key => {
      const d = new Date(`${key}T00:00:00Z`)
      const dateLabel = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
      const label = byWeek ? `Wk of ${dateLabel}` : dateLabel
      const row = { key, label }
      let sum = 0
      for (const region of regions) {
        const val = buckets[key][region] || 0
        row[region] = val
        sum += val
      }
      row[AVERAGE_KEY] = regions.length > 0 ? sum / regions.length : 0
      return row
    })

    return { rows, regions, byWeek }
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
            <p style={{ fontSize: 12.5, fontWeight: 700, color: '#0a1a24', margin: '0 0 4px' }}>Revenue Over Time</p>
            <RevenueChart
              rows={chartData.rows}
              regions={chartData.regions}
              byWeek={chartData.byWeek}
              fmtCurrency={fmtCurrency}
            />
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
