/**
 * modules/ops/DashboardView.jsx
 * Executive dashboard — live metric stat cards — Phase 6B.
 *
 * Layout:
 *   Row 1 — Pipeline:    New Leads (week) · Total Leads · Active Customers
 *   Row 2 — Operations:  Open Tickets · SLA Breached · Renewals Due (30d)
 *   Row 3 — Health:      High Churn Risk · Critical Churn · Avg NPS · Overdue Tasks
 *   Row 4 — Revenue:     MRR · Revenue at Risk  (only rendered when non-null — owner/admin)
 *
 * Revenue fields are omitted server-side for agents (ops_service.py §12.5).
 * This component renders them only when the value is not null — no client-side
 * role check needed.
 */

import { ds } from '../../utils/ds'

const CARD_GAP  = 16
const CARD_BASE = {
  background:   ds.dark2,
  border:       '1px solid #1a2f3f',
  borderRadius: 12,
  padding:      '20px 22px',
  flex:         1,
  minWidth:     0,
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent, icon, loading }) {
  return (
    <div style={{
      ...CARD_BASE,
      borderLeft: accent ? `3px solid ${accent}` : '1px solid #1a2f3f',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 11, fontWeight: 600, color: '#4a7a8a', textTransform: 'uppercase', letterSpacing: '1px', margin: '0 0 8px' }}>
            {label}
          </p>
          {loading ? (
            <div style={{ width: 48, height: 28, background: '#1a2f3f', borderRadius: 6, animation: 'pulse 1.5s infinite' }} />
          ) : (
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 28, color: accent ?? 'white', margin: 0, lineHeight: 1 }}>
              {value ?? '—'}
            </p>
          )}
          {sub && !loading && (
            <p style={{ fontSize: 12, color: '#4a7a8a', margin: '6px 0 0', lineHeight: 1.4 }}>
              {sub}
            </p>
          )}
        </div>
        {icon && (
          <span style={{ fontSize: 22, opacity: 0.6 }}>{icon}</span>
        )}
      </div>
    </div>
  )
}

function Row({ children }) {
  return (
    <div style={{ display: 'flex', gap: CARD_GAP, marginBottom: CARD_GAP }}>
      {children}
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <p style={{
      fontSize: 10, fontWeight: 600, color: '#3a5a6a',
      textTransform: 'uppercase', letterSpacing: '1.2px',
      margin: `${CARD_GAP * 1.5}px 0 ${CARD_GAP}px`,
    }}>
      {children}
    </p>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DashboardView({ metrics, loading, error, onRefresh }) {
  const m = metrics ?? {}
  const hasRevenue = m.mrr_ngn !== null && m.mrr_ngn !== undefined

  const fmtCurrency = (v) =>
    v == null ? '—' : `₦${Number(v).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`

  const fmtNps = (v) =>
    v == null ? 'No data' : `${Number(v).toFixed(1)} / 5`

  return (
    <div style={{ padding: '24px 28px' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: ds.dark, margin: 0 }}>
            Executive Dashboard
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: '4px 0 0' }}>
            Live metrics across all modules
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: loading ? '#e8edf0' : ds.teal,
            color: loading ? ds.gray : 'white',
            border: 'none', borderRadius: 8,
            padding: '8px 16px', fontSize: 13, fontWeight: 600,
            fontFamily: ds.fontDm, cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s',
          }}
        >
          <span style={{ display: 'inline-block', animation: loading ? 'spin 0.8s linear infinite' : 'none' }}>
            ↻
          </span>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* ── Error banner ── */}
      {error && (
        <div style={{
          background: '#fff1f0', border: '1px solid #fca5a5', borderRadius: 8,
          padding: '10px 14px', fontSize: 13, color: '#b91c1c', marginBottom: 20,
        }}>
          ⚠ {error}
        </div>
      )}

      {/* ── Pipeline ── */}
      <SectionLabel>Pipeline</SectionLabel>
      <Row>
        <StatCard label="New Leads This Week"  value={m.leads_this_week}   icon="🎯" loading={loading} />
        <StatCard label="Total Leads"          value={m.leads_total}        icon="📋" loading={loading} />
        <StatCard label="Active Customers"     value={m.active_customers}   icon="👥" loading={loading} accent={ds.teal} />
      </Row>

      {/* ── Operations ── */}
      <SectionLabel>Operations</SectionLabel>
      <Row>
        <StatCard
          label="Open Tickets"
          value={m.open_tickets}
          icon="🎫"
          loading={loading}
          accent={m.open_tickets > 0 ? '#d97706' : undefined}
        />
        <StatCard
          label="SLA Breached"
          value={m.sla_breached_tickets}
          icon="🚨"
          loading={loading}
          accent={m.sla_breached_tickets > 0 ? '#dc2626' : undefined}
          sub={m.sla_breached_tickets > 0 ? 'Requires immediate attention' : undefined}
        />
        <StatCard
          label="Renewals Due (30 days)"
          value={m.renewals_due_30_days}
          icon="🔄"
          loading={loading}
          accent={m.renewals_due_30_days > 0 ? '#d97706' : undefined}
        />
      </Row>

      {/* ── Health ── */}
      <SectionLabel>Customer Health</SectionLabel>
      <Row>
        <StatCard
          label="High Churn Risk"
          value={m.churn_risk_high}
          icon="⚠️"
          loading={loading}
          accent={m.churn_risk_high > 0 ? '#d97706' : undefined}
        />
        <StatCard
          label="Critical Churn Risk"
          value={m.churn_risk_critical}
          icon="🔴"
          loading={loading}
          accent={m.churn_risk_critical > 0 ? '#dc2626' : undefined}
          sub={m.churn_risk_critical > 0 ? 'Immediate follow-up required' : undefined}
        />
        <StatCard
          label="Average NPS"
          value={loading ? undefined : fmtNps(m.nps_average)}
          icon="⭐"
          loading={loading}
          accent={
            m.nps_average == null ? undefined
            : m.nps_average >= 4   ? '#16a34a'
            : m.nps_average >= 3   ? '#d97706'
            : '#dc2626'
          }
        />
        <StatCard
          label="Overdue Tasks"
          value={m.overdue_tasks}
          icon="✅"
          loading={loading}
          accent={m.overdue_tasks > 0 ? '#d97706' : undefined}
        />
      </Row>

      {/* ── Revenue (owner / admin only — null for agents) ── */}
      {(hasRevenue || loading) && (
        <>
          <SectionLabel>Revenue</SectionLabel>
          <Row>
            <StatCard
              label="Monthly Recurring Revenue"
              value={loading ? undefined : fmtCurrency(m.mrr_ngn)}
              icon="💰"
              loading={loading}
              accent={ds.teal}
            />
            <StatCard
              label="Revenue at Risk"
              value={loading ? undefined : fmtCurrency(m.revenue_at_risk_ngn)}
              icon="⚠️"
              loading={loading}
              accent={
                m.revenue_at_risk_ngn > 0 ? '#dc2626' : undefined
              }
              sub={
                m.revenue_at_risk_ngn > 0
                  ? 'From high & critical churn risk customers'
                  : undefined
              }
            />
            {/* Spacer to keep 3-col grid feel */}
            <div style={{ flex: 2, minWidth: 0 }} />
          </Row>
        </>
      )}
    </div>
  )
}
