/**
 * LeadTimeline
 *
 * Calls GET /api/v1/leads/{id}/timeline and renders a chronological
 * event list.  Event types come from the lead_timeline table schema:
 *   lead_created | stage_changed | message_sent | call_logged |
 *   score_updated | task_created | note_added
 */
import { useState, useEffect } from 'react'
import { getTimeline } from '../../services/leads.service'
import { ds, TIMELINE_ICONS } from '../../utils/ds'

export default function LeadTimeline({ leadId }) {
  const [events, setEvents]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    if (!leadId) return
    let cancelled = false
    setLoading(true)
    setError(null)

    getTimeline(leadId)
      .then((res) => {
        if (cancelled) return
        if (res.success) setEvents(res.data ?? [])
        else setError(res.error ?? 'Failed to load timeline')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err?.response?.data?.error ?? 'Failed to load timeline')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [leadId])

  if (loading) return <Skeleton />
  if (error)   return <p style={{ color: ds.red, fontSize: 13 }}>⚠ {error}</p>
  if (!events.length) return (
    <p style={{ color: ds.gray, fontSize: 13, fontStyle: 'italic' }}>
      No timeline events yet.
    </p>
  )

  return (
    <div>
      {events.map((ev, i) => (
        <TimelineItem key={ev.id ?? i} event={ev} isLast={i === events.length - 1} />
      ))}
    </div>
  )
}

function TimelineItem({ event, isLast }) {
  const icon  = TIMELINE_ICONS[event.event_type] ?? '•'
  const date  = event.created_at ? new Date(event.created_at) : null
  const dateStr = date
    ? date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : ''
  const timeStr = date
    ? date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : ''

  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: isLast ? 0 : 14 }}>
      {/* Dot + vertical line */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width:        28,
          height:       28,
          borderRadius: '50%',
          background:   ds.mint,
          border:       `1.5px solid ${ds.border}`,
          display:      'flex',
          alignItems:   'center',
          justifyContent: 'center',
          fontSize:     14,
          flexShrink:   0,
        }}>
          {icon}
        </div>
        {!isLast && (
          <div style={{ width: 1, flex: 1, background: ds.border, minHeight: 16, margin: '4px 0' }} />
        )}
      </div>

      {/* Content */}
      <div style={{ flex: 1, paddingTop: 4 }}>
        <p style={{ fontSize: 11, color: ds.gray, margin: '0 0 2px' }}>
          {dateStr} · {timeStr}
        </p>
        <p style={{ fontSize: 13, color: ds.dark, margin: 0, lineHeight: 1.55 }}>
          {event.description}
        </p>
        {/* metadata snippet — e.g. from_stage → to_stage */}
        {event.metadata && Object.keys(event.metadata).length > 0 && (
          <MetaBadges meta={event.metadata} />
        )}
      </div>
    </div>
  )
}

function MetaBadges({ meta }) {
  if (meta.from_stage && meta.to_stage) {
    return (
      <p style={{ fontSize: 11, color: ds.gray, margin: '4px 0 0', fontStyle: 'italic' }}>
        {meta.from_stage} → {meta.to_stage}
      </p>
    )
  }
  return null
}

function Skeleton() {
  return (
    <div>
      {[1, 2, 3].map((n) => (
        <div key={n} style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
          <div style={{ width: 28, height: 28, borderRadius: '50%', background: ds.border, flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ height: 10, background: ds.border, borderRadius: 4, width: '30%', marginBottom: 6 }} />
            <div style={{ height: 13, background: ds.border, borderRadius: 4, width: '80%' }} />
          </div>
        </div>
      ))}
    </div>
  )
}
