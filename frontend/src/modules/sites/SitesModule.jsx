/**
 * frontend/src/modules/sites/SitesModule.jsx
 * SITE-1A part 2 — "Sites" (WhatsApp website builder). Spec: SITE-0_Spec.md §22.
 *
 * Tabs: Overview · Sites · Builders · Templates · Settings
 * (Hosting queue / Orders / Domains & renewals are later phases — SITE-3/4/5.)
 *
 * Pattern 26: tab panels stay mounted (display:none); each tab fetches only when
 *             isActive is true.
 * Roles: owner / ops_manager write; admin read-only (matches Event Funnels' convention).
 */
import { useCallback, useEffect, useState } from 'react'
import { LayoutDashboard, Globe, Users, LayoutTemplate, Settings } from 'lucide-react'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getSiteSettings, errorMessage } from '../../services/sites.service'
import { Toast } from './sitesUi'
import { T, useSitesStyles, useToast } from './sitesKit'
import SitesOverviewTab from './SitesOverviewTab'
import SitesListTab from './SitesListTab'
import SitesBuildersTab from './SitesBuildersTab'
import SitesTemplatesTab from './SitesTemplatesTab'
import SitesSettingsTab from './SitesSettingsTab'

const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'sites', label: 'Sites', icon: Globe },
  { id: 'builders', label: 'Builders', icon: Users },
  { id: 'templates', label: 'Templates', icon: LayoutTemplate },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export default function SitesModule({ user }) {
  useSitesStyles()
  const isMobile = useIsMobile()
  const role = user?.roles?.template ?? ''
  const canEdit = ['owner', 'ops_manager'].includes(role)
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

  return (
    <div className="sts" style={{ fontFamily: 'inherit', padding: isMobile ? '16px 14px 24px' : '24px 28px 40px' }}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: isMobile ? 21 : 24, fontWeight: 700, color: T.ink }}>Sites</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: T.muted, maxWidth: 560 }}>
          The WhatsApp website builder: one-page ordering sites for builders' clients, built and previewed by hand for now.
        </p>
      </header>

      <nav role="tablist" aria-label="Sites sections" style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${T.line}`, marginBottom: 18, overflowX: 'auto', scrollbarWidth: 'none' }}>
        {TABS.map((t) => {
          const on = tab === t.id
          const Icon = t.icon
          return (
            <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => setTab(t.id)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 7, minHeight: 44, padding: '0 14px', border: 'none', background: 'none',
                borderBottom: `2px solid ${on ? T.teal : 'transparent'}`, marginBottom: -1, color: on ? T.teal : T.soft, fontWeight: on ? 700 : 500,
                fontSize: 13.5, fontFamily: 'inherit', cursor: 'pointer', whiteSpace: 'nowrap' }}>
              <Icon size={15} strokeWidth={on ? 2.3 : 1.9} aria-hidden="true" />
              {t.label}
            </button>
          )
        })}
      </nav>

      <Panel on={tab === 'overview'}>
        <SitesOverviewTab isActive={tab === 'overview'} enabled={!!enabled} onGoSettings={() => setTab('settings')} />
      </Panel>
      <Panel on={tab === 'sites'}>
        <SitesListTab isActive={tab === 'sites'} canEdit={canEdit} enabled={!!enabled} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'builders'}>
        <SitesBuildersTab isActive={tab === 'builders'} canEdit={canEdit} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'templates'}>
        <SitesTemplatesTab isActive={tab === 'templates'} canEdit={canEdit} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'settings'}>
        <SitesSettingsTab isActive={tab === 'settings'} canEdit={canEdit} showToast={showToast} onEnabledChange={setEnabled} />
      </Panel>

      <Toast t={toast} />
    </div>
  )
}

function Panel({ on, children }) {
  return <div role="tabpanel" style={{ display: on ? 'block' : 'none' }}>{children}</div>
}
