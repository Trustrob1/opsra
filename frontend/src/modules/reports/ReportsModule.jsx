/**
 * frontend/src/modules/reports/ReportsModule.jsx
 * Management Reporting System — RPT-1B.
 *
 * Layout (desktop): Left filter panel (280px) + Right report preview (flex-1)
 * Layout (mobile):  Full-width preview + slide-up filter sheet
 *
 * Pattern 13: useState navigation — no react-router-dom.
 * Pattern 11: no localStorage for state.
 * Pattern 26: mount-and-hide for section panels.
 * Pattern 51: full rewrite — never partial edit on JSX files.
 * Pattern 56: role check via user?.roles?.template.
 *
 * ds.teal for all accents. ds.reports does NOT exist — never use it.
 *
 * Props:
 *   user — current user object from Zustand auth store
 */

import { TrendingUp, DollarSign, User, Users, MessageSquare, Heart, AlertTriangle, Radio, X, Edit, ClipboardList, BarChart2, Calendar, Filter, Lock, RefreshCw, Target, Ticket, CheckSquare } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import { useIsMobile } from '../../hooks/useIsMobile'
import {
  getFullReport,
  downloadReport,
  getScheduledReports,
  createScheduledReport,
  updateScheduledReport,
  deleteScheduledReport,
  getOrgUsers,
} from '../../services/reports.service'
import { getGrowthTeams } from '../../services/growth.service'

// ─── Constants ────────────────────────────────────────────────────────────────

const SECTIONS = [
  { key: 'executive_summary', label: 'Executive Summary',    Icon: TrendingUp, desc: 'Revenue, leads, conversions, CAC, close time' },
  { key: 'lead_pipeline',     label: 'Lead & Pipeline',      Icon: Target, desc: 'Leads by source and score, funnel, pipeline value' },
  { key: 'revenue',           label: 'Revenue Summary',      Icon: DollarSign, desc: 'Revenue by source and team, weekly trend' },
  { key: 'response_time',     label: 'Response Time',        icon: '⏱️', desc: 'First-response time, SLA compliance, per-rep' },
  { key: 'rep_performance',   label: 'Sales Rep Performance',Icon: User, desc: 'Per-rep leads, conversions, revenue, tasks' },
  { key: 'team_performance',  label: 'Team Performance',     Icon: Users, desc: 'Team leads, conversion rate, revenue' },
  { key: 'whatsapp',          label: 'WhatsApp Activity',    Icon: MessageSquare, desc: 'Messages, AI vs human split, reply rate' },
  { key: 'support',           label: 'Support & Tickets',    Icon: Ticket, desc: 'Tickets opened, resolved, escalated' },
  { key: 'customer_health',   label: 'Customer Health',      Icon: Heart, desc: 'Active customers, NPS, churn risk' },
  { key: 'tasks',             label: 'Task & Activity',      Icon: CheckSquare, desc: 'Tasks created, completed, overdue' },
  { key: 'lost_leads',        label: 'Lost Lead Analysis',   Icon: AlertTriangle, desc: 'Lost leads by reason, rep, and team' },
  { key: 'channel_roi',       label: 'Channel ROI',          Icon: Radio, desc: 'Per-channel leads, conversion rate, ROI' },
]

const PRESETS = [
  { value: 'today',        label: 'Today' },
  { value: 'yesterday',    label: 'Yesterday' },
  { value: 'last_7d',      label: 'Last 7d' },
  { value: 'last_30d',     label: 'Last 30d' },
  { value: 'last_90d',     label: 'Last 90d' },
  { value: 'this_month',   label: 'This Month' },
  { value: 'last_month',   label: 'Last Month' },
  { value: 'this_quarter', label: 'This Quarter' },
  { value: 'this_year',    label: 'This Year' },
  { value: 'custom',       label: 'Custom' },
]

const COMPARE_MODES = [
  { value: 'previous_period', label: 'vs Prev Period' },
  { value: 'year_on_year',    label: 'vs Last Year' },
  { value: 'none',            label: 'Off' },
]

const ALL_SECTION_KEYS = SECTIONS.map(s => s.key)

const DEFAULT_FILTERS = {
  periodPreset: 'last_30d',
  dateFrom: '',
  dateTo: '',
  compare: 'previous_period',
  team: '',
  repId: '',
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtNum  = v  => v == null ? '—' : Number(v).toLocaleString()
const fmtCur  = v  => v == null ? '—' : `₦${Number(v).toLocaleString()}`
const fmtPct  = v  => v == null ? '—' : `${Number(v).toFixed(1)}%`
const fmtMins = v  => {
  if (v == null) return '—'
  const n = Number(v)
  return n < 60 ? `${n.toFixed(0)}m` : `${(n / 60).toFixed(1)}h`
}
const fmtAuto = (v, key = '') => {
  if (v == null) return '—'
  const k = key.toLowerCase()
  if (k.includes('revenue') || k.includes('cac') || k.includes('deal')) return fmtCur(v)
  if (k.includes('rate') || k.includes('pct') || k.includes('pct')) return fmtPct(v)
  if (k.includes('mins') || k.includes('time') || k.includes('hours')) return fmtMins(v)
  return fmtNum(v)
}

function buildParams(filters, sections) {
  const p = {}
  if (filters.periodPreset === 'custom') {
    if (filters.dateFrom) p.date_from = filters.dateFrom
    if (filters.dateTo)   p.date_to   = filters.dateTo
  } else {
    p.period_preset = filters.periodPreset
  }
  if (filters.compare !== 'previous_period') p.compare = filters.compare
  if (filters.team)  p.team   = filters.team
  if (filters.repId) p.rep_id = filters.repId
  if (sections.length < ALL_SECTION_KEYS.length) p.sections = sections.join(',')
  return p
}

// ─── DeltaChip ────────────────────────────────────────────────────────────────

function DeltaChip({ deltaPct, direction }) {
  if (direction === 'flat' || deltaPct == null) {
    return (
      <span style={{ fontSize: 11, fontWeight: 600, color: '#6B7280',
        background: '#F3F4F6', borderRadius: 12, padding: '2px 8px' }}>—</span>
    )
  }
  const up   = direction === 'up'
  const clr  = up ? '#16A34A' : '#DC2626'
  const bg   = up ? '#F0FDF4' : '#FEF2F2'
  const sign = Number(deltaPct) >= 0 ? '+' : ''
  return (
    <span style={{ fontSize: 11, fontWeight: 600, color: clr,
      background: bg, borderRadius: 12, padding: '2px 8px' }}>
      {up ? '▲' : '▼'} {sign}{Number(deltaPct).toFixed(1)}%
    </span>
  )
}

// ─── MetricRow ────────────────────────────────────────────────────────────────

function MetricRow({ label, current, previous, deltaPct, direction, isLast }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '9px 0',
      borderBottom: isLast ? 'none' : '1px solid #F3F4F6',
    }}>
      <span style={{ flex: 1, fontSize: 13, color: '#374151' }}>
        {label}
      </span>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#111827', minWidth: 70, textAlign: 'right' }}>
        {fmtAuto(current, label)}
      </span>
      <span style={{ fontSize: 12, color: '#9CA3AF', minWidth: 70, textAlign: 'right' }}>
        {fmtAuto(previous, label)}
      </span>
      <div style={{ minWidth: 80, textAlign: 'right' }}>
        <DeltaChip deltaPct={deltaPct} direction={direction} />
      </div>
    </div>
  )
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div style={{ background: 'white', borderRadius: 12, padding: 20, marginBottom: 12,
      border: '1px solid #E5E7EB' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: '#F3F4F6',
          animation: 'pulse 1.5s infinite' }} />
        <div style={{ width: 160, height: 14, borderRadius: 6, background: '#F3F4F6',
          animation: 'pulse 1.5s infinite' }} />
      </div>
      {[1,2,3].map(i => (
        <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <div style={{ flex: 1, height: 12, borderRadius: 4, background: '#F3F4F6',
            animation: 'pulse 1.5s infinite' }} />
          <div style={{ width: 60, height: 12, borderRadius: 4, background: '#F3F4F6',
            animation: 'pulse 1.5s infinite' }} />
          <div style={{ width: 60, height: 12, borderRadius: 4, background: '#F3F4F6',
            animation: 'pulse 1.5s infinite' }} />
        </div>
      ))}
    </div>
  )
}

// ─── Toast ───────────────────────────────────────────────────────────────────

function Toast({ msg, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000)
    return () => clearTimeout(t)
  }, [onClose])
  return (
    <div style={{
      position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
      background: '#1F2937', color: 'white', padding: '12px 20px',
      borderRadius: 10, fontSize: 13, fontWeight: 500,
      zIndex: 9999, boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
      display: 'flex', alignItems: 'center', gap: 10,
      maxWidth: 380, textAlign: 'center',
    }}>
      {msg}
      <button onClick={onClose} style={{ background: 'none', border: 'none',
        color: '#9CA3AF', cursor: 'pointer', display:'flex', alignItems:'center' }}><X size={16} /></button>
    </div>
  )
}

// ─── SortableTable ────────────────────────────────────────────────────────────

function SortableTable({ cols, rows }) {
  const [sortKey, setSortKey]  = useState(cols[0]?.key || '')
  const [sortDir, setSortDir]  = useState('desc')

  const sorted = [...(rows || [])].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv))
    return sortDir === 'asc' ? cmp : -cmp
  })

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  if (!rows?.length) return (
    <p style={{ fontSize: 13, color: '#9CA3AF', padding: '12px 0', margin: 0 }}>
      No data for this period
    </p>
  )

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ background: '#F9FAFB', borderBottom: '1px solid #E5E7EB' }}>
            {cols.map(col => (
              <th key={col.key}
                onClick={() => handleSort(col.key)}
                style={{ padding: '8px 10px', textAlign: col.align || 'left',
                  fontWeight: 600, color: '#6B7280', cursor: 'pointer',
                  whiteSpace: 'nowrap', userSelect: 'none' }}>
                {col.label}
                {sortKey === col.key && (
                  <span style={{ marginLeft: 4 }}>{sortDir === 'asc' ? '↑' : '↓'}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #F3F4F6',
              background: i % 2 === 0 ? 'white' : '#FAFAFA' }}>
              {cols.map(col => (
                <td key={col.key} style={{ padding: '8px 10px',
                  color: col.key === cols[0].key ? '#111827' : '#374151',
                  fontWeight: col.key === cols[0].key ? 500 : 400,
                  textAlign: col.align || 'left', whiteSpace: 'nowrap' }}>
                  {col.fmt ? col.fmt(row[col.key], row) : (row[col.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── BarChart (response time daily trend) ────────────────────────────────────

function BarChart({ data = [] }) {
  if (!data.length) return (
    <p style={{ fontSize: 12, color: '#9CA3AF', margin: 0 }}>No trend data available</p>
  )
  const values = data.map(d => d.avg_first_response_mins || 0)
  const max    = Math.max(...values, 1)
  const W = 300, H = 56
  const barW   = Math.max(3, Math.floor((W - data.length * 2) / data.length))
  return (
    <div>
      <svg width={W} height={H} style={{ display: 'block' }}>
        {data.map((d, i) => {
          const h   = Math.max(2, Math.round((d.avg_first_response_mins / max) * (H - 8)))
          const x   = i * (barW + 2)
          return (
            <rect key={i} x={x} y={H - h} width={barW} height={h}
              fill={ds.teal} rx={1} opacity={0.75}>
              <title>{d.date}: {d.avg_first_response_mins?.toFixed(1)}m avg</title>
            </rect>
          )
        })}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between',
        fontSize: 10, color: '#9CA3AF', marginTop: 2, width: W }}>
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </div>
    </div>
  )
}

// ─── Sparkline (rep weekly trend) ────────────────────────────────────────────

function RepSparkline({ values = [], orgAvg = 0 }) {
  if (!values.length) return null
  const W = 80, H = 20, pts = values.slice(-7)
  const max = Math.max(...pts, orgAvg, 1)
  const xs  = pts.map((_, i) => (i / Math.max(pts.length - 1, 1)) * W)
  const ys  = pts.map(v => H - (v / max) * H)
  const line = pts.map((_, i) => `${i === 0 ? 'M' : 'L'}${xs[i].toFixed(1)},${ys[i].toFixed(1)}`).join(' ')

  const aboveAvg = pts.filter(v => v >= orgAvg).length
  const streak   = (() => {
    let s = 0
    for (let i = pts.length - 1; i >= 0; i--) {
      if (pts[i] >= orgAvg) s++; else break
    }
    return s
  })()

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <svg width={W} height={H} style={{ overflow: 'visible' }}>
        <path d={line} fill="none" stroke={ds.teal} strokeWidth={1.5} />
        {pts.map((v, i) => (
          <circle key={i} cx={xs[i]} cy={ys[i]} r={2.5}
            fill={v >= orgAvg ? ds.teal : '#D1D5DB'}>
            <title>{v?.toFixed(1)}% (week {i + 1})</title>
          </circle>
        ))}
      </svg>
      <span style={{ fontSize: 11, color: streak > 0 ? '#16A34A' : '#9CA3AF' }}>
        {streak > 0 ? `${streak}w streak ✓` : `${pts.length - aboveAvg}w below`}
      </span>
    </div>
  )
}

// ─── Section Card ─────────────────────────────────────────────────────────────

function SectionCard({ sKey, label, icon, data, collapsed, onToggle, compareOff }) {
  if (!data) return null
  if (data.error) {
    return (
      <div style={{ background: 'white', borderRadius: 12, padding: 16, marginBottom: 12,
        border: '1px solid #FEE2E2' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {icon && <ReportIcon Icon={icon} size={18} />}
          <span style={{ fontSize: 14, fontWeight: 600, color: '#DC2626' }}>{label}</span>
          <span style={{ fontSize: 12, color: '#EF4444', marginLeft: 8 }}>
            Section unavailable — data could not be loaded
          </span>
        </div>
      </div>
    )
  }

  const colHeader = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: collapsed ? 0 : 12 }}>
      <div style={{ width: 30, height: 30, borderRadius: 7, background: '#F0FDFA',
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, flexShrink: 0 }}>
        {icon}
      </div>
      <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: '#111827' }}>{label}</span>
      {!compareOff && !collapsed && (
        <div style={{ display: 'flex', gap: 4, fontSize: 11, color: '#9CA3AF', marginRight: 8 }}>
          <span style={{ minWidth: 70, textAlign: 'right' }}>This period</span>
          <span style={{ minWidth: 70, textAlign: 'right' }}>Last period</span>
          <span style={{ minWidth: 80, textAlign: 'right' }}>Change</span>
        </div>
      )}
      <button onClick={onToggle} style={{ background: 'none', border: 'none',
        color: '#9CA3AF', cursor: 'pointer', fontSize: 16, padding: 4, lineHeight: 1 }}>
        {collapsed ? '＋' : '－'}
      </button>
    </div>
  )

  // Generic delta renderer
  const renderDeltas = (deltas) => {
    if (!deltas || typeof deltas !== 'object') return null
    const entries = Object.entries(deltas).filter(([, m]) => m && typeof m === 'object' && 'current' in m)
    if (!entries.length) return <p style={{ fontSize: 13, color: '#9CA3AF', margin: 0 }}>No data for this period</p>
    return entries.map(([key, m], i) => (
      <MetricRow
        key={key}
        label={key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
        current={m.current}
        previous={m.previous}
        deltaPct={m.delta_pct}
        direction={m.direction}
        isLast={i === entries.length - 1}
      />
    ))
  }

  const renderBody = () => {
    const curr = data.current || {}
    const deltas = data.deltas

    // ── Response Time — metrics + bar chart ──────────────────────────────────
    if (sKey === 'response_time') {
      const rt = data.current || {}
      const pr = data.previous || {}
      return (
        <div>
          <MetricRow label="Avg First Response" isLast={false}
            current={rt.org_avg_first_response_mins} previous={pr.org_avg_first_response_mins}
            deltaPct={data.delta_first_response_pct} direction={data.direction} />
          <MetricRow label="SLA Compliance" isLast={true}
            current={rt.sla_compliance_pct != null ? `${rt.sla_compliance_pct}%` : null}
            previous={pr.sla_compliance_pct != null ? `${pr.sla_compliance_pct}%` : null}
            deltaPct={null} direction={null} />
          {rt.daily_trend?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', margin: '0 0 8px' }}>
                Daily Avg Response Time
              </p>
              <BarChart data={rt.daily_trend} />
            </div>
          )}
          {rt.per_rep?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', margin: '0 0 8px' }}>Per-Rep Breakdown</p>
              <SortableTable
                cols={[
                  { key: 'rep_name',                   label: 'Rep' },
                  { key: 'avg_first_response_mins',    label: 'Avg First Response', fmt: fmtMins, align: 'right' },
                  { key: 'sla_compliance_pct',         label: 'SLA %', fmt: v => fmtPct(v), align: 'right' },
                  { key: 'sla_breaches',               label: 'Breaches', align: 'right' },
                ]}
                rows={rt.per_rep}
              />
            </div>
          )}
        </div>
      )
    }

    // ── Rep Performance — sortable table + sparkline ─────────────────────────
    if (sKey === 'rep_performance') {
      const orgAvgConv = curr.length
        ? (curr.reduce((a, r) => a + (r.close_rate || 0), 0) / curr.length)
        : 0
      return (
        <SortableTable
          cols={[
            { key: 'rep_name',          label: 'Rep' },
            { key: 'leads_assigned',    label: 'Assigned',   align: 'right', fmt: fmtNum },
            { key: 'leads_converted',   label: 'Converted',  align: 'right', fmt: fmtNum },
            { key: 'leads_lost',        label: 'Lost',       align: 'right', fmt: fmtNum },
            { key: 'leads_not_ready',   label: 'Not Ready',  align: 'right', fmt: fmtNum },
            { key: 'leads_in_progress', label: 'In Progress',align: 'right', fmt: fmtNum },
            { key: 'close_rate',        label: 'Conv %',     align: 'right', fmt: v => fmtPct(v) },
            { key: 'revenue_closed',    label: 'Revenue',    align: 'right', fmt: fmtCur },
            { key: 'tasks_completed',   label: 'Tasks Done', align: 'right', fmt: fmtNum },
            { key: 'ai_mode_pct',       label: 'AI Mode %',  align: 'right', fmt: v => fmtPct(v) },
            {
              key: 'close_rate',
              label: 'Trend',
              fmt: (_, row) => <RepSparkline values={[row.close_rate || 0]} orgAvg={orgAvgConv} />,
            },
          ]}
          rows={curr}
        />
      )
    }

    // ── Team Performance ─────────────────────────────────────────────────────
    if (sKey === 'team_performance') {
      return (
        <SortableTable
          cols={[
            { key: 'team_name',         label: 'Team' },
            { key: 'leads_generated',   label: 'Leads',    align: 'right', fmt: fmtNum },
            { key: 'conversion_rate',   label: 'Conv %',   align: 'right', fmt: v => fmtPct(v) },
            { key: 'revenue_generated', label: 'Revenue',  align: 'right', fmt: fmtCur },
            {
              key: 'is_best_performer',
              label: 'Top',
              fmt: v => v ? '⭐' : '',
              align: 'center',
            },
          ]}
          rows={curr}
        />
      )
    }

    // ── Channel ROI ──────────────────────────────────────────────────────────
    if (sKey === 'channel_roi') {
      return (
        <SortableTable
          cols={[
            { key: 'utm_source',      label: 'Channel' },
            { key: 'total_leads',     label: 'Leads',    align: 'right', fmt: fmtNum },
            { key: 'conversion_rate', label: 'Conv %',   align: 'right', fmt: v => fmtPct(v) },
            { key: 'revenue',         label: 'Revenue',  align: 'right', fmt: fmtCur },
            { key: 'roi_pct',         label: 'ROI %',    align: 'right', fmt: v => v == null ? '—' : `${Number(v).toFixed(1)}%` },
          ]}
          rows={data.current}
        />
      )
    }

    // ── Lost Leads — metric + reason table ───────────────────────────────────
    if (sKey === 'lost_leads') {
      const lostDelta = data.delta_total_lost
      return (
        <div>
          {lostDelta && (
            <MetricRow label="Total Lost" isLast={false}
              current={lostDelta.current} previous={lostDelta.previous}
              deltaPct={lostDelta.delta_pct} direction={lostDelta.direction} />
          )}
          {curr.lost_by_reason && Object.keys(curr.lost_by_reason).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', margin: '0 0 8px' }}>
                Top Lost Reasons
              </p>
              <SortableTable
                cols={[
                  { key: 'reason', label: 'Reason' },
                  { key: 'count',  label: 'Count', align: 'right', fmt: fmtNum },
                ]}
                rows={Object.entries(curr.lost_by_reason || {}).map(([reason, count]) => ({ reason, count }))}
              />
            </div>
          )}
        </div>
      )
    }

    // ── Revenue — special structure ──────────────────────────────────────────
    if (sKey === 'revenue') {
      return (
        <div>
          <MetricRow label="Total Revenue" isLast={false}
            current={curr.total_revenue} previous={data.previous?.total_revenue}
            deltaPct={data.delta_pct} direction={data.direction} />
          {curr.by_source && (
            <MetricRow label="Pipeline Revenue" isLast={false}
              current={curr.by_source.pipeline} previous={data.previous?.by_source?.pipeline}
              deltaPct={null} direction={null} />
          )}
          {curr.by_source && (
            <MetricRow label="Direct Sales Revenue" isLast={false}
              current={curr.by_source.direct} previous={data.previous?.by_source?.direct}
              deltaPct={null} direction={null} />
          )}
          {curr.avg_deal_value != null && (
            <MetricRow label="Avg Deal Value" isLast={true}
              current={curr.avg_deal_value} previous={data.previous?.avg_deal_value}
              deltaPct={null} direction={null} />
          )}
          {curr.by_team?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', margin: '0 0 8px' }}>
                Revenue by Team
              </p>
              <SortableTable
                cols={[
                  { key: 'team_name', label: 'Team' },
                  { key: 'revenue',   label: 'Revenue', align: 'right', fmt: fmtCur },
                ]}
                rows={curr.by_team}
              />
            </div>
          )}
        </div>
      )
    }

    // ── Lead Pipeline — extra tables ─────────────────────────────────────────
    if (sKey === 'lead_pipeline') {
      return (
        <div>
          {renderDeltas(deltas)}
          {data.leads_by_source?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', margin: '0 0 8px' }}>
                Leads by Source
              </p>
              <SortableTable
                cols={[
                  { key: 'source', label: 'Source' },
                  { key: 'count',  label: 'Count', align: 'right', fmt: fmtNum },
                ]}
                rows={data.leads_by_source}
              />
            </div>
          )}
          {data.top_lost_reasons?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', margin: '0 0 8px' }}>
                Top Lost Reasons
              </p>
              {data.top_lost_reasons.map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: '#374151', padding: '4px 0',
                  borderBottom: i < data.top_lost_reasons.length - 1 ? '1px solid #F3F4F6' : 'none' }}>
                  • {r.reason || r} {r.count != null ? `(${r.count})` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )
    }

    // ── Generic: render deltas ────────────────────────────────────────────────
    if (deltas) return renderDeltas(deltas)

    // ── Executive summary: render metrics ────────────────────────────────────
    if (data.metrics) return renderDeltas(data.metrics)

    return <p style={{ fontSize: 13, color: '#9CA3AF', margin: 0 }}>No data for this period</p>
  }

  return (
    <div style={{ background: 'white', borderRadius: 12, padding: '16px 20px',
      marginBottom: 12, border: '1px solid #E5E7EB' }}>
      {colHeader}
      {!collapsed && <div>{renderBody()}</div>}
    </div>
  )
}

// ─── Recipient Tag Input ──────────────────────────────────────────────────────

function RecipientTagInput({ value, onChange }) {
  const [input, setInput]   = useState('')
  const [tagErr, setTagErr] = useState('')
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  const PHONE_RE = /^\+[1-9]\d{7,14}$/

  const add = () => {
    const v = input.trim()
    if (!v) return
    if (!EMAIL_RE.test(v) && !PHONE_RE.test(v)) {
      setTagErr('Enter a valid email or E.164 phone number (e.g. +2348012345678)')
      return
    }
    if (value.length >= 10) { setTagErr('Max 10 recipients'); return }
    if (!value.includes(v)) onChange([...value, v])
    setInput(''); setTagErr('')
  }
  const remove = (i) => onChange(value.filter((_, idx) => idx !== i))

  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
        {value.map((r, i) => (
          <span key={i} style={{ background: '#F0FDFA', border: `1px solid ${ds.teal}30`,
            borderRadius: 20, padding: '3px 10px', fontSize: 12, color: '#111827',
            display: 'flex', alignItems: 'center', gap: 6 }}>
            {r}
            <button onClick={() => remove(i)} style={{ background: 'none', border: 'none',
              color: '#9CA3AF', cursor: 'pointer', padding: 0, display:'flex', alignItems:'center' }}><X size={14} /></button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={input} onChange={e => { setInput(e.target.value); setTagErr('') }}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add() } }}
          placeholder="Email or phone number, then Enter"
          style={{ flex: 1, padding: '8px 10px', border: '1px solid #D1D5DB',
            borderRadius: 8, fontSize: 13, outline: 'none' }} />
        <button onClick={add}
          style={{ padding: '8px 14px', background: ds.teal, color: 'white',
            border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 13 }}>Add</button>
      </div>
      {tagErr && <p style={{ fontSize: 12, color: '#EF4444', margin: '4px 0 0' }}>{tagErr}</p>}
    </div>
  )
}

// ─── Schedule Modal ───────────────────────────────────────────────────────────

const DOW_LABELS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
const SCHED_PRESETS = PRESETS.filter(p => p.value !== 'custom')
const HOUR_OPTIONS  = Array.from({ length: 17 }, (_, i) => i + 6)

const BLANK_FORM = {
  label: 'Weekly Management Report',
  frequency: 'weekly',
  dayOfWeek: 1,
  dayOfMonth: 1,
  sendHour: 8,
  periodPreset: 'last_7d',
  sections: ALL_SECTION_KEYS,
  deliveryChannel: 'email',
  recipients: [],
}

function ScheduleModal({ open, onClose, defaultSections }) {
  const [form, setForm]           = useState({ ...BLANK_FORM, sections: defaultSections || ALL_SECTION_KEYS })
  const [schedules, setSchedules] = useState([])
  const [loadingList, setLoadingList] = useState(false)
  const [saving, setSaving]       = useState(false)
  const [formErr, setFormErr]     = useState('')
  const [editingId, setEditingId] = useState(null)

  const loadSchedules = async () => {
    setLoadingList(true)
    try { setSchedules(await getScheduledReports()) } catch {}
    finally { setLoadingList(false) }
  }

  useEffect(() => { if (open) { loadSchedules(); setForm({ ...BLANK_FORM, sections: defaultSections || ALL_SECTION_KEYS }); setEditingId(null); setFormErr('') } }, [open])

  const upd = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const toggleSection = (key) => upd('sections',
    form.sections.includes(key) ? form.sections.filter(k => k !== key) : [...form.sections, key])

  const handleSave = async () => {
    if (!form.label.trim()) { setFormErr('Label is required'); return }
    if (!form.recipients.length) { setFormErr('At least one recipient is required'); return }
    if (!form.sections.length) { setFormErr('At least one section must be selected'); return }
    setSaving(true); setFormErr('')
    try {
      const payload = {
        label:            form.label.trim(),
        frequency:        form.frequency,
        day_of_week:      form.frequency === 'weekly'  ? form.dayOfWeek  : undefined,
        day_of_month:     form.frequency === 'monthly' ? form.dayOfMonth : undefined,
        send_hour:        form.sendHour,
        sections:         form.sections,
        period_preset:    form.periodPreset,
        delivery_channel: form.deliveryChannel,
        recipients:       form.recipients,
      }
      if (editingId) {
        await updateScheduledReport(editingId, payload)
      } else {
        await createScheduledReport(payload)
      }
      await loadSchedules()
      setEditingId(null)
      setForm({ ...BLANK_FORM, sections: defaultSections || ALL_SECTION_KEYS })
    } catch (e) {
      const msg = e?.response?.data?.detail
      setFormErr(typeof msg === 'string' ? msg : JSON.stringify(msg) || 'Save failed')
    } finally { setSaving(false) }
  }

  const handleEdit = (s) => {
    setEditingId(s.id)
    setForm({
      label: s.label, frequency: s.frequency,
      dayOfWeek: s.day_of_week ?? 1, dayOfMonth: s.day_of_month ?? 1,
      sendHour: s.send_hour ?? 8, periodPreset: s.period_preset || 'last_7d',
      sections: s.sections || ALL_SECTION_KEYS,
      deliveryChannel: s.delivery_channel || 'email',
      recipients: s.recipients || [],
    })
    setFormErr('')
  }

  const handleDelete = async (id) => {
    if (!window.confirm('Deactivate this scheduled report?')) return
    try {
      await deleteScheduledReport(id)
      await loadSchedules()
    } catch {}
  }

  if (!open) return null

  const inputStyle = { width: '100%', padding: '8px 10px', border: '1px solid #D1D5DB',
    borderRadius: 8, fontSize: 13, outline: 'none', boxSizing: 'border-box', background: 'white' }
  const lblStyle = { fontSize: 12, fontWeight: 600, color: '#374151',
    textTransform: 'uppercase', letterSpacing: '0.6px', display: 'block', marginBottom: 5 }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      zIndex: 9000, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>

      <div style={{ background: 'white', borderRadius: '20px 20px 0 0', width: '100%',
        maxWidth: 680, maxHeight: '90vh', overflowY: 'auto',
        padding: '24px 28px 32px' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, margin: 0 }}>
            Scheduled Reports
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none',
            color: '#9CA3AF', cursor: 'pointer', display:'flex', alignItems:'center', padding: 4 }}><X size={22} /></button>
        </div>

        {/* Form */}
        <div style={{ background: '#F9FAFB', borderRadius: 12, padding: 20, marginBottom: 24 }}>
          <p style={{ fontSize: 13, fontWeight: 600, color: ds.teal, margin: '0 0 16px' }}>
            {editingId ? <span style={{display:'inline-flex',alignItems:'center',gap:5}}><Edit size={13} />Edit Schedule</span> : <span style={{display:'inline-flex',alignItems:'center',gap:5}}><Calendar size={13} />New Schedule</span>}
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ gridColumn: '1/-1' }}>
              <label style={lblStyle}>Label</label>
              <input style={inputStyle} value={form.label}
                onChange={e => upd('label', e.target.value)} maxLength={100} />
            </div>

            <div>
              <label style={lblStyle}>Frequency</label>
              <div style={{ display: 'flex', gap: 6 }}>
                {['weekly','monthly'].map(f => (
                  <button key={f} onClick={() => upd('frequency', f)}
                    style={{ flex: 1, padding: '8px', border: `1px solid ${form.frequency === f ? ds.teal : '#D1D5DB'}`,
                      borderRadius: 8, background: form.frequency === f ? '#F0FDFA' : 'white',
                      color: form.frequency === f ? ds.teal : '#374151',
                      cursor: 'pointer', fontSize: 13, fontWeight: form.frequency === f ? 600 : 400 }}>
                    {f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label style={lblStyle}>{form.frequency === 'weekly' ? 'Day of Week' : 'Day of Month'}</label>
              {form.frequency === 'weekly' ? (
                <select style={inputStyle} value={form.dayOfWeek}
                  onChange={e => upd('dayOfWeek', Number(e.target.value))}>
                  {DOW_LABELS.map((d,i) => <option key={i} value={i}>{d}</option>)}
                </select>
              ) : (
                <select style={inputStyle} value={form.dayOfMonth}
                  onChange={e => upd('dayOfMonth', Number(e.target.value))}>
                  {Array.from({length:28},(_,i)=>i+1).map(d => (
                    <option key={d} value={d}>{d}{d===1?'st':d===2?'nd':d===3?'rd':'th'}</option>
                  ))}
                </select>
              )}
            </div>

            <div>
              <label style={lblStyle}>Send Time (UTC) <span style={{fontSize:11,color:'#9CA3AF',fontWeight:400}}>— stored in UTC</span></label>
              <select style={inputStyle} value={form.sendHour}
                onChange={e => upd('sendHour', Number(e.target.value))}>
                {HOUR_OPTIONS.map(h => (
                  <option key={h} value={h}>{String(h).padStart(2,'0')}:00</option>
                ))}
              </select>
            </div>

            <div>
              <label style={lblStyle}>Period to Cover</label>
              <select style={inputStyle} value={form.periodPreset}
                onChange={e => upd('periodPreset', e.target.value)}>
                {SCHED_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>

            <div>
              <label style={lblStyle}>Delivery</label>
              <div style={{ display: 'flex', gap: 6 }}>
                {['email','whatsapp'].map(c => (
                  <button key={c} onClick={() => upd('deliveryChannel', c)}
                    style={{ flex: 1, padding: '8px', border: `1px solid ${form.deliveryChannel === c ? ds.teal : '#D1D5DB'}`,
                      borderRadius: 8, background: form.deliveryChannel === c ? '#F0FDFA' : 'white',
                      color: form.deliveryChannel === c ? ds.teal : '#374151',
                      cursor: 'pointer', fontSize: 13, fontWeight: form.deliveryChannel === c ? 600 : 400 }}>
                    {c === 'email' ? <span style={{display:'inline-flex',alignItems:'center',gap:4}}><MessageSquare size={12} />Email</span> : <span style={{display:'inline-flex',alignItems:'center',gap:4}}><MessageSquare size={12} />WhatsApp</span>}
                  </button>
                ))}
              </div>
              {form.deliveryChannel === 'whatsapp' && (
                <p style={{ fontSize: 11, color: '#F59E0B', marginTop: 4 }}>
                  <span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />WhatsApp delivery coming soon — use email for now</span>
                </p>
              )}
            </div>

            <div style={{ gridColumn: '1/-1' }}>
              <label style={lblStyle}>Recipients</label>
              <RecipientTagInput value={form.recipients} onChange={v => upd('recipients', v)} />
            </div>

            <div style={{ gridColumn: '1/-1' }}>
              <label style={lblStyle}>Sections to Include</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {SECTIONS.map(s => (
                  <button key={s.key} onClick={() => toggleSection(s.key)}
                    style={{ padding: '5px 10px', border: `1px solid ${form.sections.includes(s.key) ? ds.teal : '#D1D5DB'}`,
                      borderRadius: 20, background: form.sections.includes(s.key) ? '#F0FDFA' : 'white',
                      color: form.sections.includes(s.key) ? ds.teal : '#6B7280',
                      cursor: 'pointer', fontSize: 12, fontWeight: form.sections.includes(s.key) ? 600 : 400 }}>
                    {s.Icon && <ReportIcon Icon={s.Icon} size={14} />} {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {formErr && <p style={{ fontSize: 13, color: '#EF4444', margin: '12px 0 0' }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{formErr}</span></p>}

          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button onClick={handleSave} disabled={saving}
              style={{ flex: 1, padding: '10px', background: saving ? '#9CA3AF' : ds.teal,
                color: 'white', border: 'none', borderRadius: 8, cursor: saving ? 'not-allowed' : 'pointer',
                fontSize: 13, fontWeight: 600 }}>
              {saving ? 'Saving…' : editingId ? 'Update Schedule' : 'Create Schedule'}
            </button>
            {editingId && (
              <button onClick={() => { setEditingId(null); setForm({ ...BLANK_FORM }); setFormErr('') }}
                style={{ padding: '10px 16px', background: 'none', border: '1px solid #D1D5DB',
                  borderRadius: 8, cursor: 'pointer', fontSize: 13, color: '#6B7280' }}>
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* Existing schedules */}
        <h3 style={{ fontSize: 14, fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>
          Active Schedules {schedules.length > 0 && `(${schedules.length})`}
        </h3>
        {loadingList ? (
          <p style={{ fontSize: 13, color: '#9CA3AF' }}>Loading…</p>
        ) : schedules.length === 0 ? (
          <p style={{ fontSize: 13, color: '#9CA3AF' }}>No scheduled reports yet.</p>
        ) : (
          schedules.map(s => (
            <div key={s.id} style={{ border: '1px solid #E5E7EB', borderRadius: 10,
              padding: '12px 14px', marginBottom: 8,
              background: s.is_active ? 'white' : '#F9FAFB', opacity: s.is_active ? 1 : 0.6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: '#111827', margin: 0 }}>{s.label}</p>
                  <p style={{ fontSize: 12, color: '#9CA3AF', margin: '2px 0 0' }}>
                    {s.frequency === 'weekly'
                      ? `Every ${DOW_LABELS[(s.day_of_week || 0)]} at ${String(s.send_hour || 8).padStart(2,'0')}:00 UTC`
                      : `Day ${s.day_of_month} monthly at ${String(s.send_hour || 8).padStart(2,'0')}:00 UTC`}
                    {s.next_send_at && ` · Next: ${new Date(s.next_send_at).toLocaleDateString()}`}
                  </p>
                  <p style={{ fontSize: 11, color: '#9CA3AF', margin: '2px 0 0' }}>
                    {(s.recipients || []).join(', ')}
                  </p>
                </div>
                <button onClick={() => handleEdit(s)}
                  style={{ background: 'none', border: '1px solid #D1D5DB', borderRadius: 6,
                    padding: '5px 10px', cursor: 'pointer', fontSize: 12, color: '#374151' }}>
                  Edit
                </button>
                <button onClick={() => handleDelete(s.id)}
                  style={{ background: 'none', border: '1px solid #FEE2E2', borderRadius: 6,
                    padding: '5px 10px', cursor: 'pointer', fontSize: 12, color: '#EF4444' }}>
                  Delete
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ─── Filter Panel ─────────────────────────────────────────────────────────────

function FilterPanel({ filters, setFilters, sections, setSections, teams, users, onApply, loading, isMobile, open, onClose }) {
  const upd = (k, v) => setFilters(f => ({ ...f, [k]: v }))
  const toggleSection = (key) => {
    setSections(s => s.includes(key) ? s.filter(k => k !== key) : [...s, key])
  }
  const allOn  = sections.length === ALL_SECTION_KEYS.length
  const allOff = sections.length === 0

  const content = (
    <div style={{ padding: isMobile ? '20px 16px 32px' : 20 }}>
      {/* Period preset */}
      <p style={{ fontSize: 11, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase',
        letterSpacing: '0.8px', margin: '0 0 8px' }}>Period</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 14 }}>
        {PRESETS.map(p => (
          <button key={p.value}
            onClick={() => upd('periodPreset', p.value)}
            style={{ padding: '5px 10px', fontSize: 12,
              background: filters.periodPreset === p.value ? ds.teal : '#F3F4F6',
              color: filters.periodPreset === p.value ? 'white' : '#374151',
              border: 'none', borderRadius: 20, cursor: 'pointer',
              fontWeight: filters.periodPreset === p.value ? 600 : 400 }}>
            {p.label}
          </button>
        ))}
      </div>

      {/* Custom date inputs */}
      {filters.periodPreset === 'custom' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
          <div>
            <label style={{ fontSize: 11, color: '#9CA3AF', display: 'block', marginBottom: 4 }}>From</label>
            <input type="date" value={filters.dateFrom}
              max={filters.dateTo || undefined}
              onChange={e => upd('dateFrom', e.target.value)}
              style={{ width: '100%', padding: '7px 8px', border: '1px solid #D1D5DB',
                borderRadius: 8, fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: '#9CA3AF', display: 'block', marginBottom: 4 }}>To</label>
            <input type="date" value={filters.dateTo}
              min={filters.dateFrom || undefined}
              onChange={e => upd('dateTo', e.target.value)}
              style={{ width: '100%', padding: '7px 8px', border: '1px solid #D1D5DB',
                borderRadius: 8, fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
          </div>
        </div>
      )}

      {/* Comparison mode */}
      <p style={{ fontSize: 11, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase',
        letterSpacing: '0.8px', margin: '0 0 8px' }}>Comparison</p>
      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {COMPARE_MODES.map(m => (
          <button key={m.value} onClick={() => upd('compare', m.value)}
            style={{ flex: 1, padding: '7px 6px', fontSize: 11,
              background: filters.compare === m.value ? ds.teal : '#F3F4F6',
              color: filters.compare === m.value ? 'white' : '#374151',
              border: 'none', borderRadius: 8, cursor: 'pointer',
              fontWeight: filters.compare === m.value ? 600 : 400, whiteSpace: 'nowrap' }}>
            {m.label}
          </button>
        ))}
      </div>

      {/* Team filter */}
      {teams.length > 0 && (
        <>
          <p style={{ fontSize: 11, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase',
            letterSpacing: '0.8px', margin: '0 0 6px' }}>Team</p>
          <select value={filters.team}
            onChange={e => upd('team', e.target.value)}
            style={{ width: '100%', padding: '8px 10px', border: '1px solid #D1D5DB',
              borderRadius: 8, fontSize: 13, marginBottom: 14, outline: 'none',
              boxSizing: 'border-box', background: 'white' }}>
            <option value="">All Teams</option>
            {teams.map(t => <option key={t.id || t.name} value={t.name}>{t.name}</option>)}
          </select>
        </>
      )}

      {/* Staff/rep filter */}
      {users.length > 0 && (
        <>
          <p style={{ fontSize: 11, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase',
            letterSpacing: '0.8px', margin: '0 0 6px' }}>Staff Member</p>
          <select value={filters.repId}
            onChange={e => upd('repId', e.target.value)}
            style={{ width: '100%', padding: '8px 10px', border: '1px solid #D1D5DB',
              borderRadius: 8, fontSize: 13, marginBottom: 14, outline: 'none',
              boxSizing: 'border-box', background: 'white' }}>
            <option value="">All Staff</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.full_name || u.email}</option>)}
          </select>
        </>
      )}

      {/* Section toggles */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <p style={{ fontSize: 11, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase',
          letterSpacing: '0.8px', margin: 0 }}>Sections</p>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => setSections([...ALL_SECTION_KEYS])}
            style={{ fontSize: 11, color: ds.teal, background: 'none', border: 'none',
              cursor: 'pointer', padding: 0, textDecoration: allOn ? 'none' : 'underline' }}>
            All
          </button>
          <button onClick={() => setSections([])}
            style={{ fontSize: 11, color: '#EF4444', background: 'none', border: 'none',
              cursor: 'pointer', padding: 0, textDecoration: allOff ? 'none' : 'underline' }}>
            None
          </button>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 16 }}>
        {SECTIONS.map(s => (
          <label key={s.key}
            style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '6px 0',
              cursor: 'pointer', borderBottom: '1px solid #F9FAFB' }}>
            <input type="checkbox" checked={sections.includes(s.key)}
              onChange={() => toggleSection(s.key)}
              style={{ marginTop: 2, accentColor: ds.teal, flexShrink: 0 }} />
            <div>
              <span style={{ fontSize: 13, color: '#111827', fontWeight: 500 }}>
                {s.Icon && <ReportIcon Icon={s.Icon} size={14} />} {s.label}
              </span>
              <p style={{ fontSize: 11, color: '#9CA3AF', margin: '1px 0 0' }}>{s.desc}</p>
            </div>
          </label>
        ))}
      </div>

      <button onClick={() => { onApply(); if (isMobile) onClose() }}
        disabled={loading || sections.length === 0}
        style={{ width: '100%', padding: '12px', background: loading || sections.length === 0 ? '#9CA3AF' : ds.teal,
          color: 'white', border: 'none', borderRadius: 10, cursor: loading || sections.length === 0 ? 'not-allowed' : 'pointer',
          fontSize: 14, fontWeight: 600, fontFamily: ds.fontSyne }}>
        {loading ? 'Loading…' : 'Apply Filters'}
      </button>
    </div>
  )

  // Mobile: slide-up sheet
  if (isMobile) {
    return (
      <>
        {open && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
            zIndex: 2000 }} onClick={onClose} />
        )}
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          background: 'white', borderRadius: '20px 20px 0 0',
          zIndex: 2001, maxHeight: '85vh', overflowY: 'auto',
          transform: open ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.3s cubic-bezier(0.4,0,0.2,1)',
        }}>
          <div style={{ padding: '12px 16px 0', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', borderBottom: '1px solid #F3F4F6', marginBottom: 4 }}>
            <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16 }}>Filters</span>
            <button onClick={onClose} style={{ background: 'none', border: 'none',
              color: '#9CA3AF', cursor: 'pointer', display:'flex', alignItems:'center' }}><X size={20} /></button>
          </div>
          {content}
        </div>
      </>
    )
  }

  // Desktop: sidebar
  return (
    <div style={{
      width: 280, flexShrink: 0, background: 'white',
      borderRight: '1px solid #E5E7EB', height: '100%',
      overflowY: 'auto', position: 'sticky', top: 0,
    }}>
      {content}
    </div>
  )
}

// ─── Main Module ──────────────────────────────────────────────────────────────

export default function ReportsModule({ user }) {
  const role = user?.roles?.template || useAuthStore.getState().user?.roles?.template || ''

  // RBAC guard
  if (!['owner', 'ops_manager'].includes(role)) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ display:'flex',justifyContent:'center',marginBottom:12 }}><Lock size={40} color={ds.teal} strokeWidth={1.5} /></div>
          <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 16, color: ds.dark }}>
            Access restricted
          </p>
          <p style={{ fontSize: 13, color: '#9CA3AF' }}>
            Management reports are available to owners and ops managers only.
          </p>
        </div>
      </div>
    )
  }

  const isMobile = useIsMobile()

  const [filters, setFilters]         = useState(DEFAULT_FILTERS)
  const [sections, setSections]       = useState([...ALL_SECTION_KEYS])
  const [report, setReport]           = useState(null)
  const [loading, setLoading]         = useState(false)
  const [fetchErr, setFetchErr]       = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [collapsed, setCollapsed]     = useState({})
  const [toast, setToast]             = useState(null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [teams, setTeams]             = useState([])
  const [users, setUsers]             = useState([])

  // Load supporting filter data on mount
  useEffect(() => {
    getGrowthTeams().then(setTeams).catch(() => {})
    getOrgUsers().then(us => {
      const reps = us.filter(u => {
        const t = u?.roles?.template || u?.role_template || ''
        return ['sales_agent','customer_success','ops_manager','owner'].includes(t)
      })
      setUsers(reps.length ? reps : us)
    }).catch(() => {})
  }, [])

  // Initial fetch
  useEffect(() => { handleApply() }, [])

  const handleApply = async () => {
    setLoading(true)
    setFetchErr(null)
    try {
      const params = buildParams(filters, sections)
      const data   = await getFullReport(params)
      setReport(data)
    } catch (e) {
      setFetchErr('Failed to load report. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    if (!sections.length) return
    setDownloading(true)
    try {
      const params = buildParams(filters, sections)
      const blob   = await downloadReport(params)
      const url    = URL.createObjectURL(blob)
      const a      = document.createElement('a')
      const label  = report?.report_meta?.period_label?.replace(/[^a-z0-9]/gi, '-') || 'report'
      a.href = url
      a.download = `opsra-${label}.pdf`
      document.body.appendChild(a)
      a.click()
      URL.revokeObjectURL(url)
      a.remove()
    } catch (e) {
      if (e?.response?.status === 429) {
        setToast('You can download up to 10 reports per hour.')
      } else {
        setToast('PDF download failed. Please try again.')
      }
    } finally {
      setDownloading(false) }
  }

  const toggleCollapse = (key) => setCollapsed(c => ({ ...c, [key]: !c[key] }))

  const meta = report?.report_meta

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light }}>

      {/* ── Module Header ───────────────────────────────────────────────────── */}
      <div style={{ background: ds.dark, padding: '20px 28px',
        borderBottom: '1px solid #1a2f3f', display: 'flex',
        alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: ds.teal,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 14, color: 'white', flexShrink: 0 }}><ClipboardList size={20} color={ds.teal} /></div>
          <div>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: 'white', margin: 0 }}>
              Management Reports
            </h1>
            <p style={{ fontSize: 12, color: '#6B8FA0', margin: '2px 0 0' }}>
              {meta ? `${meta.period_label} · ${meta.compare_mode?.replace(/_/g,' ')}` : 'Filterable, downloadable business reports'}
            </p>
          </div>
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {isMobile && (
            <button onClick={() => setFiltersOpen(true)}
              style={{ padding: '8px 14px', background: 'none', border: '1px solid #2a4a5a',
                borderRadius: 8, color: '#A0BDC8', cursor: 'pointer', fontSize: 13 }}>
              <span style={{display:"inline-flex",alignItems:"center",gap:5}}><Filter size={13} />Filters</span>
            </button>
          )}
          <button onClick={() => setScheduleOpen(true)}
            style={{ padding: '8px 14px', background: 'none', border: '1px solid #2a4a5a',
              borderRadius: 8, color: '#A0BDC8', cursor: 'pointer', fontSize: 13 }}>
            <span style={{display:"inline-flex",alignItems:"center",gap:5}}><Calendar size={13} />Schedule</span>
          </button>
          <button onClick={handleApply} disabled={loading}
            style={{ padding: '8px 14px', background: 'none', border: '1px solid #2a4a5a',
              borderRadius: 8, color: loading ? '#3a5a6a' : '#A0BDC8',
              cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13 }}>
            {loading ? '⟳ Loading…' : '↻ Refresh'}
          </button>
          <button
            onClick={handleDownload}
            disabled={downloading || sections.length === 0 || loading}
            title={sections.length === 0 ? 'Select at least one section' : 'Download as PDF'}
            style={{ padding: '8px 18px', background: sections.length === 0 ? '#9CA3AF' : ds.teal,
              border: 'none', borderRadius: 8, color: 'white',
              cursor: (downloading || sections.length === 0 || loading) ? 'not-allowed' : 'pointer',
              fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne,
              display: 'flex', alignItems: 'center', gap: 6 }}>
            {downloading ? (
              <>
                <span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: 'white', borderRadius: '50%', display: 'inline-block',
                  animation: 'spin 0.7s linear infinite' }} />
                Generating…
              </>
            ) : '⬇ Download PDF'}
          </button>
        </div>
      </div>

      {/* ── Body: filter panel + preview ────────────────────────────────────── */}
      <div style={{ display: 'flex', height: 'calc(100vh - 120px)', overflow: 'hidden' }}>

        {/* Desktop filter panel */}
        {!isMobile && (
          <FilterPanel
            filters={filters} setFilters={setFilters}
            sections={sections} setSections={setSections}
            teams={teams} users={users}
            onApply={handleApply} loading={loading}
            isMobile={false}
          />
        )}

        {/* Mobile filter sheet */}
        {isMobile && (
          <FilterPanel
            filters={filters} setFilters={setFilters}
            sections={sections} setSections={setSections}
            teams={teams} users={users}
            onApply={handleApply} loading={loading}
            isMobile={true} open={filtersOpen} onClose={() => setFiltersOpen(false)}
          />
        )}

        {/* Report preview */}
        <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '16px 12px' : '20px 24px' }}>

          {/* Error */}
          {fetchErr && !loading && (
            <div style={{ background: '#FEF2F2', border: '1px solid #FEE2E2',
              borderRadius: 10, padding: '14px 16px', marginBottom: 16 }}>
              <p style={{ color: '#DC2626', fontSize: 13, margin: 0 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{fetchErr}</span></p>
            </div>
          )}

          {/* Loading skeletons */}
          {loading && sections.map(s => <SkeletonCard key={s} />)}

          {/* Sections */}
          {!loading && report && (
            <>
              {/* Comparison legend */}
              {filters.compare !== 'none' && !loading && (
                <div style={{ display: 'flex', gap: 16, marginBottom: 16,
                  fontSize: 11, color: '#9CA3AF', flexWrap: 'wrap' }}>
                  <span style={{display:"inline-flex",alignItems:"center",gap:4}}><BarChart2 size={13} />Current: <strong style={{ color: '#111827' }}>
                    {meta?.period_label || '—'}</strong></span>
                  <span style={{display:"inline-flex",alignItems:"center",gap:4}}><RefreshCw size={13} />Compare: <strong style={{ color: '#111827' }}>
                    {meta?.comparison_period_label || '—'}</strong></span>
                </div>
              )}

              {sections.map(key => {
                const sec = SECTIONS.find(s => s.key === key)
                if (!sec) return null
                return (
                  <SectionCard
                    key={key}
                    sKey={key}
                    label={sec.label}
                    icon={sec.Icon}
                    data={report[key]}
                    collapsed={!!collapsed[key]}
                    onToggle={() => toggleCollapse(key)}
                    compareOff={filters.compare === 'none'}
                  />
                )
              })}
            </>
          )}

          {/* Empty state */}
          {!loading && !report && !fetchErr && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
              minHeight: 300, flexDirection: 'column', gap: 12, color: '#9CA3AF' }}>
              <div style={{ fontSize: 48 }}><ClipboardList size={20} color={ds.teal} /></div>
              <p style={{ fontSize: 14, fontWeight: 600, color: '#374151', margin: 0 }}>
                No report loaded
              </p>
              <p style={{ fontSize: 13, margin: 0 }}>
                Select filters and click Apply to generate a report.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Schedule modal */}
      <ScheduleModal
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        defaultSections={sections}
      />

      {/* Toast */}
      {toast && <Toast msg={toast} onClose={() => setToast(null)} />}
    </div>
  )
}// ── Safe icon renderer ──────────────────────────────────────────────────────
function ReportIcon({ Icon, size = 16 }) {
  if (!Icon) return null
  return <Icon size={size} strokeWidth={1.8} />
}


