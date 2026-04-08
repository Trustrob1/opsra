/**
 * LeadMessages.jsx
 *
 * WhatsApp message history + compose panel for a lead.
 * Shown on the Messages tab of LeadProfile.
 *
 * Features:
 *   - Fetches GET /api/v1/leads/{id}/messages (paginated, newest first)
 *   - Renders each message as a chat bubble with direction (inbound/outbound)
 *   - Shows delivery/read status indicators per outbound message:
 *       ✓  sent
 *       ✓✓ delivered  (grey)
 *       ✓✓ read       (teal/blue)
 *   - MessageComposer at the bottom for sending new messages
 *   - Load More pagination
 *
 * Props:
 *   leadId      — UUID
 *   leadName    — string (for composer header display)
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import MessageComposer from '../whatsapp/MessageComposer'
import { getLeadMessages } from '../../services/leads.service'

const PAGE_SIZE = 20

export default function LeadMessages({ leadId, leadName }) {
  const [messages, setMessages]   = useState([])
  const [total, setTotal]         = useState(0)
  const [page, setPage]           = useState(1)
  const [loading, setLoading]     = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError]         = useState(null)
  const [tick, setTick]           = useState(0)

  const refresh = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    if (!leadId) return
    setLoading(true)
    setError(null)
    getLeadMessages(leadId, 1, PAGE_SIZE)
      .then(res => {
        if (res.success) {
          setMessages(res.data.items ?? [])
          setTotal(res.data.total ?? 0)
          setPage(1)
        } else {
          setError(res.error ?? 'Failed to load messages')
        }
      })
      .catch(() => setError('Failed to load messages'))
      .finally(() => setLoading(false))
  }, [leadId, tick])

  const loadMore = () => {
    const nextPage = page + 1
    setLoadingMore(true)
    getLeadMessages(leadId, nextPage, PAGE_SIZE)
      .then(res => {
        if (res.success) {
          setMessages(prev => [...prev, ...(res.data.items ?? [])])
          setPage(nextPage)
        }
      })
      .catch(() => {})
      .finally(() => setLoadingMore(false))
  }

  const hasMore = messages.length < total

  return (
    <div>
      {/* Compose panel */}
      <div style={{ marginBottom: 20 }}>
        <MessageComposer
          leadId={leadId}
          windowOpen={true}   /* leads: no 24hr window enforcement at this stage */
          templates={[]}
          onSent={refresh}
        />
      </div>

      {/* Message history */}
      <div style={{ marginBottom: 8 }}>
        <p style={{
          fontSize: 11, fontWeight: 600, color: ds.teal,
          textTransform: 'uppercase', letterSpacing: '0.8px', margin: '0 0 12px',
        }}>
          Message History
        </p>

        {loading && <Skeleton />}
        {error   && <p style={{ fontSize: 13, color: ds.red }}>⚠ {error}</p>}
        {!loading && !error && messages.length === 0 && (
          <p style={{ fontSize: 13, color: ds.gray, fontStyle: 'italic' }}>
            No messages yet. Send a WhatsApp message above.
          </p>
        )}

        {!loading && messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {hasMore && (
          <button
            onClick={loadMore}
            disabled={loadingMore}
            style={{
              display: 'block', margin: '12px auto 0',
              padding: '8px 20px', borderRadius: 8,
              border: `1px solid ${ds.border}`, background: 'white',
              fontSize: 12.5, color: ds.teal, cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }) {
  const isOutbound = msg.direction === 'outbound'
  const date = msg.created_at ? new Date(msg.created_at) : null
  const timeStr = date
    ? date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : ''
  const dateStr = date
    ? date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
    : ''

  return (
    <div style={{
      display:       'flex',
      justifyContent: isOutbound ? 'flex-end' : 'flex-start',
      marginBottom:  10,
    }}>
      <div style={{
        maxWidth:     '72%',
        background:   isOutbound ? '#DCF8C6' : 'white',
        border:       `1px solid ${isOutbound ? '#B0DDB8' : ds.border}`,
        borderRadius: isOutbound ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
        padding:      '9px 12px',
        boxShadow:    '0 1px 3px rgba(0,0,0,0.06)',
      }}>
        {/* Template badge */}
        {msg.template_name && (
          <p style={{
            fontSize: 10, color: '#856404', background: '#FFF3CD',
            borderRadius: 4, padding: '2px 6px', margin: '0 0 4px',
            display: 'inline-block',
          }}>
            📋 {msg.template_name}
          </p>
        )}

        {/* Content */}
        <p style={{ fontSize: 13, color: ds.dark, margin: 0, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
          {msg.content || '—'}
        </p>

        {/* Footer: time + status */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
          gap: 4, marginTop: 4,
        }}>
          <span style={{ fontSize: 10, color: ds.gray }}>{dateStr} {timeStr}</span>
          {isOutbound && <StatusTick status={msg.status} />}
        </div>
      </div>
    </div>
  )
}

// ─── Status tick indicator ────────────────────────────────────────────────────

function StatusTick({ status }) {
  if (!status || status === 'pending') {
    return <span style={{ fontSize: 11, color: ds.gray }}>🕐</span>
  }
  if (status === 'sent') {
    return <span style={{ fontSize: 11, color: ds.gray }} title="Sent">✓</span>
  }
  if (status === 'delivered') {
    return <span style={{ fontSize: 11, color: ds.gray }} title="Delivered">✓✓</span>
  }
  if (status === 'read') {
    return <span style={{ fontSize: 11, color: '#028090' }} title="Read">✓✓</span>
  }
  if (status === 'failed') {
    return <span style={{ fontSize: 11, color: '#C0392B' }} title="Failed">✗</span>
  }
  return null
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div>
      {[1, 2, 3].map(n => (
        <div key={n} style={{
          display: 'flex',
          justifyContent: n % 2 === 0 ? 'flex-end' : 'flex-start',
          marginBottom: 10,
        }}>
          <div style={{
            width: `${40 + n * 10}%`, height: 48,
            background: ds.border, borderRadius: 12,
          }} />
        </div>
      ))}
    </div>
  )
}
