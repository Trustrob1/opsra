/**
 * frontend/src/modules/sites/BuilderPlansCard.jsx
 * SITE-ADDONS A0-3 - builder portal: the plans a client's site can have (Capture / Convert / Grow and add-ons), what the
 * site has now, and a way to set one up for the client. The CLIENT pays through a private link; the builder only creates
 * and sends it. The card stays hidden until at least one plan has a price or the site already has a plan.
 */
import { useCallback, useEffect, useState } from 'react'
import { Layers } from 'lucide-react'
import { T } from './sitesKit'
import { Card, Button, Notice, SectionTitle, Modal } from './sitesUi'
import { PurchaseForm, PayLinkResult, StatusBadge } from './SiteAddonsParts'
import { getSiteAddonPlans, startSiteAddonPlan, errorMessage } from '../../services/builder_portal.service'

const dateOnly = (iso) => (iso ? new Intl.DateTimeFormat('en-GB', { timeZone: 'Africa/Lagos', day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso)) : '')

export default function BuilderPlansCard({ token, siteId }) {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const load = useCallback(async () => {
    try { setData(await getSiteAddonPlans(token, siteId)) } catch { /* the card just stays hidden */ }
  }, [token, siteId])
  useEffect(() => { load() }, [load])

  if (!data) return null
  const plans = [
    ...data.plans.map((p) => ({ ...p, kind: 'tier' })),
    ...data.addon_plans.map((p) => ({ ...p, kind: 'addon' })),
  ]
  if (plans.length === 0 && !data.tier) return null

  // Plain names for the "choose one" tools; the server sends the plan's feature labels, so keep the keys readable.
  const toolLabel = (k) => ({ selling_catalog: 'Product catalog', selling_booking: 'Bookings' }[k] || k.replace(/_/g, ' '))
  const forForm = plans.map((p) => ({
    kind: p.kind, key: p.key, label: p.label, monthly: p.monthly_ngn, setup: p.setup_fee_ngn || 0,
    pickGroups: p.pick_one || [], includes: p.includes || [],
  }))

  const submit = async (body) => {
    setBusy(true); setError(null)
    try {
      setResult(await startSiteAddonPlan(token, siteId, body))
      load()
    } catch (e) {
      setError(errorMessage(e, 'Could not set up the payment link.'))
    } finally { setBusy(false) }
  }
  const close = () => { setOpen(false); setResult(null); setError(null) }

  return (
    <Card>
      <SectionTitle title="Plans for this site"
        hint="Turn on lead capture, instant replies and more for your client. They pay through a private link, and the plan starts as soon as the payment is confirmed." />
      {data.tier ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: T.ink }}>{data.tier.label}</span>
            <StatusBadge status={data.tier.status} />
          </div>
          {data.tier.paid_until && (
            <p style={{ margin: 0, fontSize: 12.5, color: T.soft }}>
              {data.tier.status === 'active' || data.tier.status === 'grace' ? 'Paid until' : 'Ended'} {dateOnly(data.tier.paid_until)}
            </p>
          )}
        </div>
      ) : (
        <p style={{ margin: '0 0 12px', fontSize: 13, color: T.soft }}>This site has no plan yet.</p>
      )}
      {plans.length > 0 ? (
        <div>
          <Button variant="primary" icon={Layers} onClick={() => { setOpen(true); setResult(null); setError(null) }}>
            {data.tier ? 'Change or renew the plan' : 'Set up a plan for your client'}
          </Button>
        </div>
      ) : (
        <Notice tone="info">No other plans are on sale right now.</Notice>
      )}

      <Modal open={open} onClose={close} title="Set up a plan for your client" width={620}>
        {result ? <PayLinkResult result={result} /> : (
          <PurchaseForm plans={forForm} labelOf={toolLabel} busy={busy} error={error} onSubmit={submit} />
        )}
      </Modal>
    </Card>
  )
}
