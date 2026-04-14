/**
 * CustomerList.jsx — Module 02 customer list.
 *
 * Displays all customers for the org in a table.
 * Filters: churn_risk, assigned_to, onboarding_complete.
 * Clicking a row opens CustomerProfile.
 *
 * M01-7a additions:
 *   - Attention badge system — multi-signal per row:
 *       💬 N  unread WhatsApp messages  (red)
 *       🎫 N  open tickets              (orange)
 *       ⚠    high/critical churn risk  (shown separately in Churn Risk column
 *             but also contributes to has_attention border highlight)
 *     Fetched via GET /api/v1/customers/attention-summary on mount.
 *     Replaces the previous getUnreadCounts() call.
 *
 * Design follows the existing app shell (dark topbar, teal accent).
 * All colours from ds.js — no hardcoded hex.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getCustomerAttentionSummary } from '../../services/customers.service'
import useCustomers from '../../hooks/useCustomers'
import Pagination from '../../shared/Pagination'

// ── Churn risk badge ──────────────────────────────────────────────────────────
const RISK_STYLE = {
  low:      { bg: '#E8F8EE', color: '#27AE60' },
  medium:   { bg: '#FFF9E0', color: '#D4AC0D' },
  high:     { bg: '#FFF3E0', color: '#E07B3A' },
  critical: { bg: '#FFE8E8', color: '#C0392B' },
}

function RiskBadge({ risk }) {
  const s = RISK_STYLE[risk] || RISK_STYLE.low
  return (
    <span style={{
      background: s.bg, color: s.color,
      borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 700,
      fontFamily: ds.fontHead, textTransform: 'capitalize',
    }}>
      {risk || 'low'}
    </span>
  )
}

// ── Onboarding badge ──────────────────────────────────────────────────────────
function OnboardBadge({ done }) {
  return (
    <span style={{
      background: done ? '#E8F8EE' : '#EAF0F2',
      color: done ? '#27AE60' : ds.gray,
      borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 600,
    }}>
      {done ? '✓ Complete' : 'In Progress'}
    </span>
  )
}

// ── Attention badges for a customer row ───────────────────────────────────────
function AttentionBadges({ attention }) {
  if (!attention) return null
  const badges = []
  if ((attention.unread_messages ?? 0) > 0) {
    badges.push({
      key: 'msg',
      label: `💬 ${attention.unread_messages}`,
      bg: '#E53E3E', color: 'white',
      title: `${attention.unread_messages} unread message${attention.unread_messages > 1 ? 's' : ''}`,
    })
  }
  if ((attention.open_tickets ?? 0) > 0) {
    badges.push({
      key: 'ticket',
      label: `🎫 ${attention.open_tickets}`,
      bg: '#ED8936', color: 'white',
      title: `${attention.open_tickets} open ticket${attention.open_tickets > 1 ? 's' : ''}`,
    })
  }
  if (!badges.length) return null
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 3 }}>
      {badges.map(b => (
        <span
          key={b.key}
          title={b.title}
          style={{
            background: b.bg, color: b.color,
            borderRadius: 20, padding: '1px 6px',
            fontSize: 10, fontWeight: 700,
            lineHeight: '16px',
          }}
        >
          {b.label}
        </span>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function CustomerList({ onSelectCustomer }) {
  const [filterRisk, setFilterRisk] = useState('')
  const [filterOnboard, setFilterOnboard] = useState('')
  const builtFilters = {}
  if (filterRisk)    builtFilters.churn_risk = filterRisk
  if (filterOnboard !== '') builtFilters.onboarding_complete = filterOnboard === 'true'

  const { customers, total, page, pageSize, hasMore, loading, error, goToPage, applyFilters } =
    useCustomers(builtFilters, 20)

  // M01-7a: attention summary replaces old unreadCounts
  // Shape: { customer_id: { has_attention, unread_messages, open_tickets, churn_risk, reasons } }
  const [attentionMap, setAttentionMap] = useState({})

  useEffect(() => {
    getCustomerAttentionSummary()
      .then(res => {
        if (res.success) setAttentionMap(res.data ?? {})
      })
      .catch(() => {})
  }, [customers.length])

  // Re-apply when filter dropdowns change
  useEffect(() => {
    const f = {}
    if (filterRisk)    f.churn_risk = filterRisk
    if (filterOnboard !== '') f.onboarding_complete = filterOnboard === 'true'
    applyFilters(f)
  }, [filterRisk, filterOnboard]) // eslint-disable-line react-hooks/exhaustive-deps

  const S = {
    wrap: { padding: 28 },
    header: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      marginBottom: 20,
    },
    titleRow: { display: 'flex', alignItems: 'center', gap: 14 },
    numBadge: {
      width: 44, height: 44, background: ds.teal, borderRadius: 11,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: ds.fontHead, fontWeight: 800, fontSize: 15, color: '#fff',
    },
    title: { fontFamily: ds.fontHead, fontWeight: 700, fontSize: 22, color: ds.dark },
    subtitle: { fontSize: 13, color: ds.gray, marginTop: 2 },
    filterBar: {
      display: 'flex', gap: 10, alignItems: 'center', marginBottom: 18, flexWrap: 'wrap',
    },
    select: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '9px 14px',
      fontSize: 13, color: ds.dark, fontFamily: ds.fontBody, outline: 'none',
      background: '#fff', cursor: 'pointer',
    },
    statsRow: {
      display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 22,
    },
    statCard: {
      background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 12,
      padding: '16px 18px',
    },
    statLabel: {
      fontSize: 11, color: ds.gray, textTransform: 'uppercase',
      letterSpacing: '0.6px', fontWeight: 500, marginBottom: 6,
    },
    statValue: {
      fontFamily: ds.fontHead, fontWeight: 700, fontSize: 26, color: ds.dark,
    },
    tableWrap: {
      background: '#fff', border: `1px solid ${ds.border}`,
      borderRadius: 14, overflow: 'hidden',
      boxShadow: '0 2px 12px rgba(2,128,144,0.05)',
    },
    th: {
      background: '#E0F4F6', color: '#015F6B', fontWeight: 600,
      padding: '11px 16px', textAlign: 'left',
      fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.6px',
    },
    td: {
      padding: '12px 16px', borderBottom: `1px solid ${ds.border}`,
      color: ds.dark, verticalAlign: 'middle', fontSize: 13,
    },
    rowHover: { cursor: 'pointer' },
    pagination: {
      display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
      gap: 8, padding: '14px 20px',
      borderTop: `1px solid ${ds.border}`,
    },
    pageBtn: (active) => ({
      padding: '6px 12px', borderRadius: 7, border: 'none', cursor: 'pointer',
      fontSize: 13, fontWeight: 600,
      background: active ? ds.teal : '#EAF0F2',
      color: active ? '#fff' : ds.dark,
    }),
    empty: {
      padding: 48, textAlign: 'center', color: ds.gray, fontSize: 14,
    },
    errBox: {
      background: '#FFE8E8', color: '#C0392B', borderRadius: 9,
      padding: '12px 16px', marginBottom: 16, fontSize: 13,
    },
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const critCount  = customers.filter(c => c.churn_risk === 'critical').length
  const highCount  = customers.filter(c => c.churn_risk === 'high').length
  const doneCount  = customers.filter(c => c.onboarding_complete).length

  // Count customers needing attention for the header indicator
  const needsAttentionCount = Object.values(attentionMap).filter(a => a.has_attention).length

  return (
    <div style={S.wrap}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.titleRow}>
          <div style={S.numBadge}>02</div>
          <div>
            <div style={S.title}>WhatsApp Engine</div>
            <div style={S.subtitle}>
              Communicate, onboard, and retain customers via WhatsApp
            </div>
          </div>
        </div>
        {/* Attention summary indicator */}
        {needsAttentionCount > 0 && (
          <span style={{
            background: '#FEF3C7', color: '#92400E',
            border: '1px solid #FCD34D',
            borderRadius: 20, padding: '5px 14px',
            fontSize: 12, fontWeight: 700, fontFamily: ds.fontSyne,
          }}>
            ⚠ {needsAttentionCount} customer{needsAttentionCount > 1 ? 's' : ''} need attention
          </span>
        )}
      </div>

      {/* Stat row */}
      <div style={S.statsRow}>
        <div style={S.statCard}>
          <div style={S.statLabel}>Total Customers</div>
          <div style={S.statValue}>{total}</div>
        </div>
        <div style={{ ...S.statCard, borderTop: `3px solid #C0392B` }}>
          <div style={S.statLabel}>Critical Churn Risk</div>
          <div style={{ ...S.statValue, color: '#C0392B' }}>{critCount}</div>
        </div>
        <div style={{ ...S.statCard, borderTop: `3px solid #E07B3A` }}>
          <div style={S.statLabel}>High Churn Risk</div>
          <div style={{ ...S.statValue, color: '#E07B3A' }}>{highCount}</div>
        </div>
        <div style={{ ...S.statCard, borderTop: `3px solid #27AE60` }}>
          <div style={S.statLabel}>Onboarding Complete</div>
          <div style={{ ...S.statValue, color: '#27AE60' }}>{doneCount}</div>
        </div>
      </div>

      {/* Filter bar */}
      <div style={S.filterBar}>
        <select
          style={S.select}
          value={filterRisk}
          onChange={e => setFilterRisk(e.target.value)}
        >
          <option value="">All Churn Risk</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>

        <select
          style={S.select}
          value={filterOnboard}
          onChange={e => setFilterOnboard(e.target.value)}
        >
          <option value="">All Onboarding</option>
          <option value="true">Complete</option>
          <option value="false">In Progress</option>
        </select>
      </div>

      {/* Error */}
      {error && <div style={S.errBox}>⚠ {error}</div>}

      {/* Table */}
      <div style={S.tableWrap}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['Customer', 'Business', 'WhatsApp', 'Churn Risk', 'Onboarding', 'Assigned To'].map(h => (
                <th key={h} style={S.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={S.empty}>
                  <span style={{ color: ds.teal }}>Loading customers…</span>
                </td>
              </tr>
            ) : customers.length === 0 ? (
              <tr>
                <td colSpan={6} style={S.empty}>
                  No customers found. Leads convert to customers automatically.
                </td>
              </tr>
            ) : customers.map(c => {
              const attention = attentionMap[c.id] ?? null
              const hasAttention = attention?.has_attention ?? false
              return (
                <tr
                  key={c.id}
                  style={{
                    ...S.rowHover,
                    borderLeft: hasAttention ? `3px solid #ED8936` : '3px solid transparent',
                  }}
                  onClick={() => onSelectCustomer?.(c.id)}
                  onMouseEnter={e => e.currentTarget.style.background = '#F5FAFB'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}
                >
                  <td style={S.td}>
                    <div style={{ fontWeight: 600 }}>{c.full_name}</div>
                    {c.email && (
                      <div style={{ fontSize: 11, color: ds.gray, marginTop: 2 }}>{c.email}</div>
                    )}
                    {/* Attention badges below name */}
                    <AttentionBadges attention={attention} />
                  </td>
                  <td style={S.td}>
                    <div>{c.business_name || '—'}</div>
                    {c.business_type && (
                      <div style={{ fontSize: 11, color: ds.gray, marginTop: 2 }}>{c.business_type}</div>
                    )}
                  </td>
                  <td style={S.td}>
                    <span style={{ color: '#25D366', fontWeight: 600 }}>💬</span>{' '}
                    {c.whatsapp}
                  </td>
                  <td style={S.td}>
                    <RiskBadge risk={c.churn_risk} />
                  </td>
                  <td style={S.td}>
                    <OnboardBadge done={c.onboarding_complete} />
                  </td>
                  <td style={S.td}>
                    {c.assigned_user?.full_name ?? (c.assigned_to ? '—' : 'Unassigned')}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {/* Pagination */}
        <Pagination page={page} total={total} pageSize={pageSize} onGoToPage={goToPage} />
      </div>
    </div>
  )
}
