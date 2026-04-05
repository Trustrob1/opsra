/**
 * frontend/src/modules/support/InteractionLogPanel.jsx
 * Universal Interaction Logger — log an interaction and list past logs.
 * AI structures raw_notes server-side via Haiku (§8.1).
 * logged_by is always derived server-side from JWT — never sent in payload (Pattern 12).
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { createInteractionLog, listInteractionLogs } from '../../services/support.service'

const INTERACTION_TYPES = [
  { value: 'outbound_call', label: '📞 Outbound Call' },
  { value: 'inbound_call',  label: '📲 Inbound Call' },
  { value: 'whatsapp',      label: '💬 WhatsApp' },
  { value: 'in_person',     label: '🤝 In-Person' },
  { value: 'email',         label: '✉️ Email' },
]

const OUTCOMES = [
  'Issue identified — needs follow-up',
  'Issue resolved on call',
  'General check-in — customer happy',
  'No answer — will retry',
  'Escalated to senior agent',
  'Customer requested callback',
]

// ---------------------------------------------------------------------------
// Log entry card
// ---------------------------------------------------------------------------
function LogCard({ log }) {
  const [expanded, setExpanded] = useState(false)
  const typeObj = INTERACTION_TYPES.find(t => t.value === log.interaction_type)
  const dateStr = log.interaction_date
    ? new Date(log.interaction_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'

  return (
    <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '12px', padding: '16px 18px', marginBottom: '10px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '5px' }}>
            <span style={{ fontWeight: 700, fontSize: '13px', color: ds.dark }}>{typeObj?.label || log.interaction_type}</span>
            {log.duration_minutes && (
              <span style={{ background: ds.mint, color: ds.tealDark, fontSize: '11px', fontWeight: 600, padding: '2px 8px', borderRadius: '10px' }}>
                {log.duration_minutes} min
              </span>
            )}
            {log.outcome && (
              <span style={{ background: '#F5F5F5', color: ds.gray, fontSize: '11px', padding: '2px 8px', borderRadius: '10px' }}>
                {log.outcome}
              </span>
            )}
          </div>
          <div style={{ fontSize: '11px', color: ds.gray }}>{dateStr}</div>
        </div>
        {(log.structured_notes || log.raw_notes) && (
          <button
            onClick={() => setExpanded(e => !e)}
            style={{ background: 'none', border: 'none', color: ds.teal, fontSize: '12px', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap', padding: '2px 0' }}
          >
            {expanded ? 'Hide ↑' : 'View ↓'}
          </button>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {log.structured_notes && (
            <div style={{ background: ds.mint, borderRadius: '8px', padding: '12px 14px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: ds.teal, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>🤖 AI-Structured Notes</div>
              <div style={{ fontSize: '13px', color: ds.dark, lineHeight: 1.6 }}>{log.structured_notes}</div>
            </div>
          )}
          {log.ai_recommended_action && (
            <div style={{ background: '#FFF8F0', border: '1px solid #FFD0B0', borderRadius: '8px', padding: '10px 14px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#8B4513', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>Recommended Next Step</div>
              <div style={{ fontSize: '13px', color: ds.dark }}>{log.ai_recommended_action}</div>
            </div>
          )}
          {log.raw_notes && !log.structured_notes && (
            <div style={{ background: '#F9F9F9', borderRadius: '8px', padding: '12px 14px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Raw Notes</div>
              <div style={{ fontSize: '13px', color: ds.dark, lineHeight: 1.6 }}>{log.raw_notes}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function InteractionLogPanel({ defaultCustomerId, defaultLeadId, defaultTicketId }) {
  // Form state
  const [form, setForm] = useState({
    interaction_type: 'outbound_call',
    interaction_date: new Date().toISOString().slice(0, 16),
    duration_minutes: '',
    outcome:          '',
    raw_notes:        '',
    customer_id:      defaultCustomerId || '',
    lead_id:          defaultLeadId     || '',
    ticket_id:        defaultTicketId   || '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [submitted, setSubmitted]    = useState(false)

  // Log list state
  const [logs, setLogs]         = useState([])
  const [total, setTotal]       = useState(0)
  const [loadingLogs, setLoadingLogs] = useState(false)
  const [listError, setListError]     = useState(null)
  const [tick, setTick]               = useState(0)
  const refresh = useCallback(() => setTick(t => t + 1), [])

  function set(f, v) { setForm(p => ({ ...p, [f]: v })) }

  useEffect(() => {
    let cancelled = false
    setLoadingLogs(true)
    setListError(null)
    const filters = {}
    if (defaultCustomerId) filters.customer_id = defaultCustomerId
    if (defaultLeadId)     filters.lead_id     = defaultLeadId
    listInteractionLogs({ ...filters, page_size: 30 })
      .then(data => {
        if (cancelled) return
        setLogs(data?.items || [])
        setTotal(data?.total || 0)
      })
      .catch(e => { if (!cancelled) setListError(e.message) })
      .finally(() => { if (!cancelled) setLoadingLogs(false) })
    return () => { cancelled = true }
  }, [defaultCustomerId, defaultLeadId, tick])

  async function handleSubmit() {
    if (!form.interaction_type || !form.interaction_date) {
      setSubmitError('Interaction type and date are required.')
      return
    }
    setSubmitting(true)
    setSubmitError(null)
    try {
      const payload = {
        interaction_type: form.interaction_type,
        interaction_date: new Date(form.interaction_date).toISOString(),
      }
      if (form.duration_minutes) payload.duration_minutes = parseInt(form.duration_minutes, 10)
      if (form.outcome.trim())   payload.outcome          = form.outcome.trim()
      if (form.raw_notes.trim()) payload.raw_notes        = form.raw_notes.trim()
      if (form.customer_id.trim()) payload.customer_id   = form.customer_id.trim()
      if (form.lead_id.trim())     payload.lead_id        = form.lead_id.trim()
      if (form.ticket_id.trim())   payload.ticket_id      = form.ticket_id.trim()

      await createInteractionLog(payload)
      setSubmitted(true)
      setForm(p => ({ ...p, raw_notes: '', outcome: '', duration_minutes: '' }))
      refresh()
      setTimeout(() => setSubmitted(false), 3000)
    } catch (e) {
      setSubmitError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const lb  = { fontSize: '11px', fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '5px', display: 'block' }
  const inp = { width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: '9px', padding: '10px 13px', fontSize: '13px', color: ds.dark, fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box', background: 'white' }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', alignItems: 'start' }}>

      {/* ── Log form ── */}
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', padding: '22px 24px' }}>
        <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '15px', color: ds.dark, marginBottom: '18px' }}>
          Log an Interaction
        </div>

        {submitted && (
          <div style={{ background: '#E8F8EE', border: '1px solid #B0DDB8', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: ds.green, marginBottom: '14px', fontWeight: 600 }}>
            ✓ Interaction logged — AI is structuring your notes.
          </div>
        )}
        {submitError && (
          <div style={{ background: '#FFF0F0', border: '1px solid #FFD0D0', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#C0392B', marginBottom: '14px' }}>
            {submitError}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
          <div>
            <label style={lb}>Type</label>
            <select style={inp} value={form.interaction_type} onChange={e => set('interaction_type', e.target.value)}>
              {INTERACTION_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label style={lb}>Duration (mins)</label>
            <input style={inp} type="number" min="1" placeholder="e.g. 14" value={form.duration_minutes} onChange={e => set('duration_minutes', e.target.value)} />
          </div>
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label style={lb}>Date & Time</label>
          <input style={inp} type="datetime-local" value={form.interaction_date} onChange={e => set('interaction_date', e.target.value)} />
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label style={lb}>Outcome</label>
          <select style={inp} value={form.outcome} onChange={e => set('outcome', e.target.value)}>
            <option value="">Select outcome…</option>
            {OUTCOMES.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label style={lb}>Your Notes <span style={{ color: ds.gray, fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>(rough — AI will structure)</span></label>
          <textarea
            style={{ ...inp, minHeight: '100px', resize: 'vertical' }}
            placeholder="Write rough call notes — AI will clean them up automatically…"
            value={form.raw_notes}
            onChange={e => set('raw_notes', e.target.value)}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '18px' }}>
          <div>
            <label style={lb}>Customer ID (optional)</label>
            <input style={inp} placeholder="UUID" value={form.customer_id} onChange={e => set('customer_id', e.target.value)} />
          </div>
          <div>
            <label style={lb}>Ticket ID (optional)</label>
            <input style={inp} placeholder="UUID" value={form.ticket_id} onChange={e => set('ticket_id', e.target.value)} />
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting}
          style={{ width: '100%', padding: '11px', borderRadius: '9px', border: 'none', background: ds.teal, color: 'white', fontSize: '13.5px', fontWeight: 600, cursor: submitting ? 'not-allowed' : 'pointer', opacity: submitting ? 0.7 : 1 }}
        >
          {submitting ? 'Logging…' : '+ Log Interaction'}
        </button>
      </div>

      {/* ── Log list ── */}
      <div>
        <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '15px', color: ds.dark, marginBottom: '14px' }}>
          Recent Logs
          {total > 0 && <span style={{ fontFamily: 'inherit', fontWeight: 400, fontSize: '12px', color: ds.gray, marginLeft: '8px' }}>{total} total</span>}
        </div>

        {listError && <div style={{ color: '#C0392B', fontSize: '13px', marginBottom: '10px' }}>{listError}</div>}

        {loadingLogs ? (
          <div style={{ textAlign: 'center', padding: '32px', color: ds.gray, fontSize: '13px' }}>Loading logs…</div>
        ) : logs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px', color: ds.gray, fontSize: '13px', background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px' }}>
            No interaction logs yet. Log your first interaction.
          </div>
        ) : (
          <div>
            {logs.map(log => <LogCard key={log.id} log={log} />)}
          </div>
        )}
      </div>
    </div>
  )
}
