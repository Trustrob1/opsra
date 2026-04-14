/**
 * NurtureQueue
 *
 * Read-only table showing all leads currently on the nurture track.
 * Managers only — rendered inside LeadsPipeline as a third view mode.
 *
 * Features:
 *   - Fetches GET /api/v1/leads/nurture-queue (paginated, sorted by
 *     last_nurture_sent_at ASC NULLS FIRST — most overdue leads first)
 *   - Toggle to include opted-out leads
 *   - "View" button → opens LeadProfile via onOpenLead prop
 *   - Score badge, graduation reason, sequence position, days since last send
 *
 * SECURITY: org_id never in payload — derived from JWT server-side.
 */
import { useState, useEffect, useCallback } from 'react'
import { getNurtureQueue } from '../../services/leads.service'
import { ds, SCORE_STYLE } from '../../utils/ds'
import Pagination from '../../shared/Pagination'

const GRADUATION_LABELS = {
  unassigned:               'Never assigned',
  no_contact:               'Rep never contacted',
  lead_unresponsive:        'Lead went silent',
  self_identified_not_ready: 'Said not ready',
}

const PAGE_SIZE = 20

export default function NurtureQueue({ onOpenLead }) {
  const [leads,           setLeads]           = useState([])
  const [total,           setTotal]           = useState(0)
  const [page,            setPage]            = useState(1)
  const [loading,         setLoading]         = useState(true)
  const [error,           setError]           = useState(null)
  const [includeOptedOut, setIncludeOptedOut] = useState(false)

  const fetchQueue = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getNurtureQueue({
        page,
        page_size: PAGE_SIZE,
        include_opted_out: includeOptedOut,
      })
      if (res.success) {
        setLeads(res.data.items ?? [])
        setTotal(res.data.total ?? 0)
      } else {
        setError(res.error ?? 'Failed to load nurture queue')
      }
    } catch (err) {
      setError(err?.response?.data?.error ?? 'Failed to load nurture queue')
    } finally {
      setLoading(false)
    }
  }, [page, includeOptedOut])

  useEffect(() => { fetchQueue() }, [fetchQueue])

  // Reset to page 1 when filter changes
  const handleToggleOptedOut = () => {
    setPage(1)
    setIncludeOptedOut(v => !v)
  }

  return (
    <div>
      {/* ── Header ────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14,
        marginBottom: 18, flexWrap: 'wrap',
      }}>
        <div>
          <h2 style={{
            fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17,
            color: ds.dark, margin: '0 0 2px',
          }}>
            🌱 Nurture Queue
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
            {loading ? 'Loading…' : `${total} lead${total !== 1 ? 's' : ''} on nurture track`}
            {includeOptedOut && (
              <span style={{
                marginLeft: 8, fontSize: 11, color: ds.red,
                fontWeight: 600,
              }}>
                · Including opted-out
              </span>
            )}
          </p>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
          {/* Toggle opted-out */}
          <label style={{
            display: 'flex', alignItems: 'center', gap: 7,
            fontSize: 13, color: ds.gray, cursor: 'pointer',
            userSelect: 'none',
          }}>
            <input
              type="checkbox"
              checked={includeOptedOut}
              onChange={handleToggleOptedOut}
              style={{ accentColor: ds.teal, width: 14, height: 14 }}
            />
            Show opted-out leads
          </label>
        </div>
      </div>

      {/* ── Error ─────────────────────────────────────────────────── */}
      {error && (
        <div style={{
          background: '#FFE8E8', border: `1px solid #FFCCCC`,
          borderRadius: ds.radius.md, padding: '10px 14px',
          fontSize: 13, color: ds.red, marginBottom: 16,
        }}>
          ⚠ {error}
        </div>
      )}

      {/* ── Table ─────────────────────────────────────────────────── */}
      <div style={{
        background: 'white', border: `1px solid ${ds.border}`,
        borderRadius: ds.radius.lg, overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <Th>Lead</Th>
              <Th>Score</Th>
              <Th>Reason</Th>
              <Th>Position</Th>
              <Th>Last Sent</Th>
              <Th>Assigned Rep</Th>
              <Th>Status</Th>
              <Th>{/* View button */}</Th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} style={emptyCellStyle}>
                  <span style={{ color: ds.teal }}>Loading nurture queue…</span>
                </td>
              </tr>
            ) : leads.length === 0 ? (
              <tr>
                <td colSpan={8} style={emptyCellStyle}>
                  {includeOptedOut
                    ? 'No leads on nurture track.'
                    : 'No active leads on nurture track.'}
                </td>
              </tr>
            ) : leads.map(lead => (
              <NurtureRow
                key={lead.id}
                lead={lead}
                onView={() => onOpenLead(lead.id)}
              />
            ))}
          </tbody>
        </table>

        {!loading && (
          <div style={{ padding: '0 14px' }}>
            <Pagination
              page={page}
              total={total}
              pageSize={PAGE_SIZE}
              onGoToPage={setPage}
            />
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Table row ────────────────────────────────────────────────────────────────

function NurtureRow({ lead, onView }) {
  const scoreStyle = SCORE_STYLE[lead.score] ?? SCORE_STYLE.unscored
  const repName    = lead.assigned_user?.full_name ?? '—'
  const reason     = GRADUATION_LABELS[lead.nurture_graduation_reason]
                  ?? lead.nurture_graduation_reason
                  ?? '—'
  const position   = lead.nurture_sequence_position ?? 0
  const optedOut   = lead.nurture_opted_out === true

  return (
    <tr style={{ borderBottom: `1px solid ${ds.border}` }}>
      {/* Lead name */}
      <td style={tdStyle}>
        <div style={{ fontWeight: 600, color: ds.dark }}>
          {lead.full_name}
          {optedOut && (
            <span style={{
              marginLeft: 7, fontSize: 10, fontWeight: 700,
              color: ds.red, background: '#FFE8E8',
              padding: '1px 6px', borderRadius: 10,
            }}>
              Opted out
            </span>
          )}
        </div>
      </td>

      {/* Score */}
      <td style={tdStyle}>
        <span style={{
          background: scoreStyle.bg, color: scoreStyle.color,
          padding: '2px 10px', borderRadius: 20,
          fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne,
        }}>
          {scoreStyle.label}
        </span>
      </td>

      {/* Graduation reason */}
      <td style={{ ...tdStyle, fontSize: 12, color: ds.gray }}>
        {reason}
      </td>

      {/* Sequence position */}
      <td style={{ ...tdStyle, fontSize: 12, textAlign: 'center' }}>
        <span style={{
          background: ds.mint, color: ds.tealDark,
          padding: '2px 8px', borderRadius: 10,
          fontSize: 11, fontWeight: 600,
        }}>
          #{position}
        </span>
      </td>

      {/* Last sent */}
      <td style={{ ...tdStyle, fontSize: 12, color: ds.gray, whiteSpace: 'nowrap' }}>
        <LastSentCell ts={lead.last_nurture_sent_at} />
      </td>

      {/* Assigned rep */}
      <td style={{ ...tdStyle, fontSize: 12, color: ds.gray }}>
        {repName}
      </td>

      {/* Opted-out status */}
      <td style={{ ...tdStyle, fontSize: 12 }}>
        {optedOut
          ? <span style={{ color: ds.red, fontWeight: 600 }}>Opted out</span>
          : <span style={{ color: '#38A169', fontWeight: 600 }}>Active</span>
        }
      </td>

      {/* View button */}
      <td style={{ ...tdStyle, textAlign: 'right' }}>
        <button
          onClick={onView}
          style={{
            padding: '6px 14px', borderRadius: ds.radius.sm,
            border: `1.5px solid ${ds.teal}`, background: 'white',
            color: ds.teal, fontSize: 12, fontWeight: 600,
            fontFamily: ds.fontSyne, cursor: 'pointer',
            transition: 'all 0.12s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = ds.mint }}
          onMouseLeave={e => { e.currentTarget.style.background = 'white' }}
        >
          View →
        </button>
      </td>
    </tr>
  )
}

// ─── Last sent cell ───────────────────────────────────────────────────────────

function LastSentCell({ ts }) {
  if (!ts) {
    return (
      <span style={{
        color: '#C05621', background: '#FFFAF0',
        border: '1px solid #F6AD55',
        borderRadius: 8, padding: '2px 7px', fontSize: 11, fontWeight: 600,
      }}>
        Never sent
      </span>
    )
  }

  const now      = new Date()
  const sent     = new Date(ts)
  const diffMs   = now - sent
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  const label =
    diffDays === 0 ? 'Today' :
    diffDays === 1 ? 'Yesterday' :
    `${diffDays}d ago`

  const isOverdue = diffDays >= 7
  return (
    <span style={{
      color: isOverdue ? '#C05621' : ds.gray,
      fontWeight: isOverdue ? 600 : 400,
    }}>
      {label}
    </span>
  )
}

// ─── Shared sub-components ────────────────────────────────────────────────────

function Th({ children }) {
  return (
    <th style={{
      padding: '10px 14px', textAlign: 'left',
      fontSize: 10, fontWeight: 700, color: '#5b8a9a',
      textTransform: 'uppercase', letterSpacing: '0.7px',
      whiteSpace: 'nowrap', background: '#f5fbfc',
      borderBottom: `1px solid ${ds.border}`,
    }}>
      {children}
    </th>
  )
}

const tdStyle = {
  padding: '12px 14px',
  borderBottom: `1px solid ${ds.border}`,
  verticalAlign: 'middle',
  fontSize: 13,
  color: ds.dark,
}

const emptyCellStyle = {
  padding: 48, textAlign: 'center',
  color: ds.gray, fontSize: 13,
}
