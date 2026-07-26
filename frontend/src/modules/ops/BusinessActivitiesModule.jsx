/**
 * frontend/src/modules/ops/BusinessActivitiesModule.jsx
 * REPORTS-DEPT-1 Phase 3 — the consolidated "Business Activities" hub.
 *
 * This is the module the whole REPORTS-DEPT-1 redesign was originally
 * asked for: one place to log and see daily activity, issues, and
 * contractor performance, instead of three clicks deep inside Operations
 * Hub. Distinct from ReportsModule.jsx ("Reports" nav item), which is a
 * separate, Opsra-native-data-only report and is NOT touched or folded in
 * here.
 *
 * Reuses existing, already-correct components rather than duplicating
 * their logic:
 *   - IssuesTab, ActivityLogTab   — named exports added to InternalOpsModule.jsx
 *   - ContractorModule            — mounted whole, its own internal tabs untouched
 *
 * Tabs:
 *   Activity Log  — visible to all roles (matches prior InternalOpsModule behaviour)
 *   Issues        — hidden for sales_agent (matches prior InternalOpsModule behaviour)
 *   Contractors   — owner / ops_manager only (matches prior OpsModule gate)
 *   Data Sources  — owner / ops_manager / department-scoped roles — REPORTS-DEPT-1
 *                   Phase 4 placeholder. Real external-source wiring (Google
 *                   Sheet / CSV import, per-department source selection) is
 *                   not yet built — this tab exists so the destination is in
 *                   place and findable now, rather than appearing later with
 *                   no visible home.
 *
 * Pattern 26: all tab panels stay mounted, hidden with display:none.
 * Pattern 51: full rewrite if editing this file — never partial sed.
 * Tab state is local — no URL routing (Pattern 13).
 *
 * Props:
 *   user — current user object from Zustand auth store
 */

import { useState } from 'react'
import { ClipboardList, AlertOctagon, Users, Database, Table2, DollarSign } from 'lucide-react'
import { ds } from '../../utils/ds'
import { IssuesTab, ActivityLogTab } from './InternalOpsModule'
import ContractorModule from './ContractorModule'
import DataSourcesTab from './DataSourcesTab'
import SalesRecordTab from './SalesRecordTab'
import CommissionsTab from './CommissionsTab'

const MANAGER_ROLES = ['owner', 'ops_manager']
const SALES_AGENT_ROLE = 'sales_agent'

function buildTabs(role, departmentId) {
  const isManager = MANAGER_ROLES.includes(role)
  const isDeptScoped = role !== 'owner' && !!departmentId

  const tabs = [{ id: 'activity', label: 'Activity Log' }]

  // Issues: hidden for sales_agent only — matches InternalOpsModule's
  // existing rule (IssuesTab itself doesn't gate on role).
  if (role !== SALES_AGENT_ROLE) {
    tabs.push({ id: 'issues', label: 'Issues' })
  }

  // Contractors: owner/ops_manager only — matches OpsModule.jsx's
  // existing MANAGER_ROLES gate around <ContractorModule />.
  if (isManager) {
    tabs.push({ id: 'contractors', label: 'Contractors' })
  }

  // Sales Record: owner/ops_manager only — matches list_direct_sales'
  // backend gate exactly (_require_owner_or_ops). REPORTS-DEPT-1 Phase 4b.
  if (isManager) {
    tabs.push({ id: 'sales-record', label: 'Sales Record' })
  }

  // Commissions: EVERY role including sales_agent — full leaderboard
  // transparency, client-confirmed. Matches list_commission_sales'
  // broader backend gate (_require_owner_ops_or_agent).
  tabs.push({ id: 'commissions', label: 'Commissions' })

  // Data Sources: owner/ops_manager, or a department-scoped lead managing
  // their own department's external source. REPORTS-DEPT-1 Phase 4.
  if (isManager || isDeptScoped) {
    tabs.push({ id: 'sources', label: 'Data Sources' })
  }

  return tabs
}

const TAB_ICONS = {
  activity:      ClipboardList,
  issues:        AlertOctagon,
  contractors:   Users,
  'sales-record': Table2,
  commissions:   DollarSign,
  sources:       Database,
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

function ModuleHeader({ departmentLabel }) {
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
        BA
      </div>
      <div>
        <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: 'white', margin: 0 }}>
          Business Activities
        </h1>
        <p style={{ fontSize: 12, color: '#6B8FA0', margin: '2px 0 0' }}>
          Activity log &middot; Issues &middot; Contractors &middot; Data sources
          {departmentLabel ? ` \u2014 ${departmentLabel}` : ''}
        </p>
      </div>
    </div>
  )
}

// Data Sources tab now implemented in DataSourcesTab.jsx (REPORTS-DEPT-1 Phase 4)

// ─── Main component ───────────────────────────────────────────────────────────

export default function BusinessActivitiesModule({ user }) {
  const role         = user?.roles?.template || ''
  const departmentId = user?.roles?.department_id || null
  const tabs         = buildTabs(role, departmentId)

  const [activeTab, setActiveTab] = useState(tabs[0]?.id || 'activity')

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light }}>
      <ModuleHeader />
      <TabBar active={activeTab} onChange={setActiveTab} tabs={tabs} />

      {/* Pattern 26: mount-and-hide — all panels stay in the DOM */}
      <div style={{ display: activeTab === 'activity' ? 'block' : 'none' }}>
        <ActivityLogTab user={user} />
      </div>

      {tabs.some(t => t.id === 'issues') && (
        <div style={{ display: activeTab === 'issues' ? 'block' : 'none' }}>
          <IssuesTab user={user} />
        </div>
      )}

      {tabs.some(t => t.id === 'contractors') && (
        <div style={{ display: activeTab === 'contractors' ? 'block' : 'none' }}>
          <ContractorModule user={user} />
        </div>
      )}

      {tabs.some(t => t.id === 'sales-record') && (
        <div style={{ display: activeTab === 'sales-record' ? 'block' : 'none' }}>
          <SalesRecordTab isActive={activeTab === 'sales-record'} />
        </div>
      )}

      {tabs.some(t => t.id === 'commissions') && (
        <div style={{ display: activeTab === 'commissions' ? 'block' : 'none' }}>
          <CommissionsTab user={user} isActive={activeTab === 'commissions'} />
        </div>
      )}

      {tabs.some(t => t.id === 'sources') && (
        <div style={{ display: activeTab === 'sources' ? 'block' : 'none' }}>
          <DataSourcesTab />
        </div>
      )}
    </div>
  )
}
