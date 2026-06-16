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
 * UI-SIDEBAR: Horizontal tab bar replaced with collapsible left sidebar.
 *   Expanded: 210px with icon + label. Collapsed: 52px icon-only.
 *   Toggle button at top of sidebar. Sidebar state persisted in localStorage.
 *   Tabs grouped into logical sections for scannability.
 * UI-ICONS: Lucide React icons replace all emojis in sidebar nav.
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
import {
  Users, Shield, GitBranch, Plug, Smartphone,
  Briefcase, Target, ClipboardList, FileText, BarChart2,
  Clock, AlarmClock, ArrowRightLeft, Leaf, Menu as MenuIcon,
  Layers, Tag, UsersRound, AlertCircle, Building2,
  ShoppingCart, ShoppingBag, Store, Bot, TrendingUp,
  DollarSign, MessageSquare, CalendarDays, Zap, Package,
  ChevronLeft, ChevronRight, Settings,
} from 'lucide-react'
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
import TeamsConfig                    from './TeamsConfig'
import InternalIssueCategoriesConfig  from './InternalIssueCategoriesConfig'
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
import AutomationConfig        from './AutomationConfig'
import DemoSettings            from './DemoSettings'
import CatalogConfig           from './CatalogConfig'
import CatalogItems            from './CatalogItems'

// ── Sidebar tab groups ────────────────────────────────────────────────────────
const TAB_GROUPS = [
  {
    section: 'Organisation',
    tabs: [
      { id: 'users',         label: 'Users',           Icon: Users },
      { id: 'roles',         label: 'Roles',           Icon: Shield },
      { id: 'teams',         label: 'Teams',           Icon: UsersRound },
      { id: 'routing',       label: 'Routing Rules',   Icon: GitBranch },
      { id: 'integrations',  label: 'Integrations',    Icon: Plug },
    ],
  },
  {
    section: 'Leads',
    tabs: [
      { id: 'pipeline',        label: 'Pipeline',        Icon: Layers },
      { id: 'scoring',         label: 'Lead Scoring',    Icon: Target },
      { id: 'lead-assignment', label: 'Lead Assignment', Icon: ArrowRightLeft },
      { id: 'lead-form',       label: 'Lead Form',       Icon: FileText },
      { id: 'qualification',   label: 'Qual. Flow',      Icon: ClipboardList },
      { id: 'nurture',         label: 'Nurture Engine',  Icon: Leaf },
    ],
  },
  {
    section: 'WhatsApp',
    tabs: [
      { id: 'whatsapp',         label: 'WhatsApp',      Icon: Smartphone },
      { id: 'whatsapp-menu',    label: 'WA Menu',       Icon: MenuIcon },
      { id: 'wa-sales-mode',    label: 'WA Sales Mode', Icon: Bot },
      { id: 'messaging-limits', label: 'Msg Limits',    Icon: MessageSquare },
    ],
  },
  {
    section: 'Commerce',
    tabs: [
      { id: 'catalog',      label: 'Catalog',     Icon: Package },
      { id: 'sales-system', label: 'Sales System',Icon: ShoppingCart },
      { id: 'shopify',      label: 'Shopify',     Icon: ShoppingBag },
      { id: 'commerce',     label: 'Commerce',    Icon: Store },
      { id: 'sales-log',    label: 'Sales Log',   Icon: DollarSign },
      { id: 'commission',   label: 'Commissions', Icon: Briefcase },
    ],
  },
  {
    section: 'Support',
    tabs: [
      { id: 'categories',   label: 'Categories',       Icon: Tag },
      { id: 'internal_cats',label: 'Issue Categories', Icon: AlertCircle },
      { id: 'sla',          label: 'SLA Targets',      Icon: AlarmClock },
      { id: 'sla-hours',    label: 'Business Hours',   Icon: Clock },
    ],
  },
  {
    section: 'Growth & Config',
    tabs: [
      { id: 'growth-dashboard', label: 'Dashboard Config', Icon: BarChart2 },
      { id: 'growth-config',    label: 'Growth Config',    Icon: TrendingUp },
      { id: 'biz-types',        label: 'Business Types',   Icon: Building2 },
      { id: 'automation',       label: 'Automation',       Icon: Zap },
      { id: 'demo-settings',    label: 'Demo Settings',    Icon: CalendarDays },
    ],
  },
]

// Flat list for lookup
const ALL_TABS = TAB_GROUPS.flatMap(g => g.tabs)

const SALES_SUB_TABS = [
  { id: 'sales-mode',    label: 'Sales Mode' },
  { id: 'contact-menus', label: 'Contact Menus' },
]

const CATALOG_SUB_TABS = [
  { id: 'catalog-config', label: '⚙️ Config' },
  { id: 'catalog-items',  label: '📦 Items' },
]

// ── Sidebar width constants ───────────────────────────────────────────────────
const SIDEBAR_W_OPEN   = 210
const SIDEBAR_W_CLOSED = 52

// ── Lazy mount helper ─────────────────────────────────────────────────────────
function LazyTab({ active, visited, children }) {
  if (!visited) return null
  return (
    <div style={{ display: active ? 'block' : 'none' }}>
      {children}
    </div>
  )
}

// ── Sub-tab bar ───────────────────────────────────────────────────────────────
function SubTabBar({ tabs, active, onChange }) {
  return (
    <div style={{ display: 'flex', borderBottom: '2px solid #E2EFF4', marginBottom: 24 }}>
      {tabs.map(st => (
        <button
          key={st.id}
          onClick={() => onChange(st.id)}
          style={{
            background: 'none', border: 'none',
            borderBottom: `2px solid ${active === st.id ? ds.teal : 'transparent'}`,
            padding: '9px 18px', cursor: 'pointer',
            fontFamily: ds.fontDm, fontSize: 13.5,
            fontWeight: active === st.id ? 600 : 400,
            color: active === st.id ? ds.teal : '#5a8a9f',
            marginBottom: -2, whiteSpace: 'nowrap',
          }}
        >
          {st.label}
        </button>
      ))}
    </div>
  )
}

export default function AdminModule({ user }) {
  const [tab, setTab]                     = useState('users')
  const [salesSubTab, setSalesSubTab]     = useState('sales-mode')
  const [catalogSubTab, setCatalogSubTab] = useState('catalog-config')
  const [accessDenied, setAccessDenied]   = useState(false)
  const [checking, setChecking]           = useState(true)
  const [visited, setVisited]             = useState({ users: true })

  // Sidebar open/closed — persist preference
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try {
      const stored = localStorage.getItem('admin_sidebar_open')
      return stored === null ? true : stored === 'true'
    } catch { return true }
  })

  function toggleSidebar() {
    setSidebarOpen(prev => {
      const next = !prev
      try { localStorage.setItem('admin_sidebar_open', String(next)) } catch {}
      return next
    })
  }

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

  const activeTabMeta = ALL_TABS.find(t => t.id === tab)
  const ActiveIcon = activeTabMeta?.Icon ?? Settings
  const sidebarW = sidebarOpen ? SIDEBAR_W_OPEN : SIDEBAR_W_CLOSED

  return (
    <div style={{ display: 'flex', minHeight: '100%' }}>

      {/* ── Collapsible Sidebar ── */}
      <div style={{
        width: sidebarW,
        minWidth: sidebarW,
        background: '#0a1a24',
        borderRight: '1px solid #1a2f3f',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.2s ease, min-width 0.2s ease',
        overflow: 'hidden',
        flexShrink: 0,
      }}>

        {/* Sidebar header */}
        <div style={{
          padding: sidebarOpen ? '16px 14px 13px' : '16px 0 13px',
          borderBottom: '1px solid #1a2f3f',
          display: 'flex',
          alignItems: 'center',
          justifyContent: sidebarOpen ? 'space-between' : 'center',
          gap: 8,
        }}>
          {sidebarOpen && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
              <div style={{
                background: ds.teal, color: 'white', borderRadius: 7,
                width: 30, height: 30, display: 'flex', alignItems: 'center',
                justifyContent: 'center', fontFamily: ds.fontSyne,
                fontWeight: 800, fontSize: 11, flexShrink: 0,
              }}>
                08
              </div>
              <span style={{
                fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14,
                color: 'white', whiteSpace: 'nowrap',
              }}>
                Admin
              </span>
            </div>
          )}
          <button
            onClick={toggleSidebar}
            title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: '#5a8a9f', padding: 4, borderRadius: 6,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {sidebarOpen
              ? <ChevronLeft size={16} />
              : <ChevronRight size={16} />
            }
          </button>
        </div>

        {/* Nav groups */}
        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', paddingBottom: 16 }}>
          {TAB_GROUPS.map(group => (
            <div key={group.section}>
              {sidebarOpen ? (
                <div style={{
                  padding: '14px 14px 4px',
                  fontSize: 10, fontWeight: 600,
                  color: '#3a6a7f', textTransform: 'uppercase',
                  letterSpacing: '0.08em', whiteSpace: 'nowrap',
                }}>
                  {group.section}
                </div>
              ) : (
                <div style={{
                  height: 1, background: '#1a2f3f',
                  margin: '10px 10px 6px',
                }} />
              )}

              {group.tabs.map(t => {
                const isActive = tab === t.id
                const { Icon } = t
                return (
                  <button
                    key={t.id}
                    onClick={() => handleTabChange(t.id)}
                    title={!sidebarOpen ? t.label : undefined}
                    style={{
                      width: '100%', border: 'none',
                      cursor: 'pointer', textAlign: 'left',
                      display: 'flex', alignItems: 'center',
                      gap: sidebarOpen ? 10 : 0,
                      justifyContent: sidebarOpen ? 'flex-start' : 'center',
                      padding: sidebarOpen ? '7px 14px' : '8px 0',
                      borderLeft: isActive
                        ? `3px solid ${ds.teal}`
                        : '3px solid transparent',
                      background: isActive
                        ? 'rgba(2,128,144,0.12)'
                        : 'transparent',
                      transition: 'background 0.12s',
                    }}
                  >
                    <Icon
                      size={16}
                      color={isActive ? ds.teal : '#5a8a9f'}
                      strokeWidth={isActive ? 2.5 : 1.8}
                      style={{ flexShrink: 0 }}
                    />
                    {sidebarOpen && (
                      <span style={{
                        fontFamily: ds.fontDm, fontSize: 13,
                        fontWeight: isActive ? 600 : 400,
                        color: isActive ? ds.teal : '#7a9bad',
                        whiteSpace: 'nowrap', overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}>
                        {t.label}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* ── Main content area ── */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>

        {/* Content header */}
        <div style={{
          background: '#0a1a24',
          padding: '16px 28px 14px',
          borderBottom: '1px solid #1a2f3f',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <ActiveIcon size={18} color={ds.teal} strokeWidth={2} />
          <div>
            <h1 style={{
              fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18,
              color: 'white', margin: 0,
            }}>
              {activeTabMeta?.label ?? 'Admin Dashboard'}
            </h1>
            <p style={{ fontSize: 11, color: '#5a8a9f', margin: '2px 0 0' }}>
              Admin · {TAB_GROUPS.find(g => g.tabs.some(t => t.id === tab))?.section ?? 'Settings'}
            </p>
          </div>
        </div>

        {/* Tab content */}
        <div style={{ padding: 28, flex: 1, minWidth: 0 }}>

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
          <LazyTab active={tab === 'teams'}            visited={visited['teams']}>            <TeamsConfig /></LazyTab>
          <LazyTab active={tab === 'internal_cats'}    visited={visited['internal_cats']}>    <InternalIssueCategoriesConfig /></LazyTab>
          <LazyTab active={tab === 'biz-types'}        visited={visited['biz-types']}>        <DripBusinessTypesConfig /></LazyTab>
          <LazyTab active={tab === 'messaging-limits'} visited={visited['messaging-limits']}> <MessagingLimitsConfig /></LazyTab>
          <LazyTab active={tab === 'demo-settings'}    visited={visited['demo-settings']}>    <DemoSettings /></LazyTab>
          <LazyTab active={tab === 'automation'}       visited={visited['automation']}>       <AutomationConfig /></LazyTab>

          <LazyTab active={tab === 'catalog'} visited={visited['catalog']}>
            <SubTabBar tabs={CATALOG_SUB_TABS} active={catalogSubTab} onChange={setCatalogSubTab} />
            <div style={{ display: catalogSubTab === 'catalog-config' ? 'block' : 'none' }}><CatalogConfig /></div>
            <div style={{ display: catalogSubTab === 'catalog-items'  ? 'block' : 'none' }}><CatalogItems /></div>
          </LazyTab>

          <LazyTab active={tab === 'sales-system'} visited={visited['sales-system']}>
            <SubTabBar tabs={SALES_SUB_TABS} active={salesSubTab} onChange={setSalesSubTab} />
            <div style={{ display: salesSubTab === 'sales-mode'    ? 'block' : 'none' }}><SalesModeConfig /></div>
            <div style={{ display: salesSubTab === 'contact-menus' ? 'block' : 'none' }}><ContactMenuConfig /></div>
          </LazyTab>

          <LazyTab active={tab === 'shopify'}       visited={visited['shopify']}>       <ShopifyIntegration /></LazyTab>
          <LazyTab active={tab === 'commerce'}      visited={visited['commerce']}>      <CommerceSettings /></LazyTab>
          <LazyTab active={tab === 'wa-sales-mode'} visited={visited['wa-sales-mode']}> <WASalesModeConfig /></LazyTab>
          <LazyTab active={tab === 'growth-config'} visited={visited['growth-config']}> <GrowthConfig /></LazyTab>
          <LazyTab active={tab === 'sales-log'}     visited={visited['sales-log']}>     <SalesLog /></LazyTab>

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
