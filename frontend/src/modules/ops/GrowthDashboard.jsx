/**
 * frontend/src/modules/ops/GrowthDashboard.jsx
 * Growth & Performance Dashboard — GPM-1B + GPM-1D + GPM-2 (full rewrite — Pattern 51)
 *
 * GPM-2 additions over GPM-1D:
 *   1. AnomalyBanner    — active growth anomaly alerts shown at top of dashboard
 *   2. InsightCard      — inline AI card rendered below each section's content
 *   3. InsightPanel     — slide-in drawer with full narrative + top 3 priorities (on demand)
 *
 * All existing sections, styles, helpers, and data-fetch logic preserved exactly.
 *
 * Pattern 11: JWT in Zustand only
 * Pattern 13: no react-router-dom
 * Pattern 26: InsightPanel always mounted, display:none when closed
 * Pattern 50: all API calls via growth.service.js
 * Pattern 51: full rewrite — never sed
 * Pattern 56: user?.roles?.template for role check
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { ds } from '../../utils/ds'
import {
  getGrowthOverview,
  getTeamPerformance,
  getFunnelMetrics,
  getSalesRepMetrics,
  getChannelMetrics,
  getLeadVelocity,
  getPipelineAtRisk,
  getWinLoss,
  getInsightSections,
  getInsightPanel,
  getInsightAnomalies,
  clearInsightCache,
} from '../../services/growth.service'
import useAuthStore from '../../store/authStore'
import { getGrowthDashboardConfig } from '../../services/admin.service'


// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n, prefix = '₦') {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${prefix}${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toLocaleString()}`
}

function pct(n) {
  if (n == null) return '—'
  return `${n}%`
}

function trend(val) {
  if (val == null) return null
  if (val > 0)  return { arrow: '↑', color: '#16a34a' }
  if (val < 0)  return { arrow: '↓', color: '#dc2626' }
  return { arrow: '→', color: '#6b7280' }
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

// ─── Shared styles ────────────────────────────────────────────────────────────

const card = {
  background:   'white',
  borderRadius: 12,
  padding:      '20px 24px',
  boxShadow:    '0 1px 4px rgba(0,0,0,0.07)',
  border:       '1px solid #edf2f6',
}

const sectionTitle = {
  fontFamily: ds.fontSyne,
  fontWeight: 700,
  fontSize:   15,
  color:      ds.dark,
  margin:     '0 0 16px',
}

const tableStyle = {
  width:          '100%',
  borderCollapse: 'collapse',
  fontSize:       13,
}

const th = {
  padding:       '9px 14px',
  textAlign:     'left',
  fontFamily:    ds.fontDm,
  fontWeight:    600,
  fontSize:      11.5,
  color:         '#6b8fa0',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  borderBottom:  '2px solid #edf2f6',
  whiteSpace:    'nowrap',
}

const td = {
  padding:      '10px 14px',
  borderBottom: '1px solid #f1f5f8',
  color:        ds.dark,
  fontFamily:   ds.fontDm,
}

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function Skeleton({ height = 120, width = '100%' }) {
  return (
    <div style={{
      height,
      width,
      background:     'linear-gradient(90deg, #f0f4f8 25%, #e4ecf1 50%, #f0f4f8 75%)',
      backgroundSize: '200% 100%',
      animation:      'shimmer 1.4s infinite',
      borderRadius:   8,
    }} />
  )
}

// ─── GPM-2: Anomaly Banner ────────────────────────────────────────────────────

const ANOMALY_STYLES = {
  high:   { bg: '#FFF1F2', border: '#FCA5A5', text: '#991B1B', icon: '🚨' },
  medium: { bg: '#FFFBEB', border: '#FCD34D', text: '#92400E', icon: '⚠️' },
  low:    { bg: '#EFF6FF', border: '#93C5FD', text: '#1E40AF', icon: 'ℹ️' },
}

function AnomalyBanner({ anomalies }) {
  const [dismissed, setDismissed] = useState([])
  const visible = (anomalies || []).filter(a => !dismissed.includes(a.type))
  if (!visible.length) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
      {visible.map(a => {
        const s = ANOMALY_STYLES[a.severity] || ANOMALY_STYLES.medium
        return (
          <div key={a.type} style={{
            background:    s.bg,
            border:        `1px solid ${s.border}`,
            borderRadius:  8,
            padding:       '10px 16px',
            display:       'flex',
            alignItems:    'flex-start',
            justifyContent:'space-between',
            gap:           10,
          }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <span style={{ fontSize: 16, lineHeight: 1.4 }}>{s.icon}</span>
              <div>
                <div style={{ fontFamily: ds.fontDm, fontWeight: 700, fontSize: 13, color: s.text }}>
                  {a.title}
                </div>
                <div style={{ fontFamily: ds.fontDm, fontSize: 12, color: s.text, opacity: 0.85, marginTop: 2 }}>
                  {a.detail}
                </div>
              </div>
            </div>
            <button
              onClick={() => setDismissed(d => [...d, a.type])}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: s.text, fontSize: 18, padding: 0, lineHeight: 1, flexShrink: 0 }}
            >×</button>
          </div>
        )
      })}
    </div>
  )
}

// ─── GPM-2: Insight Card ──────────────────────────────────────────────────────

function InsightCard({ insight, loading }) {
  if (loading) {
    return (
      <div style={{
        marginTop:    12,
        background:   '#F0FDFA',
        border:       `1px solid ${ds.teal}33`,
        borderRadius: 8,
        padding:      '9px 14px',
        display:      'flex',
        alignItems:   'center',
        gap:          6,
      }}>
        <span style={{ fontSize: 12, display: 'inline-block', animation: 'spin 1.2s linear infinite', color: ds.teal }}>✦</span>
        <span style={{ fontSize: 12, color: ds.teal, fontFamily: ds.fontDm }}>Generating AI insight…</span>
      </div>
    )
  }

  if (!insight) {
    return (
      <div style={{
        marginTop:    12,
        background:   '#F9FAFB',
        border:       '1px solid #E5E7EB',
        borderRadius: 8,
        padding:      '8px 14px',
        color:        '#9CA3AF',
        fontSize:     12,
        fontFamily:   ds.fontDm,
      }}>
        Insights unavailable
      </div>
    )
  }

  return (
    <div style={{
      marginTop:    12,
      background:   'linear-gradient(135deg, #F0FDFA 0%, #E6FAF8 100%)',
      border:       `1px solid ${ds.teal}40`,
      borderRadius: 8,
      padding:      '12px 14px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
        <span style={{ color: ds.teal, fontSize: 12 }}>✦</span>
        <span style={{ fontFamily: ds.fontDm, fontWeight: 700, fontSize: 11.5, color: ds.teal, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          AI Insight
        </span>
      </div>
      {insight.headline && (
        <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: ds.dark, marginBottom: 5 }}>
          {insight.headline}
        </div>
      )}
      {insight.detail && (
        <div style={{ fontFamily: ds.fontDm, fontSize: 12.5, color: '#374151', lineHeight: 1.6, marginBottom: 6 }}>
          {insight.detail}
        </div>
      )}
      {insight.action && (
        <div style={{
          fontFamily:  ds.fontDm,
          fontSize:    12,
          color:       ds.teal,
          fontWeight:  600,
          borderTop:   `1px solid ${ds.teal}30`,
          paddingTop:  6,
        }}>
          → {insight.action}
        </div>
      )}
    </div>
  )
}

// ─── GPM-2: AI Insight Panel (slide-in drawer) ────────────────────────────────

function InsightPanel({ open, onClose, dateFrom, dateTo }) {
  const [loading,   setLoading]   = useState(false)
  const [result,    setResult]    = useState(null)
  const [error,     setError]     = useState(null)
  const hasFetched = useRef(false)

  useEffect(() => {
    if (open && !hasFetched.current) {
      hasFetched.current = true
      setLoading(true)
      setError(null)
      getInsightPanel(dateFrom, dateTo)
        .then(d => setResult(d))
        .catch(() => setError('Unable to generate insights. Please try again.'))
        .finally(() => setLoading(false))
    }
    if (!open) {
      hasFetched.current = false
      setResult(null)
      setError(null)
    }
  }, [open, dateFrom, dateTo])

  // Pattern 26 — always mounted, display:none when closed
  return (
    <div style={{ display: open ? 'flex' : 'none', position: 'fixed', inset: 0, zIndex: 1050, background: 'rgba(0,0,0,0.4)', alignItems: 'flex-start', justifyContent: 'flex-end' }}>
      <div style={{ width: 420, maxWidth: '100vw', height: '100vh', background: 'white', display: 'flex', flexDirection: 'column', boxShadow: '-4px 0 24px rgba(0,0,0,0.13)', overflowY: 'auto' }}>

        {/* Header */}
        <div style={{
          padding:      '18px 22px',
          borderBottom: '1px solid #edf2f6',
          background:   'linear-gradient(135deg, #F0FDFA, #E6FAF8)',
          display:      'flex',
          alignItems:   'center',
          justifyContent: 'space-between',
          flexShrink:   0,
        }}>
          <div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: ds.teal }}>✦</span> AI Growth Insights
            </div>
            <div style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#6b8fa0', marginTop: 2 }}>Full dashboard narrative</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#94a3b8' }}>×</button>
        </div>

        {/* Body */}
        <div style={{ padding: '22px', flex: 1 }}>
          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, paddingTop: 50 }}>
              <span style={{ fontSize: 30, display: 'inline-block', animation: 'spin 1.5s linear infinite', color: ds.teal }}>✦</span>
              <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, color: ds.teal, fontSize: 14 }}>Analysing your growth data…</div>
              <div style={{ fontFamily: ds.fontDm, color: '#94a3b8', fontSize: 12, textAlign: 'center' }}>This usually takes a few seconds</div>
            </div>
          )}

          {error && !loading && (
            <div style={{ background: '#fff1f2', border: '1px solid #fecdd3', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#dc2626', fontFamily: ds.fontDm }}>
              {error}
            </div>
          )}

          {result && !loading && (
            <>
              {result.narrative && (
                <div style={{ fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.75, color: '#374151', whiteSpace: 'pre-wrap', marginBottom: 24 }}>
                  {result.narrative}
                </div>
              )}
              {result.top_priorities?.length > 0 && (
                <div>
                  <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: ds.dark, marginBottom: 10 }}>
                    🎯 Top Priorities
                  </div>
                  {result.top_priorities.map((p, i) => (
                    <div key={i} style={{
                      display:      'flex',
                      gap:          10,
                      padding:      '10px 14px',
                      background:   i % 2 === 0 ? '#F0FDFA' : '#F9FAFB',
                      borderRadius: 8,
                      marginBottom: 6,
                      fontFamily:   ds.fontDm,
                      fontSize:     13,
                      color:        ds.dark,
                    }}>
                      <span style={{ fontWeight: 700, color: ds.teal, flexShrink: 0 }}>{i + 1}.</span>
                      {p}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── 1. Date range selector ───────────────────────────────────────────────────

const PRESETS = [
  { label: '7d',  days: 7  },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
]

function DateRangeBar({ dateFrom, dateTo, onApply, loading, onRefresh }) {
  const [preset,     setPreset]     = useState('30d')
  const [customFrom, setCustomFrom] = useState(dateFrom)
  const [customTo,   setCustomTo]   = useState(dateTo)
  const [showCustom, setShowCustom] = useState(false)

  function applyPreset(p) {
    setPreset(p.label)
    setShowCustom(false)
    onApply({ dateFrom: daysAgo(p.days), dateTo: today() })
  }

  function applyCustom() {
    if (customFrom && customTo) {
      setPreset('custom')
      onApply({ dateFrom: customFrom, dateTo: customTo })
      setShowCustom(false)
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {PRESETS.map(p => (
        <button key={p.label} onClick={() => applyPreset(p)} style={{
          padding: '6px 14px', borderRadius: 20,
          border:      `1.5px solid ${preset === p.label ? ds.teal : '#dde4e8'}`,
          background:  preset === p.label ? ds.teal : 'white',
          color:       preset === p.label ? 'white' : ds.gray,
          fontFamily:  ds.fontDm, fontWeight: 600, fontSize: 12.5, cursor: 'pointer',
        }}>
          Last {p.label}
        </button>
      ))}

      <button onClick={() => setShowCustom(v => !v)} style={{
        padding: '6px 14px', borderRadius: 20,
        border:     `1.5px solid ${preset === 'custom' ? ds.teal : '#dde4e8'}`,
        background: preset === 'custom' ? ds.teal : 'white',
        color:      preset === 'custom' ? 'white' : ds.gray,
        fontFamily: ds.fontDm, fontWeight: 600, fontSize: 12.5, cursor: 'pointer',
      }}>
        Custom
      </button>

      {showCustom && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
            style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid #dde4e8', fontSize: 12, fontFamily: ds.fontDm }} />
          <span style={{ color: ds.gray, fontSize: 12 }}>→</span>
          <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
            style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid #dde4e8', fontSize: 12, fontFamily: ds.fontDm }} />
          <button onClick={applyCustom} style={{
            padding: '5px 12px', borderRadius: 6, background: ds.teal, color: 'white',
            border: 'none', fontFamily: ds.fontDm, fontWeight: 600, fontSize: 12, cursor: 'pointer',
          }}>Apply</button>
        </div>
      )}

      <button onClick={onRefresh} disabled={loading} style={{
        marginLeft: 'auto', padding: '6px 14px', borderRadius: 20,
        border: '1.5px solid #dde4e8', background: 'white', color: ds.gray,
        fontFamily: ds.fontDm, fontWeight: 600, fontSize: 12.5,
        cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
        display: 'flex', alignItems: 'center', gap: 5,
      }}>
        <span style={{ display: 'inline-block', animation: loading ? 'spin 0.8s linear infinite' : 'none' }}>↻</span>
        Refresh
      </button>
    </div>
  )
}

// ─── 2. Executive Overview ────────────────────────────────────────────────────

function KPICard({ label, value, sub, trendVal, color }) {
  const t = trend(trendVal)
  return (
    <div style={{ ...card, flex: '1 1 160px', minWidth: 150, borderTop: `3px solid ${color || ds.teal}` }}>
      <div style={{ fontSize: 11, color: '#6b8fa0', fontFamily: ds.fontDm, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark }}>
        {value}
      </div>
      {(sub || t) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5 }}>
          {t && <span style={{ fontSize: 12, fontWeight: 700, color: t.color, fontFamily: ds.fontDm }}>{t.arrow} {Math.abs(trendVal)}%</span>}
          {sub && <span style={{ fontSize: 11.5, color: '#6b8fa0', fontFamily: ds.fontDm }}>{sub}</span>}
        </div>
      )}
    </div>
  )
}

function OverviewSection({ data, loading }) {
  if (loading) return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      {[...Array(6)].map((_, i) => <Skeleton key={i} height={100} width={160} />)}
    </div>
  )
  if (!data) return null

  const bd = data.revenue_breakdown || {}
  return (
    <div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <KPICard label="Total Revenue"   value={fmt(data.total_revenue)}         trendVal={data.revenue_growth_pct} color={ds.teal} />
        <KPICard label="Leads Revenue"   value={fmt(bd.leads)}                   sub="from pipeline"  color="#0ea5e9" />
        <KPICard label="Renewals"        value={fmt(bd.renewals)}                sub="subscriptions"  color="#8b5cf6" />
        <KPICard label="Direct Sales"    value={fmt(bd.direct_sales)}            sub="manual entries" color="#f59e0b" />
        <KPICard label="Total Leads"     value={data.total_leads ?? '—'}                              color="#64748b" />
        <KPICard label="Conversion Rate" value={pct(data.overall_conversion_rate)}                    color="#16a34a" />
        <KPICard label="Avg Close Time"  value={data.avg_close_time_days != null ? `${data.avg_close_time_days}d` : '—'} sub="days" color="#e11d48" />
        <KPICard label="CAC"             value={data.cac != null ? fmt(data.cac) : '—'}               sub="per customer" color="#dc2626" />
      </div>
    </div>
  )
}

// ─── 3. Team Performance ──────────────────────────────────────────────────────

function bestInCol(rows, key) {
  if (!rows.length) return null
  return rows.reduce((best, r) => (r[key] > best[key] ? r : best), rows[0]).team_name
}

function TeamSection({ data, loading }) {
  if (loading) return <Skeleton height={140} />
  if (!data || !data.length) return <div style={{ color: '#6b8fa0', fontSize: 13, fontFamily: ds.fontDm }}>No team data for this period.</div>

  const metrics = ['leads_generated', 'conversion_rate', 'revenue_generated', 'avg_lead_score']
  const bestMap  = Object.fromEntries(metrics.map(m => [m, bestInCol(data, m)]))

  function cellStyle(row, key) {
    const isB = bestMap[key] === row.team_name && row[key] > 0
    return { ...td, background: isB ? '#f0fdf4' : 'transparent', color: isB ? '#16a34a' : ds.dark, fontWeight: isB ? 700 : 400 }
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={tableStyle}>
        <thead>
          <tr>{['Team','Leads','Conv Rate','Revenue','Avg Score','Spend','CAC','Cost/Lead'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data.map(row => (
            <tr key={row.team_name}>
              <td style={{ ...td, fontWeight: 600 }}>
                {row.team_name === 'Unattributed' ? <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>Unattributed</span> : row.team_name}
              </td>
              <td style={cellStyle(row, 'leads_generated')}>{row.leads_generated}</td>
              <td style={cellStyle(row, 'conversion_rate')}>{pct(row.conversion_rate)}</td>
              <td style={cellStyle(row, 'revenue_generated')}>{fmt(row.revenue_generated)}</td>
              <td style={cellStyle(row, 'avg_lead_score')}>{row.avg_lead_score ?? '—'}</td>
              <td style={td}>{row.total_spend > 0 ? fmt(row.total_spend) : '—'}</td>
              <td style={td}>{row.cac != null ? fmt(row.cac) : '—'}</td>
              <td style={td}>{row.cost_per_lead != null ? fmt(row.cost_per_lead) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── 4. Funnel ────────────────────────────────────────────────────────────────

const STAGE_LABELS = {
  new:           'New',
  contacted:     'Contacted',
  meeting_done:  'Demo Done',
  proposal_sent: 'Proposal',
  converted:     'Closed',
}

const STAGE_COLORS = ['#0ea5e9','#06b6d4','#14b8a6','#10b981','#16a34a']

function FunnelBar({ stage, count, pctFromTop, pctFromPrev, color, isLast, stageLabels }) {
  const width = Math.max(pctFromTop, 4)
  return (
    <div style={{ marginBottom: isLast ? 0 : 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 3 }}>
        <div style={{ width: 100, fontSize: 12, color: '#6b8fa0', fontFamily: ds.fontDm, fontWeight: 600 }}>
          {stageLabels[stage] || stage}
        </div>
        <div style={{ flex: 1, background: '#f1f5f8', borderRadius: 4, height: 28, overflow: 'hidden' }}>
          <div style={{
            width: `${width}%`, height: '100%', background: color, borderRadius: 4,
            display: 'flex', alignItems: 'center', paddingLeft: 10, transition: 'width 0.5s ease',
          }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'white', fontFamily: ds.fontDm }}>{count}</span>
          </div>
        </div>
        <div style={{ width: 60, textAlign: 'right', fontSize: 12, fontFamily: ds.fontDm, color: '#6b8fa0' }}>{pct(pctFromTop)}</div>
        {!isLast && (
          <div style={{ width: 70, textAlign: 'right', fontSize: 11, fontFamily: ds.fontDm, color: pctFromPrev < 50 ? '#dc2626' : '#16a34a', fontWeight: 600 }}>
            → {pct(pctFromPrev)}
          </div>
        )}
      </div>
    </div>
  )
}

function FunnelSection({ data, loading, teams, params, onParamsChange }) {
  // GROWTH-DASH-CONFIG: use org stage labels from API if available, fall back to constant
  const stageLabels = data?.stage_labels || STAGE_LABELS
  const allTeams = ['All', ...(teams || []).map(t => t.name), 'Unattributed']
  if (loading) return <Skeleton height={180} />
  if (!data)   return null

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
        {allTeams.map(t => {
          const active = (params.team || 'All') === t
          return (
            <button key={t} onClick={() => onParamsChange({ team: t === 'All' ? undefined : t })} style={{
              padding: '4px 12px', borderRadius: 16,
              border: `1.5px solid ${active ? ds.teal : '#dde4e8'}`,
              background: active ? ds.teal : 'white', color: active ? 'white' : ds.gray,
              fontFamily: ds.fontDm, fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>{t}</button>
          )
        })}
      </div>
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: '#6b8fa0', fontFamily: ds.fontDm }}>Total leads: <strong>{data.total_leads}</strong></div>
          <div style={{ marginLeft: 'auto', fontSize: 12, color: '#6b8fa0', fontFamily: ds.fontDm }}>
            Overall close rate: <strong style={{ color: ds.teal }}>{pct(data.overall_close_rate)}</strong>
          </div>
        </div>
        {(data.stages || []).map((s, i) => (
          <FunnelBar key={s.stage} stage={s.stage} count={s.count} pctFromTop={s.pct_from_top}
            pctFromPrev={s.pct_from_previous_stage} color={STAGE_COLORS[i] || ds.teal} isLast={i === data.stages.length - 1} stageLabels={stageLabels} />
        ))}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={tableStyle}>
          <thead>
            <tr>{['Stage','Count','% from Top','% from Previous'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {(data.stages || []).map(s => (
              <tr key={s.stage}>
                <td style={{ ...td, fontWeight: 600 }}>{stageLabels[s.stage] || s.stage}</td>
                <td style={td}>{s.count}</td>
                <td style={td}>{pct(s.pct_from_top)}</td>
                <td style={{ ...td, color: s.pct_from_previous_stage < 50 ? '#dc2626' : '#16a34a', fontWeight: 600 }}>
                  {pct(s.pct_from_previous_stage)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── 5. Lead Velocity ─────────────────────────────────────────────────────────

function VelocitySection({ data, loading }) {
  if (loading) return <Skeleton height={140} />
  if (!data || !data.length) return (
    <div style={{ color: '#6b8fa0', fontSize: 13, fontFamily: ds.fontDm }}>No velocity data for this period.</div>
  )

  const max  = Math.max(...data.map(d => d.lead_count), 1)
  const svgW = 600, svgH = 120, pad = 30

  const pts = data.map((d, i) => {
    const x = pad + (i / Math.max(data.length - 1, 1)) * (svgW - pad * 2)
    const y = svgH - pad - (d.lead_count / max) * (svgH - pad * 2)
    return { x, y, ...d }
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
              <text x={pad - 4} y={y + 4} fontSize={9} fill="#94a3b8" textAnchor="end" fontFamily={ds.fontDm}>
                {Math.round(f * max)}
              </text>
            </g>
          )
        })}
        <path d={`${pathD} L ${pts[pts.length-1].x} ${svgH - pad} L ${pts[0].x} ${svgH - pad} Z`} fill={`${ds.teal}18`} />
        <path d={pathD} fill="none" stroke={ds.teal} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
        {pts.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={4} fill={ds.teal} stroke="white" strokeWidth={2} />
            <text x={p.x} y={p.y - 9} fontSize={10} fill={ds.dark} textAnchor="middle" fontFamily={ds.fontDm} fontWeight="600">{p.lead_count}</text>
            {p.pct_change_from_prior_week != null && (
              <text x={p.x} y={p.y - 20} fontSize={9} textAnchor="middle" fontFamily={ds.fontDm}
                fill={p.pct_change_from_prior_week > 0 ? '#16a34a' : p.pct_change_from_prior_week < 0 ? '#dc2626' : '#94a3b8'}>
                {p.pct_change_from_prior_week > 0 ? '↑' : p.pct_change_from_prior_week < 0 ? '↓' : '→'}{Math.abs(p.pct_change_from_prior_week)}%
              </text>
            )}
            <text x={p.x} y={svgH - 6} fontSize={9} fill="#94a3b8" textAnchor="middle" fontFamily={ds.fontDm}>{p.week_start?.slice(5)}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}

// ─── 6. Pipeline at Risk ──────────────────────────────────────────────────────

function RiskSection({ data, loading, onLeadClick }) {
  if (loading) return <Skeleton height={140} />
  if (!data || !data.length) return (
    <div style={{ color: '#16a34a', fontSize: 13, fontFamily: ds.fontDm }}>✓ No stuck leads. Pipeline is healthy.</div>
  )

  function rowColor(days) {
    if (days >= 21) return '#fff1f2'
    if (days >= 14) return '#fffbeb'
    return 'transparent'
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={tableStyle}>
        <thead>
          <tr>{['Lead','Stage','Days Stuck','Assigned Rep','Est. Value'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data.map(row => (
            <tr key={row.lead_id} style={{ background: rowColor(row.days_stuck), cursor: onLeadClick ? 'pointer' : 'default' }}
              onClick={() => onLeadClick && onLeadClick(row.lead_id)}>
              <td style={{ ...td, fontWeight: 600, color: ds.teal }}>{row.lead_name}</td>
              <td style={td}>{STAGE_LABELS[row.stage] || row.stage}</td>
              <td style={{ ...td, fontWeight: 700, color: row.days_stuck >= 21 ? '#dc2626' : row.days_stuck >= 14 ? '#d97706' : ds.dark }}>{row.days_stuck}d</td>
              <td style={td}>{row.assigned_rep || '—'}</td>
              <td style={td}>{fmt(row.estimated_value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 8, fontSize: 11, color: '#94a3b8', fontFamily: ds.fontDm }}>
        <span style={{ color: '#dc2626', fontWeight: 700 }}>Red</span> = 21+ days · <span style={{ color: '#d97706', fontWeight: 700 }}>Amber</span> = 14+ days
      </div>
    </div>
  )
}

// ─── 7. Sales Rep Leaderboard ─────────────────────────────────────────────────

const REP_COLS = [
  { key: 'rep_name',               label: 'Rep',          fmt: v => v },
  { key: 'leads_assigned',         label: 'Leads',        fmt: v => v },
  { key: 'customers_assigned',     label: 'Customers',    fmt: v => v ?? '—' },
  { key: 'messages_sent',          label: 'Msgs Sent',    fmt: v => v ?? '—' },
  { key: 'avg_response_time_mins', label: 'Resp Time',    fmt: v => v != null ? `${v}m` : '—' },
  { key: 'demo_show_rate',         label: 'Demo Rate',    fmt: pct },
  { key: 'close_rate',             label: 'Close Rate',   fmt: pct },
  { key: 'revenue_closed',         label: 'Revenue',      fmt: fmt },
]

function RepSection({ data, loading }) {
  const [sortKey, setSortKey] = useState('revenue_closed')
  const [sortDir, setSortDir] = useState('desc')

  if (loading) return <Skeleton height={140} />
  if (!data || !data.length) return (
    <div style={{ color: '#6b8fa0', fontSize: 13, fontFamily: ds.fontDm }}>No rep data for this period.</div>
  )

  function toggleSort(key) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={tableStyle}>
        <thead>
          <tr>
            {REP_COLS.map(col => (
              <th key={col.key} style={{ ...th, cursor: 'pointer', userSelect: 'none' }} onClick={() => toggleSort(col.key)}>
                {col.label} {sortKey === col.key ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={row.rep_id}>
              {REP_COLS.map(col => (
                <td key={col.key} style={{ ...td, fontWeight: col.key === 'rep_name' ? 600 : 400, color: col.key === 'revenue_closed' ? ds.teal : td.color }}>
                  {i === 0 && col.key === 'rep_name' ? <span>🏆 {col.fmt(row[col.key])}</span> : col.fmt(row[col.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── 8. Channel Performance ───────────────────────────────────────────────────

function ChannelSection({ data, loading }) {
  if (loading) return <Skeleton height={140} />
  if (!data || !data.length) return (
    <div style={{ color: '#6b8fa0', fontSize: 13, fontFamily: ds.fontDm }}>No channel data for this period.</div>
  )

  const channelIcon = (source) => {
    const s = (source || '').toLowerCase()
    if (s === 'whatsapp')       return '💬 '
    if (s === 'instagram')      return '📸 '
    if (s === 'facebook')       return '🔵 '
    if (s === 'messenger')      return '💙 '
    if (s === 'web form')       return '🌐 '
    if (s === 'meta lead ad')   return '📣 '
    if (s === 'manual')         return '✍️ '
    return ''
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={tableStyle}>
        <thead>
          <tr>{['Source','Leads','Conv Rate','Revenue','Spend','CAC','Cost/Lead','Top Ads'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data.map(row => (
            <tr key={row.utm_source}>
              <td style={{ ...td, fontWeight: 600 }}>
                <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 10, background: '#f0f9ff', color: '#0369a1', fontSize: 11.5, fontWeight: 600 }}>
                  {channelIcon(row.utm_source)}{row.utm_source}
                </span>
              </td>
              <td style={td}>{row.total_leads}</td>
              <td style={{ ...td, color: row.conversions === 0 ? '#94a3b8' : ds.dark }}>{pct(row.conversion_rate)}</td>
              <td style={{ ...td, color: ds.teal, fontWeight: 600 }}>{fmt(row.revenue)}</td>
              <td style={td}>{row.total_spend > 0 ? fmt(row.total_spend) : '—'}</td>
              <td style={td}>{row.cac != null ? fmt(row.cac) : '—'}</td>
              <td style={td}>{row.cost_per_lead != null ? fmt(row.cost_per_lead) : '—'}</td>
              <td style={td}>
                {row.top_ads && row.top_ads.length > 0 ? (
                  <span title={row.top_ads.join(', ')} style={{ cursor: 'default', fontSize: 12, color: '#5a8a9f' }}>
                    {row.top_ads.map(ad => ad.length > 20 ? ad.slice(0, 20) + '…' : ad).join(', ')}
                  </span>
                ) : (
                  <span style={{ color: '#94a3b8' }}>—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── 9. Win / Loss Analysis ───────────────────────────────────────────────────

function WinLossSection({ data, loading }) {
  if (loading) return <Skeleton height={140} />
  if (!data)   return null

  const maxCount = Math.max(...(data.lost_reasons || []).map(r => r.count), 1)

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <div style={{ ...card, flex: 1, borderTop: '3px solid #16a34a', textAlign: 'center' }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 28, color: '#16a34a' }}>{data.won}</div>
          <div style={{ fontSize: 11.5, color: '#6b8fa0', fontFamily: ds.fontDm, fontWeight: 600, textTransform: 'uppercase' }}>Won</div>
        </div>
        <div style={{ ...card, flex: 1, borderTop: '3px solid #dc2626', textAlign: 'center' }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 28, color: '#dc2626' }}>{data.lost}</div>
          <div style={{ fontSize: 11.5, color: '#6b8fa0', fontFamily: ds.fontDm, fontWeight: 600, textTransform: 'uppercase' }}>Lost</div>
        </div>
        <div style={{ ...card, flex: 1, borderTop: `3px solid ${ds.teal}`, textAlign: 'center' }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 28, color: ds.teal }}>{pct(data.win_rate)}</div>
          <div style={{ fontSize: 11.5, color: '#6b8fa0', fontFamily: ds.fontDm, fontWeight: 600, textTransform: 'uppercase' }}>Win Rate</div>
        </div>
      </div>
      {data.lost_reasons?.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: ds.dark, fontFamily: ds.fontDm, marginBottom: 12 }}>Lost Reasons</div>
          {data.lost_reasons.map(r => (
            <div key={r.reason} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 12.5, color: ds.dark, fontFamily: ds.fontDm }}>{r.reason}</span>
                <span style={{ fontSize: 12, color: '#6b8fa0', fontFamily: ds.fontDm }}>{r.count} · {pct(r.pct)}</span>
              </div>
              <div style={{ background: '#f1f5f8', borderRadius: 4, height: 8 }}>
                <div style={{ width: `${(r.count / maxCount) * 100}%`, height: '100%', background: '#dc2626', borderRadius: 4, transition: 'width 0.4s ease' }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children, action, insight, insightLoading }) {
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={sectionTitle}>{title}</h3>
        {action}
      </div>
      {children}
      {/* GPM-2: inline AI insight card per section */}
      <InsightCard insight={insight} loading={insightLoading} />
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function GrowthDashboard({ user, setView }) {
  const role = user?.roles?.template || ''

  const [dateRange,    setDateRange]    = useState({ dateFrom: daysAgo(30), dateTo: today() })
  const [funnelParams, setFunnelParams] = useState({})

  // Section data
  const [overview,  setOverview]  = useState(null)
  const [teams,     setTeams]     = useState(null)
  const [funnel,    setFunnel]    = useState(null)
  const [reps,      setReps]      = useState(null)
  const [channels,  setChannels]  = useState(null)
  const [velocity,  setVelocity]  = useState(null)
  const [atRisk,    setAtRisk]    = useState(null)
  const [winLoss,   setWinLoss]   = useState(null)
  const [teamsList, setTeamsList] = useState([])

  const [loadingMap,   setLoadingMap]   = useState({})
  const [error,        setError]        = useState(null)
  // GROWTH-DASH-CONFIG: section visibility config
  const [dashConfig,   setDashConfig]   = useState(null)

  // GPM-2: AI insight state
  const [insights,        setInsights]        = useState({})
  const [insightRefreshing, setInsightRefreshing] = useState(false)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [anomalies,       setAnomalies]       = useState([])
  const [panelOpen,       setPanelOpen]       = useState(false)

  function setLoading(key, val) {
    setLoadingMap(m => ({ ...m, [key]: val }))
  }

  const fetchAll = useCallback(async (range, fp) => {
    const p = { ...range }
    setError(null)

    const tasks = [
      { key: 'overview', fn: () => getGrowthOverview(p).then(setOverview) },
      { key: 'teams',    fn: () => getTeamPerformance(p).then(setTeams) },
      { key: 'funnel',   fn: () => getFunnelMetrics({ ...p, ...(fp || funnelParams) }).then(setFunnel) },
      { key: 'channels', fn: () => getChannelMetrics(p).then(setChannels) },
      { key: 'velocity', fn: () => getLeadVelocity(p).then(setVelocity) },
      { key: 'atRisk',   fn: () => getPipelineAtRisk().then(setAtRisk) },
      { key: 'winLoss',  fn: () => getWinLoss(p).then(setWinLoss) },
      { key: 'reps',     fn: () => getSalesRepMetrics(p).then(setReps) },
    ]

    tasks.forEach(({ key, fn }) => {
      setLoading(key, true)
      fn()
        .catch(e => { console.error(`Growth fetch error [${key}]:`, e); setError(prev => prev || `Failed to load ${key} data`) })
        .finally(() => setLoading(key, false))
    })
  }, [funnelParams])

  // GPM-2: fetch insight cards — polls if backend returns generating status
  const fetchInsights = useCallback((range, attempt = 0) => {
    setInsightsLoading(true)
    getInsightSections(range.dateFrom, range.dateTo)
      .then(d => {
        if (d?.status === 'generating' && attempt < 6) {
          // Cache miss — backend is generating in background, poll every 4s
          setTimeout(() => fetchInsights(range, attempt + 1), 4000)
        } else {
          setInsights(d?.sections || {})
          setInsightsLoading(false)
        }
      })
      .catch(() => {
        setInsights({})
        setInsightsLoading(false)
      })
  }, [])

  // GPM-2: fetch anomaly alerts
  const fetchAnomalies = useCallback(() => {
    getInsightAnomalies()
      .then(d => setAnomalies(d?.alerts || []))
      .catch(() => {})
  }, [])

  const handleRefreshInsights = useCallback(async () => {
    setInsightRefreshing(true)
    try { await clearInsightCache() } catch (e) { console.error(e) }
    setInsightRefreshing(false)
    fetchInsights(dateRange)
  }, [dateRange, fetchInsights])

  useEffect(() => {
    fetchAll(dateRange, funnelParams)
    fetchInsights(dateRange)
    fetchAnomalies()
    import('../../services/growth.service').then(m =>
      m.getGrowthTeams().then(setTeamsList).catch(() => {})
    )
    // GROWTH-DASH-CONFIG: fetch section visibility — fail silently (show all on error)
    getGrowthDashboardConfig()
      .then(data => { if (data?.sections) setDashConfig(data) })
      .catch(() => {})
  }, [])

  function handleDateApply(range) {
    setDateRange(range)
    fetchAll(range, funnelParams)
    fetchInsights(range)
  }

  function handleFunnelParamsChange(fp) {
    const merged = { ...funnelParams, ...fp }
    setFunnelParams(merged)
    setLoading('funnel', true)
    getFunnelMetrics({ ...dateRange, ...merged })
      .then(setFunnel)
      .catch(console.error)
      .finally(() => setLoading('funnel', false))
  }

  const anyLoading = Object.values(loadingMap).some(Boolean)

  // GROWTH-DASH-CONFIG: return true if section is visible (default true if config not loaded)
  function isSectionVisible(key) {
    if (!dashConfig?.sections) return true
    const section = dashConfig.sections.find(s => s.key === key)
    return section ? section.visible : true
  }

  return (
    <div style={{ padding: '20px 28px', maxWidth: 1200 }}>

      <style>{`
        @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
        @keyframes spin    { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
      `}</style>

      {/* GPM-2: Anomaly banner */}
      <AnomalyBanner anomalies={anomalies} />

      {/* Header row with date range + AI Insights button */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ flex: 1 }}>
            <DateRangeBar
              dateFrom={dateRange.dateFrom}
              dateTo={dateRange.dateTo}
              onApply={handleDateApply}
              loading={anyLoading}
              onRefresh={() => { fetchAll(dateRange, funnelParams); fetchInsights(dateRange) }}
            />
          </div>
          {/* GPM-2: AI Insights panel button */}
          <button
            onClick={() => setPanelOpen(true)}
            style={{
              display:      'flex',
              alignItems:   'center',
              gap:          6,
              padding:      '7px 16px',
              borderRadius: 20,
              border:       `1.5px solid ${ds.teal}`,
              background:   ds.teal,
              color:        'white',
              fontFamily:   ds.fontDm,
              fontWeight:   700,
              fontSize:     12.5,
              cursor:       'pointer',
              flexShrink:   0,
            }}
          >
            <span style={{ fontSize: 13 }}>✦</span> AI Insights
          </button>
          <button
            onClick={handleRefreshInsights}
            disabled={insightRefreshing || insightsLoading}
            title="Clear cached insights and regenerate"
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '7px 14px', borderRadius: 20,
              border: '1.5px solid #dde4e8', background: 'white',
              color: ds.gray, fontFamily: ds.fontDm, fontWeight: 600,
              fontSize: 12.5, flexShrink: 0,
              cursor: (insightRefreshing || insightsLoading) ? 'not-allowed' : 'pointer',
              opacity: (insightRefreshing || insightsLoading) ? 0.6 : 1,
            }}
          >
            <span style={{ display: 'inline-block', animation: (insightRefreshing || insightsLoading) ? 'spin 0.8s linear infinite' : 'none' }}>✦</span>
            {insightRefreshing ? 'Clearing…' : 'Refresh Insights'}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: '#fff1f2', border: '1px solid #fecdd3', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontSize: 13, color: '#dc2626', fontFamily: ds.fontDm }}>
          ⚠ {error}
        </div>
      )}

      {/* Section 1 — Overview */}
      <Section title="📊 Executive Overview" insight={insights.overview} insightLoading={insightsLoading}>
        <OverviewSection data={overview} loading={loadingMap.overview} />
      </Section>

      {/* Section 2 — Team Performance */}
      {isSectionVisible('team_performance') && (
        <Section title="👥 Team Performance" insight={insights.team_performance} insightLoading={insightsLoading}>
          <TeamSection data={teams} loading={loadingMap.teams} />
        </Section>
      )}

      {/* Section 3 — Funnel */}
      {isSectionVisible('funnel') && (
        <Section title="🔽 Funnel Breakdown" insight={insights.funnel} insightLoading={insightsLoading}>
          <FunnelSection data={funnel} loading={loadingMap.funnel} teams={teamsList} params={funnelParams} onParamsChange={handleFunnelParamsChange} />
        </Section>
      )}

      {/* Section 4 — Lead Velocity */}
      {isSectionVisible('velocity') && (
        <Section title="📈 Lead Velocity" insight={insights.velocity} insightLoading={insightsLoading}>
          <VelocitySection data={velocity} loading={loadingMap.velocity} />
        </Section>
      )}

      {/* Section 5 — Pipeline at Risk (always visible) */}
      <Section title="⚠️ Pipeline at Risk" insight={insights.pipeline_at_risk} insightLoading={insightsLoading}>
        <RiskSection data={atRisk} loading={loadingMap.atRisk} onLeadClick={setView ? (id) => setView('lead-profile', id) : null} />
      </Section>

      {/* Section 6 — Rep Leaderboard */}
      {isSectionVisible('sales_reps') && (
        <Section title="🏆 Sales Rep Leaderboard" insight={insights.sales_reps} insightLoading={insightsLoading}>
          <RepSection data={reps} loading={loadingMap.reps} />
        </Section>
      )}

      {/* Section 7 — Channels */}
      {isSectionVisible('channels') && (
        <Section title="📡 Channel Performance" insight={insights.channels} insightLoading={insightsLoading}>
          <ChannelSection data={channels} loading={loadingMap.channels} />
        </Section>
      )}

      {/* Section 8 — Win / Loss */}
      {isSectionVisible('win_loss') && (
        <Section title="🎯 Win / Loss Analysis" insight={insights.win_loss} insightLoading={insightsLoading}>
          <WinLossSection data={winLoss} loading={loadingMap.winLoss} />
        </Section>
      )}
      
      {/* GPM-2: AI Insight Panel — Pattern 26, always mounted */}
      <InsightPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        dateFrom={dateRange.dateFrom}
        dateTo={dateRange.dateTo}
      />

    </div>
  )
}
