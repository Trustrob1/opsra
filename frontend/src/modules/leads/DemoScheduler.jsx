/**
 * DemoScheduler — M01-7 + M01-9
 *
 * Full demo lifecycle UI on the lead profile Demos tab.
 *
 * Status machine:
 *   pending_assignment → confirmed → attended | no_show | rescheduled
 *
 * M01-9 additions:
 *   - LogOutcomeModal: when "Attended" selected, notes field becomes prominent
 *     with explicit prompt that notes feed the AI recap.
 *   - DemoCard: RecapCard section rendered below attended demos that have recap data.
 *
 * Panel sections:
 *   1. "Request Demo" form — any rep/admin creates a pending_assignment request
 *   2. Demo cards — pending ones show "Confirm" button for admin/manager
 *   3. Confirm modal — admin sets scheduled_at, medium, assigns rep
 *   4. Log Outcome modal — attended | no_show | rescheduled
 *   5. Recap card — AI-generated summary shown below attended demo card (M01-9)
 *
 * API calls (via leads.service.js):
 *   POST   /api/v1/leads/{id}/demos                    — createDemoRequest
 *   GET    /api/v1/leads/{id}/demos                    — listDemos
 *   POST   /api/v1/leads/{id}/demos/{id}/confirm       — confirmDemo
 *   PATCH  /api/v1/leads/{id}/demos/{id}               — logDemoOutcome
 *
 * Security: org_id never in payload — Pattern 12.
 */
import { useState, useEffect, useCallback } from 'react'
import { createDemoRequest, listDemos, confirmDemo, logDemoOutcome } from '../../services/leads.service'
import { ds } from '../../utils/ds'
import UserSelect from '../../shared/UserSelect'
import useAuthStore from '../../store/authStore'

// ── Status display config ─────────────────────────────────────────────────────

const STATUS_STYLE = {
  pending_assignment: { label: '🕐 Pending Confirmation', bg: '#FFFBEB', color: '#92400E' },
  confirmed:          { label: '✅ Confirmed',            bg: '#F0FFF4', color: '#276749' },
  attended:           { label: '🎉 Attended',             bg: '#EBF8FF', color: '#2B6CB0' },
  no_show:            { label: '❌ No-show',              bg: '#FFF5F5', color: '#C53030' },
  rescheduled:        { label: '🔄 Rescheduled',          bg: '#FAF5FF', color: '#6B46C1' },
}

const MEDIUM_LABELS = { virtual: '💻 Virtual (Online)', in_person: '🤝 In Person' }

const fmtDateTime = (iso) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', {
    weekday: 'short', day: 'numeric', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DemoScheduler({ leadId, leadName }) {
  const [demos, setDemos]               = useState([])
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState(null)
  const [showRequestForm, setShowRequestForm] = useState(false)
  const [confirmModal, setConfirmModal] = useState(null)
  const [outcomeModal, setOutcomeModal] = useState(null)

  const isManager = useAuthStore.getState().isManager()

  const loadDemos = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listDemos(leadId)
      if (res.success) setDemos(res.data || [])
      else setError(res.error?.message ?? 'Failed to load demos')
    } catch (e) {
      setError(e?.response?.data?.error?.message ?? 'Failed to load demos')
    } finally {
      setLoading(false)
    }
  }, [leadId])

  useEffect(() => { loadDemos() }, [loadDemos])

  const pending   = demos.filter(d => d.status === 'pending_assignment')
  const confirmed = demos.filter(d => d.status === 'confirmed')
  const past      = demos.filter(d => !['pending_assignment', 'confirmed'].includes(d.status))

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark, margin: 0 }}>
          📅 Demo Scheduling
        </h3>
        {!showRequestForm && (
          <button
            onClick={() => setShowRequestForm(true)}
            style={{
              background: ds.teal, color: 'white', border: 'none',
              borderRadius: ds.radius.md, padding: '8px 16px',
              fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer',
            }}
          >
            + Request Demo
          </button>
        )}
      </div>

      {error && <p style={{ color: ds.red, fontSize: 13, marginBottom: 12 }}>⚠ {error}</p>}

      {/* Request form */}
      {showRequestForm && (
        <RequestDemoForm
          leadId={leadId}
          leadName={leadName}
          onCreated={(demo) => { setDemos(prev => [demo, ...prev]); setShowRequestForm(false) }}
          onCancel={() => setShowRequestForm(false)}
        />
      )}

      {loading && !showRequestForm && (
        <p style={{ color: ds.gray, fontSize: 13, padding: '16px 0' }}>Loading demos…</p>
      )}

      {/* Pending section */}
      {!loading && pending.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <p style={sectionLabel}>Awaiting Confirmation</p>
          {pending.map(demo => (
            <DemoCard
              key={demo.id}
              demo={demo}
              onConfirm={isManager ? () => setConfirmModal(demo) : null}
            />
          ))}
        </section>
      )}

      {/* Confirmed section */}
      {!loading && confirmed.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <p style={sectionLabel}>Upcoming</p>
          {confirmed.map(demo => (
            <DemoCard
              key={demo.id}
              demo={demo}
              onLogOutcome={() => setOutcomeModal(demo)}
            />
          ))}
        </section>
      )}

      {/* Past section */}
      {!loading && past.length > 0 && (
        <section>
          <p style={sectionLabel}>History</p>
          {past.map(demo => <DemoCard key={demo.id} demo={demo} />)}
        </section>
      )}

      {/* Empty state */}
      {!loading && demos.length === 0 && !showRequestForm && (
        <div style={{
          textAlign: 'center', padding: '32px 20px',
          background: ds.light, borderRadius: ds.radius.lg,
          border: `1.5px dashed ${ds.border}`,
        }}>
          <p style={{ fontSize: 28, marginBottom: 8 }}>📅</p>
          <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, color: ds.dark, fontSize: 14, margin: '0 0 4px' }}>
            No demos yet
          </p>
          <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
            Request a demo to start the scheduling process for {leadName}.
          </p>
        </div>
      )}

      {/* Confirm modal */}
      {confirmModal && (
        <ConfirmDemoModal
          leadId={leadId}
          demo={confirmModal}
          onConfirmed={(updated) => {
            setDemos(prev => prev.map(d => d.id === updated.id ? updated : d))
            setConfirmModal(null)
          }}
          onClose={() => setConfirmModal(null)}
        />
      )}

      {/* Log outcome modal */}
      {outcomeModal && (
        <LogOutcomeModal
          leadId={leadId}
          demo={outcomeModal}
          onLogged={(updated) => {
            setDemos(prev => prev.map(d => d.id === updated.id ? updated : d))
            setOutcomeModal(null)
            if (updated.status === 'rescheduled') loadDemos()
          }}
          onClose={() => setOutcomeModal(null)}
        />
      )}
    </div>
  )
}

// ── Request Demo Form ─────────────────────────────────────────────────────────

function RequestDemoForm({ leadId, leadName, onCreated, onCancel }) {
  const [preferredTime, setPreferredTime] = useState('')
  const [medium, setMedium]               = useState('')
  const [notes, setNotes]                 = useState('')
  const [saving, setSaving]               = useState(false)
  const [formError, setFormError]         = useState(null)

  const handleSubmit = async () => {
    setFormError(null)
    setSaving(true)
    try {
      const res = await createDemoRequest(leadId, {
        lead_preferred_time: preferredTime || undefined,
        medium:              medium || undefined,
        notes:               notes  || undefined,
      })
      if (res.success) onCreated(res.data)
      else setFormError(res.error?.message ?? 'Failed to create demo request')
    } catch (e) {
      setFormError(e?.response?.data?.error?.message ?? 'Failed to create demo request')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      background: '#F0FFF4', border: '1.5px solid #9AE6B4',
      borderRadius: ds.radius.lg, padding: '18px 20px', marginBottom: 20,
    }}>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: ds.dark, margin: '0 0 14px' }}>
        📅 Request Demo — {leadName}
      </p>
      <p style={{ fontSize: 12.5, color: '#276749', margin: '0 0 14px', lineHeight: 1.5 }}>
        Admin will be notified to confirm the date, time, and assign a rep.
      </p>

      {formError && <p style={{ color: ds.red, fontSize: 13, marginBottom: 10 }}>⚠ {formError}</p>}

      <label style={labelStyle}>Lead's Preferred Time (optional)</label>
      <input
        style={inputStyle}
        placeholder="e.g. Monday afternoon, any weekday after 3pm…"
        value={preferredTime}
        onChange={e => setPreferredTime(e.target.value)}
        maxLength={500}
      />

      <label style={labelStyle}>Preferred Medium (optional)</label>
      <select
        value={medium}
        onChange={e => setMedium(e.target.value)}
        style={inputStyle}
      >
        <option value="">— Not specified —</option>
        <option value="virtual">💻 Virtual (Online)</option>
        <option value="in_person">🤝 In Person</option>
      </select>

      <label style={labelStyle}>Notes (optional)</label>
      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Any context for admin or the assigned rep…"
        maxLength={5000}
        rows={2}
        style={{ ...inputStyle, resize: 'vertical', fontFamily: ds.fontDm }}
      />

      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
        <button
          onClick={handleSubmit}
          disabled={saving}
          style={{
            background: saving ? '#9ca3af' : ds.teal, color: 'white',
            border: 'none', borderRadius: ds.radius.md, padding: '9px 18px',
            fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Submitting…' : '✓ Submit Request'}
        </button>
        <button
          onClick={onCancel} disabled={saving}
          style={{
            background: 'white', color: ds.gray, border: `1.5px solid ${ds.border}`,
            borderRadius: ds.radius.md, padding: '9px 18px',
            fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Demo Card ─────────────────────────────────────────────────────────────────

function DemoCard({ demo, onConfirm, onLogOutcome }) {
  const s = STATUS_STYLE[demo.status] ?? STATUS_STYLE.pending_assignment

  return (
    <div style={{
      background: 'white', border: `1px solid ${ds.border}`,
      borderRadius: ds.radius.md, marginBottom: 10,
      overflow: 'hidden',
    }}>
      {/* Main card body */}
      <div style={{ padding: '14px 16px', position: 'relative' }}>
        {/* Status badge */}
        <span style={{
          position: 'absolute', top: 12, right: 14,
          background: s.bg, color: s.color,
          padding: '3px 10px', borderRadius: 20,
          fontSize: 11, fontWeight: 700, fontFamily: ds.fontSyne,
        }}>
          {s.label}
        </span>

        {/* Scheduled time or preferred time */}
        {demo.scheduled_at ? (
          <p style={{ fontSize: 14, fontWeight: 700, color: ds.dark, margin: '0 0 4px', fontFamily: ds.fontSyne }}>
            {fmtDateTime(demo.scheduled_at)}
          </p>
        ) : demo.lead_preferred_time ? (
          <p style={{ fontSize: 13.5, color: ds.dark, margin: '0 0 4px' }}>
            <span style={{ fontWeight: 600 }}>Lead prefers:</span> {demo.lead_preferred_time}
          </p>
        ) : (
          <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 4px', fontStyle: 'italic' }}>
            No time preference noted
          </p>
        )}

        {/* Details row */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', margin: '4px 0 6px', fontSize: 12.5, color: ds.gray }}>
          {demo.duration_minutes && demo.scheduled_at && (
            <span>{demo.duration_minutes} min</span>
          )}
          {demo.medium && (
            <span>{MEDIUM_LABELS[demo.medium] ?? demo.medium}</span>
          )}
          {demo.users?.full_name && (
            <span>👤 {demo.users.full_name}</span>
          )}
        </div>

        {demo.notes && (
          <p style={{ fontSize: 12.5, color: ds.gray, margin: '0 0 6px', lineHeight: 1.5 }}>
            {demo.notes}
          </p>
        )}

        {demo.outcome_notes && (
          <p style={{ fontSize: 12.5, color: ds.gray, margin: '0 0 6px', fontStyle: 'italic' }}>
            "{demo.outcome_notes}"
          </p>
        )}

        {/* Reminder pills — only for confirmed */}
        {demo.status === 'confirmed' && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            <ReminderPill sent={demo.confirmation_sent} label="Confirmed" />
            <ReminderPill sent={demo.reminder_24h_sent} label="24h reminder" />
            <ReminderPill sent={demo.reminder_1h_sent}  label="1h reminder"  />
          </div>
        )}

        {/* Parent demo reference */}
        {demo.parent_demo_id && (
          <p style={{ fontSize: 11, color: ds.gray, margin: '8px 0 0', fontStyle: 'italic' }}>
            Rescheduled from a previous demo
          </p>
        )}

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          {demo.status === 'pending_assignment' && onConfirm && (
            <button
              onClick={onConfirm}
              style={{
                background: ds.teal, color: 'white', border: 'none',
                borderRadius: ds.radius.md, padding: '7px 14px',
                fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer',
              }}
            >
              ✓ Confirm Demo
            </button>
          )}
          {demo.status === 'confirmed' && onLogOutcome && (
            <button
              onClick={onLogOutcome}
              style={{
                background: 'white', color: ds.teal,
                border: `1.5px solid ${ds.teal}`,
                borderRadius: ds.radius.md, padding: '7px 14px',
                fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer',
              }}
            >
              Log Outcome
            </button>
          )}
        </div>
      </div>

      {/* M01-9: AI Recap card — only shown for attended demos with recap data */}
      {demo.status === 'attended' && <RecapCard recap={demo.recap} />}
    </div>
  )
}

// ── M01-9: Recap Card ─────────────────────────────────────────────────────────

function RecapCard({ recap }) {
  const [expanded, setExpanded] = useState(false)

  // recap=null means attended but recap not available (AI failed or notes were thin)
  if (recap === undefined) return null

  if (!recap) {
    return (
      <div style={{
        borderTop: `1px solid ${ds.border}`,
        padding: '10px 16px',
        background: ds.light,
      }}>
        <p style={{ fontSize: 12, color: ds.gray, margin: 0, fontStyle: 'italic' }}>
          🤖 AI recap not available for this demo.
        </p>
      </div>
    )
  }

  const READINESS_COLOR = {
    'Ready to proceed':   { bg: '#F0FFF4', color: '#276749', border: '#9AE6B4' },
    'Needs proposal':     { bg: '#EBF8FF', color: '#2B6CB0', border: '#90CDF4' },
    'Still evaluating':   { bg: '#FFFBEB', color: '#92400E', border: '#F6E05E' },
    'Needs follow-up':    { bg: '#FFF5F5', color: '#C53030', border: '#FEB2B2' },
  }
  const readinessStyle = READINESS_COLOR[recap.lead_readiness] || { bg: ds.light, color: ds.gray, border: ds.border }

  return (
    <div style={{
      borderTop: `1px solid ${ds.border}`,
      background: '#F7FBFF',
    }}>
      {/* Recap header — always visible */}
      <button
        onClick={() => setExpanded(prev => !prev)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 16px', background: 'none', border: 'none',
          cursor: 'pointer', textAlign: 'left',
        }}
      >
        <span style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 12,
          color: '#2B6CB0', display: 'flex', alignItems: 'center', gap: 6,
        }}>
          🤖 AI Demo Recap
          <span style={{
            background: readinessStyle.bg, color: readinessStyle.color,
            border: `1px solid ${readinessStyle.border}`,
            padding: '1px 8px', borderRadius: 20, fontSize: 10.5, fontWeight: 700,
          }}>
            {recap.lead_readiness}
          </span>
        </span>
        <span style={{ fontSize: 12, color: ds.gray }}>
          {expanded ? '▲ Collapse' : '▼ View recap'}
        </span>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div style={{ padding: '0 16px 16px' }}>

          {/* Summary */}
          {recap.summary && (
            <div style={{ marginBottom: 12 }}>
              <p style={recapSectionLabel}>Summary</p>
              <p style={{ fontSize: 13, color: ds.dark, margin: 0, lineHeight: 1.6 }}>
                {recap.summary}
              </p>
            </div>
          )}

          {/* Key interests + concerns — side by side if both present */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
            {recap.key_interests && recap.key_interests.length > 0 && (
              <div style={{ flex: 1, minWidth: 140 }}>
                <p style={recapSectionLabel}>Key Interests</p>
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {recap.key_interests.map((item, i) => (
                    <li key={i} style={{ fontSize: 12.5, color: ds.dark, marginBottom: 3, lineHeight: 1.5 }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {recap.concerns_raised && recap.concerns_raised.length > 0 && (
              <div style={{ flex: 1, minWidth: 140 }}>
                <p style={recapSectionLabel}>Concerns Raised</p>
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {recap.concerns_raised.map((item, i) => (
                    <li key={i} style={{ fontSize: 12.5, color: '#C53030', marginBottom: 3, lineHeight: 1.5 }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Recommended next action */}
          {recap.recommended_next_action && (
            <div style={{
              background: '#EBF8FF', border: '1px solid #90CDF4',
              borderRadius: ds.radius.md, padding: '10px 12px',
            }}>
              <p style={{ ...recapSectionLabel, color: '#2B6CB0', marginBottom: 4 }}>
                💡 Recommended Next Action
              </p>
              <p style={{ fontSize: 13, color: '#2B6CB0', margin: 0, fontWeight: 600, lineHeight: 1.5 }}>
                {recap.recommended_next_action}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ReminderPill({ sent, label }) {
  return (
    <span style={{
      background: sent ? '#F0FFF4' : ds.light,
      color:      sent ? '#276749' : ds.gray,
      border:     `1px solid ${sent ? '#9AE6B4' : ds.border}`,
      padding: '2px 8px', borderRadius: 20, fontSize: 10.5, fontWeight: 600,
    }}>
      {sent ? '✓' : '○'} {label}
    </span>
  )
}

// ── Confirm Demo Modal ────────────────────────────────────────────────────────

function ConfirmDemoModal({ leadId, demo, onConfirmed, onClose }) {
  const [scheduledAt, setScheduledAt] = useState('')
  const [medium, setMedium]           = useState(demo.medium || '')
  const [assignedTo, setAssignedTo]   = useState(demo.assigned_to || '')
  const [duration, setDuration]       = useState(demo.duration_minutes || 30)
  const [notes, setNotes]             = useState(demo.notes || '')
  const [saving, setSaving]           = useState(false)
  const [formError, setFormError]     = useState(null)

  const handleSubmit = async () => {
    if (!scheduledAt) { setFormError('Please select a date and time.'); return }
    if (!medium)      { setFormError('Please select a medium.'); return }
    if (!assignedTo)  { setFormError('Please assign a rep.'); return }
    setFormError(null)
    setSaving(true)
    try {
      const isoScheduled = new Date(scheduledAt).toISOString()
      const res = await confirmDemo(leadId, demo.id, {
        scheduled_at:     isoScheduled,
        medium,
        assigned_to:      assignedTo,
        duration_minutes: duration,
        notes:            notes || undefined,
      })
      if (res.success) onConfirmed(res.data)
      else setFormError(res.error?.message ?? 'Failed to confirm demo')
    } catch (e) {
      setFormError(e?.response?.data?.error?.message ?? 'Failed to confirm demo')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="✓ Confirm Demo" onClose={onClose}>
      {demo.lead_preferred_time && (
        <div style={{
          background: '#FFFBEB', border: '1px solid #F6E05E',
          borderRadius: 8, padding: '10px 12px', marginBottom: 14, fontSize: 13,
        }}>
          <strong>Lead's preference:</strong> {demo.lead_preferred_time}
        </div>
      )}

      {formError && <p style={{ color: ds.red, fontSize: 13, marginBottom: 10 }}>⚠ {formError}</p>}

      <label style={labelStyle}>Date & Time *</label>
      <input
        type="datetime-local"
        value={scheduledAt}
        onChange={e => setScheduledAt(e.target.value)}
        style={inputStyle}
      />

      <label style={labelStyle}>Medium *</label>
      <select value={medium} onChange={e => setMedium(e.target.value)} style={inputStyle}>
        <option value="">— Select —</option>
        <option value="virtual">💻 Virtual (Online)</option>
        <option value="in_person">🤝 In Person</option>
      </select>

      <label style={labelStyle}>Assign Rep *</label>
      <div style={{ marginBottom: 12 }}>
        <UserSelect value={assignedTo} onChange={setAssignedTo} placeholder="— Select rep —" />
      </div>

      <label style={labelStyle}>Duration</label>
      <select value={duration} onChange={e => setDuration(Number(e.target.value))} style={inputStyle}>
        {[15, 30, 45, 60, 90, 120].map(m => (
          <option key={m} value={m}>{m} minutes</option>
        ))}
      </select>

      <label style={labelStyle}>Notes (optional)</label>
      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Agenda, topics to cover…"
        maxLength={5000} rows={2}
        style={{ ...inputStyle, resize: 'vertical', fontFamily: ds.fontDm }}
      />

      <p style={{ fontSize: 12, color: '#276749', margin: '0 0 14px', lineHeight: 1.5 }}>
        ℹ️ A WhatsApp confirmation will be sent automatically to the lead once confirmed.
        The rep will receive an in-app notification only.
      </p>

      <ModalActions
        onConfirm={handleSubmit}
        onCancel={onClose}
        saving={saving}
        confirmLabel="✓ Confirm & Notify Lead"
      />
    </Modal>
  )
}

// ── Log Outcome Modal — M01-9: upgraded notes field for attended ──────────────

function LogOutcomeModal({ leadId, demo, onLogged, onClose }) {
  const [outcome, setOutcome]       = useState('')
  const [outcomeNotes, setNotes]    = useState('')
  const [saving, setSaving]         = useState(false)
  const [formError, setFormError]   = useState(null)

  const isAttended = outcome === 'attended'

  const OUTCOMES = [
    {
      value: 'attended',
      label: '🎉 Attended',
      desc: 'Demo took place. Pipeline will auto-advance to Demo Done.',
    },
    {
      value: 'no_show',
      label: '❌ No-show',
      desc: 'Lead did not attend. Follow-up task created + rescheduling message sent.',
    },
    {
      value: 'rescheduled',
      label: '🔄 Rescheduled',
      desc: 'A new demo request will be created for admin to confirm a new time.',
    },
  ]

  const handleSubmit = async () => {
    if (!outcome) { setFormError('Please select an outcome.'); return }
    setFormError(null)
    setSaving(true)
    try {
      const res = await logDemoOutcome(leadId, demo.id, {
        outcome,
        outcome_notes: outcomeNotes || undefined,
      })
      if (res.success) onLogged(res.data)
      else setFormError(res.error?.message ?? 'Failed to log outcome')
    } catch (e) {
      setFormError(e?.response?.data?.error?.message ?? 'Failed to log outcome')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Log Demo Outcome" onClose={onClose}>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 16px' }}>
        {fmtDateTime(demo.scheduled_at)}
      </p>

      {formError && <p style={{ color: ds.red, fontSize: 13, marginBottom: 10 }}>⚠ {formError}</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
        {OUTCOMES.map(o => (
          <label
            key={o.value}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              padding: '10px 12px', borderRadius: ds.radius.md,
              border: `1.5px solid ${outcome === o.value ? ds.teal : ds.border}`,
              background: outcome === o.value ? ds.mint : 'white',
              cursor: 'pointer', transition: 'all 0.15s',
            }}
          >
            <input
              type="radio" name="outcome" value={o.value}
              checked={outcome === o.value}
              onChange={() => setOutcome(o.value)}
              style={{ marginTop: 2, accentColor: ds.teal, flexShrink: 0 }}
            />
            <div>
              <p style={{ fontSize: 13.5, fontWeight: 600, color: ds.dark, margin: '0 0 2px', fontFamily: ds.fontSyne }}>
                {o.label}
              </p>
              <p style={{ fontSize: 12, color: ds.gray, margin: 0 }}>{o.desc}</p>
            </div>
          </label>
        ))}
      </div>

      {/* M01-9: Contextual notes section — prominent for attended, plain for others */}
      {isAttended ? (
        <div style={{
          background: '#F0F7FF', border: '1.5px solid #90CDF4',
          borderRadius: ds.radius.md, padding: '12px 14px', marginBottom: 14,
        }}>
          <p style={{
            fontSize: 11, fontWeight: 700, color: '#2B6CB0',
            textTransform: 'uppercase', letterSpacing: '0.5px', margin: '0 0 6px',
          }}>
            🤖 Post-Demo Notes — Used for AI Recap
          </p>
          <p style={{ fontSize: 12, color: '#2B6CB0', margin: '0 0 10px', lineHeight: 1.5 }}>
            The more detail you add, the better the AI recap. What did the lead engage with?
            Any concerns raised? What are the next steps?
          </p>
          <textarea
            value={outcomeNotes}
            onChange={e => setNotes(e.target.value)}
            placeholder="e.g. Lead was very interested in the automation features. Concerned about pricing — needs to check with MD. Agreed to send a proposal by Friday…"
            maxLength={5000}
            rows={4}
            style={{
              width: '100%', padding: '9px 12px',
              border: `1.5px solid #90CDF4`, borderRadius: ds.radius.md,
              fontSize: 13, color: ds.dark, fontFamily: ds.fontDm,
              background: 'white', outline: 'none',
              resize: 'vertical', boxSizing: 'border-box',
            }}
          />
          <p style={{ fontSize: 11, color: '#2B6CB0', margin: '4px 0 0', textAlign: 'right' }}>
            {outcomeNotes.length}/5000
          </p>
        </div>
      ) : (
        <>
          <label style={labelStyle}>Notes (optional)</label>
          <textarea
            value={outcomeNotes}
            onChange={e => setNotes(e.target.value)}
            placeholder="What was discussed, next steps…"
            maxLength={5000} rows={2}
            style={{ ...inputStyle, resize: 'vertical', fontFamily: ds.fontDm }}
          />
        </>
      )}

      <ModalActions
        onConfirm={handleSubmit}
        onCancel={onClose}
        saving={saving}
        disabled={!outcome}
        confirmLabel={isAttended ? '✓ Log & Generate Recap' : '✓ Log Outcome'}
      />
    </Modal>
  )
}

// ── Shared modal wrapper ──────────────────────────────────────────────────────

function Modal({ title, onClose, children }) {
  return (
    <>
      <div onClick={onClose} style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100,
      }} />
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        background: 'white', borderRadius: ds.radius.xl,
        padding: '28px 28px 24px',
        width: 'min(460px, 94vw)', zIndex: 101,
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
        maxHeight: '90vh', overflowY: 'auto',
      }}>
        <h3 style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16,
          color: ds.dark, margin: '0 0 16px',
        }}>
          {title}
        </h3>
        {children}
      </div>
    </>
  )
}

function ModalActions({ onConfirm, onCancel, saving, disabled, confirmLabel = 'Confirm' }) {
  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
      <button
        onClick={onConfirm}
        disabled={saving || disabled}
        style={{
          background: (saving || disabled) ? '#9ca3af' : ds.teal,
          color: 'white', border: 'none',
          borderRadius: ds.radius.md, padding: '9px 18px',
          fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne,
          cursor: (saving || disabled) ? 'not-allowed' : 'pointer', flex: 1,
        }}
      >
        {saving ? 'Saving…' : confirmLabel}
      </button>
      <button
        onClick={onCancel} disabled={saving}
        style={{
          background: 'white', color: ds.gray, border: `1.5px solid ${ds.border}`,
          borderRadius: ds.radius.md, padding: '9px 18px',
          fontSize: 13, fontWeight: 600, cursor: 'pointer',
        }}
      >
        Cancel
      </button>
    </div>
  )
}

// ── Style helpers ─────────────────────────────────────────────────────────────

const labelStyle = {
  display: 'block', fontSize: 11, fontWeight: 600, color: ds.gray,
  textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 5,
}

const inputStyle = {
  width: '100%', padding: '9px 12px',
  border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
  fontSize: 13.5, color: ds.dark, fontFamily: 'inherit',
  background: 'white', outline: 'none', marginBottom: 12,
  boxSizing: 'border-box',
}

const sectionLabel = {
  fontSize: 11, fontWeight: 600, color: ds.teal,
  textTransform: 'uppercase', letterSpacing: '0.8px',
  margin: '0 0 8px',
}

const recapSectionLabel = {
  fontSize: 10.5, fontWeight: 700, color: ds.gray,
  textTransform: 'uppercase', letterSpacing: '0.5px',
  margin: '0 0 6px',
}
