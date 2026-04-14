/**
 * LeadTasks
 *
 * Calls GET /api/v1/leads/{id}/tasks and renders the task list.
 *
 * Fix (post M01-9): replaced read-only inline card with the real TaskCard
 * component so reps and managers can mark tasks complete directly from the
 * lead profile. Completion updates local state immediately (optimistic update)
 * so the status reflects as "completed" without a page reload.
 *
 * Layout:
 *   Active tasks (pending / in_progress / snoozed) — shown first
 *   Completed tasks — collapsed section at the bottom, togglable
 */
import { useState, useEffect, useCallback } from 'react'
import { getLeadTasks } from '../../services/leads.service'
import TaskCard from '../tasks/TaskCard'
import { ds } from '../../utils/ds'

export default function LeadTasks({ leadId }) {
  const [tasks, setTasks]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [actionError, setActionError] = useState(null)
  const [showCompleted, setShowCompleted] = useState(false)

  const loadTasks = useCallback(() => {
    if (!leadId) return
    setLoading(true)
    setError(null)

    getLeadTasks(leadId)
      .then((res) => {
        if (res.success) setTasks(res.data ?? [])
        else setError(res.error ?? 'Failed to load tasks')
      })
      .catch((err) => {
        setError(err?.response?.data?.error ?? 'Failed to load tasks')
      })
      .finally(() => setLoading(false))
  }, [leadId])

  useEffect(() => { loadTasks() }, [loadTasks])

  // Optimistic update — mark task as completed in local state immediately.
  // The server has already written completed_at; we just reflect it in the UI.
  const handleComplete = (taskId) => {
    setTasks(prev => prev.map(t =>
      t.id === taskId
        ? { ...t, status: 'completed', completed_at: new Date().toISOString() }
        : t
    ))
    setActionError(null)
  }

  const handleSnooze = (taskId) => {
    // Reload to get the updated snoozed_until value from the server
    loadTasks()
  }

  const handleReassigned = (taskId) => {
    loadTasks()
  }

  const activeTasks    = tasks.filter(t => (t.status || '').toLowerCase() !== 'completed')
  const completedTasks = tasks.filter(t => (t.status || '').toLowerCase() === 'completed')

  if (loading) return <Skeleton />

  if (error) return (
    <p style={{ color: ds.red, fontSize: 13 }}>⚠ {error}</p>
  )

  if (!tasks.length) return (
    <p style={{ color: ds.gray, fontSize: 13, fontStyle: 'italic' }}>
      No tasks linked to this lead yet.
    </p>
  )

  return (
    <div>
      {actionError && (
        <p style={{ color: ds.red, fontSize: 13, marginBottom: 10 }}>⚠ {actionError}</p>
      )}

      {/* ── Active tasks ─────────────────────────────────────────────── */}
      {activeTasks.length === 0 ? (
        <p style={{ color: ds.gray, fontSize: 13, fontStyle: 'italic', marginBottom: 12 }}>
          All tasks completed. ✅
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {activeTasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              onComplete={handleComplete}
              onSnooze={handleSnooze}
              onReassigned={handleReassigned}
              onError={setActionError}
            />
          ))}
        </div>
      )}

      {/* ── Completed tasks — collapsible ────────────────────────────── */}
      {completedTasks.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button
            onClick={() => setShowCompleted(prev => !prev)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 12, fontWeight: 600, color: ds.gray,
              fontFamily: ds.fontSyne, padding: '4px 0', marginBottom: 8,
            }}
          >
            <span style={{
              background: '#E8F8EE', color: '#276749',
              borderRadius: 20, padding: '2px 8px', fontSize: 11,
            }}>
              ✓ {completedTasks.length} completed
            </span>
            <span style={{ fontSize: 10 }}>{showCompleted ? '▲ Hide' : '▼ Show'}</span>
          </button>

          {showCompleted && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, opacity: 0.8 }}>
              {completedTasks.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onComplete={handleComplete}
                  onSnooze={handleSnooze}
                  onReassigned={handleReassigned}
                  onError={setActionError}
                />
              ))}
            </div>
          )}
        </div>
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
