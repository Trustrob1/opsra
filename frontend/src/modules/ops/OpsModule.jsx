/**
 * modules/ops/OpsModule.jsx
 * Operations Intelligence module container — Phase 6B + GPM-1B.
 *
 * Tabs:
 *   📊 Dashboard    — live metric stat cards (DashboardView)
 *   💬 Ask Data     — conversational AI interface (AskDataView)
 *   📈 Growth       — Growth Performance Dashboard (GrowthDashboard)
 *
 * Pattern 26: all tab panels stay mounted, hidden with display:none.
 * Pattern 51: full rewrite — never partial edit on JSX files.
 * Tab state is local — no URL routing (Pattern 13).
 * Pattern 56: role check via user?.roles?.template
 *
 * Props:
 *   user        — current user object from Zustand auth store
 *   setView     — AppShell view setter (Pattern 13)
 *   setActiveNav — AppShell nav setter
 */

import { useState } from 'react'
import { LayoutDashboard, MessageSquare, Building2, Users, TrendingUp } from 'lucide-react'
import { ds } from '../../utils/ds'
import useOps from '../../hooks/useOps'
import DashboardView  from './DashboardView'
import AskDataView    from './AskDataView'
import GrowthDashboard from './GrowthDashboard'
import InternalOpsModule from './InternalOpsModule'
import ContractorModule  from './ContractorModule'

// Role groups
const MANAGER_ROLES    = ['owner', 'ops_manager']
const SALES_AGENT_ROLE = 'sales_agent'
const SUPPORT_ROLE     = 'support_agent'

function buildTabs(role) {
  // Support agents see nothing in this module
  if (role === SUPPORT_ROLE) return []

  // Sales agents see only Internal Ops (Activity Log — Issues hidden inside InternalOpsModule)
  if (role === SALES_AGENT_ROLE) {
    return [{ id: 'internal', label: 'Internal Ops' }]
  }

  // Owner + ops_manager see everything
  const tabs = [
    { id: 'dashboard',   label: 'Dashboard' },
    { id: 'ask',         label: 'Ask Data' },
    { id: 'internal',    label: 'Internal Ops' },
    { id: 'contractors', label: 'Contractors' },
    { id: 'growth',      label: 'Growth' },
  ]
  return tabs
}

const TAB_ICONS = {
  dashboard:   LayoutDashboard,
  ask:         MessageSquare,
  internal:    Building2,
  contractors: Users,
  growth:      TrendingUp,
}

// ─── Tab bar ──────────────────────────────────────────────────────────────────

function TabBar({ active, onChange, tabs }) {
  return (
    <div style={{
      display:      'flex',
      gap:          4,
      borderBottom: '1px solid #dde4e8',
      padding:      '0 28px',
      background:   'white',
      position:     'sticky',
      top:          0,
      zIndex:       10,
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.id
        const TabIcon = TAB_ICONS[tab.id] || null
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              display:      'flex',
              alignItems:   'center',
              gap:          6,
              padding:      '14px 16px 12px',
              background:   'none',
              border:       'none',
              borderBottom: isActive ? `2px solid ${ds.teal}` : '2px solid transparent',
              cursor:       'pointer',
              fontSize:     13.5,
              fontWeight:   isActive ? 600 : 400,
              fontFamily:   ds.fontDm,
              color:        isActive ? ds.teal : ds.gray,
              transition:   'all 0.15s',
              whiteSpace:   'nowrap',
              marginBottom: -1,
            }}
          >
            {TabIcon && <TabIcon size={14} strokeWidth={isActive ? 2.5 : 1.8} />}
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

// ─── Module header ────────────────────────────────────────────────────────────

function ModuleHeader() {
  return (
    <div style={{
      background:   ds.dark,
      padding:      '20px 28px',
      display:      'flex',
      alignItems:   'center',
      gap:          16,
      borderBottom: '1px solid #1a2f3f',
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: ds.teal, display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        fontFamily: ds.fontSyne, fontWeight: 800,
        fontSize: 14, color: 'white', flexShrink: 0,
      }}>
        05
      </div>
      <div>
        <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: 'white', margin: 0 }}>
          Operations Intelligence
        </h1>
        <p style={{ fontSize: 12, color: '#6B8FA0', margin: '2px 0 0' }}>
          Executive dashboard · Ask-your-data · Anomaly detection · Monday digest · Growth analytics
        </p>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function OpsModule({ user, setView, setActiveNav }) {
  const role    = user?.roles?.template || ''
  const tabs    = buildTabs(role)

  // Sales agents land on internal tab; all others land on dashboard
  const defaultTab = role === SALES_AGENT_ROLE ? 'internal' : 'dashboard'
  const [activeTab, setActiveTab] = useState(defaultTab)
  const { metrics, loading, error, refresh, ask } = useOps()

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light }}>
      <ModuleHeader />
      <TabBar active={activeTab} onChange={setActiveTab} tabs={tabs} />

      {/* Pattern 26: mount-and-hide — all panels stay in the DOM */}
      {/* Dashboard — manager only */}
      <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
        {MANAGER_ROLES.includes(role) && (
          <DashboardView
            metrics={metrics}
            loading={loading}
            error={error}
            onRefresh={refresh}
          />
        )}
      </div>

      {/* Ask Data — manager only */}
      <div style={{ display: activeTab === 'ask' ? 'block' : 'none' }}>
        {MANAGER_ROLES.includes(role) && (
          <AskDataView onAsk={ask} />
        )}
      </div>

      {/* Internal Ops — managers + sales_agent (sales_agent sees activity log only — enforced inside InternalOpsModule) */}
      <div style={{ display: activeTab === 'internal' ? 'block' : 'none' }}>
        <InternalOpsModule user={user} />
      </div>

      {/* Contractors — manager only */}
      <div style={{ display: activeTab === 'contractors' ? 'block' : 'none' }}>
        {MANAGER_ROLES.includes(role) && (
          <ContractorModule user={user} />
        )}
      </div>

      {/* Growth — manager only */}
      <div style={{ display: activeTab === 'growth' ? 'block' : 'none' }}>
        {MANAGER_ROLES.includes(role) && (
          <GrowthDashboard user={user} setView={setView} />
        )}
      </div>
    </div>
  )
}
