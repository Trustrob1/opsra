/**
 * frontend/src/modules/performance/PerformanceModule.jsx
 *
 * Top-level Performance & Operations Hub shell.
 * Handles role-based view routing:
 *   owner / ops_manager → Scorecard (default) or any sub-view
 *   all other staff     → My Performance only
 *
 * Pattern 13 — Zustand view-state, no react-router.
 * Pattern 26 — mount-and-hide tabs (never conditional render).
 * Pattern 56 — authStore: getRoleTemplate() is a method.
 */
import { useState } from 'react'
import useAuthStore from '../../store/authStore'
import { ds } from '../../utils/ds'
import ScorecardView     from './ScorecardView'
import StaffProfileView  from './StaffProfileView'
import MyPerformanceView from './MyPerformanceView'
import KpiTemplateManager from './KpiTemplateManager'
import BusinessGoalsTab   from './BusinessGoalsTab'

const _MANAGER_ROLES = ['owner', 'ops_manager']

export default function PerformanceModule({ user }) {
  const roleTemplate = useAuthStore.getState().user?.roles?.template ?? ''
  const isManager    = _MANAGER_ROLES.includes(roleTemplate)

  // Default view: managers → scorecard, staff → my-performance
  const [subView, setSubView]           = useState(isManager ? 'scorecard' : 'my-performance')
  const [selectedUserId, setSelectedUserId] = useState(null)
  const [selectedMonth, setSelectedMonth]   = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })

  const openStaffProfile = (userId, month) => {
    setSelectedUserId(userId)
    if (month) setSelectedMonth(month)
    setSubView('staff-profile')
  }

  const backToScorecard = () => {
    setSelectedUserId(null)
    setSubView('scorecard')
  }

  const TAB_STYLE = (active) => ({
    padding: '8px 18px',
    borderRadius: 8,
    border: 'none',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 500,
    fontFamily: ds.fontDm,
    background: active ? ds.teal : 'transparent',
    color: active ? 'white' : '#7A9BAD',
    transition: 'all 0.15s',
  })

  return (
    <div style={{ padding: '24px 28px', minHeight: '100vh', background: ds.light }}>
      {/* ── Header ── */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 4px' }}>
          📊 Performance Hub
        </h1>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: 0 }}>
          {isManager ? 'Org-wide performance tracking and KPI management' : 'Your personal performance and daily log'}
        </p>
      </div>

      {/* ── Tab bar — managers only ── */}
      {isManager && subView !== 'staff-profile' && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 24, borderBottom: '1px solid #e5e7eb', paddingBottom: 16 }}>
          <button style={TAB_STYLE(subView === 'scorecard')}    onClick={() => setSubView('scorecard')}>Scorecard</button>
          <button style={TAB_STYLE(subView === 'my-performance')} onClick={() => setSubView('my-performance')}>My Performance</button>
          <button style={TAB_STYLE(subView === 'templates')}    onClick={() => setSubView('templates')}>KPI Templates</button>
          <button style={TAB_STYLE(subView === 'goals')}        onClick={() => setSubView('goals')}>Business Goals</button>
        </div>
      )}

      {/* ── Views — Pattern 26: mount-and-hide ── */}
      <div style={{ display: subView === 'scorecard' && isManager ? 'block' : 'none' }}>
        <ScorecardView onOpenProfile={openStaffProfile} />
      </div>

      <div style={{ display: subView === 'staff-profile' ? 'block' : 'none' }}>
        <StaffProfileView
          userId={selectedUserId}
          month={selectedMonth}
          onBack={backToScorecard}
          isManager={isManager}
        />
      </div>

      <div style={{ display: subView === 'my-performance' ? 'block' : 'none' }}>
        <MyPerformanceView user={user} />
      </div>

      <div style={{ display: subView === 'templates' && isManager ? 'block' : 'none' }}>
        <KpiTemplateManager />
      </div>

      <div style={{ display: subView === 'goals' && isManager ? 'block' : 'none' }}>
        <BusinessGoalsTab />
      </div>
    </div>
  )
}
