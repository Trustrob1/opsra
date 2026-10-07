/**
 * frontend/src/modules/sites/SitesModule.jsx
 * SITE-1A part 2 — "Sites" (WhatsApp website builder). Spec: SITE-0_Spec.md §22.
 *
 * Tabs (spec §13): Overview · Hosting queue · Orders · Sites · Domains & renewals · Builders · Templates · Settings
 * Orders / Hosting queue / Domains & renewals are SITE-3 part 3. Approve, reject and record-refund
 * are owner-only (spec §17); everything else follows canEdit (owner / ops_manager).
 *
 * Pattern 26: tab panels stay mounted (display:none); each tab fetches only when
 *             isActive is true.
 * Roles: owner / ops_manager write; admin read-only (matches Event Funnels' convention).
 */
import { useCallback, useEffect, useState } from 'react'
import { LayoutDashboard, Globe, Users, LayoutTemplate, Settings, Server, ClipboardList, CalendarClock, Handshake } from 'lucide-react'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getSiteSettings, getSitesOverview } from '../../services/sites.service'
import { Toast } from './sitesUi'
import { T, useSitesStyles, useToast } from './sitesKit'
import SitesOverviewTab from './SitesOverviewTab'
import SitesListTab from './SitesListTab'
import SitesBuildersTab from './SitesBuildersTab'
import SitesPartnersTab from './SitesPartnersTab'                         // PARTNER-1B
import SitesTemplatesTab from './SitesTemplatesTab'
import SitesSettingsTab from './SitesSettingsTab'
import SitesOrdersTab from './SitesOrdersTab'
import SitesHostingTab from './SitesHostingTab'
import SitesDomainsTab from './SitesDomainsTab'
import { CountPill } from './sitesOpsUi'

const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'hosting', label: 'Hosting queue', icon: Server },
  { id: 'orders', label: 'Orders', icon: ClipboardList },
  { id: 'sites', label: 'Sites', icon: Globe },
  { id: 'domains', label: 'Domains & renewals', icon: CalendarClock },
  { id: 'builders', label: 'Builders', icon: Users },
  { id: 'partners', label: 'Partners', icon: Handshake },
  { id: 'templates', label: 'Templates', icon: LayoutTemplate },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export default function SitesModule({ user }) {
  useSitesStyles()
  const isMobile = useIsMobile()
  const role = user?.roles?.template ?? ''
  const canEdit = ['owner', 'ops_manager'].includes(role)
  const canApprove = role === 'owner' // spec §17 — approve / reject / record refund
  const [toast, showToast] = useToast()
  const [tab, setTab] = useState('overview')
  const [enabled, setEnabled] = useState(null)

  const loadEnabled = useCallback(async () => {
    try {
      const row = await getSiteSettings()
      setEnabled(!!row?.enabled)
    } catch (e) {
      setEnabled(false)
    }
  }, [])

  useEffect(() => { loadEnabled() }, [loadEnabled])

  // Small counts on the Orders / Hosting tabs — refreshed on every tab switch and after any action.
  const [counts, setCounts] = useState(null)
  const loadCounts = useCallback(() => getSitesOverview()
    .then((ov) => setCounts(ov?.orders ? {
      approval: ov.orders.orders_awaiting_approval || 0,
      refunds: ov.orders.orders_refund_pending || 0,
      jobs: ov.orders.hosting_jobs_open || 0,
      overdue: ov.orders.hosting_jobs_overdue || 0,
    } : null))
    .catch(() => setCounts(null)), []) // the pills are a convenience — never block the tabs on them
  useEffect(() => { if (enabled) loadCounts() }, [enabled, tab, loadCounts])

  return (
    <div className="sts" style={{ fontFamily: 'inherit', padding: isMobile ? '16px 14px 24px' : '24px 28px 40px' }}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: isMobile ? 21 : 24, fontWeight: 700, color: T.ink }}>Sites</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: T.muted, maxWidth: 560 }}>
          The WhatsApp website builder: one-page ordering sites for builders' clients — from preview to paid order, hosting and renewal.
        </p>
      </header>

      <nav role="tablist" aria-label="Sites sections" style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${T.line}`, marginBottom: 18, overflowX: 'auto', scrollbarWidth: 'none' }}>
        {TABS.map((t) => {
          const on = tab === t.id
          const Icon = t.icon
          const pill = t.id === 'orders' ? { n: (counts?.approval || 0) + (counts?.refunds || 0), tone: 'warn', label: 'orders need you' }
            : t.id === 'hosting' ? { n: counts?.overdue || counts?.jobs || 0, tone: counts?.overdue ? 'bad' : 'warn',
              label: counts?.overdue ? 'jobs overdue' : 'open jobs' } : null
          return (
            <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => setTab(t.id)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 7, minHeight: 44, padding: '0 14px', border: 'none', background: 'none',
                borderBottom: `2px solid ${on ? T.teal : 'transparent'}`, marginBottom: -1, color: on ? T.teal : T.soft, fontWeight: on ? 700 : 500,
                fontSize: 13.5, fontFamily: 'inherit', cursor: 'pointer', whiteSpace: 'nowrap' }}>
              <Icon size={15} strokeWidth={on ? 2.3 : 1.9} aria-hidden="true" />
              {t.label}
              {pill && <CountPill n={pill.n} tone={pill.tone} label={pill.label} />}
            </button>
          )
        })}
      </nav>

      <Panel on={tab === 'overview'}>
        <SitesOverviewTab isActive={tab === 'overview'} enabled={!!enabled} onGoSettings={() => setTab('settings')} onGoTab={setTab} />
      </Panel>
      <Panel on={tab === 'hosting'}>
        <SitesHostingTab isActive={tab === 'hosting'} user={user} canEdit={canEdit} showToast={showToast}
          onGoOrders={() => setTab('orders')} onChanged={loadCounts} />
      </Panel>
      <Panel on={tab === 'orders'}>
        <SitesOrdersTab isActive={tab === 'orders'} canApprove={canApprove} canEdit={canEdit} showToast={showToast}
          onGoHosting={() => setTab('hosting')} onChanged={loadCounts} />
      </Panel>
      <Panel on={tab === 'sites'}>
        <SitesListTab isActive={tab === 'sites'} canEdit={canEdit} enabled={!!enabled} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'domains'}>
        <SitesDomainsTab isActive={tab === 'domains'} canEdit={canEdit} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'builders'}>
        <SitesBuildersTab isActive={tab === 'builders'} canEdit={canEdit} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'partners'}>
        <SitesPartnersTab isActive={tab === 'partners'} canEdit={canEdit} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'templates'}>
        <SitesTemplatesTab isActive={tab === 'templates'} canEdit={canEdit} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'settings'}>
        <SitesSettingsTab isActive={tab === 'settings'} canEdit={canEdit} isOwner={canApprove} showToast={showToast} onEnabledChange={setEnabled} />
      </Panel>

      <Toast t={toast} />
    </div>
  )
}

function Panel({ on, children }) {
  return <div role="tabpanel" style={{ display: on ? 'block' : 'none' }}>{children}</div>
}
