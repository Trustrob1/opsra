/**
 * shared/LogInteractionPanel.jsx
 * Inline interaction log panel — Phase 7B UX additions.
 *
 * Used in:
 *   LeadProfile     — tab "Log Interaction"
 *   CustomerProfile — tab "Log Interaction"
 *
 * Props:
 *   linkedTo     — { type: 'lead'|'customer', id: string }
 *   contextName  — display name of the lead/customer (for empty state messaging)
 *
 * Renders:
 *   1. Create form (collapsed by default, expands on "Log Interaction" button)
 *   2. Paginated history of past logs for this specific lead or customer
 *
 * Uses existing API routes from Phase 4A:
 *   POST /api/v1/interaction-logs
 *   GET  /api/v1/interaction-logs?lead_id=X   or   ?customer_id=X
 *
 * Uses Phase 7A tasks API:
 *   POST /api/v1/tasks  — confirm an AI-recommended task from an interaction log
 *
 * Pattern 12: org_id never in payload — derived server-side.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../utils/ds'
import { createInteractionLog, listInteractionLogs } from '../services/support.service'
import { createTask } from '../services/tasks.service'

// ── Constants ─────────────────────────────────────────────────────────────────

const INTERACTION_TYPES = [
  { value: 'outbound_call', label: 'Outbound Call' },
  { value: 'inbound_call',  label: 'Inbound Call'  },
  { value: 'whatsapp',      label: 'WhatsApp'      },
  { value: 'in_person',     label: 'In Person'     },
  { value: 'email',         label: 'Email'         },
]

const OUTCOMES = [
  { value: '',                  label: 'No specific outcome' },
  { value: 'issue_identified',  label: 'Issue Identified'    },
  { value: 'issue_resolved',    label: 'Issue Resolved'      },
  { value: 'general_checkin',   label: 'General Check-in'    },
  { value: 'no_answer',         label: 'No Answer'           },
]

const TYPE_ICONS = {
  outbound_call: '📞',
  inbound_call:  '📲',
  whatsapp:      '💬',
  in_person:     '🤝',
  email:         '✉️',
}

function todayDatetimeLocal() {
  const now = new Date()
  now.setSeconds(0, 0)
  return now.toISOString().slice(0, 16)  // YYYY-MM-DDTHH:MM
}

// ── Log entry card ────────────────────────────────────────────────────────────

function LogEntry({ log, linkedTo }) {
  const icon  = TYPE_ICONS[log.interaction_type] ?? '📋'
  const label = INTERACTION_TYPES.find(t => t.value === log.interaction_type)?.label ?? log.interaction_type
  const date  = log.interaction_date
    ? new Date(log.interaction_date).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'

  const [taskCreated,  setTaskCreated]  = useState(false)
  const [taskLoading,  setTaskLoading]  = useState(false)
  const [taskError,    setTaskError]    = useState(null)

  const handleConfirmTask = async () => {
    setTaskLoading(true)
    setTaskError(null)
    try {
      await createTask({
        title:            log.ai_recommended_action,
        task_type:        'ai_recommended',
        source_module:    linkedTo.type === 'lead' ? 'leads' : 'whatsapp',
        source_record_id: linkedTo.id,
        // org_id and assigned_to derived server-side — Pattern 12
      })
      setTaskCreated(true)
    } catch {
      setTaskError('Could not create task. Please try again.')
    } finally {
      setTaskLoading(false)
    }
  }

  return (
    <div style={{
      background: '#F5FAFB', border: '1px solid #E8EDF0', borderRadius: 10,
      padding: '14px 16px', marginBottom: 10,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 17 }}>{icon}</span>
          <span style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13, color: ds.dark }}>
            {label}
          </span>
          {log.duration_minutes && (
            <span style={{ fontSize: 11, color: ds.gray, background: '#E8EDF0', borderRadius: 10, padding: '2px 8px' }}>
              {log.duration_minutes} min
            </span>
          )}
          {log.outcome && log.outcome !== 'no_answer' && (
            <span style={{ fontSize: 11, fontWeight: 600, background: '#E8F8EE', color: '#27AE60', borderRadius: 10, padding: '2px 8px' }}>
              {OUTCOMES.find(o => o.value === log.outcome)?.label ?? log.outcome}
            </span>
          )}
          {log.outcome === 'no_answer' && (
            <span style={{ fontSize: 11, fontWeight: 600, background: '#FFF3E0', color: '#E07B3A', borderRadius: 10, padding: '2px 8px' }}>
              No Answer
            </span>
          )}
        </div>
        <span style={{ fontSize: 12, color: ds.gray }}>{date}</span>
      </div>

      {/* Structured notes (AI-generated) */}
      {log.structured_notes && (
        <p style={{ fontSize: 13, color: ds.dark, lineHeight: 1.6, margin: '0 0 6px', whiteSpace: 'pre-wrap' }}>
          {log.structured_notes}
        </p>
      )}

      {/* Raw notes (fallback if no structured notes yet) */}
      {!log.structured_notes && log.raw_notes && (
        <p style={{ fontSize: 13, color: '#5a7a8a', lineHeight: 1.6, margin: '0 0 6px', fontStyle: 'italic' }}>
          {log.raw_notes}
        </p>
      )}

      {/* AI recommended action with one-click task creation */}
      {log.ai_recommended_action && (
        <div style={{
          marginTop: 8, padding: '10px 12px',
          background: '#FFF9F0', border: '1px solid #FFD8A8', borderRadius: 7,
        }}>
          <div style={{ fontSize: 12.5, color: '#8B4513', marginBottom: taskCreated ? 0 : 8 }}>
            <span style={{ fontWeight: 600 }}>🤖 AI suggests: </span>
            {log.ai_recommended_action}
          </div>
          {!taskCreated ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={handleConfirmTask}
                disabled={taskLoading}
                style={{
                  background: taskLoading ? '#9ca3af' : ds.teal,
                  color: 'white', border: 'none', borderRadius: 7,
                  padding: '5px 12px', fontSize: 11.5, fontWeight: 600,
                  fontFamily: ds.fontSyne, cursor: taskLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {taskLoading ? 'Creating…' : '✓ Confirm as Task'}
              </button>
              {taskError && (
                <span style={{ fontSize: 11, color: '#dc2626' }}>{taskError}</span>
              )}
            </div>
          ) : (
            <span style={{ fontSize: 11.5, color: '#16a34a', fontWeight: 600 }}>
              ✓ Task created — visible on the Task Board
            </span>
          )}
        </div>
      )}

      {/* Logged by */}
      {log.logged_by_user?.full_name && (
        <p style={{ fontSize: 11, color: ds.gray, margin: '6px 0 0' }}>
          Logged by {log.logged_by_user.full_name}
        </p>
      )}
    </div>
  )
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateForm({ linkedTo, contextName, onCreated }) {
  const [open,     setOpen]     = useState(false)
  const [form,     setForm]     = useState({
    interaction_type: 'outbound_call',
    interaction_date: todayDatetimeLocal(),
    duration_minutes: '',
    outcome:          '',
    raw_notes:        '',
  })
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [success,  setSuccess]  = useState(false)

  function set(key, val) { setForm(f => ({ ...f, [key]: val })) }

  async function handleSubmit() {
    setLoading(true)
    setError(null)
    try {
      const payload = {
        interaction_type: form.interaction_type,
        interaction_date: new Date(form.interaction_date).toISOString(),
      }
      if (form.duration_minutes) payload.duration_minutes = parseInt(form.duration_minutes, 10)
      if (form.outcome)          payload.outcome          = form.outcome
      if (form.raw_notes.trim()) payload.raw_notes        = form.raw_notes.trim()

      // Link to the lead or customer — org_id never in payload (Pattern 12)
      if (linkedTo.type === 'lead')     payload.lead_id     = linkedTo.id
      if (linkedTo.type === 'customer') payload.customer_id = linkedTo.id

      await createInteractionLog(payload)
      setForm({
        interaction_type: 'outbound_call',
        interaction_date: todayDatetimeLocal(),
        duration_minutes: '',
        outcome:          '',
        raw_notes:        '',
      })
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
      setOpen(false)
      onCreated?.()
    } catch (err) {
      setError(err?.response?.data?.error?.message ?? 'Failed to log interaction.')
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          background: ds.teal, color: 'white', border: 'none',
          borderRadius: 9, padding: '10px 20px',
          fontSize: 13.5, fontWeight: 600, fontFamily: ds.fontSyne,
          cursor: 'pointer', marginBottom: 24,
        }}
      >
        📞 Log Interaction with {contextName}
      </button>
    )
  }

  return (
    <div style={{
      background: 'white', border: `1.5px solid ${ds.teal}`, borderRadius: 12,
      padding: '20px 22px', marginBottom: 24,
    }}>
      <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark, marginBottom: 16 }}>
        Log Interaction
      </div>

      {/* Type + Date row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <div>
          <label style={lbl}>Interaction Type *</label>
          <select value={form.interaction_type} onChange={e => set('interaction_type', e.target.value)} style={inp}>
            {INTERACTION_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={lbl}>Date & Time *</label>
          <input
            type="datetime-local"
            value={form.interaction_date}
            onChange={e => set('interaction_date', e.target.value)}
            style={inp}
          />
        </div>
      </div>

      {/* Duration + Outcome row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <div>
          <label style={lbl}>Duration (minutes)</label>
          <input
            type="number"
            value={form.duration_minutes}
            onChange={e => set('duration_minutes', e.target.value)}
            placeholder="e.g. 15"
            min="1"
            style={inp}
          />
        </div>
        <div>
          <label style={lbl}>Outcome</label>
          <select value={form.outcome} onChange={e => set('outcome', e.target.value)} style={inp}>
            {OUTCOMES.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Notes */}
      <label style={lbl}>Notes (AI will structure these)</label>
      <textarea
        value={form.raw_notes}
        onChange={e => set('raw_notes', e.target.value)}
        placeholder="Describe what happened, what was discussed, any issues raised or resolved…"
        rows={4}
        maxLength={5000}
        style={{ ...inp, resize: 'vertical', marginBottom: 4 }}
      />
      <p style={{ fontSize: 11, color: ds.gray, margin: '0 0 16px' }}>
        AI will organise your notes and suggest a next action automatically.
      </p>

      {error && (
        <p style={{ fontSize: 13, color: ds.red, marginBottom: 12 }}>⚠ {error}</p>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <button
          onClick={handleSubmit}
          disabled={loading}
          style={{
            background: loading ? '#9ca3af' : ds.teal, color: 'white',
            border: 'none', borderRadius: 9, padding: '10px 22px',
            fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne,
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Saving…' : 'Save Interaction'}
        </button>
        <button
          onClick={() => setOpen(false)}
          style={{
            background: 'none', border: `1.5px solid ${ds.border}`,
            borderRadius: 9, padding: '10px 16px',
            fontSize: 13, color: ds.gray, fontFamily: ds.fontDm, cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function LogInteractionPanel({ linkedTo, contextName }) {
  const [logs,      setLogs]      = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [tick,      setTick]      = useState(0)
  const [page,      setPage]      = useState(1)
  const [total,     setTotal]     = useState(0)
  const PAGE_SIZE = 10

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (linkedTo.type === 'lead')     params.lead_id     = linkedTo.id
      if (linkedTo.type === 'customer') params.customer_id = linkedTo.id

      const res = await listInteractionLogs(params)
      // support.service.js request() already unwraps json.data,
      // so res is { items, total, page, ... } directly
      setLogs(res?.items ?? [])
      setTotal(res?.total ?? 0)
    } catch {
      setError('Could not load interaction history.')
    } finally {
      setLoading(false)
    }
  }, [linkedTo.id, linkedTo.type, page, tick])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  const refresh = () => { setPage(1); setTick(t => t + 1) }

  return (
    <div>
      <CreateForm
        linkedTo={linkedTo}
        contextName={contextName}
        onCreated={refresh}
      />

      {/* History */}
      <div style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13, color: ds.teal, textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: 14 }}>
        Interaction History {total > 0 && `· ${total} total`}
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: ds.gray, fontSize: 13 }}>
          Loading interaction history…
        </div>
      )}

      {error && (
        <p style={{ fontSize: 13, color: ds.red }}>{error}</p>
      )}

      {!loading && !error && logs.length === 0 && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: ds.gray }}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>📋</div>
          <p style={{ fontSize: 13 }}>No interactions logged yet for {contextName}.</p>
          <p style={{ fontSize: 12, color: '#9ca3af' }}>Use the button above to log your first interaction.</p>
        </div>
      )}

      {!loading && logs.map(log => (
        <LogEntry key={log.id} log={log} linkedTo={linkedTo} />
      ))}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
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
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────

const lbl = {
  display: 'block', fontSize: 11, fontWeight: 600,
  color: '#6b7280', textTransform: 'uppercase',
  letterSpacing: '0.6px', marginBottom: 6,
}

const inp = {
  width: '100%', border: '1.5px solid #e5e7eb',
  borderRadius: 8, padding: '10px 12px', fontSize: 13.5,
  fontFamily: ds.fontDm, outline: 'none',
  transition: 'border-color 0.2s', boxSizing: 'border-box',
}

const pagBtn = (disabled) => ({
  padding: '6px 14px', borderRadius: 7,
  border: `1px solid ${ds.border}`, background: 'white',
  fontSize: 12, cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.5 : 1,
})
