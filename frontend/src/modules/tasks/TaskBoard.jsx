/**
 * modules/tasks/TaskBoard.jsx
 * Task Management module container — Phase 7B (fixed Phase 7C, TEMP-6 resolved Phase 9).
 *
 * Tabs: 👤 My Tasks (Personal) · 👥 Team View (managers only)
 * Pattern 26: both tab panels stay mounted, hidden with display:none.
 *
 * TEMP-6 resolved (Phase 9):
 *   Team tab now gated on isManager — derived from authStore.isManager()
 *   which reads roles.template from the full user profile loaded by auth/me.
 *   Non-manager users see only the Personal tab with no tab bar visible.
 *
 * Props:
 *   user — current user object from Zustand auth store (includes roles after TEMP-1 fix)
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import useTasks from '../../hooks/useTasks'
import TaskList from './TaskList'
import CreateTaskModal from './CreateTaskModal'

// ── Tab bar ───────────────────────────────────────────────────────────────────

function TabBar({ active, onChange, showTeam }) {
  const tabs = [
    { id: 'personal', label: 'My Tasks',  icon: '👤' },
    ...(showTeam ? [{ id: 'team', label: 'Team View', icon: '👥' }] : []),
  ]

  // Only one tab — no bar needed
  if (tabs.length === 1) return null

  return (
    <div style={{
      display: 'flex', gap: 4,
      borderBottom: '1px solid #e5e7eb',
      padding: '0 28px',
      background: 'white',
      position: 'sticky', top: 0, zIndex: 10,
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '14px 16px 12px',
              background: 'none', border: 'none',
              borderBottom: isActive ? `2px solid ${ds.teal}` : '2px solid transparent',
              cursor: 'pointer', fontSize: 13.5,
              fontWeight: isActive ? 600 : 400,
              fontFamily: ds.fontDm,
              color: isActive ? ds.teal : ds.gray,
              transition: 'all 0.15s',
              marginBottom: -1,
            }}
          >
            {tab.icon} {tab.label}
          </button>
        )
      })}
    </div>
  )
}

// ── Module header ─────────────────────────────────────────────────────────────

function ModuleHeader({ onNewTask }) {
  return (
    <div style={{
      background: ds.dark, padding: '20px 28px',
      display: 'flex', alignItems: 'center',
      justifyContent: 'space-between',
      borderBottom: '1px solid #1a2f3f',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 10,
          background: ds.teal, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          fontSize: 20, flexShrink: 0,
        }}>
          ✅
        </div>
        <div>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: 'white', margin: 0 }}>
            Task Board
          </h1>
          <p style={{ fontSize: 12, color: '#6B8FA0', margin: '2px 0 0' }}>
            All tasks across all modules · Personal and team view
          </p>
        </div>
      </div>
      <button
        onClick={onNewTask}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: ds.teal, color: 'white', border: 'none',
          borderRadius: 8, padding: '9px 18px',
          fontSize: 13.5, fontWeight: 600,
          fontFamily: ds.fontDm, cursor: 'pointer',
        }}
      >
        + New Task
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TaskBoard({ user }) {
  // TEMP-6 fix: gate Team tab on roles.template (Phase 9)
  // isManager() reads roles.template from the full user profile loaded by auth/me.
  // Matches backend _is_manager(): owner | ops_manager | manage_tasks permission.
  const isManager = useAuthStore.getState().isManager()

  const [activeTab,  setActiveTab]  = useState('personal')
  const [showCreate, setShowCreate] = useState(false)

  // Single hook instance — teamView flag switches what the backend returns.
  // Two instances caused both to mount simultaneously and double-fetch.
  const {
    tasks, loading, error,
    filters, applyFilters,
    refresh, setTeamView,
  } = useTasks(20)

  const handleTabChange = (tabId) => {
    // Guard: non-managers cannot access team view even if they somehow trigger it
    if (tabId === 'team' && !isManager) return
    setActiveTab(tabId)
    setTeamView(tabId === 'team')
  }

  const handleCreated = () => {
    setShowCreate(false)
    refresh()
  }

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light }}>
      <ModuleHeader onNewTask={() => setShowCreate(true)} />
      <TabBar active={activeTab} onChange={handleTabChange} showTeam={isManager} />

      {/* Pattern 26: both panels stay mounted, hidden with display:none */}
      <div style={{ padding: '24px 28px' }}>
        <div style={{ display: activeTab === 'personal' ? 'block' : 'none' }}>
          <TaskList
            tasks={tasks}
            loading={loading}
            error={error}
            teamView={false}
            filters={filters}
            applyFilters={applyFilters}
            onRefresh={refresh}
            onActionDone={refresh}
          />
        </div>

        {/* Team panel only rendered for managers — Pattern 26 */}
        {isManager && (
          <div style={{ display: activeTab === 'team' ? 'block' : 'none' }}>
            <TaskList
              tasks={tasks}
              loading={loading}
              error={error}
              teamView={true}
              filters={filters}
              applyFilters={applyFilters}
              onRefresh={refresh}
              onActionDone={refresh}
            />
          </div>
        )}
      </div>

      {showCreate && (
        <CreateTaskModal
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
