/**
 * frontend/src/modules/sites/SitesOverviewTab.jsx
 * SITE-1A part 2 — Overview: totals by status, previews shared, builders count.
 * SITE-3 part 3 adds the money side (spec §13): paid orders, revenue and profit (this month and all time),
 * conversion, renewals due, overdue hosting jobs and orders waiting for approval.
 */
import { useCallback, useEffect, useState } from 'react'
import { Globe, Layers, Users, Eye, Wallet, TrendingUp, ClipboardList, CalendarClock, Server, TriangleAlert, Percent } from 'lucide-react'
import { getSitesOverview, errorMessage } from '../../services/sites.service'
import { Card, Kpi, SectionTitle, Notice, Spinner, Badge, Button } from './sitesUi'
import { T, num, money, SITE_STATUS } from './sitesKit'

export default function SitesOverviewTab({ isActive, enabled, onGoSettings, onGoTab }) {
  const [ov, setOv] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setOv(await getSitesOverview())
    } catch (e) {
      setError(errorMessage(e, 'Could not load the numbers.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isActive && enabled) load() }, [isActive, enabled, load])

  if (!enabled) {
    return (
      <Card>
        <SectionTitle title="Site engine is off"
          hint="Turn it on in Settings to start building and previewing sites by hand. Presets and builders can be set up either way." />
        <Badge tone="neutral" icon={Globe}>Disabled for this org</Badge>
        {onGoSettings && <div style={{ marginTop: 14 }}><a href="#" onClick={(e) => { e.preventDefault(); onGoSettings() }}
          style={{ fontSize: 13, fontWeight: 600, color: T.teal, textDecoration: 'none' }}>Go to Settings →</a></div>}
      </Card>
    )
  }

  if (loading) return <Spinner />
  if (error) return <Notice tone="bad">{error}</Notice>
  if (!ov) return null

  const kpiGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(165px, 1fr))', gap: 12 }
  const byStatus = ov.sites_by_status || {}
  const statusEntries = Object.entries(byStatus)
  const o = ov.orders // null when the order figures couldn't be worked out

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {o && (o.orders_awaiting_approval > 0 || o.hosting_jobs_overdue > 0 || o.orders_refund_pending > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {o.orders_awaiting_approval > 0 && (
            <Notice tone="warn" icon={ClipboardList}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                {o.orders_awaiting_approval} paid order{o.orders_awaiting_approval === 1 ? ' is' : 's are'} waiting for your approval.
                {onGoTab && <Button size="sm" onClick={() => onGoTab('orders')}>Review orders</Button>}
              </span>
            </Notice>
          )}
          {o.hosting_jobs_overdue > 0 && (
            <Notice tone="bad" icon={TriangleAlert}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                {o.hosting_jobs_overdue} hosting job{o.hosting_jobs_overdue === 1 ? ' is' : 's are'} past the 24-hour deadline.
                {onGoTab && <Button size="sm" onClick={() => onGoTab('hosting')}>Open the queue</Button>}
              </span>
            </Notice>
          )}
          {o.orders_refund_pending > 0 && (
            <Notice tone="warn" icon={Wallet}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                {o.orders_refund_pending} refund{o.orders_refund_pending === 1 ? ' is' : 's are'} waiting to be sent.
                {onGoTab && <Button size="sm" onClick={() => onGoTab('orders')}>See refunds</Button>}
              </span>
            </Notice>
          )}
        </div>
      )}

      {o && (
        <div style={kpiGrid}>
          <Kpi label="Revenue this month" icon={Wallet} value={money(o.this_month?.revenue)} sub={`${money(o.all_time?.revenue)} all time`} />
          <Kpi label="Expected profit this month" icon={TrendingUp} value={money(o.this_month?.expected_profit)} sub={`${money(o.all_time?.expected_profit)} all time`} />
          <Kpi label="Paid orders" icon={ClipboardList} value={num(o.orders_paid)} />
          <Kpi label="Sites that paid" icon={Percent} value={o.conversion_rate == null ? '—' : `${o.conversion_rate}%`} sub="paid orders ÷ sites started" />
          <Kpi label="Renewals due (30 days)" icon={CalendarClock} value={num(o.renewals_due_30d)} tone={o.renewals_due_30d ? 'warn' : undefined} />
          <Kpi label="Open hosting jobs" icon={Server} value={num(o.hosting_jobs_open)}
            sub={o.hosting_jobs_overdue ? `${o.hosting_jobs_overdue} overdue` : 'none overdue'} tone={o.hosting_jobs_overdue ? 'bad' : undefined} />
        </div>
      )}

      <div style={kpiGrid}>
        <Kpi label="Sites total" icon={Globe} value={num(ov.sites_total)} />
        <Kpi label="Previews shared" icon={Eye} value={num(ov.previews_shared)} sub="preview ready or revising" />
        <Kpi label="Builders" icon={Users} value={num(ov.builders_total)} />
        <Kpi label="Statuses in use" icon={Layers} value={num(statusEntries.length)} />
      </div>

      <Card>
        <SectionTitle title="Sites by status" hint="Where every site currently sits in the pipeline." />
        {statusEntries.length ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {statusEntries.map(([key, count]) => {
              const st = SITE_STATUS[key] || { tone: 'neutral', label: key }
              return (
                <Badge key={key} tone={st.tone}>{st.label} · <span className="tnum">{count}</span></Badge>
              )
            })}
          </div>
        ) : <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No sites yet — build one from the Sites tab.</p>}
      </Card>
    </div>
  )
}
