/**
 * modules/tasks/TaskCard.jsx
 * Individual task card — Phase 7B.
 *
 * Props:
 *   task       — task object from API
 *   onComplete(id, notes) — callback after successful complete
 *   onSnooze(id, until)   — callback after successful snooze
 *   onError(msg)          — callback on action error
 *
 * Inline actions (no modal needed for these common operations):
 *   ✓ Mark Complete → expands notes textarea → Confirm / Cancel
 *   💤 Snooze       → expands date input     → Confirm / Cancel
 *
 * Priority badge colours: critical=red, high=amber, medium=blue, low=gray
 * Source module colours:  leads=blue, whatsapp=green, support=amber,
 *                         renewal=teal, ops=dark
 * task_type badge: 🤖 AI Recommended / 📋 System Event / (manual = no badge)
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import { completeTask, snoozeTask, updateTask } from '../../services/tasks.service'
import useAuthStore from '../../store/authStore'
import UserSelect   from '../../shared/UserSelect'

// ── Design tokens ─────────────────────────────────────────────────────────────

const PRIORITY_STYLES = {
  critical: { bg: '#fef2f2', color: '#dc2626', border: '#fca5a5' },
  high:     { bg: '#fffbeb', color: '#d97706', border: '#fcd34d' },
  medium:   { bg: '#eff6ff', color: '#2563eb', border: '#93c5fd' },
  low:      { bg: '#f9fafb', color: '#6b7280', border: '#d1d5db' },
}

const MODULE_STYLES = {
  leads:    { bg: '#eff6ff', color: '#2563eb' },
  whatsapp: { bg: '#f0fdf4', color: '#16a34a' },
  support:  { bg: '#fffbeb', color: '#d97706' },
  renewal:  { bg: '#f0fdfa', color: '#0d9488' },
  ops:      { bg: '#f1f5f9', color: '#475569' },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function isOverdue(task) {
  if (!task.due_at) return false
  const status = (task.status || 'open').toLowerCase()
  if (status === 'completed' || status === 'snoozed') return false
  return task.due_at < new Date().toISOString()
}

function fmtDueDate(due_at) {
  if (!due_at) return null
  const d = new Date(due_at)
  const now = new Date()
  const diffMs = d - now
  const diffDays = Math.ceil(diffMs / 86400000)

  if (diffDays < 0) {
    const absDays = Math.abs(diffDays)
    return absDays === 1 ? 'Yesterday' : `${absDays}d overdue`
  }
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Tomorrow'
  if (diffDays <= 7)  return `${diffDays}d left`
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

// Tomorrow's date as YYYY-MM-DD for snooze default
function tomorrowDate() {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().split('T')[0]
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PriorityBadge({ priority }) {
  const s = PRIORITY_STYLES[(priority || 'medium').toLowerCase()] || PRIORITY_STYLES.medium
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne,
      padding: '2px 8px', borderRadius: 10,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      textTransform: 'uppercase', letterSpacing: '0.5px',
    }}>
      {priority || 'medium'}
    </span>
  )
}

function ModuleBadge({ module: mod }) {
  if (!mod) return null
  const s = MODULE_STYLES[mod] || { bg: '#f1f5f9', color: '#475569' }
  const labels = { leads: 'Leads', whatsapp: 'WhatsApp', support: 'Support', renewal: 'Renewal', ops: 'Ops Intel' }
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, fontFamily: ds.fontDm,
      padding: '2px 8px', borderRadius: 10,
      background: s.bg, color: s.color,
    }}>
      {labels[mod] || mod}
    </span>
  )
}

function TypeBadge({ taskType }) {
  if (taskType === 'ai_recommended') {
    return (
      <span style={{ fontSize: 10, color: '#7c3aed', fontWeight: 600 }}>
        🤖 AI Recommended
      </span>
    )
  }
  if (taskType === 'system_event') {
    return (
      <span style={{ fontSize: 10, color: '#64748b', fontWeight: 600 }}>
        📋 System Event
      </span>
    )
  }
  return null
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TaskCard({ task, onComplete, onSnooze, onError, onReassigned }) {
  const isManager = useAuthStore.getState().isManager()
  const [mode,        setMode]        = useState(null)   // null | 'completing' | 'snoozing' | 'reassigning'
  const [notes,       setNotes]       = useState('')
  const [snoozeDate,  setSnoozeDate]  = useState(tomorrowDate)
  const [newAssignee, setNewAssignee] = useState('')
  const [submitting,  setSubmitting]  = useState(false)

  const overdue = isOverdue(task)
  const dueLabel = fmtDueDate(task.due_at)
  const isCompleted = (task.status || '').toLowerCase() === 'completed'
  const isSnoozed   = (task.status || '').toLowerCase() === 'snoozed'

  const handleComplete = async () => {
    setSubmitting(true)
    try {
      await completeTask(task.id, notes || null)
      setMode(null)
      setNotes('')
      onComplete?.(task.id)
    } catch {
      onError?.('Failed to complete task. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSnooze = async () => {
    setSubmitting(true)
    try {
      const iso = new Date(`${snoozeDate}T09:00:00`).toISOString()
      await snoozeTask(task.id, iso)
      setMode(null)
      onSnooze?.(task.id)
    } catch {
      onError?.('Failed to snooze task. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReassign = async () => {
    if (!newAssignee) return
    setSubmitting(true)
    try {
      await updateTask(task.id, { assigned_to: newAssignee })
      setMode(null); setNewAssignee('')
      onReassigned?.(task.id)
    } catch {
      onError?.('Failed to reassign task. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const cancel = () => { setMode(null); setNotes(''); setNewAssignee('') }

  return (
    <div style={{
      background:   'white',
      border:       '1px solid #e5e7eb',
      borderLeft:   overdue ? '3px solid #dc2626'
                  : isSnoozed ? '3px solid #a855f7'
                  : isCompleted ? '3px solid #16a34a'
                  : '1px solid #e5e7eb',
      borderRadius: 10,
      padding:      '14px 16px',
      marginBottom: 10,
      opacity:      isCompleted ? 0.65 : 1,
      transition:   'box-shadow 0.15s',
    }}
    onMouseEnter={e => { if (!isCompleted) e.currentTarget.style.boxShadow = '0 2px 8px rgba(2,128,144,0.1)' }}
    onMouseLeave={e => { e.currentTarget.style.boxShadow = 'none' }}
    >
      {/* ── Header row ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
        <p style={{
          fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13.5,
          color: ds.dark, margin: 0, lineHeight: 1.4, flex: 1,
          textDecoration: isCompleted ? 'line-through' : 'none',
        }}>
          {task.title}
        </p>
        {dueLabel && (
          <span style={{
            fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap', flexShrink: 0,
            color: overdue ? '#dc2626' : isSnoozed ? '#a855f7' : '#6b7280',
          }}>
            {isSnoozed ? `💤 Snoozed` : dueLabel}
          </span>
        )}
      </div>

      {/* ── Meta row ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: mode ? 10 : 0 }}>
        <PriorityBadge priority={task.priority} />
        <ModuleBadge module={task.source_module} />
        <TypeBadge taskType={task.task_type} />
        {task.assigned_user?.full_name && (
          <span style={{ fontSize: 10, color: '#6b7280', marginLeft: 'auto' }}>
            → {task.assigned_user.full_name}
          </span>
        )}
      </div>

      {/* ── Inline complete form ── */}
      {mode === 'completing' && (
        <div style={{ marginTop: 10, borderTop: '1px solid #f3f4f6', paddingTop: 10 }}>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Completion notes (optional)…"
            rows={2}
            style={{
              width: '100%', border: '1px solid #d1d5db', borderRadius: 7,
              padding: '8px 10px', fontSize: 13, fontFamily: ds.fontDm,
              resize: 'none', outline: 'none', boxSizing: 'border-box',
              marginBottom: 8,
            }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleComplete} disabled={submitting} style={btnPrimary}>
              {submitting ? 'Completing…' : '✓ Confirm Complete'}
            </button>
            <button onClick={cancel} style={btnGhost}>Cancel</button>
          </div>
        </div>
      )}

      {/* ── Inline snooze form ── */}
      {mode === 'snoozing' && (
        <div style={{ marginTop: 10, borderTop: '1px solid #f3f4f6', paddingTop: 10 }}>
          <p style={{ fontSize: 12, color: '#6b7280', margin: '0 0 6px' }}>Snooze until:</p>
          <input
            type="date"
            value={snoozeDate}
            onChange={e => setSnoozeDate(e.target.value)}
            min={tomorrowDate()}
            style={{
              border: '1px solid #d1d5db', borderRadius: 7,
              padding: '7px 10px', fontSize: 13, fontFamily: ds.fontDm,
              marginBottom: 8, outline: 'none', cursor: 'pointer',
            }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleSnooze} disabled={submitting} style={btnSecondary}>
              {submitting ? 'Snoozing…' : '💤 Confirm Snooze'}
            </button>
            <button onClick={cancel} style={btnGhost}>Cancel</button>
          </div>
        </div>
      )}

      {/* ── Inline reassign form (managers only) ── */}
      {mode === 'reassigning' && (
        <div style={{ marginTop: 10, borderTop: '1px solid #f3f4f6', paddingTop: 10 }}>
          <p style={{ fontSize: 12, color: '#6b7280', margin: '0 0 6px' }}>Reassign to:</p>
          <UserSelect
            value={newAssignee}
            onChange={setNewAssignee}
            placeholder="— Select user —"
            style={{
              border: '1px solid #d1d5db', borderRadius: 7,
              padding: '7px 10px', fontSize: 13, fontFamily: ds.fontDm,
              width: '100%', boxSizing: 'border-box', marginBottom: 8,
            }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleReassign}
              disabled={submitting || !newAssignee}
              style={{ ...(newAssignee ? btnPrimary : btnGhost) }}
            >
              {submitting ? 'Reassigning…' : '↔ Confirm Reassign'}
            </button>
            <button onClick={cancel} style={btnGhost}>Cancel</button>
          </div>
        </div>
      )}

      {/* ── Action buttons (hidden when inline form open or task done) ── */}
      {mode === null && !isCompleted && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button onClick={() => setMode('completing')} style={btnPrimary}>
            ✓ Complete
          </button>
          {!isSnoozed && (
            <button onClick={() => setMode('snoozing')} style={btnGhost}>
              💤 Snooze
            </button>
          )}
        {isManager && (
            <button onClick={() => setMode('reassigning')} style={btnGhost}>
              ↔ Reassign
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Button styles ─────────────────────────────────────────────────────────────

const btnPrimary = {
  background: ds.teal, color: 'white', border: 'none',
  borderRadius: 7, padding: '7px 14px', fontSize: 12,
  fontWeight: 600, fontFamily: ds.fontDm, cursor: 'pointer',
}

const btnSecondary = {
  background: '#f0fdf4', color: '#16a34a',
  border: '1px solid #86efac',
  borderRadius: 7, padding: '7px 14px', fontSize: 12,
  fontWeight: 600, fontFamily: ds.fontDm, cursor: 'pointer',
}

const btnGhost = {
  background: 'none', color: '#6b7280',
  border: '1px solid #e5e7eb',
  borderRadius: 7, padding: '7px 12px', fontSize: 12,
  fontFamily: ds.fontDm, cursor: 'pointer',
}
