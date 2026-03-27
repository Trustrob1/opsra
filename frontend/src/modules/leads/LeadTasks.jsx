/**
 * LeadTasks
 *
 * Calls GET /api/v1/leads/{id}/tasks and renders the task list.
 * Task fields come from the tasks table schema in Technical Spec §3.x.
 * Tasks are read-only in Phase 2B — creation is handled via the backend
 * (AI-recommended tasks are created server-side; manual task creation
 * is scoped to Phase 6B in the Unified Task Management build).
 */
import { useState, useEffect } from 'react'
import { getLeadTasks } from '../../services/leads.service'
import { ds } from '../../utils/ds'

const STATUS_STYLE = {
  pending:     { bg: '#FFF9E0', color: '#A07C00', label: 'Pending' },
  in_progress: { bg: '#E8F0FF', color: '#3450A4', label: 'In Progress' },
  done:        { bg: '#E8F8EE', color: '#1A7A40', label: 'Done' },
  overdue:     { bg: '#FFE8E8', color: '#C0392B', label: 'Overdue' },
  cancelled:   { bg: '#F0F0F0', color: '#9E9E9E', label: 'Cancelled' },
}

export default function LeadTasks({ leadId }) {
  const [tasks, setTasks]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    if (!leadId) return
    let cancelled = false
    setLoading(true)
    setError(null)

    getLeadTasks(leadId)
      .then((res) => {
        if (cancelled) return
        if (res.success) setTasks(res.data ?? [])
        else setError(res.error ?? 'Failed to load tasks')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err?.response?.data?.error ?? 'Failed to load tasks')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [leadId])

  if (loading) return <Skeleton />
  if (error)   return <p style={{ color: ds.red, fontSize: 13 }}>⚠ {error}</p>
  if (!tasks.length) return (
    <p style={{ color: ds.gray, fontSize: 13, fontStyle: 'italic' }}>
      No tasks linked to this lead yet.
    </p>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {tasks.map((task, i) => <TaskCard key={task.id ?? i} task={task} />)}
    </div>
  )
}

function TaskCard({ task }) {
  const statusStyle = STATUS_STYLE[task.status] ?? STATUS_STYLE.pending
  const dueDate     = task.due_date ? new Date(task.due_date) : null
  const dueDateStr  = dueDate
    ? dueDate.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : null
  const isOverdue   = dueDate && dueDate < new Date() && task.status !== 'done' && task.status !== 'cancelled'

  return (
    <div style={{
      background:   'white',
      border:       `1px solid ${ds.border}`,
      borderLeft:   `3px solid ${isOverdue ? ds.red : ds.teal}`,
      borderRadius: 10,
      padding:      '14px 16px',
      boxShadow:    '0 1px 4px rgba(0,0,0,0.05)',
    }}>
      {/* Title + status */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 6 }}>
        <p style={{ fontWeight: 600, fontSize: 13.5, color: ds.dark, margin: 0, lineHeight: 1.4 }}>
          {task.title ?? task.description ?? 'Untitled task'}
        </p>
        <span style={{
          background:   statusStyle.bg,
          color:        statusStyle.color,
          padding:      '3px 10px',
          borderRadius: 20,
          fontSize:     11,
          fontWeight:   600,
          fontFamily:   ds.fontSyne,
          flexShrink:   0,
        }}>
          {statusStyle.label}
        </span>
      </div>

      {/* Meta row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 11.5, color: ds.gray }}>
        {dueDateStr && (
          <span style={{ color: isOverdue ? ds.red : ds.gray }}>
            📅 {isOverdue ? '⚠ Overdue — ' : ''}{dueDateStr}
          </span>
        )}
        {task.assigned_to_name && (
          <span>👤 {task.assigned_to_name}</span>
        )}
        {task.source === 'ai' && (
          <span style={{
            background: '#FFF3E0',
            color:      '#8B4513',
            padding:    '2px 7px',
            borderRadius: 10,
            fontSize:   10,
            fontWeight: 600,
          }}>
            AI Recommended
          </span>
        )}
      </div>

      {/* Notes / description */}
      {task.notes && (
        <p style={{ marginTop: 8, fontSize: 12.5, color: ds.gray, lineHeight: 1.5, margin: '8px 0 0' }}>
          {task.notes}
        </p>
      )}
    </div>
  )
}

function Skeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {[1, 2].map((n) => (
        <div key={n} style={{
          background: 'white', border: `1px solid ${ds.border}`,
          borderLeft: `3px solid ${ds.border}`, borderRadius: 10, padding: '14px 16px',
        }}>
          <div style={{ height: 14, background: ds.border, borderRadius: 4, width: '60%', marginBottom: 8 }} />
          <div style={{ height: 11, background: ds.border, borderRadius: 4, width: '30%' }} />
        </div>
      ))}
    </div>
  )
}
