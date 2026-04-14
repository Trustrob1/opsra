/**
 * SubscriptionList.jsx — Subscription list with stat cards, filters, and pagination
 *
 * Props:
 *   user          {object}   — authenticated user (role check for confirm-payment button)
 *   onSelect      {function} — (id) => void; opens SubscriptionDetail inline
 *   externalTick  {number}   — increment from parent to trigger a refresh (Pattern 30)
 *
 * Filters: status, plan_tier, renewal_window_days
 * Stat cards derived from paginated data: counts computed server-side via filters
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { ds } from '../../utils/ds'
import useSubscriptions from '../../hooks/useSubscriptions'
import ConfirmPaymentModal from './ConfirmPaymentModal'
import Pagination from '../../shared/Pagination'

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_OPTIONS = [
  { value: '',             label: 'All statuses' },
  { value: 'trial',        label: 'Trial' },
  { value: 'active',       label: 'Active' },
  { value: 'grace_period', label: 'Grace Period' },
  { value: 'expired',      label: 'Expired' },
  { value: 'suspended',    label: 'Suspended' },
  { value: 'cancelled',    label: 'Cancelled' },
]

const PLAN_OPTIONS = [
  { value: '',           label: 'All plans' },
  { value: 'starter',   label: 'Starter' },
  { value: 'basic',     label: 'Basic' },
  { value: 'pro',       label: 'Pro' },
  { value: 'enterprise',label: 'Enterprise' },
]

const WINDOW_OPTIONS = [
  { value: '',   label: 'All renewals' },
  { value: '7',  label: 'Expiring in 7 days' },
  { value: '14', label: 'Expiring in 14 days' },
  { value: '30', label: 'Expiring in 30 days' },
  { value: '60', label: 'Expiring in 60 days' },
]

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_MAP = {
  trial:        { bg: ds.teal,    label: 'Trial' },
  active:       { bg: ds.green,   label: 'Active' },
  grace_period: { bg: ds.amber,   label: 'Grace Period' },
  expired:      { bg: ds.gray,    label: 'Expired' },
  suspended:    { bg: ds.amber,   label: 'Suspended' },
  cancelled:    { bg: ds.gray,    label: 'Cancelled' },
}

function StatusBadge({ status }) {
  const { bg, label } = STATUS_MAP[status] ?? { bg: ds.gray, label: status }
  return (
    <span style={{
      display: 'inline-block',
      background: bg, color: 'white',
      borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 600,
      textTransform: 'capitalize', whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

// ─── Plan badge ───────────────────────────────────────────────────────────────

function PlanBadge({ plan }) {
  const colourMap = { enterprise: ds.tealDark, pro: ds.teal, basic: '#4B7A8A', starter: ds.gray }
  return (
    <span style={{
      display: 'inline-block',
      background: colourMap[plan] ?? ds.gray,
      color: 'white', borderRadius: 6,
      padding: '2px 8px', fontSize: 11, fontWeight: 600,
      textTransform: 'capitalize',
    }}>
      {plan ?? '—'}
    </span>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

function fmtAmount(n) {
  if (n == null) return '—'
  return `₦${Number(n).toLocaleString('en-NG', { minimumFractionDigits: 0 })}`
}

function daysUntil(iso) {
  if (!iso) return null
  const diff = Math.ceil((new Date(iso) - Date.now()) / 86400000)
  return diff
}

// ─────────────────────────────────────────────────────────────────────────────

export default function SubscriptionList({ user, onSelect, externalTick = 0 }) {
  const [filterStatus, setFilterStatus]     = useState('')
  const [filterPlan, setFilterPlan]         = useState('')
  const [filterWindow, setFilterWindow]     = useState('')
  const [searchName, setSearchName]         = useState('')
  const [debouncedName, setDebouncedName]   = useState('')
  const [confirmTarget, setConfirmTarget]   = useState(null)

  const {
    subscriptions, total, page, pageSize, hasMore,
    loading, error, applyFilters, goToPage, refresh,
  } = useSubscriptions({}, 20)

  // Pattern 30: refresh list when externalTick changes (e.g., after bulk upload)
  const prevTickRef = useRef(externalTick)
  useEffect(() => {
    if (externalTick !== prevTickRef.current) {
      prevTickRef.current = externalTick
      refresh()
    }
  }, [externalTick, refresh])

  // Debounce the search name — waits 500ms after the user stops typing
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedName(searchName), 500)
    return () => clearTimeout(timer)
  }, [searchName])

  // Auto-apply filters whenever debouncedName changes (live typeahead)
  useEffect(() => {
    const f = {}
    if (filterStatus)           f.status              = filterStatus
    if (filterPlan)             f.plan_tier            = filterPlan
    if (filterWindow)           f.renewal_window_days  = parseInt(filterWindow, 10)
    if (debouncedName.trim().length >= 2)   f.customer_name        = debouncedName.trim()
    applyFilters(f)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedName])

  const handleApply = useCallback(() => {
    const f = {}
    if (filterStatus)           f.status              = filterStatus
    if (filterPlan)             f.plan_tier            = filterPlan
    if (filterWindow)           f.renewal_window_days  = parseInt(filterWindow, 10)
    if (debouncedName.trim())   f.customer_name        = debouncedName.trim()
    applyFilters(f)
  }, [filterStatus, filterPlan, filterWindow, debouncedName, applyFilters])

  const handleClear = useCallback(() => {
    setFilterStatus('')
    setFilterPlan('')
    setFilterWindow('')
    setSearchName('')
    setDebouncedName('')
    applyFilters({})
  }, [applyFilters])

  // Stat totals derived from current page (full-org counts come from server total)
  const activeCount  = subscriptions.filter(s => s.status === 'active').length
  const graceCount   = subscriptions.filter(s => s.status === 'grace_period').length
  const expiringCount = subscriptions.filter(s => {
    const d = daysUntil(s.current_period_end)
    return d != null && d >= 0 && d <= 30 && s.status === 'active'
  }).length

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div>
      {/* ── Stat cards ────────────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {[
          { label: 'Total Subscriptions', value: total,        color: ds.teal },
          { label: 'Active',              value: activeCount,  color: ds.green },
          { label: 'Expiring in 30 days', value: expiringCount,color: ds.amber },
          { label: 'Grace Period',        value: graceCount,   color: ds.amber },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: 'white', borderRadius: 12, padding: '18px 20px', border: '1px solid #e2ecf0', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 26, color, margin: 0 }}>
              {loading ? '—' : value}
            </p>
            <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>{label}</p>
          </div>
        ))}
      </div>

      {/* ── Filter bar ────────────────────────────────────────────────────── */}
      <div style={{ background: 'white', borderRadius: 12, padding: '16px 20px', border: '1px solid #e2ecf0', marginBottom: 20 }}>

        {/* Search by customer name — live typeahead */}
        <div style={{ marginBottom: 14 }}>
          <label style={filterLabel}>Search customer</label>
          <div style={{ position: 'relative' }}>
            <span style={{
              position: 'absolute', left: 12, top: '50%',
              transform: 'translateY(-50%)',
              fontSize: 15, color: '#a0b8c4', pointerEvents: 'none',
            }}>🔍</span>
            <input
              type="text"
              placeholder="Type a customer name…"
              value={searchName}
              onChange={e => setSearchName(e.target.value)}
              style={{
                ...filterSelect,
                paddingLeft: 36,
                width: '100%',
                boxSizing: 'border-box',
              }}
            />
            {searchName && (
              <button
                onClick={() => { setSearchName(''); setDebouncedName('') }}
                style={{
                  position: 'absolute', right: 10, top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none', border: 'none',
                  fontSize: 14, color: '#a0b8c4',
                  cursor: 'pointer', lineHeight: 1, padding: 2,
                }}
              >✕</button>
            )}
          </div>
          {searchName.length >= 2 && !loading && (
            <p style={{ fontSize: 11, color: ds.teal, margin: '4px 0 0' }}>
              {total} result{total !== 1 ? 's' : ''} for "{debouncedName}"
            </p>
          )}
        </div>

        {/* Dropdown filters row */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 160px' }}>
          <label style={filterLabel}>Status</label>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={filterSelect}>
            {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ flex: '1 1 160px' }}>
          <label style={filterLabel}>Plan Tier</label>
          <select value={filterPlan} onChange={e => setFilterPlan(e.target.value)} style={filterSelect}>
            {PLAN_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ flex: '1 1 180px' }}>
          <label style={filterLabel}>Renewal Window</label>
          <select value={filterWindow} onChange={e => setFilterWindow(e.target.value)} style={filterSelect}>
            {WINDOW_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleApply} style={applyBtn}>Apply</button>
          <button onClick={handleClear} style={clearBtn}>Clear</button>
        </div>
      </div>
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────── */}
      <div style={{ background: 'white', borderRadius: 12, border: '1px solid #e2ecf0', overflow: 'hidden' }}>
        {/* Table header */}
        <div style={tableHeader}>
          <span style={{ flex: 2 }}>Customer</span>
          <span style={{ flex: 1 }}>Plan</span>
          <span style={{ flex: 1 }}>Status</span>
          <span style={{ flex: 1 }}>Billing</span>
          <span style={{ flex: 1 }}>Amount</span>
          <span style={{ flex: 1 }}>Period End</span>
          <span style={{ flex: 1 }}>Days Left</span>
          <span style={{ flex: 1, textAlign: 'right' }}>Actions</span>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ padding: '40px 24px', textAlign: 'center', color: ds.gray, fontSize: 14 }}>
            Loading subscriptions…
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div style={{ padding: '24px', background: '#FEF2F2', color: '#B91C1C', fontSize: 13 }}>
            ⚠ {error}
          </div>
        )}

        {/* Empty */}
        {!loading && !error && subscriptions.length === 0 && (
          <div style={{ padding: '48px 24px', textAlign: 'center', color: ds.gray }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>🔄</div>
            <p style={{ fontSize: 14, margin: 0 }}>No subscriptions found matching current filters.</p>
          </div>
        )}

        {/* Rows */}
        {!loading && subscriptions.map((sub, i) => {
          const days = daysUntil(sub.current_period_end)
          const isUrgent = days != null && days <= 7 && days >= 0 && sub.status === 'active'
          const customerName = sub.customer?.full_name ?? sub.customer?.phone ?? '—'

          return (
            <div
              key={sub.id}
              style={{
                display: 'flex', alignItems: 'center',
                padding: '14px 24px',
                borderTop: i > 0 ? '1px solid #f0f5f8' : 'none',
                background: isUrgent ? '#FFFBEB' : 'white',
                cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onClick={() => onSelect(sub.id)}
              onMouseEnter={e => e.currentTarget.style.background = isUrgent ? '#FFF8DC' : '#f7fbfc'}
              onMouseLeave={e => e.currentTarget.style.background = isUrgent ? '#FFFBEB' : 'white'}
            >
              <div style={{ flex: 2, minWidth: 0 }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: ds.dark, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {customerName}
                </p>
                <p style={{ fontSize: 11, color: ds.gray, margin: '2px 0 0' }}>
                  {sub.id?.slice(0, 8)}…
                </p>
              </div>
              <div style={{ flex: 1 }}><PlanBadge plan={sub.plan_tier} /></div>
              <div style={{ flex: 1 }}><StatusBadge status={sub.status} /></div>
              <div style={{ flex: 1, fontSize: 12, color: ds.gray, textTransform: 'capitalize' }}>
                {sub.billing_cycle ?? '—'}
              </div>
              <div style={{ flex: 1, fontSize: 13, fontWeight: 600, color: ds.dark }}>
                {fmtAmount(sub.amount)}
              </div>
              <div style={{ flex: 1, fontSize: 12, color: ds.gray }}>
                {fmtDate(sub.current_period_end)}
              </div>
              <div style={{ flex: 1 }}>
                {days != null ? (
                  <span style={{ fontSize: 12, fontWeight: 600, color: isUrgent ? ds.amber : (days < 30 ? ds.teal : ds.gray) }}>
                    {days < 0 ? `${Math.abs(days)}d overdue` : `${days}d`}
                  </span>
                ) : <span style={{ fontSize: 12, color: ds.gray }}>—</span>}
              </div>
              <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  onClick={(e) => { e.stopPropagation(); setConfirmTarget(sub.id) }}
                  style={confirmBtn}
                >
                  + Payment
                </button>
              </div>
            </div>
          )
        })}

        {/* Pagination */}
        {!loading && (
          <Pagination page={page} total={total} pageSize={pageSize} onGoToPage={goToPage} />
        )}
      </div>

      {/* ── Confirm Payment quick-action modal ───────────────────────────── */}
      {confirmTarget && (
        <ConfirmPaymentModal
          subscriptionId={confirmTarget}
          onClose={() => setConfirmTarget(null)}
          onConfirmed={() => { setConfirmTarget(null); refresh() }}
        />
      )}
    </div>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const filterLabel = {
  display: 'block', fontSize: 11, fontWeight: 600,
  color: '#7a9bad', textTransform: 'uppercase',
  letterSpacing: '0.7px', marginBottom: 6,
}

const filterSelect = {
  width: '100%', border: '1.5px solid #d1dde4',
  borderRadius: 8, padding: '9px 12px',
  fontSize: 13, fontFamily: ds.fontDm,
  color: ds.dark, background: 'white', outline: 'none',
}

const applyBtn = {
  background: ds.teal, color: 'white',
  border: 'none', borderRadius: 8,
  padding: '9px 18px', fontSize: 13,
  fontWeight: 600, cursor: 'pointer',
  fontFamily: ds.fontSyne, whiteSpace: 'nowrap',
}

const clearBtn = {
  background: 'white', border: '1.5px solid #d1dde4',
  borderRadius: 8, padding: '9px 14px',
  fontSize: 13, color: ds.gray,
  cursor: 'pointer', fontFamily: ds.fontDm, whiteSpace: 'nowrap',
}

const tableHeader = {
  display: 'flex', alignItems: 'center',
  padding: '12px 24px',
  background: '#f7fbfc',
  borderBottom: '1px solid #e2ecf0',
  fontSize: 11, fontWeight: 700,
  color: '#7a9bad', textTransform: 'uppercase',
  letterSpacing: '0.8px',
}

const confirmBtn = {
  background: 'none', border: `1.5px solid ${ds.teal}`,
  borderRadius: 7, padding: '5px 10px',
  fontSize: 11, fontWeight: 600, color: ds.teal,
  cursor: 'pointer', fontFamily: ds.fontSyne,
  whiteSpace: 'nowrap', transition: 'all 0.15s',
}

const paginBtn = {
  background: 'white', border: '1.5px solid #d1dde4',
  borderRadius: 7, padding: '6px 14px',
  fontSize: 12, color: ds.gray,
  cursor: 'pointer', fontFamily: ds.fontDm,
}
