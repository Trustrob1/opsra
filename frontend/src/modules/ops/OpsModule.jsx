/**
 * modules/ops/OpsModule.jsx
 * Operations Intelligence module container — Phase 6B.
 *
 * Tabs:
 *   📊 Dashboard    — live metric stat cards (DashboardView)
 *   💬 Ask Data     — conversational AI interface (AskDataView)
 *
 * Pattern 26: all tab panels stay mounted, hidden with display:none.
 * Tab state is local — no URL routing (Pattern 13).
 *
 * Props:
 *   user — current user object from Zustand auth store
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import useOps from '../../hooks/useOps'
import DashboardView from './DashboardView'
import AskDataView   from './AskDataView'

const TABS = [
  { id: 'dashboard', label: 'Dashboard',  icon: '📊' },
  { id: 'ask',       label: 'Ask Data',   icon: '💬' },
]

// ─── Tab bar ──────────────────────────────────────────────────────────────────

function TabBar({ active, onChange }) {
  return (
    <div style={{
      display:        'flex',
      gap:            4,
      borderBottom:   '1px solid #dde4e8',
      padding:        '0 28px',
      background:     'white',
      position:       'sticky',
      top:            0,
      zIndex:         10,
    }}>
      {TABS.map(tab => {
        const isActive = active === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              display:        'flex',
              alignItems:     'center',
              gap:            6,
              padding:        '14px 16px 12px',
              background:     'none',
              border:         'none',
              borderBottom:   isActive ? `2px solid ${ds.teal}` : '2px solid transparent',
              cursor:         'pointer',
              fontSize:       13.5,
              fontWeight:     isActive ? 600 : 400,
              fontFamily:     ds.fontDm,
              color:          isActive ? ds.teal : ds.gray,
              transition:     'all 0.15s',
              whiteSpace:     'nowrap',
              marginBottom:   -1,
            }}
          >
            <span>{tab.icon}</span>
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
          Executive dashboard · Ask-your-data · Anomaly detection · Monday digest
        </p>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function OpsModule({ user }) {
  const [activeTab, setActiveTab] = useState('dashboard')
  const { metrics, loading, error, refresh, ask } = useOps()

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light }}>
      <ModuleHeader />
      <TabBar active={activeTab} onChange={setActiveTab} />

      {/* Pattern 26: mount-and-hide — both panels stay in the DOM */}
      <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
        <DashboardView
          metrics={metrics}
          loading={loading}
          error={error}
          onRefresh={refresh}
        />
      </div>

      <div style={{ display: activeTab === 'ask' ? 'block' : 'none' }}>
        <AskDataView onAsk={ask} />
      </div>
    </div>
  )
}
