/**
 * frontend/src/modules/funnels/EventFunnelsModule.jsx
 * FUNNEL-1B — "Event Funnels" (Sales & Marketing). Spec: FUNNEL-1_Spec.md §15.2.
 *
 * List of funnels → one funnel with tabs:
 *   Overview · Leads · Attendees · Messages · Broadcast · Setup
 *
 * Pattern 26: tab panels stay mounted (display:none); every tab fetches only when
 *             `isActive` is true (no hidden-tab fetch storms — REPORTS-DEPT-1 lesson).
 * Pattern 13: view state is local (no router).
 * Roles: owner / ops_manager write; admin read-only (canEdit=false hides write actions).
 *
 * Props:
 *   user       — current user (auth store)
 *   onOpenLead — (leadId) => void, opens Lead Center profile (chat lives there)
 */
import { useCallback, useEffect, useState } from 'react'
import {
  ArrowLeft, Plus, CalendarClock, LayoutDashboard, Users, UserCheck, MessageSquareText, Megaphone, Settings,
} from 'lucide-react'
import { useIsMobile } from '../../hooks/useIsMobile'
import { listFunnels, getFunnel, getOverview, errorMessage } from '../../services/funnels.service'
import { Card, Button, Badge, Spinner, Empty, Notice, Toast } from './funnelUi'
import { T, FUNNEL_STATUS, dateTime, money, useFunnelStyles, useToast } from './funnelKit'
import CreateFunnelModal from './CreateFunnelModal'
import FunnelOverviewTab from './FunnelOverviewTab'
import FunnelLeadsTab from './FunnelLeadsTab'
import FunnelAttendeesTab from './FunnelAttendeesTab'
import FunnelMessagesTab from './FunnelMessagesTab'
import FunnelBroadcastTab from './FunnelBroadcastTab'
import FunnelSetupTab from './FunnelSetupTab'

const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'leads', label: 'Leads', icon: Users },
  { id: 'attendees', label: 'Attendees', icon: UserCheck },
  { id: 'messages', label: 'Messages', icon: MessageSquareText },
  { id: 'broadcast', label: 'Broadcast', icon: Megaphone },
  { id: 'setup', label: 'Setup', icon: Settings },
]

export default function EventFunnelsModule({ user, onOpenLead }) {
  useFunnelStyles()
  const isMobile = useIsMobile()
  const role = user?.roles?.template ?? ''
  const canEdit = ['owner', 'ops_manager'].includes(role)
  const [toast, showToast] = useToast()

  const [funnels, setFunnels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [creating, setCreating] = useState(false)

  const loadList = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setFunnels(await listFunnels())
    } catch (e) {
      setError(errorMessage(e, 'Could not load funnels.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadList() }, [loadList])

  if (selectedId) {
    return (
      <div className="fnl" style={{ fontFamily: 'inherit' }}>
        <FunnelDetail id={selectedId} canEdit={canEdit} isMobile={isMobile} showToast={showToast}
          onBack={() => { setSelectedId(null); loadList() }} onOpenLead={onOpenLead}
          onOpenFunnel={(fid) => setSelectedId(fid)} />
        <Toast t={toast} />
      </div>
    )
  }

  return (
    <div className="fnl" style={{ fontFamily: 'inherit' }}>
      <header style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: isMobile ? 21 : 24, fontWeight: 700, color: T.ink }}>Event Funnels</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: T.muted, maxWidth: 560 }}>
            WhatsApp sign-ups for live events: greeting, pay link, follow-ups and seat confirmation, all automatic.
          </p>
        </div>
        {canEdit && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>New funnel</Button>}
      </header>

      {error && <Notice tone="bad" style={{ marginBottom: 16 }}>{error}</Notice>}

      {loading ? <Spinner /> : funnels.length === 0 ? (
        <Card>
          <Empty icon={CalendarClock} title="No funnels yet"
            text="Create one for your next webinar. It stays a draft until you link a WhatsApp number and switch it live."
            action={canEdit && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>New funnel</Button>} />
        </Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
          {funnels.map((f) => <FunnelCard key={f.id} f={f} onOpen={() => setSelectedId(f.id)} />)}
        </div>
      )}

      <CreateFunnelModal open={creating} onClose={() => setCreating(false)}
        onCreated={(f) => { setCreating(false); showToast('Funnel created as a draft'); setSelectedId(f.id) }} />
      <Toast t={toast} />
    </div>
  )
}

function FunnelCard({ f, onOpen }) {
  const st = FUNNEL_STATUS[f.status] || FUNNEL_STATUS.draft
  return (
    <button type="button" onClick={onOpen} className="fnl-row"
      style={{ textAlign: 'left', background: '#fff', border: `1px solid ${T.line}`, borderRadius: 12, padding: 18, cursor: 'pointer',
        fontFamily: 'inherit', display: 'flex', flexDirection: 'column', gap: 10, minHeight: 44 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, width: '100%' }}>
        <span style={{ flex: 1, minWidth: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>{f.name}</span>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      <span style={{ fontSize: 12.5, color: T.soft }}>{f.event_title}</span>
      <div className="tnum" style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12.5, color: T.muted }}>
        <span>{dateTime(f.event_starts_at)}</span>
        <span>{money(f.early_price)} → {money(f.regular_price)}</span>
        <span>{f.pricing_mode === 'deadline' ? 'Fixed deadline' : '24-hour window'}</span>
      </div>
    </button>
  )
}

function FunnelDetail({ id, canEdit, isMobile, showToast, onBack, onOpenLead, onOpenFunnel }) {
  const [funnel, setFunnel] = useState(null)
  const [overview, setOverview] = useState(null)
  const [tab, setTab] = useState('overview')
  const [error, setError] = useState(null)
  const [overviewTick, setOverviewTick] = useState(0)

  const loadFunnel = useCallback(async () => {
    try {
      setFunnel(await getFunnel(id))
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load this funnel.'))
    }
  }, [id])

  const loadOverview = useCallback(async () => {
    try { setOverview(await getOverview(id)) } catch { /* Overview tab shows its own error */ }
  }, [id])

  useEffect(() => { loadFunnel(); loadOverview() }, [loadFunnel, loadOverview])

  const refreshAll = useCallback(() => { loadFunnel(); loadOverview(); setOverviewTick((t) => t + 1) }, [loadFunnel, loadOverview])

  if (error) return (<><BackLink onBack={onBack} /><Notice tone="bad">{error}</Notice></>)
  if (!funnel) return <Spinner />

  const st = FUNNEL_STATUS[funnel.status] || FUNNEL_STATUS.draft
  const needsYou = overview?.needs_human ?? 0

  return (
    <div>
      <BackLink onBack={onBack} />
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', margin: '6px 0 16px' }}>
        <h1 style={{ margin: 0, fontSize: isMobile ? 20 : 23, fontWeight: 700, color: T.ink, minWidth: 0 }}>{funnel.name}</h1>
        <Badge tone={st.tone}>{st.label}</Badge>
        <span className="tnum" style={{ fontSize: 12.5, color: T.muted }}>
          {dateTime(funnel.event_starts_at)} · {funnel.pricing_mode === 'deadline' ? 'Fixed deadline pricing' : `${funnel.window_hours}-hour window pricing`}
        </span>
      </header>

      {funnel.status === 'draft' && (
        <Notice tone="warn" style={{ marginBottom: 14 }}>
          This funnel is a draft: nobody gets messages yet. Finish <strong>Setup</strong> and switch it live.
        </Notice>
      )}

      <nav role="tablist" aria-label="Funnel sections" style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${T.line}`, marginBottom: 18, overflowX: 'auto', scrollbarWidth: 'none' }}>
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
              {t.id === 'leads' && needsYou > 0 && (
                <span className="tnum" aria-label={`${needsYou} need you`} style={{ background: T.bad, color: '#fff', fontSize: 10.5, fontWeight: 700, borderRadius: 10, padding: '1px 6px' }}>{needsYou}</span>
              )}
            </button>
          )
        })}
      </nav>

      <Panel on={tab === 'overview'}>
        <FunnelOverviewTab funnel={funnel} isActive={tab === 'overview'} canEdit={canEdit} isMobile={isMobile}
          overview={overview} reloadOverview={loadOverview} showToast={showToast} tick={overviewTick}
          goTo={setTab} />
      </Panel>
      <Panel on={tab === 'leads'}>
        <FunnelLeadsTab funnel={funnel} isActive={tab === 'leads'} canEdit={canEdit} isMobile={isMobile}
          showToast={showToast} onOpenLead={onOpenLead} onChanged={loadOverview} needsYou={needsYou} />
      </Panel>
      <Panel on={tab === 'attendees'}>
        <FunnelAttendeesTab funnel={funnel} isActive={tab === 'attendees'} canEdit={canEdit} isMobile={isMobile} showToast={showToast} />
      </Panel>
      <Panel on={tab === 'messages'}>
        <FunnelMessagesTab funnel={funnel} isActive={tab === 'messages'} canEdit={canEdit} isMobile={isMobile}
          showToast={showToast} onSaved={loadFunnel} />
      </Panel>
      <Panel on={tab === 'broadcast'}>
        <FunnelBroadcastTab funnel={funnel} isActive={tab === 'broadcast'} canEdit={canEdit} isMobile={isMobile}
          showToast={showToast} budget={overview?.template_budget} onSent={loadOverview} />
      </Panel>
      <Panel on={tab === 'setup'}>
        <FunnelSetupTab funnel={funnel} isActive={tab === 'setup'} canEdit={canEdit} isMobile={isMobile}
          showToast={showToast} onSaved={refreshAll} onOpenFunnel={onOpenFunnel} />
      </Panel>
    </div>
  )
}

function Panel({ on, children }) {
  return <div role="tabpanel" style={{ display: on ? 'block' : 'none' }}>{children}</div>
}

function BackLink({ onBack }) {
  return (
    <button type="button" onClick={onBack}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 36, padding: '0 4px', border: 'none', background: 'none',
        color: T.teal, fontSize: 13, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer' }}>
      <ArrowLeft size={15} aria-hidden="true" /> All funnels
    </button>
  )
}
