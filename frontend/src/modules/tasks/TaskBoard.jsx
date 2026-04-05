/**
 * modules/tasks/TaskBoard.jsx
 * Task Management module container — Phase 7B.
 *
 * Tabs: 👤 My Tasks (Personal) · 👥 Team View
 * Pattern 26: both tab panels stay mounted, hidden with display:none.
 *
 * ⚠️ TEMP-6: Team tab shown to all users.
 * The frontend cannot gate it on roles.template because the login response
 * only stores id and email in Zustand (TEMP-1 not yet resolved).
 * The backend silently returns only the caller's own tasks for non-managers
 * even when team=true — so the UX is correct, just not visually gated.
 * RESOLVE in Phase 9 when TEMP-1 is fixed and roles are stored in authStore.
 *
 * Props:
 *   user — current user object from Zustand auth store
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import useTasks from '../../hooks/useTasks'
import TaskList from './TaskList'
import CreateTaskModal from './CreateTaskModal'

// ── Tab bar ───────────────────────────────────────────────────────────────────

function TabBar({ active, onChange }) {
  const tabs = [
    { id: 'personal', label: 'My Tasks',    icon: '👤' },
    { id: 'team',     label: 'Team View',   icon: '👥' },
  ]
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

function ModuleHeader({ onNewTask, totalOpen }) {
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
  const [activeTab,      setActiveTab]      = useState('personal')
  const [showCreate,     setShowCreate]     = useState(false)

  // Personal view hook
  const personal = useTasks(20)

  // Team view hook — separate instance so each tab maintains its own state
  const team = useTasks(20)

  const handleTabChange = (tabId) => {
    setActiveTab(tabId)
    // Sync team view flag to the correct hook
    if (tabId === 'team') {
      team.setTeamView(true)
      team.refresh()
    } else {
      personal.setTeamView(false)
    }
  }

  const handleCreated = () => {
    setShowCreate(false)
    personal.refresh()
    team.refresh()
  }

  // Current hook based on active tab
  const current = activeTab === 'personal' ? personal : team

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light }}>
      <ModuleHeader onNewTask={() => setShowCreate(true)} />
      <TabBar active={activeTab} onChange={handleTabChange} />

      {/* Pattern 26: both panels stay mounted */}
      <div style={{ padding: '24px 28px' }}>
        <div style={{ display: activeTab === 'personal' ? 'block' : 'none' }}>
          <TaskList
            tasks={personal.tasks}
            loading={personal.loading}
            error={personal.error}
            teamView={false}
            filters={personal.filters}
            applyFilters={personal.applyFilters}
            onRefresh={personal.refresh}
            onActionDone={personal.refresh}
          />
        </div>
        <div style={{ display: activeTab === 'team' ? 'block' : 'none' }}>
          <TaskList
            tasks={team.tasks}
            loading={team.loading}
            error={team.error}
            teamView={true}
            filters={team.filters}
            applyFilters={team.applyFilters}
            onRefresh={team.refresh}
            onActionDone={team.refresh}
          />
        </div>
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
