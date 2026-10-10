/**
 * frontend/src/modules/sites/SiteAddonsCard.jsx
 * SITE-ADDONS A0-3 - staff view of one site's plan (Capture / Convert / Grow) and add-ons: what is on, what it has
 * used this month, and the actions: set up a plan for the client to pay, send the payment link, give free access,
 * pause, resume, cancel. The CLIENT pays (through a private link); staff never take the card here.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus, Gift, Pause, Play, XCircle, Send } from 'lucide-react'
import {
  getSiteAddons, getSiteAddonsCatalog, grantSiteAddon, startSiteAddonCheckout, sendSiteAddonLink, changeSiteAddon, errorMessage,
} from '../../services/sites.service'
import { Card, SectionTitle, Button, Notice, Spinner, Modal, Field } from './sitesUi'
import { T, INPUT, dateOnly } from './sitesKit'
import { PurchaseForm, PayLinkResult, StatusBadge } from './SiteAddonsParts'
import { money } from './siteAddonsKit'

const CAP_LABELS = { ai_messages: 'AI replies this month', bulk_recipients: 'Bulk message recipients this month' }

function Meter({ label, used, cap }) {
  const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0
  const full = cap > 0 && used >= cap
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12.5, color: T.ink }}>
        <span>{label}</span>
        <span className="tnum" style={{ color: full ? T.bad : T.soft }}>{cap > 0 ? `${used.toLocaleString('en-NG')} of ${cap.toLocaleString('en-NG')}` : 'None included'}</span>
      </div>
      <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={cap || 0} aria-valuenow={used}
        style={{ height: 6, borderRadius: 6, background: T.line, marginTop: 5, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: full ? T.bad : T.teal }} />
      </div>
    </div>
  )
}

export default function SiteAddonsCard({ siteId, siteName, canEdit, showToast }) {
  const [data, setData] = useState(null)
  const [cat, setCat] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [modal, setModal] = useState(null)        // 'buy' | 'grant' | { cancel: row } | { resume: row }
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [grant, setGrant] = useState({ planKey: '', pick: '', until: '' })

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const [d, c] = await Promise.all([getSiteAddons(siteId), getSiteAddonsCatalog()])
      setData(d); setCat(c)
    } catch (e) {
      setLoadError(errorMessage(e, 'Could not load the plan for this site.'))
    } finally {
      setLoading(false)
    }
  }, [siteId])
  useEffect(() => { setLoading(true); load() }, [load])

  const featureLabel = useMemo(() => {
    const m = {}
    ;(cat?.features || []).forEach((f) => { m[f.key] = f.label })
    return (k) => m[k] || k
  }, [cat])

  const toPlan = (kind) => (d) => ({
    kind, key: d.key, label: d.label, monthly: d.monthly_ngn, setup: d.setup_fee_ngn || 0,
    pickGroups: d.pick_one || [], includes: (d.features || []).map(featureLabel),
  })
  const sellable = useMemo(() => (cat ? [
    ...cat.tiers.filter((t) => t.sellable).map(toPlan('tier')),
    ...cat.addons.filter((a) => a.sellable).map(toPlan('addon')),
  ] : []), [cat, featureLabel]) // eslint-disable-line react-hooks/exhaustive-deps
  const allPlans = useMemo(() => (cat ? [
    ...cat.tiers.map(toPlan('tier')), ...cat.addons.map(toPlan('addon')),
  ] : []), [cat, featureLabel]) // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => { setModal(null); setError(null); setResult(null); setBusy(null) }

  const buy = async (body) => {
    setBusy('buy'); setError(null)
    try {
      const r = await startSiteAddonCheckout(siteId, body)
      setResult(r)
      load()
    } catch (e) {
      setError(errorMessage(e, 'Could not set up the payment link.'))
    } finally { setBusy(null) }
  }

  const doGrant = async () => {
    const plan = allPlans.find((p) => `${p.kind}:${p.key}` === grant.planKey)
    if (!plan) return
    setBusy('grant'); setError(null)
    try {
      const body = { kind: plan.kind, key: plan.key }
      if (plan.pickGroups.length) body.picks = [grant.pick]
      if (grant.until) body.until = `${grant.until}T23:59:59+01:00`
      await grantSiteAddon(siteId, body)
      showToast?.(`${plan.label} switched on`)
      close(); load()
    } catch (e) {
      setError(errorMessage(e, 'Could not switch this on.'))
    } finally { setBusy(null) }
  }

  const change = async (row, action, until) => {
    setBusy(`${action}:${row.id}`); setError(null)
    try {
      await changeSiteAddon(siteId, row.id, action, until)
      showToast?.(action === 'pause' ? 'Paused' : action === 'resume' ? 'Resumed' : 'Cancelled')
      close(); load()
    } catch (e) {
      const msg = errorMessage(e, `Could not ${action} this.`)
      if (modal) setError(msg); else showToast?.(msg, 'bad')
    } finally { setBusy(null) }
  }

  const sendLink = async (row) => {
    setBusy(`send:${row.id}`)
    try {
      const r = await sendSiteAddonLink(siteId, row.id)
      showToast?.(r?.sent ? 'Payment link sent' : 'It could not be delivered. Set up the plan again to copy the link.', r?.sent ? undefined : 'bad')
    } catch (e) {
      showToast?.(errorMessage(e, 'Could not send the link.'), 'bad')
    } finally { setBusy(null) }
  }

  if (loading) return <Card><Spinner /></Card>
  if (loadError) return <Card><Notice tone="bad">{loadError}</Notice></Card>

  const tier = data.tier
  const rows = [
    ...(tier ? [{ ...tier, kind: 'tier' }] : []),
    ...data.addons.map((a) => ({ ...a, kind: 'addon', label: cat.addons.find((x) => x.key === a.key)?.label || a.key })),
  ]
  const usage = Object.entries(data.usage || {}).filter(([, v]) => v.cap > 0 || v.used > 0)
  const grantPlan = allPlans.find((p) => `${p.kind}:${p.key}` === grant.planKey)
  const grantNeedsPick = grantPlan?.pickGroups?.length > 0 && !grant.pick

  const rowLine = (r) => {
    const who = r.source === 'staff' ? 'Given free' : 'Paid by the client'
    const until = r.paid_until ? (r.status === 'active' || r.status === 'grace' ? `until ${dateOnly(r.paid_until)}` : `ended ${dateOnly(r.paid_until)}`) : 'no end date'
    return `${who} · ${until}`
  }

  return (
    <Card>
      <SectionTitle title="Plan and add-ons"
        hint="What this site's client has bought, what is switched on, and what they have used this month."
        right={canEdit && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button icon={Plus} variant="primary" onClick={() => { setModal('buy'); setResult(null); setError(null) }}>Set up a plan</Button>
            <Button icon={Gift} onClick={() => { setModal('grant'); setGrant({ planKey: '', pick: '', until: '' }); setError(null) }}>Give free access</Button>
          </div>
        )} />

      {rows.length === 0 ? (
        <p style={{ margin: 0, fontSize: 13, color: T.soft }}>
          This site has no plan yet. {canEdit ? 'Use “Set up a plan” to send the client a payment link, or “Give free access” to switch one on without payment.' : ''}
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r) => {
            const live = r.status === 'active' || r.status === 'grace'
            return (
              <li key={r.id} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: T.ink }}>{r.label}</span>
                  <StatusBadge status={r.status} />
                  <span style={{ fontSize: 12, color: T.muted }}>{r.kind === 'tier' ? 'Plan' : 'Add-on'}</span>
                </div>
                <p style={{ margin: 0, fontSize: 12.5, color: T.soft }}>
                  {rowLine(r)}
                  {r.picks?.length ? ` · Selling tool: ${r.picks.map(featureLabel).join(', ')}` : ''}
                </p>
                {canEdit && (
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {r.source === 'paid' && r.status !== 'cancelled' && (
                      <Button size="sm" icon={Send} loading={busy === `send:${r.id}`} onClick={() => sendLink(r)}>Send payment link</Button>
                    )}
                    {live && <Button size="sm" icon={Pause} loading={busy === `pause:${r.id}`} onClick={() => change(r, 'pause')}>Pause</Button>}
                    {r.status === 'paused' && <Button size="sm" icon={Play} onClick={() => { setGrant({ planKey: '', pick: '', until: '' }); setModal({ resume: r }); setError(null) }}>Resume</Button>}
                    {r.status !== 'cancelled' && <Button size="sm" variant="danger" icon={XCircle} onClick={() => { setModal({ cancel: r }); setError(null) }}>Cancel</Button>}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {data.features.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: T.ink }}>Switched on for this site ({data.features.length})</summary>
          <ul style={{ margin: '8px 0 0', paddingLeft: 20, fontSize: 12.5, color: T.soft, lineHeight: 1.7 }}>
            {data.features.map((k) => <li key={k}>{featureLabel(k)}</li>)}
          </ul>
        </details>
      )}

      {usage.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 14 }}>
          {usage.map(([k, v]) => <Meter key={k} label={CAP_LABELS[k] || k} used={v.used} cap={v.cap} />)}
        </div>
      )}

      <Modal open={modal === 'buy'} onClose={close} title="Set up a plan for the client" width={620}>
        {result ? (
          <PayLinkResult result={result} onCopied={() => showToast?.('Link copied')} />
        ) : sellable.length === 0 ? (
          <Notice tone="info">No plan has a monthly price yet. Set prices in Settings under “Plans and add-ons”, or use “Give free access”.</Notice>
        ) : (
          <PurchaseForm plans={sellable} labelOf={featureLabel} busy={busy === 'buy'} error={error} onSubmit={buy} />
        )}
      </Modal>

      <Modal open={modal === 'grant'} onClose={close} title="Give free access" width={520}
        footer={<>
          <Button onClick={close}>Close</Button>
          <Button variant="primary" loading={busy === 'grant'} disabled={!grantPlan || grantNeedsPick} onClick={doGrant}>Switch on</Button>
        </>}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p style={{ margin: 0, fontSize: 13, color: T.soft }}>
            This switches the plan on without any payment, for example for a trial or a partner. Nothing is charged.
          </p>
          <Field label="Plan or add-on">
            <select style={INPUT} value={grant.planKey} onChange={(e) => setGrant({ planKey: e.target.value, pick: '', until: grant.until })}>
              <option value="">Choose…</option>
              {allPlans.map((p) => (
                <option key={`${p.kind}:${p.key}`} value={`${p.kind}:${p.key}`}>
                  {p.label}{p.kind === 'addon' ? ' (add-on)' : ''}{p.monthly > 0 ? ` · ${money(p.monthly)} a month` : ' · no price set'}
                </option>
              ))}
            </select>
          </Field>
          {grantPlan?.pickGroups?.map((g, i) => (
            <Field key={i} label="Which selling tool?" group>
              <div role="radiogroup" aria-label="Selling tool" style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                {g.map((k) => (
                  <label key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, minHeight: 34 }}>
                    <input type="radio" name="grant-pick" checked={grant.pick === k} onChange={() => setGrant((s) => ({ ...s, pick: k }))} />
                    {featureLabel(k)}
                  </label>
                ))}
              </div>
            </Field>
          ))}
          <Field label="Ends on (optional)" hint="Leave empty to keep it on until you pause or cancel it.">
            <input type="date" style={INPUT} value={grant.until} onChange={(e) => setGrant((s) => ({ ...s, until: e.target.value }))} />
          </Field>
          {error && <Notice tone="bad">{error}</Notice>}
        </div>
      </Modal>

      <Modal open={!!modal?.cancel} onClose={close} title={`Cancel ${modal?.cancel?.label || ''}?`} width={460}
        footer={<>
          <Button onClick={close}>Keep it</Button>
          <Button variant="danger" icon={XCircle} loading={busy === `cancel:${modal?.cancel?.id}`} onClick={() => change(modal.cancel, 'cancel')}>
            Cancel {modal?.cancel?.label}
          </Button>
        </>}>
        <p style={{ margin: 0, fontSize: 13.5, color: T.ink, lineHeight: 1.55 }}>
          {modal?.cancel?.label} will be switched off for {siteName || 'this site'} straight away and its payment link stops working. Money already paid is not refunded here.
          The site and its data stay as they are.
        </p>
        {error && <Notice tone="bad" style={{ marginTop: 12 }}>{error}</Notice>}
      </Modal>

      <Modal open={!!modal?.resume} onClose={close} title={`Resume ${modal?.resume?.label || ''}`} width={460}
        footer={<>
          <Button onClick={close}>Close</Button>
          <Button variant="primary" icon={Play} loading={busy === `resume:${modal?.resume?.id}`}
            onClick={() => change(modal.resume, 'resume', grant.until ? `${grant.until}T23:59:59+01:00` : undefined)}>Resume</Button>
        </>}>
        <Field label="Ends on (optional)" hint="A paid plan resumes until its paid date. For a free one, you can set an end date or leave it open.">
          <input type="date" style={INPUT} value={grant.until} onChange={(e) => setGrant((s) => ({ ...s, until: e.target.value }))} />
        </Field>
        {error && <Notice tone="bad" style={{ marginTop: 12 }}>{error}</Notice>}
      </Modal>
    </Card>
  )
}
