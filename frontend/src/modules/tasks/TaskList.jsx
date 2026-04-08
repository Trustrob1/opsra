/**
 * modules/tasks/TaskList.jsx
 * Grouped task list — Phase 7B (updated Phase 9C).
 *
 * Phase 9C filter additions:
 *   - Assigned To dropdown (team view only — sales_agent + affiliate_partner)
 *   - Created Date preset: Today | Last 7 days | Last 30 days | Custom
 *   - Due Date preset: Today | Next 7 days | Next 30 days | Overdue | Custom
 *   - FilterBar now visible in BOTH personal and team view
 *
 * Props:
 *   tasks      — array of task objects (now includes assigned_user join)
 *   loading    — bool
 *   error      — string or null
 *   teamView   — bool: whether team tab is active
 *   filters    — current filter state from useTasks
 *   applyFilters(newFilters) — update filters
 *   onRefresh() — re-fetch callback
 *   onActionDone() — called after complete/snooze/reassign to refresh list
 */

import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import TaskCard from './TaskCard'
import { listUsers } from '../../services/admin.service'

// ── Grouping logic ────────────────────────────────────────────────────────────

function groupTasks(tasks) {
  const now      = new Date()
  const todayStr = now.toISOString().split('T')[0]
  const in7      = new Date(now.getTime() + 7 * 86400000).toISOString()

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
    if (status === 'completed') continue
    if (status === 'snoozed')   { groups.snoozed.push(task); continue }

    const due = task.due_at
    if (!due)                   { groups.noDueDate.push(task); continue }
    if (due < now.toISOString()){ groups.overdue.push(task);   continue }
    if (due.startsWith(todayStr)){ groups.today.push(task);    continue }
    if (due <= in7)             { groups.thisWeek.push(task);  continue }
    groups.upcoming.push(task)
  }

  return groups
}

const GROUP_META = [
  { key: 'overdue',   label: '🔴 Overdue',     accent: '#dc2626' },
  { key: 'today',     label: '📅 Today',        accent: '#d97706' },
  { key: 'thisWeek',  label: '📆 This Week',    accent: '#2563eb' },
  { key: 'upcoming',  label: '🔮 Upcoming',     accent: '#6b7280' },
  { key: 'noDueDate', label: '📌 No Due Date',  accent: '#9ca3af' },
  { key: 'snoozed',   label: '💤 Snoozed',      accent: '#a855f7' },
]

// ── Filter bar ────────────────────────────────────────────────────────────────

const CREATED_PRESETS = [
  { value: '',        label: 'Any time' },
  { value: 'today',   label: 'Today' },
  { value: 'last_7',  label: 'Last 7 days' },
  { value: 'last_30', label: 'Last 30 days' },
  { value: 'custom',  label: 'Custom range' },
]

const DUE_PRESETS = [
  { value: '',        label: 'Any due date' },
  { value: 'today',   label: 'Due today' },
  { value: 'next_7',  label: 'Next 7 days' },
  { value: 'next_30', label: 'Next 30 days' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'custom',  label: 'Custom range' },
]

const SEL = {
  border: '1px solid #d1d5db', borderRadius: 7,
  padding: '7px 10px', fontSize: 12.5,
  fontFamily: 'inherit', color: '#111827',
  background: 'white', cursor: 'pointer', outline: 'none',
}
const LBL = {
  display: 'block', fontSize: 10, fontWeight: 600, color: '#6b7280',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 4,
}
const DATE_INPUT = {
  ...SEL, cursor: 'text', fontSize: 12,
}

function FilterBar({ filters, applyFilters, showAssignedTo }) {
  const [local,  setLocal]  = useState({ ...filters })
  const [users,  setUsers]  = useState([])

  // Load assignable users for team view filter
  useEffect(() => {
    if (!showAssignedTo) return
    listUsers()
      .then(data => {
        const eligible = (data ?? []).filter(u =>
          u.is_active &&
          ['sales_agent', 'affiliate_partner', 'ops_manager', 'owner',
           'customer_success', 'support_agent'].includes(u.roles?.template)
        )
        setUsers(eligible)
      })
      .catch(() => {})
  }, [showAssignedTo])

  // Keep local in sync if parent resets filters
  useEffect(() => { setLocal({ ...filters }) }, [filters])

  const set = (key, val) => setLocal(p => ({ ...p, [key]: val }))

  const apply = () => applyFilters(local)

  const clear = () => {
    const empty = {
      priority: '', status: '', module: '', assigned_to: '',
      created_preset: '', created_from: '', created_to: '',
      due_preset: '', due_from: '', due_to: '',
    }
    setLocal(empty)
    applyFilters(empty)
  }

  const hasActiveFilters = Object.entries(local).some(([k, v]) => v !== '')

  return (
    <div style={{
      background: '#f9fafb', border: '1px solid #e5e7eb',
      borderRadius: 10, padding: '16px', marginBottom: 20,
    }}>
      {/* Row 1 — scalar filters */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 12 }}>

        {/* Priority */}
        <div>
          <label style={LBL}>Priority</label>
          <select value={local.priority} onChange={e => set('priority', e.target.value)} style={SEL}>
            <option value="">All Priorities</option>
            {['critical', 'high', 'medium', 'low'].map(o => (
              <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
            ))}
          </select>
        </div>

        {/* Status */}
        <div>
          <label style={LBL}>Status</label>
          <select value={local.status} onChange={e => set('status', e.target.value)} style={SEL}>
            <option value="">All Statuses</option>
            {['open', 'in_progress', 'snoozed'].map(o => (
              <option key={o} value={o}>{o.replace('_', ' ').charAt(0).toUpperCase() + o.replace('_', ' ').slice(1)}</option>
            ))}
          </select>
        </div>

        {/* Module */}
        <div>
          <label style={LBL}>Module</label>
          <select value={local.module} onChange={e => set('module', e.target.value)} style={SEL}>
            <option value="">All Modules</option>
            {['leads', 'whatsapp', 'support', 'renewal', 'ops'].map(o => (
              <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
            ))}
          </select>
        </div>

        {/* Assigned To — team view only */}
        {showAssignedTo && (
          <div>
            <label style={LBL}>Assigned To</label>
            <select
              value={local.assigned_to}
              onChange={e => set('assigned_to', e.target.value)}
              style={{ ...SEL, minWidth: 160 }}
            >
              <option value="">All Users</option>
              {users.map(u => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                  {u.roles?.template === 'affiliate_partner' ? ' (Affiliate)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Row 2 — date filters */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', paddingTop: 12, borderTop: '1px solid #e5e7eb', marginBottom: 12 }}>

        {/* Created Date preset */}
        <div>
          <label style={LBL}>Created Date</label>
          <select value={local.created_preset} onChange={e => set('created_preset', e.target.value)} style={SEL}>
            {CREATED_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>

        {/* Created custom range */}
        {local.created_preset === 'custom' && (
          <>
            <div>
              <label style={LBL}>From</label>
              <input
                type="date"
                value={local.created_from}
                onChange={e => set('created_from', e.target.value)}
                style={DATE_INPUT}
              />
            </div>
            <div>
              <label style={LBL}>To</label>
              <input
                type="date"
                value={local.created_to}
                onChange={e => set('created_to', e.target.value)}
                style={DATE_INPUT}
              />
            </div>
          </>
        )}

        {/* Divider */}
        <div style={{ width: 1, height: 36, background: '#d1d5db', alignSelf: 'flex-end', margin: '0 4px' }} />

        {/* Due Date preset */}
        <div>
          <label style={LBL}>Due Date</label>
          <select value={local.due_preset} onChange={e => set('due_preset', e.target.value)} style={SEL}>
            {DUE_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>

        {/* Due custom range */}
        {local.due_preset === 'custom' && (
          <>
            <div>
              <label style={LBL}>From</label>
              <input
                type="date"
                value={local.due_from}
                onChange={e => set('due_from', e.target.value)}
                style={DATE_INPUT}
              />
            </div>
            <div>
              <label style={LBL}>To</label>
              <input
                type="date"
                value={local.due_to}
                onChange={e => set('due_to', e.target.value)}
                style={DATE_INPUT}
              />
            </div>
          </>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          onClick={apply}
          style={{
            background: ds.teal, color: 'white', border: 'none',
            borderRadius: 7, padding: '8px 18px', fontSize: 12.5,
            fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
          }}
        >
          Apply Filters
        </button>
        {hasActiveFilters && (
          <button
            onClick={clear}
            style={{
              background: 'none', border: '1px solid #d1d5db',
              borderRadius: 7, padding: '8px 14px', fontSize: 12.5,
              color: '#6b7280', fontFamily: 'inherit', cursor: 'pointer',
            }}
          >
            Clear All
          </button>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TaskList({ tasks, loading, error, teamView, filters, applyFilters, onRefresh, onActionDone }) {
  const [actionError, setActionError] = useState(null)

  const groups       = groupTasks(tasks)
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
      {/* Filter bar — shown in both personal and team view */}
      <FilterBar
        filters={filters}
        applyFilters={applyFilters}
        showAssignedTo={teamView}
      />

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
                onReassigned={() => onActionDone?.()}
              />
            ))}
          </div>
        )
      })}
    </div>
  )
}
