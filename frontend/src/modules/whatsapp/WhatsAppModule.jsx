/**
 * WhatsAppModule.jsx — Module 02 top-level container.
 *
 * Sub-nav tabs:
 *   Customers | Broadcasts | Templates | Drip Sequence
 *
 * Handles view-state routing for CustomerProfile (Zustand-free — local state
 * only, following Pattern 13: no react-router, no Zustand for module routing).
 *
 * isOwner is derived from the org's role template — passed in from App.jsx
 * so no org-specific logic lives here.
 *
 * Props:
 *   org — the current org object from get_current_org (has org.roles.template)
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import CustomerList from './CustomerList'
import CustomerProfile from './CustomerProfile'
import BroadcastManager from './BroadcastManager'
import TemplateManager from './TemplateManager'
import DripSequenceConfig from './DripSequenceConfig'

const VIEWS = ['customers', 'broadcasts', 'templates', 'drip']
const VIEW_LABELS = {
  customers:  '👥 Customers',
  broadcasts: '📢 Broadcasts',
  templates:  '📋 Templates',
  drip:       '💧 Drip Sequence',
}

export default function WhatsAppModule({ org }) {
  const [view, setView]               = useState('customers')
  const [selectedCustomerId, setSel]  = useState(null)

  // TEMPORARY — always true for local dev until auth/me endpoint returns roles
  const isOwner = true

  const S = {
    wrap: { minHeight: 'calc(100vh - 60px)' },
    subNav: {
      display: 'flex', gap: 4, padding: '0 28px',
      background: '#fff', borderBottom: `1px solid ${ds.border}`,
    },
    navBtn: (active) => ({
      padding: '14px 18px', border: 'none', background: 'none',
      fontSize: 13.5, fontWeight: active ? 600 : 500,
      color: active ? ds.teal : ds.gray,
      borderBottom: active ? `2.5px solid ${ds.teal}` : '2.5px solid transparent',
      cursor: 'pointer', fontFamily: ds.fontBody,
      transition: 'color 0.15s, border-color 0.15s',
    }),
  }

  function handleSelectCustomer(id) {
    setSel(id)
    // stay on customers view — CustomerProfile replaces CustomerList
  }

  function handleBack() {
    setSel(null)
  }

  return (
    <div style={S.wrap}>
      {/* Sub-navigation */}
      <div style={S.subNav}>
        {VIEWS.map(v => (
          <button
            key={v}
            style={S.navBtn(view === v)}
            onClick={() => { setView(v); setSel(null) }}
          >
            {VIEW_LABELS[v]}
          </button>
        ))}
      </div>

      {/* Content — all tabs stay mounted, visibility controlled by CSS */}
      <div style={{ display: view === 'customers' && !selectedCustomerId ? 'block' : 'none' }}>
        <CustomerList onSelectCustomer={handleSelectCustomer} />
      </div>

      {view === 'customers' && selectedCustomerId && (
        <CustomerProfile customerId={selectedCustomerId} onBack={handleBack} />
      )}

      <div style={{ display: view === 'broadcasts' ? 'block' : 'none' }}>
        <BroadcastManager />
      </div>

      <div style={{ display: view === 'templates' ? 'block' : 'none' }}>
        <TemplateManager />
      </div>

      <div style={{ display: view === 'drip' ? 'block' : 'none' }}>
        <DripSequenceConfig isOwner={isOwner} />
      </div>
    </div>
  )
}
