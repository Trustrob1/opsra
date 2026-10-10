/**
 * frontend/src/modules/sites/SiteAddonsParts.jsx
 * SITE-ADDONS A0-3 - pieces shared by the staff Add-ons card and the builder's plans card:
 * money / status helpers, the "set up a plan for the client" form, and the "here is the payment link" result.
 */
import { useState } from 'react'
import { Link2, Copy, Send } from 'lucide-react'
import { T, INPUT } from './sitesKit'
import { Button, Field, Notice, Badge } from './sitesUi'
import { money, STATUS, copyText } from './siteAddonsKit'

export function StatusBadge({ status }) {
  const s = STATUS[status] || { tone: 'neutral', label: status || '—' }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

/** plan: { kind, key, label, monthly, setup, pickGroups: [[key,...]], labelOf(key), includes: [label] } */
export function PurchaseForm({ plans, labelOf, busy, error, canSend = true, onSubmit, submitLabel }) {
  const [planKey, setPlanKey] = useState(null)
  const [picks, setPicks] = useState({})
  const [payer, setPayer] = useState({ name: '', phone: '', email: '' })
  const [send, setSend] = useState(true)

  const plan = plans.find((p) => `${p.kind}:${p.key}` === planKey)
  const groups = plan?.pickGroups || []
  const picksDone = groups.every((_, i) => picks[i])
  const hasContact = !!(payer.phone.trim() || payer.email.trim())

  const submit = () => {
    if (!plan || !picksDone) return
    const body = { kind: plan.kind, key: plan.key, send: canSend && send }
    if (groups.length) body.picks = groups.map((_, i) => picks[i])
    const p = {}
    if (payer.name.trim()) p.name = payer.name.trim()
    if (payer.phone.trim()) p.phone = payer.phone.trim()
    if (payer.email.trim()) p.email = payer.email.trim()
    if (Object.keys(p).length) body.payer = p
    onSubmit(body)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Field label="Choose a plan" group>
        <div role="radiogroup" aria-label="Plan" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {plans.map((p) => {
            const on = `${p.kind}:${p.key}` === planKey
            return (
              <label key={`${p.kind}:${p.key}`} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: 12, cursor: 'pointer',
                border: `1px solid ${on ? T.teal : T.line}`, background: on ? T.mint : '#fff', borderRadius: 10 }}>
                <input type="radio" name="plan" checked={on} style={{ marginTop: 3 }}
                  onChange={() => { setPlanKey(`${p.kind}:${p.key}`); setPicks({}) }} />
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 13.5, fontWeight: 700, color: T.ink }}>
                    {p.label} · {money(p.monthly)} a month
                  </span>
                  {p.setup > 0 && <span style={{ display: 'block', fontSize: 12, color: T.soft }}>plus a one-time set-up fee of {money(p.setup)}</span>}
                  {p.includes?.length > 0 && (
                    <span style={{ display: 'block', fontSize: 12, color: T.muted, marginTop: 3, lineHeight: 1.5 }}>
                      Includes {p.includes.join(', ')}
                    </span>
                  )}
                </span>
              </label>
            )
          })}
        </div>
      </Field>

      {groups.map((g, i) => (
        <Field key={i} label="Which selling tool does this site get?" group hint="This plan includes one of these. It can be changed later.">
          <div role="radiogroup" aria-label="Selling tool" style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            {g.map((k) => (
              <label key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: T.ink, minHeight: 34 }}>
                <input type="radio" name={`pick-${i}`} checked={picks[i] === k} onChange={() => setPicks((s) => ({ ...s, [i]: k }))} />
                {labelOf(k)}
              </label>
            ))}
          </div>
        </Field>
      ))}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        <Field label="Client's name"><input style={INPUT} value={payer.name} autoComplete="off"
          onChange={(e) => setPayer((s) => ({ ...s, name: e.target.value }))} /></Field>
        <Field label="Client's WhatsApp number"><input style={INPUT} inputMode="tel" value={payer.phone} autoComplete="off"
          onChange={(e) => setPayer((s) => ({ ...s, phone: e.target.value }))} /></Field>
        <Field label="Client's email"><input style={INPUT} type="email" value={payer.email} autoComplete="off"
          onChange={(e) => setPayer((s) => ({ ...s, email: e.target.value }))} /></Field>
      </div>
      <p style={{ margin: '-6px 0 0', fontSize: 11.5, color: T.muted }}>
        Leave these blank to use the site owner's details. The client pays, so these are where the link and reminders go.
      </p>

      {canSend && (
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, color: T.ink, minHeight: 34 }}>
          <input type="checkbox" checked={send} onChange={(e) => setSend(e.target.checked)} />
          Send the payment link to the client now
        </label>
      )}
      {canSend && send && !hasContact && (
        <Notice tone="info">No contact typed here, so the link goes to the site owner's saved details if there are any. If it can't be delivered you can copy the link and send it yourself.</Notice>
      )}
      {error && <Notice tone="bad">{error}</Notice>}
      <div>
        <Button variant="primary" icon={send && canSend ? Send : Link2} loading={busy} disabled={!plan || !picksDone} onClick={submit}>
          {submitLabel || (send && canSend ? 'Create and send payment link' : 'Create payment link')}
        </Button>
      </div>
    </div>
  )
}

/** The result of creating a purchase: what the client pays, the private link, and whether it was sent. */
export function PayLinkResult({ result, onCopied }) {
  const [copied, setCopied] = useState(false)
  const q = result.quote || {}
  if (result.scheduled) {
    return (
      <Notice tone="good">
        The change is saved. It takes effect when the next renewal is paid, so there is nothing to pay now.
      </Notice>
    )
  }
  const copy = async () => {
    const ok = await copyText(result.pay_url)
    setCopied(ok)
    if (ok) onCopied?.()
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Notice tone="good">
        {q.label || 'The plan'} is ready for the client to pay: <b>{money(q.total)}</b>
        {q.days ? <> for {q.days} days</> : null}
        {q.setup_fee > 0 ? <> (includes a one-time set-up fee of {money(q.setup_fee)})</> : null}
        {q.credit > 0 ? <>, after {money(q.credit)} credit for unused days</> : null}.
        {result.sent === true && <> The link has been sent.</>}
        {result.sent === false && <> It could not be delivered, so please send the link yourself.</>}
      </Notice>
      <Field label="Private payment link" hint="Anyone with this link can pay for this plan. It does not need a login.">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input readOnly style={{ ...INPUT, flex: '1 1 220px', width: 'auto' }} value={result.pay_url} onFocus={(e) => e.target.select()} />
          <Button icon={Copy} onClick={copy}>{copied ? 'Copied' : 'Copy link'}</Button>
        </div>
      </Field>
    </div>
  )
}
