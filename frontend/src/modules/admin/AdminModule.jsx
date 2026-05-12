/**
 * frontend/src/modules/admin/AdminModule.jsx
 * Admin Dashboard — Phase 8B
 *
 * WH-1b update: "Qualification Bot" tab swapped for "Qualification Flow" tab.
 * CONFIG-2: "🏢 Business Types" tab added.
 * CONFIG-3: "🕐 Business Hours" tab added.
 * SM-1: "🛒 Sales System" tab added — SalesModeConfig + ContactMenuConfig.
 * SHOP-1B: "🛍️ Shopify" tab added — ShopifyIntegration.
 * GPM-1E: "💰 Sales Log" tab added — SalesLog.
 * MULTI-ORG-WA-1: "📱 WhatsApp" tab added — WhatsAppIntegration.
 * LEAD-FORM-CONFIG: "📋 Lead Form" tab added — LeadFormConfig.
 *
 * LAZY MOUNT FIX: Tab components are only mounted when first visited.
 * Once mounted they stay mounted (display:none) to preserve state.
 * This replaces Pattern 26 (mount-all-on-load) which caused 25+ simultaneous
 * API calls on mount, saturating the Supabase connection pool and triggering
 * the sign-out loop via clearAuth().
 *
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
import SalesModeConfig         from './SalesModeConfig'
import ContactMenuConfig       from './ContactMenuConfig'
import ShopifyIntegration      from './ShopifyIntegration'
import GrowthConfig            from './GrowthConfig'
import SalesLog                from './SalesLog'
import WhatsAppIntegration     from './WhatsAppIntegration'
import CommerceSettings        from './CommerceSettings'
import MessagingLimitsConfig   from './MessagingLimitsConfig'
import LeadAssignmentConfig    from './LeadAssignmentConfig'
import LeadFormConfig          from './LeadFormConfig'
import GrowthDashboardConfig   from './GrowthDashboardConfig'
import WASalesModeConfig       from './WASalesModeConfig'

const TABS = [
  { id: 'users',            label: '👥 Users' },
  { id: 'roles',            label: '🎭 Roles' },
  { id: 'routing',          label: '🔀 Routing Rules' },
  { id: 'integrations',     label: '🔌 Integrations' },
  { id: 'whatsapp',         label: '📱 WhatsApp' },
  { id: 'commission',       label: '💼 Commissions' },
  { id: 'scoring',          label: '🎯 Lead Scoring' },
  { id: 'qualification',    label: '📋 Qualification Flow' },
  { id: 'lead-form',        label: '📝 Lead Form' },
  { id: 'growth-dashboard', label: '📊 Dashboard Config' },
  { id: 'sla',              label: '⏱️ SLA Targets' },
  { id: 'sla-hours',        label: '🕐 Business Hours' },
  { id: 'lead-assignment',  label: '🔀 Lead Assignment' },
  { id: 'nurture',          label: '🌱 Nurture Engine' },
  { id: 'whatsapp-menu',    label: '📋 WhatsApp Menu' },
  { id: 'pipeline',         label: '🗂️ Pipeline' },
  { id: 'categories',       label: '🏷️ Categories' },
  { id: 'biz-types',        label: '🏢 Business Types' },
  { id: 'sales-system',     label: '🛒 Sales System' },
  { id: 'shopify',          label: '🛍️ Shopify' },
  { id: 'commerce',         label: '🛒 Commerce' },
  { id: 'wa-sales-mode',    label: '🤖 WA Sales Mode' },
  { id: 'growth-config',    label: '📈 Growth Config' },
  { id: 'sales-log',        label: '💰 Sales Log' },
  { id: 'messaging-limits', label: '💬 Messaging Limits' },
]

const SALES_SUB_TABS = [
  { id: 'sales-mode',    label: 'Sales Mode' },
  { id: 'contact-menus', label: 'Contact Menus' },
]

// ── Lazy mount helper ─────────────────────────────────────────────────────────
// Renders children only after the tab has been visited at least once.
// Once mounted, stays mounted (display:none when inactive) to preserve state.
function LazyTab({ active, visited, children }) {
  if (!visited) return null
  return (
    <div style={{ display: active ? 'block' : 'none' }}>
      {children}
    </div>
  )
}

export default function AdminModule({ user }) {
  const [tab, setTab]                 = useState('users')
  const [salesSubTab, setSalesSubTab] = useState('sales-mode')
  const [accessDenied, setAccessDenied] = useState(false)
  const [checking, setChecking]       = useState(true)

  // Track which tabs have been visited so we only mount them on first visit
  const [visited, setVisited] = useState({ users: true }) // 'users' is default tab

  function handleTabChange(newTab) {
    setTab(newTab)
    setVisited(prev => ({ ...prev, [newTab]: true }))
  }

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
      <div style={{ background: '#0a1a24', padding: '28px 32px 0', borderBottom: '1px solid #1a2f3f' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <div style={{
            background: ds.teal, color: 'white', borderRadius: 8,
            width: 36, height: 36, display: 'flex', alignItems: 'center',
            justifyContent: 'center', fontFamily: ds.fontSyne,
            fontWeight: 800, fontSize: 12, flexShrink: 0,
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

        <div style={{ display: 'flex', gap: 0, overflowX: 'auto' }}>
          {TABS.map(t => {
            const isActive = tab === t.id
            return (
              <button
                key={t.id}
                onClick={() => handleTabChange(t.id)}
                title={t.link ? 'View-only — manage in the respective module' : undefined}
                style={{
                  background: 'none', border: 'none',
                  borderBottom: isActive ? `2px solid ${ds.teal}` : '2px solid transparent',
                  padding: '10px 18px', cursor: 'pointer',
                  fontFamily: ds.fontDm, fontSize: 13.5,
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? ds.teal : '#5a8a9f',
                  transition: 'all 0.15s', opacity: t.link ? 0.7 : 1,
                  whiteSpace: 'nowrap',
                }}
              >
                {t.label}{t.link ? ' ↗' : ''}
              </button>
            )
          })}
        </div>
      </div>

      <div style={{ padding: 28 }}>

        <LazyTab active={tab === 'users'}            visited={visited['users']}>            <UserManagement /></LazyTab>
        <LazyTab active={tab === 'roles'}            visited={visited['roles']}>            <RoleBuilder /></LazyTab>
        <LazyTab active={tab === 'routing'}          visited={visited['routing']}>          <RoutingRules /></LazyTab>
        <LazyTab active={tab === 'integrations'}     visited={visited['integrations']}>     <IntegrationStatus /></LazyTab>
        <LazyTab active={tab === 'whatsapp'}         visited={visited['whatsapp']}>         <WhatsAppIntegration /></LazyTab>
        <LazyTab active={tab === 'commission'}       visited={visited['commission']}>       <CommissionSettings /></LazyTab>
        <LazyTab active={tab === 'scoring'}          visited={visited['scoring']}>          <ScoringRubric /></LazyTab>
        <LazyTab active={tab === 'qualification'}    visited={visited['qualification']}>    <QualificationFlow /></LazyTab>
        <LazyTab active={tab === 'lead-form'}        visited={visited['lead-form']}>        <LeadFormConfig /></LazyTab>
        <LazyTab active={tab === 'growth-dashboard'} visited={visited['growth-dashboard']}> <GrowthDashboardConfig /></LazyTab>
        <LazyTab active={tab === 'sla'}              visited={visited['sla']}>              <LeadSLASettings /></LazyTab>
        <LazyTab active={tab === 'sla-hours'}        visited={visited['sla-hours']}>        <SLABusinessHoursConfig /></LazyTab>
        <LazyTab active={tab === 'lead-assignment'}  visited={visited['lead-assignment']}>  <LeadAssignmentConfig /></LazyTab>
        <LazyTab active={tab === 'nurture'}          visited={visited['nurture']}>          <NurtureSettings /></LazyTab>
        <LazyTab active={tab === 'whatsapp-menu'}    visited={visited['whatsapp-menu']}>    <CustomerMenuConfig /></LazyTab>
        <LazyTab active={tab === 'pipeline'}         visited={visited['pipeline']}>         <PipelineConfig /></LazyTab>
        <LazyTab active={tab === 'categories'}       visited={visited['categories']}>       <TicketCategoriesConfig /></LazyTab>
        <LazyTab active={tab === 'biz-types'}        visited={visited['biz-types']}>        <DripBusinessTypesConfig /></LazyTab>
        <LazyTab active={tab === 'messaging-limits'} visited={visited['messaging-limits']}> <MessagingLimitsConfig /></LazyTab>

        {/* SM-1: Sales System — sub-tabbed */}
        <LazyTab active={tab === 'sales-system'} visited={visited['sales-system']}>
          <div style={{ display: 'flex', borderBottom: '2px solid #E2EFF4', marginBottom: 24 }}>
            {SALES_SUB_TABS.map(st => (
              <button
                key={st.id}
                onClick={() => setSalesSubTab(st.id)}
                style={{
                  background: 'none', border: 'none',
                  borderBottom: `2px solid ${salesSubTab === st.id ? ds.teal : 'transparent'}`,
                  padding: '9px 18px', cursor: 'pointer',
                  fontFamily: ds.fontDm, fontSize: 13.5,
                  fontWeight: salesSubTab === st.id ? 600 : 400,
                  color: salesSubTab === st.id ? ds.teal : '#5a8a9f',
                  marginBottom: -2, whiteSpace: 'nowrap',
                }}
              >
                {st.label}
              </button>
            ))}
          </div>
          <div style={{ display: salesSubTab === 'sales-mode'    ? 'block' : 'none' }}><SalesModeConfig /></div>
          <div style={{ display: salesSubTab === 'contact-menus' ? 'block' : 'none' }}><ContactMenuConfig /></div>
        </LazyTab>

        <LazyTab active={tab === 'shopify'}      visited={visited['shopify']}>      <ShopifyIntegration /></LazyTab>
        <LazyTab active={tab === 'commerce'}     visited={visited['commerce']}>     <CommerceSettings /></LazyTab>
        <LazyTab active={tab === 'wa-sales-mode'} visited={visited['wa-sales-mode']}><WASalesModeConfig /></LazyTab>
        <LazyTab active={tab === 'growth-config'} visited={visited['growth-config']}><GrowthConfig /></LazyTab>
        <LazyTab active={tab === 'sales-log'}    visited={visited['sales-log']}>    <SalesLog /></LazyTab>

        {tab === 'kb' && (
          <LinkMessage
            icon="📚" title="Knowledge Base"
            body="KB articles are managed in the Support Tickets module."
            hint="Navigate to Support → KB Manager tab to create and publish articles."
          />
        )}
        {tab === 'templates' && (
          <LinkMessage
            icon="💬" title="WhatsApp Templates"
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
      <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 10px' }}>{title}</h3>
      <p style={{ fontSize: 14, color: '#4a7a8a', margin: '0 0 6px' }}>{body}</p>
      <p style={{ fontSize: 13, color: '#7A9BAD' }}>{hint}</p>
    </div>
  )
}
