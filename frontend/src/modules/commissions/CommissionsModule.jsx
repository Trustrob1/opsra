/**
 * frontend/src/modules/commissions/CommissionsModule.jsx
 * Commission Tracking — Phase 9C
 *
 * Two views based on role (from authStore — TEMP-1 fix applied):
 *
 * affiliate_partner / sales_agent:
 *   - Summary cards: Pending | Approved | Paid totals
 *   - Table of own commissions (read-only)
 *
 * owner / ops_manager / is_admin:
 *   - Same summary cards (org-wide)
 *   - Affiliate filter dropdown
 *   - Table of all commissions with inline edit (amount + status)
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import * as commSvc from '../../services/commissions.service'
import Pagination from '../../shared/Pagination'

const STATUS_COLORS = {
  pending:  { bg: '#FEF9C3', color: '#92400E' },
  approved: { bg: '#DCFCE7', color: '#166534' },
  paid:     { bg: '#DBEAFE', color: '#1E40AF' },
  rejected: { bg: '#FEE2E2', color: '#991B1B' },
}

const EVENT_LABELS = {
  lead_converted:    'Lead Converted',
  payment_confirmed: 'Payment Confirmed',
}

function _fmt(amount) {
  return `₦${Number(amount || 0).toLocaleString('en-NG', { minimumFractionDigits: 2 })}`
}

function _timeAgo(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function CommissionsModule({ user }) {
  const isManager   = useAuthStore.getState().isManager()
  const isAffiliate = useAuthStore.getState().getRoleTemplate() === 'affiliate_partner'

  const [summary, setSummary]           = useState(null)
  const [commissions, setCommissions]   = useState([])
  const [total, setTotal]               = useState(0)
  const [page, setPage]                 = useState(1)
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState(null)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterAffiliate, setFilterAffiliate] = useState('')
  const [editingId, setEditingId]       = useState(null)
  const [editForm, setEditForm]         = useState({})
  const [saving, setSaving]             = useState(false)

  const PAGE_SIZE = 20

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [summaryData, listData] = await Promise.all([
        commSvc.getCommissionSummary(),
        commSvc.listCommissions({
          status:          filterStatus    || undefined,
          affiliateUserId: filterAffiliate || undefined,
          page,
          pageSize:        PAGE_SIZE,
        }),
      ])
      setSummary(summaryData)
      setCommissions(listData.items ?? [])
      setTotal(listData.total ?? 0)
    } catch {
      setError('Failed to load commissions.')
    } finally {
      setLoading(false)
    }
  }, [filterStatus, filterAffiliate, page])

  useEffect(() => { load() }, [load])

  const handleSaveEdit = async (id) => {
    setSaving(true)
    try {
      await commSvc.updateCommission(id, editForm)
      setEditingId(null)
      setEditForm({})
      load()
    } catch {
      // silent — user sees stale data but no crash
    } finally {
      setSaving(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  // ── Summary cards ──────────────────────────────────────────────────────────

  function SummaryCards() {
    if (!summary) return null
    const cards = [
      { label: 'Pending',  key: 'pending',  icon: '⏳' },
      { label: 'Approved', key: 'approved', icon: '✅' },
      { label: 'Paid',     key: 'paid',     icon: '💰' },
      { label: 'Total',    key: null,       icon: '📊' },
    ]
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14, marginBottom: 24 }}>
        {cards.map(card => {
          const data   = card.key ? summary.by_status?.[card.key] : null
          const count  = card.key ? (data?.count ?? 0) : summary.total_count
          const amount = card.key ? (data?.amount_ngn ?? 0) : summary.total_amount_ngn
          return (
            <div key={card.label} style={{
              background: 'white', borderRadius: 12,
              border: '1px solid #E4EEF2', padding: '16px 18px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: 18 }}>{card.icon}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.7px' }}>
                  {card.label}
                </span>
              </div>
              <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: '#0a1a24' }}>
                {_fmt(amount)}
              </div>
              <div style={{ fontSize: 12, color: '#7A9BAD', marginTop: 2 }}>
                {count} record{count !== 1 ? 's' : ''}
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div style={{ padding: 28, minHeight: 'calc(100vh - 60px)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
        <div style={{
          width: 44, height: 44, background: ds.teal, borderRadius: 11, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 14, color: 'white',
        }}>
          {isAffiliate ? '👤' : '💼'}
        </div>
        <div>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: '#0a1a24', margin: 0 }}>
            {isAffiliate ? 'My Commissions' : 'Commission Tracking'}
          </h1>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '3px 0 0' }}>
            {isAffiliate
              ? 'Your referral commissions — updated by your manager'
              : 'Manage affiliate and sales rep commissions across the organisation'}
          </p>
        </div>
        <button
          onClick={load}
          style={{ marginLeft: 'auto', background: 'none', border: '1px solid #CBD5E1', borderRadius: 8, padding: '7px 14px', fontSize: 13, color: '#4a7a8a', cursor: 'pointer', fontFamily: ds.fontDm }}
        >
          ↻ Refresh
        </button>
      </div>

      {/* Summary cards */}
      <SummaryCards />

      {/* Filters — managers only */}
      {isManager && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
          <select
            value={filterStatus}
            onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
            style={SELECT}
          >
            <option value="">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="paid">Paid</option>
            <option value="rejected">Rejected</option>
          </select>
          {(filterStatus) && (
            <button
              onClick={() => { setFilterStatus(''); setPage(1) }}
              style={{ fontSize: 12, color: '#7A9BAD', background: 'none', border: 'none', cursor: 'pointer' }}
            >
              ✕ Clear
            </button>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#DC2626', marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}

      {/* Table */}
      <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#F5F9FA' }}>
              {[
                'Event',
                ...(isManager ? ['Affiliate'] : []),
                'Lead / Customer',
                'Amount',
                'Status',
                'Date',
                ...(isManager ? ['Actions'] : []),
              ].map(h => (
                <th key={h} style={{ padding: '11px 14px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={isManager ? 7 : 5} style={{ padding: 32, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
                  Loading…
                </td>
              </tr>
            ) : commissions.length === 0 ? (
              <tr>
                <td colSpan={isManager ? 7 : 5} style={{ padding: 32, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
                  No commissions found.
                </td>
              </tr>
            ) : commissions.map((c, i) => {
              const isEditing = editingId === c.id
              const sc        = STATUS_COLORS[c.status] ?? STATUS_COLORS.pending
              return (
                <tr key={c.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none', background: isEditing ? '#F0FAFA' : 'white' }}>
                  {/* Event */}
                  <td style={{ padding: '12px 14px' }}>
                    <span style={{ fontSize: 12, background: '#F1F5F9', borderRadius: 5, padding: '2px 8px', color: '#475569' }}>
                      {EVENT_LABELS[c.event_type] ?? c.event_type}
                    </span>
                  </td>

                  {/* Affiliate (managers only) */}
                  {isManager && (
                    <td style={{ padding: '12px 14px', fontSize: 13, color: '#0a1a24' }}>
                      {c.affiliate?.full_name ?? c.affiliate_user_id?.slice(0, 8) + '…'}
                    </td>
                  )}

                  {/* Lead / Customer */}
                  <td style={{ padding: '12px 14px', fontSize: 12, color: '#7A9BAD' }}>
                    {c.customer_id ? `Customer: ${c.customer_id.slice(0, 8)}…` :
                     c.lead_id     ? `Lead: ${c.lead_id.slice(0, 8)}…` : '—'}
                  </td>

                  {/* Amount */}
                  <td style={{ padding: '12px 14px' }}>
                    {isEditing ? (
                      <input
                        type="number"
                        min={0}
                        value={editForm.amount_ngn ?? c.amount_ngn}
                        onChange={e => setEditForm(f => ({ ...f, amount_ngn: Number(e.target.value) }))}
                        style={{ width: 120, padding: '5px 8px', border: '1px solid #CBD5E1', borderRadius: 6, fontSize: 13, fontFamily: 'inherit' }}
                      />
                    ) : (
                      <span style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13, color: '#0a1a24' }}>
                        {_fmt(c.amount_ngn)}
                      </span>
                    )}
                  </td>

                  {/* Status */}
                  <td style={{ padding: '12px 14px' }}>
                    {isEditing ? (
                      <select
                        value={editForm.status ?? c.status}
                        onChange={e => setEditForm(f => ({ ...f, status: e.target.value }))}
                        style={{ padding: '5px 8px', border: '1px solid #CBD5E1', borderRadius: 6, fontSize: 12, fontFamily: 'inherit' }}
                      >
                        <option value="pending">Pending</option>
                        <option value="approved">Approved</option>
                        <option value="paid">Paid</option>
                        <option value="rejected">Rejected</option>
                      </select>
                    ) : (
                      <span style={{ fontSize: 11, fontWeight: 700, borderRadius: 6, padding: '3px 9px', background: sc.bg, color: sc.color }}>
                        {c.status?.toUpperCase()}
                      </span>
                    )}
                  </td>

                  {/* Date */}
                  <td style={{ padding: '12px 14px', fontSize: 12, color: '#7A9BAD' }}>
                    {_fmt_date(c.created_at)}
                  </td>

                  {/* Actions (managers only) */}
                  {isManager && (
                    <td style={{ padding: '12px 14px' }}>
                      {isEditing ? (
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button
                            onClick={() => handleSaveEdit(c.id)}
                            disabled={saving}
                            style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 6, padding: '5px 12px', fontSize: 12, cursor: 'pointer', fontFamily: ds.fontSyne }}
                          >
                            {saving ? '…' : 'Save'}
                          </button>
                          <button
                            onClick={() => { setEditingId(null); setEditForm({}) }}
                            style={{ background: 'white', border: '1px solid #CBD5E1', borderRadius: 6, padding: '5px 10px', fontSize: 12, cursor: 'pointer', color: '#4a7a8a', fontFamily: ds.fontDm }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => { setEditingId(c.id); setEditForm({ amount_ngn: c.amount_ngn, status: c.status }) }}
                          style={{ background: 'white', border: '1px solid #CBD5E1', borderRadius: 6, padding: '5px 10px', fontSize: 12, cursor: 'pointer', color: '#4a7a8a', fontFamily: ds.fontDm }}
                        >
                          ✏ Edit
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <Pagination page={page} total={total} pageSize={PAGE_SIZE} onGoToPage={setPage} />
    </div>
  )
}

function _fmt_date(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

const SELECT = {
  border: '1.5px solid #E4EEF2', borderRadius: 8,
  padding: '8px 12px', fontSize: 13, color: '#0a1a24',
  fontFamily: 'inherit', background: 'white', cursor: 'pointer',
}

const BTN = {
  background: 'white', border: '1px solid #CBD5E1', borderRadius: 8,
  padding: '7px 16px', fontSize: 13, cursor: 'pointer', color: '#4a7a8a', fontFamily: 'inherit',
}
