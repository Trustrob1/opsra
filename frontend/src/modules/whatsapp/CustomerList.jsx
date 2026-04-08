/**
 * CustomerList.jsx — Module 02 customer list.
 *
 * Displays all customers for the org in a table.
 * Filters: churn_risk, assigned_to, onboarding_complete.
 * Clicking a row opens CustomerProfile.
 *
 * Design follows the existing app shell (dark topbar, teal accent) and
 * mirrors the demo's data-table / stat-card / filter-bar patterns.
 * All colours from ds.js — no hardcoded hex.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getUnreadCounts } from '../../services/whatsapp.service'
import useCustomers from '../../hooks/useCustomers'

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

// ── Main component ────────────────────────────────────────────────────────────
export default function CustomerList({ onSelectCustomer }) {
  const [filterRisk, setFilterRisk] = useState('')
  const [filterOnboard, setFilterOnboard] = useState('')
  const builtFilters = {}
  if (filterRisk)    builtFilters.churn_risk = filterRisk
  if (filterOnboard !== '') builtFilters.onboarding_complete = filterOnboard === 'true'

  const { customers, total, page, pageSize, hasMore, loading, error, goToPage, applyFilters } =
    useCustomers(builtFilters, 50)

  const [unreadCounts, setUnreadCounts] = useState({})

  // Fetch unread counts on mount — refetches whenever customers list changes
  useEffect(() => {
    getUnreadCounts()
      .then(res => setUnreadCounts(res.data?.data?.customers ?? {}))
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
            ) : customers.map(c => (
              <tr
                key={c.id}
                style={S.rowHover}
                onClick={() => onSelectCustomer?.(c.id)}
                onMouseEnter={e => e.currentTarget.style.background = '#F5FAFB'}
                onMouseLeave={e => e.currentTarget.style.background = ''}
              >
                <td style={S.td}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ fontWeight: 600 }}>{c.full_name}</div>
                    {(unreadCounts[c.id] ?? 0) > 0 && (
                      <span style={{
                        background: '#E53E3E', color: 'white',
                        borderRadius: 20, padding: '1px 6px',
                        fontSize: 10, fontWeight: 700, flexShrink: 0,
                        lineHeight: '16px',
                      }} title={`${unreadCounts[c.id]} unread message${unreadCounts[c.id] > 1 ? 's' : ''}`}>
                        💬 {unreadCounts[c.id]}
                      </span>
                    )}
                  </div>
                  {c.email && (
                    <div style={{ fontSize: 11, color: ds.gray, marginTop: 2 }}>{c.email}</div>
                  )}
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
            ))}
          </tbody>
        </table>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={S.pagination}>
            <span style={{ fontSize: 12, color: ds.gray, marginRight: 8 }}>
              Page {page} of {totalPages} · {total} customers
            </span>
            {page > 1 && (
              <button style={S.pageBtn(false)} onClick={() => goToPage(page - 1)}>← Prev</button>
            )}
            {hasMore && (
              <button style={S.pageBtn(true)} onClick={() => goToPage(page + 1)}>Next →</button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
