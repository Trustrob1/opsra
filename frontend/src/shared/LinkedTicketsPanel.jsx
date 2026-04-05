/**
 * shared/LinkedTicketsPanel.jsx
 * Ticket history + creation for Lead and Customer profile pages.
 *
 * Props:
 *   linkedTo    — { type: 'customer'|'lead', id: string }
 *   contextName — display name for empty state messaging
 *
 * Shows a compact ticket list filtered by customer_id or lead_id,
 * plus a "+ New Ticket" button that opens TicketCreateModal.
 * After creation the list refreshes automatically.
 *
 * Does NOT navigate to ticket detail — users open the Support module for that.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../utils/ds'
import { listTickets } from '../services/support.service'
import TicketCreateModal from '../modules/support/TicketCreateModal'

// ── Badge helpers (mirrored from TicketList.jsx) ──────────────────────────────

const URGENCY_STYLE = {
  critical: { bg: '#FFE8E8', color: '#C0392B' },
  high:     { bg: '#FFF3E0', color: '#E07B3A' },
  medium:   { bg: '#FFF9E0', color: '#D4AC0D' },
  low:      { bg: '#EAF0F2', color: '#6b7280' },
}

const STATUS_MAP = {
  open:              { bg: '#EAF0F2', color: '#6b7280', label: 'Open'               },
  in_progress:       { bg: '#E8F0FF', color: '#3450A4', label: 'In Progress'        },
  awaiting_customer: { bg: '#FFF9E0', color: '#D4AC0D', label: 'Awaiting Customer'  },
  resolved:          { bg: '#E8F8EE', color: '#27AE60', label: 'Resolved'           },
  closed:            { bg: '#F0F0F0', color: '#888',    label: 'Closed'             },
}

function UrgencyBadge({ urgency }) {
  const s = URGENCY_STYLE[urgency] || URGENCY_STYLE.low
  return (
    <span style={{ ...s, padding: '2px 8px', borderRadius: 20, fontSize: 11, fontWeight: 700, display: 'inline-block', textTransform: 'capitalize' }}>
      {urgency || '—'}
    </span>
  )
}

function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP.open
  return (
    <span style={{ background: s.bg, color: s.color, padding: '2px 8px', borderRadius: 20, fontSize: 11, fontWeight: 600, display: 'inline-block', whiteSpace: 'nowrap' }}>
      {s.label}
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function LinkedTicketsPanel({ linkedTo, contextName }) {
  const [tickets,     setTickets]     = useState([])
  const [total,       setTotal]       = useState(0)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [showCreate,  setShowCreate]  = useState(false)
  const [tick,        setTick]        = useState(0)
  const [page,        setPage]        = useState(1)
  const PAGE_SIZE = 10

  const fetchTickets = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (linkedTo.type === 'customer') params.customer_id = linkedTo.id
      if (linkedTo.type === 'lead')     params.lead_id     = linkedTo.id

      // support.service.js request() returns json.data directly
      const res = await listTickets(params)
      setTickets(res?.items ?? [])
      setTotal(res?.total ?? 0)
    } catch {
      setError('Could not load tickets.')
    } finally {
      setLoading(false)
    }
  }, [linkedTo.id, linkedTo.type, page, tick])

  useEffect(() => { fetchTickets() }, [fetchTickets])

  const handleCreated = () => {
    setShowCreate(false)
    setPage(1)
    setTick(t => t + 1)
  }

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13, color: ds.teal, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
          Support Tickets {total > 0 && `· ${total} total`}
        </span>
        <button
          onClick={() => setShowCreate(true)}
          style={{
            background: ds.teal, color: 'white', border: 'none',
            borderRadius: 8, padding: '8px 16px',
            fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer',
          }}
        >
          + New Ticket
        </button>
      </div>

      {/* Error */}
      {error && (
        <p style={{ fontSize: 13, color: ds.red, marginBottom: 12 }}>⚠ {error}</p>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: ds.gray, fontSize: 13 }}>
          Loading tickets…
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && tickets.length === 0 && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: ds.gray }}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>🎫</div>
          <p style={{ fontSize: 13, margin: '0 0 4px' }}>
            No tickets for {contextName} yet.
          </p>
          <p style={{ fontSize: 12, color: '#9ca3af' }}>
            Use "+ New Ticket" above to open one.
          </p>
        </div>
      )}

      {/* Ticket list */}
      {!loading && tickets.length > 0 && (
        <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: 12, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: ds.mint }}>
                {['Ref', 'Title', 'Urgency', 'Status', 'Created'].map(h => (
                  <th key={h} style={{ padding: '9px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: ds.tealDark, textTransform: 'uppercase', letterSpacing: '0.5px', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <tr key={t.id} style={{ borderBottom: `1px solid ${ds.border}` }}>
                  <td style={{ padding: '10px 12px', fontWeight: 700, color: ds.teal, whiteSpace: 'nowrap' }}>
                    {t.reference}
                  </td>
                  <td style={{ padding: '10px 12px', color: ds.dark, maxWidth: 220 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {t.title || '—'}
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <UrgencyBadge urgency={t.urgency} />
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <StatusBadge status={t.status} />
                  </td>
                  <td style={{ padding: '10px 12px', color: ds.gray, fontSize: 12, whiteSpace: 'nowrap' }}>
                    {t.created_at ? new Date(t.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
          <span style={{ fontSize: 12, color: ds.gray }}>Page {page} · {total} total</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              style={pagBtn(page <= 1)}
            >
              ← Prev
            </button>
            <button
              disabled={page * PAGE_SIZE >= total}
              onClick={() => setPage(p => p + 1)}
              style={pagBtn(page * PAGE_SIZE >= total)}
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Hint */}
      {!loading && tickets.length > 0 && (
        <p style={{ fontSize: 11, color: '#9ca3af', marginTop: 10, textAlign: 'center' }}>
          Open the Support Tickets module for full ticket detail and thread.
        </p>
      )}

      {showCreate && (
        <TicketCreateModal
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
          customerId={linkedTo.type === 'customer' ? linkedTo.id : undefined}
          leadId={linkedTo.type === 'lead' ? linkedTo.id : undefined}
        />
      )}
    </div>
  )
}

const pagBtn = (disabled) => ({
  padding: '6px 14px', borderRadius: 7,
  border: `1px solid ${ds.border}`, background: 'white',
  fontSize: 12, cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.5 : 1,
})
