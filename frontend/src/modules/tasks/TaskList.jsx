/**
 * modules/tasks/TaskList.jsx
 * Grouped task list — Phase 7B (updated Phase 9C, M01-9b).
 *
 * M01-9b restructure:
 *   Three inner tabs (Active | Completed | Archived) replace the single
 *   scrollable list + bottom-of-page completed section.
 *
 *   Active tab:
 *     - Existing grouped view (Overdue / Today / This Week / Upcoming /
 *       No Due Date / Snoozed)
 *     - Pagination controls wired to page/goToPage/total from useTasks
 *     - Delete → optimistic removal from list, onDelete fires
 *
 *   Completed tab:
 *     - Session-only optimistic state (Option 1 — no server re-fetch)
 *     - Tasks moved here when ✓ Complete is confirmed
 *     - Archive action available on completed cards
 *
 *   Archived tab:
 *     - Server-fetched on first activation (lazy load)
 *     - Separate local pagination state
 *     - Restore action on each card
 *
 * Pattern 26: all three tab panels stay mounted after first activation,
 *   hidden with display:none.
 * Pattern 51: full rewrite — no sed edits.
 *
 * Props:
 *   tasks        — active task objects from useTasks hook
 *   total        — total active task count (for pagination)
 *   loading      — bool
 *   error        — string or null
 *   teamView     — bool: whether team tab is active
 *   filters      — current filter state from useTasks
 *   applyFilters — update filters
 *   page         — current page number
 *   goToPage(n)  — navigate to page n
 *   onRefresh()  — re-fetch active tasks
 *   onActionDone()— called after snooze/reassign (NOT after complete/delete)
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import TaskCard from './TaskCard'
import { listTasks } from '../../services/tasks.service'
import { listUsers } from '../../services/admin.service'

const PAGE_SIZE = 20

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
    if (status === 'snoozed')   { groups.snoozed.push(task);   continue }
    const due = task.due_at
    if (!due)                    { groups.noDueDate.push(task); continue }
    if (due < now.toISOString()) { groups.overdue.push(task);   continue }
    if (due.startsWith(todayStr)){ groups.today.push(task);     continue }
    if (due <= in7)              { groups.thisWeek.push(task);  continue }
    groups.upcoming.push(task)
  }

  return groups
}

const GROUP_META = [
  { key: 'overdue',   label: '🔴 Overdue',    accent: '#dc2626' },
  { key: 'today',     label: '📅 Today',       accent: '#d97706' },
  { key: 'thisWeek',  label: '📆 This Week',   accent: '#2563eb' },
  { key: 'upcoming',  label: '🔮 Upcoming',    accent: '#6b7280' },
  { key: 'noDueDate', label: '📌 No Due Date', accent: '#9ca3af' },
  { key: 'snoozed',   label: '💤 Snoozed',     accent: '#a855f7' },
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
const DATE_INPUT = { ...SEL, cursor: 'text', fontSize: 12 }

function FilterBar({ filters, applyFilters, showAssignedTo }) {
  const [local, setLocal] = useState({ ...filters })
  const [users, setUsers] = useState([])

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

  const hasActiveFilters = Object.values(local).some(v => v !== '')

  return (
    <div style={{
      background: '#f9fafb', border: '1px solid #e5e7eb',
      borderRadius: 10, padding: '16px', marginBottom: 20,
    }}>
      {/* Row 1 — scalar filters */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 12 }}>
        <div>
          <label style={LBL}>Priority</label>
          <select value={local.priority} onChange={e => set('priority', e.target.value)} style={SEL}>
            <option value="">All Priorities</option>
            {['critical', 'high', 'medium', 'low'].map(o => (
              <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={LBL}>Status</label>
          <select value={local.status} onChange={e => set('status', e.target.value)} style={SEL}>
            <option value="">All Statuses</option>
            {['open', 'in_progress', 'snoozed'].map(o => (
              <option key={o} value={o}>
                {o.replace('_', ' ').charAt(0).toUpperCase() + o.replace('_', ' ').slice(1)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label style={LBL}>Module</label>
          <select value={local.module} onChange={e => set('module', e.target.value)} style={SEL}>
            <option value="">All Modules</option>
            {['leads', 'whatsapp', 'support', 'renewal', 'ops'].map(o => (
              <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
            ))}
          </select>
        </div>
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
                  {u.full_name}{u.roles?.template === 'affiliate_partner' ? ' (Affiliate)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Row 2 — date filters */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', paddingTop: 12, borderTop: '1px solid #e5e7eb', marginBottom: 12 }}>
        <div>
          <label style={LBL}>Created Date</label>
          <select value={local.created_preset} onChange={e => set('created_preset', e.target.value)} style={SEL}>
            {CREATED_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
        {local.created_preset === 'custom' && (
          <>
            <div>
              <label style={LBL}>From</label>
              <input type="date" value={local.created_from} onChange={e => set('created_from', e.target.value)} style={DATE_INPUT} />
            </div>
            <div>
              <label style={LBL}>To</label>
              <input type="date" value={local.created_to} onChange={e => set('created_to', e.target.value)} style={DATE_INPUT} />
            </div>
          </>
        )}
        <div style={{ width: 1, height: 36, background: '#d1d5db', alignSelf: 'flex-end', margin: '0 4px' }} />
        <div>
          <label style={LBL}>Due Date</label>
          <select value={local.due_preset} onChange={e => set('due_preset', e.target.value)} style={SEL}>
            {DUE_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
        {local.due_preset === 'custom' && (
          <>
            <div>
              <label style={LBL}>From</label>
              <input type="date" value={local.due_from} onChange={e => set('due_from', e.target.value)} style={DATE_INPUT} />
            </div>
            <div>
              <label style={LBL}>To</label>
              <input type="date" value={local.due_to} onChange={e => set('due_to', e.target.value)} style={DATE_INPUT} />
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

// ── Inner tab bar ─────────────────────────────────────────────────────────────

function InnerTabBar({ active, onChange, completedCount, archivedTotal }) {
  const tabs = [
    { id: 'active',    label: 'Active',    count: null },
    { id: 'completed', label: 'Completed', count: completedCount },
    { id: 'archived',  label: 'Archived',  count: archivedTotal },
  ]

  return (
    <div style={{
      display: 'flex', gap: 6, marginBottom: 20,
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 16px',
              background: isActive ? ds.teal : 'white',
              color: isActive ? 'white' : '#6b7280',
              border: isActive ? `1px solid ${ds.teal}` : '1px solid #e5e7eb',
              borderRadius: 20, cursor: 'pointer',
              fontSize: 12.5, fontWeight: isActive ? 600 : 400,
              fontFamily: ds.fontDm,
              transition: 'all 0.15s',
            }}
          >
            {tab.label}
            {tab.count !== null && tab.count > 0 && (
              <span style={{
                background: isActive ? 'rgba(255,255,255,0.25)' : '#f3f4f6',
                color: isActive ? 'white' : '#374151',
                fontSize: 10, fontWeight: 700,
                padding: '1px 6px', borderRadius: 10,
                minWidth: 18, textAlign: 'center',
              }}>
                {tab.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ── Pagination controls ───────────────────────────────────────────────────────

function Pagination({ page, total, onGoToPage }) {
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  if (totalPages <= 1) return null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: 12, marginTop: 24, padding: '16px 0',
      borderTop: '1px solid #f3f4f6',
    }}>
      <button
        onClick={() => onGoToPage(page - 1)}
        disabled={page <= 1}
        style={{
          background: 'none', border: '1px solid #e5e7eb',
          borderRadius: 7, padding: '7px 14px', fontSize: 12.5,
          color: page <= 1 ? '#d1d5db' : '#374151',
          fontFamily: ds.fontDm, cursor: page <= 1 ? 'default' : 'pointer',
        }}
      >
        ← Previous
      </button>
      <span style={{ fontSize: 12.5, color: '#6b7280', fontFamily: ds.fontDm }}>
        Page <strong style={{ color: ds.dark }}>{page}</strong> of <strong style={{ color: ds.dark }}>{totalPages}</strong>
      </span>
      <button
        onClick={() => onGoToPage(page + 1)}
        disabled={page >= totalPages}
        style={{
          background: 'none', border: '1px solid #e5e7eb',
          borderRadius: 7, padding: '7px 14px', fontSize: 12.5,
          color: page >= totalPages ? '#d1d5db' : '#374151',
          fontFamily: ds.fontDm, cursor: page >= totalPages ? 'default' : 'pointer',
        }}
      >
        Next →
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TaskList({
  tasks,
  total,
  loading,
  error,
  teamView,
  filters,
  applyFilters,
  page,
  goToPage,
  onRefresh,
  onActionDone,
}) {
  const [innerTab,     setInnerTab]     = useState('active')
  const [actionError,  setActionError]  = useState(null)

  // ── Optimistic completed state (M01-9b — session-only, Option 1) ───────────
  const [completedIds,   setCompletedIds]   = useState(new Set())
  const [completedTasks, setCompletedTasks] = useState([])

  // ── Optimistic deleted state (removed from active + completed lists) ───────
  const [deletedIds, setDeletedIds] = useState(new Set())

  // ── Archived tab local state ───────────────────────────────────────────────
  const [archivedLoaded,  setArchivedLoaded]  = useState(false)
  const [archivedTasks,   setArchivedTasks]   = useState([])
  const [archivedTotal,   setArchivedTotal]   = useState(0)
  const [archivedPage,    setArchivedPage]    = useState(1)
  const [archivedLoading, setArchivedLoading] = useState(false)
  const [archivedError,   setArchivedError]   = useState(null)

  const fetchArchived = useCallback(async (pageNum) => {
    setArchivedLoading(true)
    setArchivedError(null)
    try {
      const data = await listTasks({
        archived:  true,
        team:      teamView,
        page:      pageNum,
        page_size: PAGE_SIZE,
      })
      setArchivedTasks(data.items || [])
      setArchivedTotal(data.total || 0)
      setArchivedPage(pageNum)
    } catch {
      setArchivedError('Could not load archived tasks.')
    } finally {
      setArchivedLoading(false)
    }
  }, [teamView])

  // Lazy-load archived tab on first activation
  const handleInnerTabChange = (tab) => {
    setInnerTab(tab)
    if (tab === 'archived' && !archivedLoaded) {
      setArchivedLoaded(true)
      fetchArchived(1)
    }
  }

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleCompleteOptimistic = (id) => {
    const task = tasks.find(t => t.id === id)
    if (!task) return
    setCompletedIds(prev => new Set([...prev, id]))
    setCompletedTasks(prev => [...prev, { ...task, status: 'completed' }])
    // No onActionDone — re-fetch with completed:false would vanish the task
  }

  const handleDeleteOptimistic = (id) => {
    // Remove from active list and completed list immediately
    setDeletedIds(prev => new Set([...prev, id]))
    setCompletedTasks(prev => prev.filter(t => t.id !== id))
    // Refresh archived count
    fetchArchived(archivedPage)
  }

  const handleRestoreFromArchived = (id) => {
    // Remove from archived list optimistically
    setArchivedTasks(prev => prev.filter(t => t.id !== id))
    setArchivedTotal(prev => Math.max(0, prev - 1))
    // Remove from deletedIds so it can reappear in active list on next refresh
    setDeletedIds(prev => { const s = new Set(prev); s.delete(id); return s })
    // Refresh active list
    onRefresh?.()
  }

  // Active tasks = fetched tasks minus optimistically completed/deleted ones
  const activeTasks     = tasks.filter(t => !completedIds.has(t.id) && !deletedIds.has(t.id))
  const activeCompleted = completedTasks.filter(t => !deletedIds.has(t.id))
  const groups          = groupTasks(activeTasks)
  const totalVisible    = Object.values(groups).flat().length

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center', color: '#9ca3af' }}>
        <div style={{
          width: 28, height: 28,
          border: '3px solid #e5e7eb', borderTopColor: ds.teal,
          borderRadius: '50%', animation: 'spin 0.8s linear infinite',
          margin: '0 auto 12px',
        }} />
        <p style={{ fontSize: 13 }}>Loading tasks…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '20px 0' }}>
        <p style={{ fontSize: 13, color: '#dc2626' }}>⚠ {error}</p>
        <button
          onClick={onRefresh}
          style={{ fontSize: 13, color: ds.teal, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div>
      {/* Inner tab bar — Active | Completed | Archived */}
      <InnerTabBar
        active={innerTab}
        onChange={handleInnerTabChange}
        completedCount={activeCompleted.length}
        archivedTotal={archivedTotal}
      />

      {/* Action error banner */}
      {actionError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fca5a5',
          borderRadius: 8, padding: '10px 14px',
          fontSize: 13, color: '#dc2626', marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ flex: 1 }}>⚠ {actionError}</span>
          <button
            onClick={() => setActionError(null)}
            style={{ background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer', fontSize: 14 }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── ACTIVE TAB ──────────────────────────────────────────────────────── */}
      <div style={{ display: innerTab === 'active' ? 'block' : 'none' }}>
        <FilterBar
          filters={filters}
          applyFilters={applyFilters}
          showAssignedTo={teamView}
        />

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
                <span style={{
                  background: accent, color: 'white',
                  fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 10,
                }}>
                  {items.length}
                </span>
              </div>
              {items.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onComplete={handleCompleteOptimistic}
                  onSnooze={() => onActionDone?.()}
                  onDelete={handleDeleteOptimistic}
                  onError={msg => setActionError(msg)}
                  onReassigned={() => onActionDone?.()}
                />
              ))}
            </div>
          )
        })}

        <Pagination page={page} total={total} onGoToPage={goToPage} />
      </div>

      {/* ── COMPLETED TAB ───────────────────────────────────────────────────── */}
      <div style={{ display: innerTab === 'completed' ? 'block' : 'none' }}>
        {activeCompleted.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#9ca3af' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>☑️</div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 15, color: '#6b7280', margin: '0 0 6px' }}>
              No tasks completed this session
            </p>
            <p style={{ fontSize: 13 }}>Tasks you complete will appear here.</p>
          </div>
        ) : (
          <>
            <p style={{ fontSize: 12, color: '#9ca3af', marginBottom: 16, fontFamily: ds.fontDm }}>
              Tasks completed in this session. Archived tasks move to the Archived tab.
            </p>
            {activeCompleted.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                onDelete={handleDeleteOptimistic}
                onError={msg => setActionError(msg)}
              />
            ))}
          </>
        )}
      </div>

      {/* ── ARCHIVED TAB ────────────────────────────────────────────────────── */}
      <div style={{ display: innerTab === 'archived' ? 'block' : 'none' }}>
        {archivedLoading && (
          <div style={{ padding: '40px 0', textAlign: 'center', color: '#9ca3af' }}>
            <div style={{
              width: 28, height: 28,
              border: '3px solid #e5e7eb', borderTopColor: '#9ca3af',
              borderRadius: '50%', animation: 'spin 0.8s linear infinite',
              margin: '0 auto 12px',
            }} />
            <p style={{ fontSize: 13 }}>Loading archived tasks…</p>
          </div>
        )}

        {archivedError && !archivedLoading && (
          <div style={{ padding: '20px 0' }}>
            <p style={{ fontSize: 13, color: '#dc2626' }}>⚠ {archivedError}</p>
            <button
              onClick={() => fetchArchived(archivedPage)}
              style={{ fontSize: 13, color: ds.teal, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              Retry
            </button>
          </div>
        )}

        {!archivedLoading && !archivedError && archivedTasks.length === 0 && (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#9ca3af' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>🗄</div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 15, color: '#6b7280', margin: '0 0 6px' }}>
              No archived tasks
            </p>
            <p style={{ fontSize: 13 }}>Tasks you archive will appear here and can be restored.</p>
          </div>
        )}

        {!archivedLoading && !archivedError && archivedTasks.length > 0 && (
          <>
            <p style={{ fontSize: 12, color: '#9ca3af', marginBottom: 16, fontFamily: ds.fontDm }}>
              Archived tasks are hidden from the active list. Restore to make them active again.
            </p>
            {archivedTasks.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                onRestore={handleRestoreFromArchived}
                onError={msg => setActionError(msg)}
              />
            ))}
            <Pagination
              page={archivedPage}
              total={archivedTotal}
              onGoToPage={(p) => fetchArchived(p)}
            />
          </>
        )}
      </div>
    </div>
  )
}
