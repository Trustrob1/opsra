/**
 * modules/tasks/TaskList.jsx
 * Grouped task list — Phase 7B.
 *
 * Props:
 *   tasks      — array of task objects
 *   loading    — bool
 *   error      — string or null
 *   teamView   — bool: whether team tab is active (shows filter bar)
 *   filters    — current filter state from useTasks
 *   applyFilters(newFilters) — update filters
 *   onRefresh() — re-fetch callback
 *   onActionDone() — called after complete/snooze to refresh list
 *
 * Groups (rendered in order, hidden if empty):
 *   🔴 Overdue        — due_at < now, status not completed/snoozed
 *   📅 Today          — due_at is today
 *   📆 This Week      — due_at within next 7 days (not today)
 *   🔮 Upcoming       — due_at > 7 days
 *   📌 No Due Date    — due_at null, not completed/snoozed
 *   💤 Snoozed        — status = snoozed
 *
 * Pattern 26 does NOT apply here — groups are sections within a single
 * rendered list, not tabs. All visible at once, scroll to see them.
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import TaskCard from './TaskCard'

// ── Grouping logic ────────────────────────────────────────────────────────────

function groupTasks(tasks) {
  const now  = new Date()
  const todayStr = now.toISOString().split('T')[0]
  const in7  = new Date(now.getTime() + 7 * 86400000).toISOString()

  const groups = {
    overdue:   [],
    today:     [],
    thisWeek:  [],
    upcoming:  [],
    noDueDate: [],
    snoozed:   [],
  }

  for (const task of tasks) {
    const status = (task.status || 'open').toLowerCase()
    if (status === 'completed') continue   // completed tasks fetched separately
    if (status === 'snoozed')  { groups.snoozed.push(task); continue }

    const due = task.due_at
    if (!due) { groups.noDueDate.push(task); continue }

    if (due < now.toISOString())  { groups.overdue.push(task);  continue }
    if (due.startsWith(todayStr)) { groups.today.push(task);    continue }
    if (due <= in7)               { groups.thisWeek.push(task); continue }
    groups.upcoming.push(task)
  }

  return groups
}

const GROUP_META = [
  { key: 'overdue',   label: '🔴 Overdue',      accent: '#dc2626' },
  { key: 'today',     label: '📅 Today',         accent: '#d97706' },
  { key: 'thisWeek',  label: '📆 This Week',     accent: '#2563eb' },
  { key: 'upcoming',  label: '🔮 Upcoming',      accent: '#6b7280' },
  { key: 'noDueDate', label: '📌 No Due Date',   accent: '#9ca3af' },
  { key: 'snoozed',   label: '💤 Snoozed',       accent: '#a855f7' },
]

// ── Filter bar (team view only) ───────────────────────────────────────────────

function FilterBar({ filters, applyFilters }) {
  const [local, setLocal] = useState(filters)

  const apply = () => applyFilters(local)
  const clear = () => {
    const empty = { priority: '', status: '', module: '' }
    setLocal(empty)
    applyFilters(empty)
  }

  return (
    <div style={{
      display: 'flex', gap: 10, flexWrap: 'wrap',
      alignItems: 'flex-end', marginBottom: 20,
      padding: '14px 16px', background: '#f9fafb',
      border: '1px solid #e5e7eb', borderRadius: 10,
    }}>
      {[
        { label: 'Priority', key: 'priority', opts: ['', 'critical', 'high', 'medium', 'low'] },
        { label: 'Status',   key: 'status',   opts: ['', 'open', 'in_progress', 'snoozed'] },
        { label: 'Module',   key: 'module',   opts: ['', 'leads', 'whatsapp', 'support', 'renewal', 'ops'] },
      ].map(({ label, key, opts }) => (
        <div key={key}>
          <p style={{ fontSize: 10, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.6px', margin: '0 0 4px' }}>
            {label}
          </p>
          <select
            value={local[key]}
            onChange={e => setLocal(prev => ({ ...prev, [key]: e.target.value }))}
            style={{
              border: '1px solid #d1d5db', borderRadius: 7,
              padding: '7px 10px', fontSize: 12.5,
              fontFamily: ds.fontDm, color: ds.dark,
              background: 'white', cursor: 'pointer', outline: 'none',
            }}
          >
            {opts.map(o => (
              <option key={o} value={o}>
                {o ? (o.charAt(0).toUpperCase() + o.slice(1)) : `All ${label}s`}
              </option>
            ))}
          </select>
        </div>
      ))}
      <button onClick={apply} style={{ alignSelf: 'flex-end', background: ds.teal, color: 'white', border: 'none', borderRadius: 7, padding: '8px 16px', fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontDm, cursor: 'pointer' }}>
        Apply
      </button>
      <button onClick={clear} style={{ alignSelf: 'flex-end', background: 'none', border: '1px solid #d1d5db', borderRadius: 7, padding: '8px 12px', fontSize: 12.5, color: '#6b7280', fontFamily: ds.fontDm, cursor: 'pointer' }}>
        Clear
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TaskList({ tasks, loading, error, teamView, filters, applyFilters, onRefresh, onActionDone }) {
  const [actionError, setActionError] = useState(null)

  const groups = groupTasks(tasks)
  const totalVisible = Object.values(groups).flat().length

  if (loading) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center', color: '#9ca3af' }}>
        <div style={{ width: 28, height: 28, border: `3px solid #e5e7eb`, borderTopColor: ds.teal, borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto 12px' }} />
        <p style={{ fontSize: 13 }}>Loading tasks…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '20px 0' }}>
        <p style={{ fontSize: 13, color: '#dc2626' }}>⚠ {error}</p>
        <button onClick={onRefresh} style={{ fontSize: 13, color: ds.teal, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>Retry</button>
      </div>
    )
  }

  return (
    <div>
      {teamView && (
        <FilterBar filters={filters} applyFilters={applyFilters} />
      )}

      {actionError && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#dc2626', marginBottom: 16 }}>
          ⚠ {actionError}
          <button onClick={() => setActionError(null)} style={{ marginLeft: 12, background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer', fontSize: 13 }}>✕</button>
        </div>
      )}

      {totalVisible === 0 && (
        <div style={{ textAlign: 'center', padding: '48px 0', color: '#9ca3af' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
          <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 15, color: '#6b7280', margin: '0 0 6px' }}>
            {teamView ? 'No tasks match the filters' : 'All clear — no pending tasks!'}
          </p>
          <p style={{ fontSize: 13 }}>
            {teamView ? 'Try adjusting the filters above.' : 'Use + New Task to create one.'}
          </p>
        </div>
      )}

      {GROUP_META.map(({ key, label, accent }) => {
        const items = groups[key]
        if (!items.length) return null
        return (
          <div key={key} style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: accent }}>
                {label}
              </span>
              <span style={{ background: accent, color: 'white', fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 10 }}>
                {items.length}
              </span>
            </div>
            {items.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                onComplete={() => onActionDone?.()}
                onSnooze={() => onActionDone?.()}
                onError={msg => setActionError(msg)}
              />
            ))}
          </div>
        )
      })}
    </div>
  )
}
