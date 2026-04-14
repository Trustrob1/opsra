/**
 * frontend/src/modules/support/TicketList.jsx
 * Paginated, filterable ticket table with stat cards.
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import useTickets from '../../hooks/useTickets'
import TicketCreateModal from './TicketCreateModal'
import Pagination from '../../shared/Pagination'

// ---------------------------------------------------------------------------
// Badge helpers
// ---------------------------------------------------------------------------
const URGENCY_STYLE = {
  critical: { background: '#FFE8E8', color: '#C0392B' },
  high:     { background: '#FFF3E0', color: '#E07B3A' },
  medium:   { background: '#FFF9E0', color: '#D4AC0D' },
  low:      { background: '#EAF0F2', color: ds.gray   },
}

const STATUS_MAP = {
  open:              { bg: '#EAF0F2', color: ds.gray,   label: 'Open' },
  in_progress:       { bg: '#E8F0FF', color: '#3450A4', label: 'In Progress' },
  awaiting_customer: { bg: '#FFF9E0', color: '#D4AC0D', label: 'Awaiting Customer' },
  resolved:          { bg: '#E8F8EE', color: ds.green,  label: 'Resolved' },
  closed:            { bg: '#F0F0F0', color: '#888',    label: 'Closed' },
}

function UrgencyBadge({ urgency }) {
  const s = URGENCY_STYLE[urgency] || URGENCY_STYLE.low
  return (
    <span style={{ ...s, padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 700, textTransform: 'capitalize', display: 'inline-block' }}>
      {urgency || '—'}
    </span>
  )
}

function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP.open
  return (
    <span style={{ background: s.bg, color: s.color, padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 600, display: 'inline-block', whiteSpace: 'nowrap' }}>
      {s.label}
    </span>
  )
}

function StatCard({ label, value, accent }) {
  return (
    <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '12px', padding: '16px 20px' }}>
      <div style={{ fontSize: '11px', fontWeight: 500, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px' }}>{label}</div>
      <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 800, fontSize: '26px', color: accent || ds.dark }}>{value}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter options
// ---------------------------------------------------------------------------
const STATUSES   = ['', 'open', 'in_progress', 'awaiting_customer', 'resolved', 'closed']
const CATEGORIES = ['', 'technical_bug', 'billing', 'feature_question', 'onboarding_help', 'account_access', 'hardware']
const URGENCIES  = ['', 'critical', 'high', 'medium', 'low']

export default function TicketList({ onSelectTicket }) {
  const [showCreate, setShowCreate]       = useState(false)
  const [localFilters, setLocalFilters]   = useState({ status: '', category: '', urgency: '', sla_breached: '' })

  const {
    tickets, total, page, pageSize, hasMore,
    loading, error, refresh, applyFilters, goToPage,
  } = useTickets({}, 20)

  function handleFilterChange(field, val) {
    const next = { ...localFilters, [field]: val }
    setLocalFilters(next)
    const clean = {}
    if (next.status)   clean.status   = next.status
    if (next.category) clean.category = next.category
    if (next.urgency)  clean.urgency  = next.urgency
    if (next.sla_breached === 'true')  clean.sla_breached = true
    if (next.sla_breached === 'false') clean.sla_breached = false
    applyFilters(clean)
  }

  function onCreated(ticket) {
    setShowCreate(false)
    refresh()
    if (ticket?.id) onSelectTicket(ticket.id)
  }

  const openCount     = tickets.filter(t => ['open', 'in_progress'].includes(t.status)).length
  const breachedCount = tickets.filter(t => t.sla_breached).length
  const resolvedCount = tickets.filter(t => t.status === 'resolved').length

  const sel = {
    border: `1.5px solid ${ds.border}`, borderRadius: '8px',
    padding: '8px 12px', fontSize: '12.5px', color: ds.dark,
    background: 'white', cursor: 'pointer', outline: 'none',
  }

  return (
    <div>
      {/* Stat row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '14px', marginBottom: '22px' }}>
        <StatCard label="Total Tickets"   value={total} />
        <StatCard label="Open / Active"   value={openCount}     accent={ds.teal} />
        <StatCard label="SLA Breached"    value={breachedCount} accent="#C0392B" />
        <StatCard label="Resolved (page)" value={resolvedCount} accent={ds.green} />
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <select style={sel} value={localFilters.status} onChange={e => handleFilterChange('status', e.target.value)}>
          <option value="">All Statuses</option>
          {STATUSES.filter(Boolean).map(s => <option key={s} value={s}>{STATUS_MAP[s]?.label || s}</option>)}
        </select>

        <select style={sel} value={localFilters.category} onChange={e => handleFilterChange('category', e.target.value)}>
          <option value="">All Categories</option>
          {CATEGORIES.filter(Boolean).map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </select>

        <select style={sel} value={localFilters.urgency} onChange={e => handleFilterChange('urgency', e.target.value)}>
          <option value="">All Urgencies</option>
          {URGENCIES.filter(Boolean).map(u => <option key={u} value={u} style={{ textTransform: 'capitalize' }}>{u}</option>)}
        </select>

        <select style={sel} value={localFilters.sla_breached} onChange={e => handleFilterChange('sla_breached', e.target.value)}>
          <option value="">SLA: All</option>
          <option value="true">SLA Breached</option>
          <option value="false">SLA OK</option>
        </select>

        <div style={{ flex: 1 }} />

        <button
          onClick={() => setShowCreate(true)}
          style={{ padding: '9px 18px', borderRadius: '8px', border: 'none', background: ds.teal, color: 'white', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
        >
          + New Ticket
        </button>
      </div>

      {/* Error */}
      {error && <div style={{ color: '#C0392B', marginBottom: '12px', fontSize: '13px' }}>{error}</div>}

      {/* Table */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px', color: ds.gray, fontSize: '13px' }}>Loading tickets…</div>
      ) : tickets.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px', color: ds.gray, fontSize: '13px' }}>No tickets found for the selected filters.</div>
      ) : (
        <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: ds.mint }}>
                {['Reference', 'Title', 'Category', 'Urgency', 'Status', 'SLA', 'Assigned'].map(h => (
                  <th key={h} style={{ padding: '11px 14px', textAlign: 'left', fontSize: '11px', fontWeight: 600, color: ds.tealDark, textTransform: 'uppercase', letterSpacing: '0.6px', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <tr
                  key={t.id}
                  onClick={() => onSelectTicket(t.id)}
                  style={{ cursor: 'pointer', borderBottom: `1px solid ${ds.border}`, background: 'white', transition: 'background 0.12s' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#f8fdfe'}
                  onMouseLeave={e => e.currentTarget.style.background = 'white'}
                >
                  <td style={{ padding: '11px 14px', fontWeight: 700, color: ds.teal, whiteSpace: 'nowrap' }}>{t.reference}</td>
                  <td style={{ padding: '11px 14px', color: ds.dark, maxWidth: '260px' }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title || '—'}</div>
                  </td>
                  <td style={{ padding: '11px 14px', color: ds.gray, whiteSpace: 'nowrap', textTransform: 'capitalize' }}>
                    {t.category ? t.category.replace(/_/g, ' ') : '—'}
                  </td>
                  <td style={{ padding: '11px 14px' }}><UrgencyBadge urgency={t.urgency} /></td>
                  <td style={{ padding: '11px 14px' }}><StatusBadge status={t.status} /></td>
                  <td style={{ padding: '11px 14px', whiteSpace: 'nowrap' }}>
                    {t.sla_breached
                      ? <span style={{ color: '#C0392B', fontWeight: 700, fontSize: '11px' }}>⚠ Breached</span>
                      : <span style={{ color: ds.green, fontSize: '11px' }}>✓ OK</span>
                    }
                  </td>
                  <td style={{ padding: '11px 14px', color: ds.gray, fontSize: '12px' }}>
                    {t.assigned_user?.full_name || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <Pagination page={page} total={total} pageSize={pageSize} onGoToPage={goToPage} />

      {showCreate && <TicketCreateModal onCreated={onCreated} onClose={() => setShowCreate(false)} />}
    </div>
  )
}
