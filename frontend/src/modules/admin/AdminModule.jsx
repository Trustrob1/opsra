/**
 * frontend/src/modules/admin/AdminModule.jsx
 * Admin Dashboard — Phase 8B
 *
 * WH-1b update: "Qualification Bot" tab swapped for "Qualification Flow" tab.
 * CONFIG-2: "🏢 Business Types" tab added.
 * CONFIG-3: "🕐 Business Hours" tab added.
 *
 * Pattern 26: main content tabs use mount-and-hide (display:none) to preserve
 * table state, filters, and open modals when switching between tabs.
 * Pattern 51: full rewrite only — never sed.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import UserManagement          from './UserManagement'
import RoleBuilder             from './RoleBuilder'
import RoutingRules            from './RoutingRules'
import IntegrationStatus       from './IntegrationStatus'
import CommissionSettings      from './CommissionSettings'
import ScoringRubric           from './ScoringRubric'
import QualificationFlow       from './QualificationFlow'
import LeadSLASettings         from './LeadSLASettings'
import NurtureSettings         from './NurtureSettings'
import CustomerMenuConfig      from './CustomerMenuConfig'
import PipelineConfig          from './PipelineConfig'
import TicketCategoriesConfig  from './TicketCategoriesConfig'
import DripBusinessTypesConfig from './DripBusinessTypesConfig'
import SLABusinessHoursConfig  from './SLABusinessHoursConfig'

const TABS = [
  { id: 'users',          label: '👥 Users' },
  { id: 'roles',          label: '🎭 Roles' },
  { id: 'routing',        label: '🔀 Routing Rules' },
  { id: 'integrations',   label: '🔌 Integrations' },
  { id: 'commission',     label: '💼 Commissions' },
  { id: 'scoring',        label: '🎯 Lead Scoring' },
  { id: 'qualification',  label: '📋 Qualification Flow' },
  { id: 'sla',            label: '⏱️ SLA Targets' },
  { id: 'sla-hours',      label: '🕐 Business Hours' },
  { id: 'nurture',        label: '🌱 Nurture Engine' },
  { id: 'whatsapp-menu',  label: '📋 WhatsApp Menu' },
  { id: 'pipeline',       label: '🗂️ Pipeline' },
  { id: 'categories',     label: '🏷️ Categories' },
  { id: 'biz-types',      label: '🏢 Business Types' },
  { id: 'kb',             label: '📚 Knowledge Base', link: true },
  { id: 'templates',      label: '💬 WA Templates',   link: true },
]

export default function AdminModule({ user }) {
  const [tab, setTab]               = useState('users')
  const [accessDenied, setAccessDenied] = useState(false)
  const [checking, setChecking]     = useState(true)

  useEffect(() => {
    adminSvc.listUsers()
      .then(() => setChecking(false))
      .catch(err => {
        if (err?.response?.status === 403) setAccessDenied(true)
        setChecking(false)
      })
  }, [])

  if (checking) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
        <div style={{ fontSize: 24, marginBottom: 8 }}>⚙️</div>
        Checking access…
      </div>
    )
  }

  if (accessDenied) {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🔒</div>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: '#0a1a24', margin: '0 0 10px' }}>
          Access Restricted
        </h2>
        <p style={{ fontSize: 14, color: '#7A9BAD', maxWidth: 360, margin: '0 auto', lineHeight: 1.6 }}>
          You need Owner or Admin access to view this section.
          Contact your organisation administrator.
        </p>
      </div>
    )
  }

  return (
    <div>
      {/* Module header */}
      <div style={{
        background:   '#0a1a24',
        padding:      '28px 32px 0',
        borderBottom: '1px solid #1a2f3f',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <div style={{
            background:     ds.teal,
            color:          'white',
            borderRadius:   8,
            width:          36,
            height:         36,
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            fontFamily:     ds.fontSyne,
            fontWeight:     800,
            fontSize:       12,
            flexShrink:     0,
          }}>
            08
          </div>
          <div>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: 'white', margin: 0 }}>
              Admin Dashboard
            </h1>
            <p style={{ fontSize: 12, color: '#5a8a9f', margin: '2px 0 0' }}>
              Users · Roles · Routing rules · Integrations
            </p>
          </div>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 0, overflowX: 'auto' }}>
          {TABS.map(t => {
            const isActive = tab === t.id
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                title={t.link ? 'View-only — manage in the respective module' : undefined}
                style={{
                  background:   'none',
                  border:       'none',
                  borderBottom: isActive ? `2px solid ${ds.teal}` : '2px solid transparent',
                  padding:      '10px 18px',
                  cursor:       'pointer',
                  fontFamily:   ds.fontDm,
                  fontSize:     13.5,
                  fontWeight:   isActive ? 600 : 400,
                  color:        isActive ? ds.teal : '#5a8a9f',
                  transition:   'all 0.15s',
                  opacity:      t.link ? 0.7 : 1,
                  whiteSpace:   'nowrap',
                }}
              >
                {t.label}{t.link ? ' ↗' : ''}
              </button>
            )
          })}
        </div>
      </div>

      {/* Tab content */}
      <div style={{ padding: 28 }}>

        {/* Pattern 26: mount-and-hide — preserves table state + open modals */}
        <div style={{ display: tab === 'users' ? 'block' : 'none' }}>
          <UserManagement />
        </div>
        <div style={{ display: tab === 'roles' ? 'block' : 'none' }}>
          <RoleBuilder />
        </div>
        <div style={{ display: tab === 'routing' ? 'block' : 'none' }}>
          <RoutingRules />
        </div>
        <div style={{ display: tab === 'integrations' ? 'block' : 'none' }}>
          <IntegrationStatus />
        </div>
        <div style={{ display: tab === 'commission' ? 'block' : 'none' }}>
          <CommissionSettings />
        </div>
        <div style={{ display: tab === 'scoring' ? 'block' : 'none' }}>
          <ScoringRubric />
        </div>
        <div style={{ display: tab === 'qualification' ? 'block' : 'none' }}>
          <QualificationFlow />
        </div>
        <div style={{ display: tab === 'sla' ? 'block' : 'none' }}>
          <LeadSLASettings />
        </div>
        <div style={{ display: tab === 'sla-hours' ? 'block' : 'none' }}>
          <SLABusinessHoursConfig />
        </div>
        <div style={{ display: tab === 'nurture' ? 'block' : 'none' }}>
          <NurtureSettings />
        </div>
        <div style={{ display: tab === 'whatsapp-menu' ? 'block' : 'none' }}>
          <CustomerMenuConfig />
        </div>
        <div style={{ display: tab === 'pipeline' ? 'block' : 'none' }}>
          <PipelineConfig />
        </div>
        <div style={{ display: tab === 'categories' ? 'block' : 'none' }}>
          <TicketCategoriesConfig />
        </div>
        <div style={{ display: tab === 'biz-types' ? 'block' : 'none' }}>
          <DripBusinessTypesConfig />
        </div>

        {/* Nav links — conditional render (no state to preserve) */}
        {tab === 'kb' && (
          <LinkMessage
            icon="📚"
            title="Knowledge Base"
            body="KB articles are managed in the Support Tickets module."
            hint="Navigate to Support → KB Manager tab to create and publish articles."
          />
        )}
        {tab === 'templates' && (
          <LinkMessage
            icon="💬"
            title="WhatsApp Templates"
            body="Message templates are managed in the WhatsApp Engine module."
            hint="Navigate to WhatsApp → Templates tab to create and manage templates."
          />
        )}
      </div>
    </div>
  )
}

function LinkMessage({ icon, title, body, hint }) {
  return (
    <div style={{ textAlign: 'center', padding: '48px 32px' }}>
      <div style={{ fontSize: 40, marginBottom: 14 }}>{icon}</div>
      <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 10px' }}>
        {title}
      </h3>
      <p style={{ fontSize: 14, color: '#4a7a8a', margin: '0 0 6px' }}>{body}</p>
      <p style={{ fontSize: 13, color: '#7A9BAD' }}>{hint}</p>
    </div>
  )
}
