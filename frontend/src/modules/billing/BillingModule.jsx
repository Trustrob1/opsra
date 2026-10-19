/**
 * frontend/src/modules/billing/BillingModule.jsx
 * ACCOUNT-PLANS AP-3 — the organisation-wide Billing area (owner / ops manager / admin).
 * Tabs: Plan · Usage · Credits · Payments. Backend: routers/account_plan.py and routers/credits.py.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  getPlan, previewPlan, startPlanCheckout, verifyPlanPayment, clearPendingPlanChange, ngn, planError, PENDING_PLAN_KEY,
} from '../../services/accountPlan.service'
import { naira } from '../../services/credits.service'
import CreditsPanel from '../admin/CreditsPanel'
import { ds } from '../../utils/ds'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const h3 = { fontSize: 15, fontWeight: 600, color: ds.dark, margin: '0 0 10px', fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 44, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
const lsGet = () => { try { return localStorage.getItem(PENDING_PLAN_KEY) } catch { return null } }
const lsSet = (v) => { try { v ? localStorage.setItem(PENDING_PLAN_KEY, v) : localStorage.removeItem(PENDING_PLAN_KEY) } catch { /* private mode */ } }
const day = (v) => (v ? String(v).slice(0, 10) : '—')
const STATUS = { active: ['Active', '#0f7b5f'], grace: ['Ended — still on for a few days', '#b45309'], paused: ['Paused', '#b91c1c'], pending: ['Not paid yet', '#6b7280'] }
const ACTION = { new: 'Choose', renewal: 'Renew', upgrade: 'Upgrade', switch: 'Switch to this', downgrade_renewal: 'Renew at this price', downgrade: 'Switch at next renewal' }
const ORDER_KIND = { new: 'New plan', renewal: 'Renewal', upgrade: 'Upgrade', switch: 'Switch', downgrade_renewal: 'Renewal (lower plan)' }
const CAP_LABEL = { ai_messages: 'AI replies this month', bulk_recipients: 'Bulk message recipients this month' }

function PlanCard({ plan, busy, onPay }) {
  const [code, setCode] = useState('')
  const [pv, setPv] = useState(null)
  const [err, setErr] = useState('')
  const canCode = plan.action === 'new'
  const apply = async () => {
    setErr('')
    try { setPv(await previewPlan(plan.key, code)) } catch (e) { setErr(planError(e)) }
  }
  const due = pv && !pv.discount_error ? pv.amount_due : plan.amount_due
  return (
    <div style={{ ...card, marginBottom: 0, borderColor: plan.is_current ? ds.teal : ds.border }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: ds.dark }}>{plan.label}</div>
        {plan.is_current && <span style={{ fontSize: 11, color: ds.teal, fontWeight: 700 }}>YOUR PLAN</span>}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: ds.dark, margin: '4px 0' }}>{ngn(plan.monthly_ngn)}<span style={{ fontSize: 12, color: ds.gray, fontWeight: 400 }}> / month</span></div>
      <ul style={{ margin: '8px 0 12px', paddingLeft: 18, fontSize: 13, color: ds.dark }}>
        {plan.includes.map((f) => <li key={f}>{f}</li>)}
        {Object.entries(plan.caps || {}).filter(([, v]) => v > 0).map(([k, v]) => (
          <li key={k}>{k === 'reps' ? `Up to ${v} team members` : CAP_LABEL[k] ? `${CAP_LABEL[k].replace(' this month', '')}: ${v.toLocaleString()} a month` : `${k}: ${v}`}</li>
        ))}
      </ul>
      {canCode && (
        <div style={{ marginBottom: 10 }}>
          <label htmlFor={`code-${plan.key}`} style={{ display: 'block', fontSize: 12, fontWeight: 600, color: ds.dark, marginBottom: 4 }}>Discount code (optional)</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input id={`code-${plan.key}`} value={code} onChange={(e) => { setCode(e.target.value); setPv(null); setErr('') }}
              style={{ flex: 1, minHeight: 40, padding: '6px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontFamily: ds.fontDm }} />
            <button type="button" style={btn(false)} disabled={!code.trim()} onClick={apply}>Apply</button>
          </div>
          {pv?.discount && <div style={{ fontSize: 12, color: ds.teal, marginTop: 4 }}>Code {pv.discount.code}: {ngn(pv.discount.discount)} off.</div>}
          {(err || pv?.discount_error) && <div role="alert" style={{ fontSize: 12, color: ds.red, marginTop: 4 }}>{err || pv.discount_error}</div>}
        </div>
      )}
      {plan.action === 'downgrade'
        ? <p style={{ fontSize: 12, color: ds.gray, margin: '0 0 8px' }}>Nothing to pay now. This applies when your current plan ends.</p>
        : plan.action === 'upgrade'
          ? <p style={{ fontSize: 12, color: ds.gray, margin: '0 0 8px' }}>You pay {ngn(due)} today — your unused days are credited. It starts at once.</p>
          : <p style={{ fontSize: 12, color: ds.gray, margin: '0 0 8px' }}>You pay {ngn(due)}.</p>}
      <button type="button" style={{ ...btn(true), width: '100%' }} disabled={busy} onClick={() => onPay(plan, canCode ? code : '')}>
        {busy ? 'Please wait…' : ACTION[plan.action] || 'Choose'}
      </button>
    </div>
  )
}

function PlanTab({ data, reload, setMsg }) {
  const [busy, setBusy] = useState(false)
  const cur = data.current
  const pay = async (plan, code) => {
    setBusy(true); setMsg('')
    try {
      const r = await startPlanCheckout(plan.key, code)
      if (r.scheduled) { setMsg(`Done. You will move to ${r.label} when your current plan ends on ${day(r.applies_at)}.`); setBusy(false); reload(); return }
      lsSet(r.reference)
      window.location.assign(r.checkout_url)
    } catch (e) { setMsg(planError(e)); setBusy(false) }
  }
  const cancelChange = async () => {
    try { await clearPendingPlanChange(); setMsg('The scheduled change was cancelled.'); reload() } catch (e) { setMsg(planError(e)) }
  }
  const st = cur ? STATUS[cur.status] || [cur.status, ds.gray] : null
  return (
    <>
      <div style={card}>
        <h3 style={h3}>Your plan</h3>
        {!cur ? (
          <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
            You are not on a paid plan.{!data.enforced && ' Everything in your account is on for now — you can choose a plan below whenever you are ready.'}
          </p>
        ) : (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 10 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: ds.dark }}>{cur.label}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: st[1] }}>{st[0]}</span>
            </div>
            {cur.source !== 'paid'
              ? <p style={{ fontSize: 13, color: ds.gray, margin: '6px 0 0' }}>{cur.source === 'staff' ? 'Set up by Opsra.' : 'Included with your account.'}{cur.paid_until ? ` Runs until ${day(cur.paid_until)}.` : ''}</p>
              : <p style={{ fontSize: 13, color: ds.gray, margin: '6px 0 0' }}>{ngn(cur.monthly_ngn)} a month · {cur.status === 'active' ? `renews by ${day(cur.paid_until)} (${cur.days_left} days left)` : `ended ${day(cur.paid_until)}`}</p>}
            {cur.status === 'grace' && <div role="alert" style={{ marginTop: 8, color: '#b45309', fontSize: 13 }}>Your plan has ended. Renew below to keep everything on.</div>}
            {cur.status === 'paused' && <div role="alert" style={{ marginTop: 8, color: ds.red, fontSize: 13 }}>Your plan is paused and its features are off. Your data and login are safe — renew below to switch it back on.</div>}
            {cur.pending_change && (
              <div style={{ marginTop: 8, fontSize: 13, color: ds.dark }}>
                You will move to <b>{cur.pending_change.label}</b> when this plan ends.{' '}
                <button type="button" style={{ ...btn(false), minHeight: 32, padding: '2px 10px', fontSize: 12 }} onClick={cancelChange}>Cancel this change</button>
              </div>
            )}
          </>
        )}
      </div>
      {data.plans.length === 0
        ? <div style={card}><p style={{ margin: 0, fontSize: 13, color: ds.gray }}>No plans are on sale yet. Please check back soon.</p></div>
        : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, marginBottom: 16 }}>
            {data.plans.map((p) => <PlanCard key={p.key} plan={p} busy={busy} onPay={pay} />)}
          </div>}
      <p style={{ fontSize: 12, color: ds.gray }}>Plans are paid monthly with Paystack and are not refundable. Credits are separate and are bought in the Credits tab.</p>
    </>
  )
}

function UsageTab({ data }) {
  const rows = Object.entries(data.allowances || {})
  return (
    <>
      <div style={card}>
        <h3 style={h3}>Plan allowances this month</h3>
        {!data.enforced
          ? <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>Allowances are not being counted for your account yet.</p>
          : rows.length === 0
            ? <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>Your plan has no monthly allowances to track.</p>
            : rows.map(([k, v]) => {
                const pct = Math.min(100, Math.round(((v.used || 0) / Math.max(v.cap, 1)) * 100))
                return (
                  <div key={k} style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: ds.dark }}>
                      <span>{CAP_LABEL[k] || k}</span><span>{(v.used || 0).toLocaleString()} of {v.cap.toLocaleString()}</span>
                    </div>
                    <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} style={{ height: 8, background: '#EEF2F5', borderRadius: 4, marginTop: 4 }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: pct >= 90 ? ds.red : ds.teal, borderRadius: 4 }} />
                    </div>
                  </div>
                )
              })}
      </div>
      <p style={{ fontSize: 12, color: ds.gray }}>What you spend from your credit balance (AI replies, WhatsApp fees) is shown in the Credits tab.</p>
    </>
  )
}

function PaymentsTab({ data }) {
  return (
    <div style={card}>
      <h3 style={h3}>Plan payments</h3>
      {data.orders.length === 0 ? <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>No plan payments yet.</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr style={{ textAlign: 'left', color: ds.gray }}><th scope="col">Date</th><th scope="col">What</th><th scope="col" style={{ textAlign: 'right' }}>Amount</th><th scope="col" style={{ textAlign: 'right' }}>Status</th></tr></thead>
            <tbody>
              {data.orders.map((o) => (
                <tr key={o.id} style={{ borderTop: `1px solid ${ds.border}` }}>
                  <td style={{ padding: '6px 0' }}>{day(o.paid_at || o.created_at)}</td>
                  <td>{ORDER_KIND[o.change_kind] || o.change_kind} · {o.plan_key}</td>
                  <td style={{ textAlign: 'right' }}>{naira(o.amount_kobo)}</td>
                  <td style={{ textAlign: 'right', color: o.status === 'paid' ? ds.teal : ds.gray }}>{o.status === 'paid' ? 'Paid' : o.status === 'pending' ? 'Not completed' : o.status === 'expired' ? 'Replaced' : 'Failed'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const TABS = [['plan', 'Plan'], ['usage', 'Usage'], ['credits', 'Credits'], ['payments', 'Payments']]

export default function BillingModule() {
  const [tab, setTab] = useState(() => {
    try { return new URLSearchParams(window.location.search).get('credits') ? 'credits' : 'plan' } catch { return 'plan' }
  })
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState('')
  const [denied, setDenied] = useState(false)

  const load = useCallback(async () => {
    try { setData(await getPlan()) } catch (e) {
      if (e?.response?.status === 403) setDenied(true)
      else setMsg(planError(e, 'Could not load your plan.'))
    }
  }, [])
  useEffect(() => { load() }, [load])

  // Coming back from Paystack: confirm the payment we were waiting for.
  useEffect(() => {
    const ref = lsGet()
    if (!ref) return
    let tries = 0
    let stop = false
    const check = async () => {
      if (stop) return
      try {
        const r = await verifyPlanPayment(ref)
        if (r.status === 'paid') { lsSet(null); setMsg('Payment received. Your plan is active.'); load(); return }
        if (r.status === 'failed') { lsSet(null); setMsg('That payment did not go through. You have not been charged.'); return }
      } catch { lsSet(null); return }
      if (++tries < 6) setTimeout(check, 4000)
      else setMsg('We have not received that payment yet. Your plan will switch on automatically once Paystack confirms it.')
    }
    check()
    return () => { stop = true }
  }, [load])

  if (denied) return <div style={{ padding: 20, color: ds.gray, fontFamily: ds.fontDm }}>Only the owner, an admin or an operations manager can see Billing.</div>
  return (
    <div style={{ maxWidth: 900, fontFamily: ds.fontDm }}>
      <h2 style={{ fontSize: 22, color: ds.dark, margin: '0 0 4px' }}>Billing</h2>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 14px' }}>Your Opsra plan, what you have used, your credits and your payments.</p>
      <div role="tablist" style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} style={btn(tab === id)} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {msg && tab !== 'credits' && <div role="status" style={{ ...card, padding: 12, color: ds.dark }}>{msg}</div>}
      {tab === 'credits' && <CreditsPanel />}
      {tab !== 'credits' && !data && <div style={{ color: ds.gray, fontSize: 13 }}>{msg ? '' : 'Loading…'}</div>}
      {data && tab === 'plan' && <PlanTab data={data} reload={load} setMsg={setMsg} />}
      {data && tab === 'usage' && <UsageTab data={data} />}
      {data && tab === 'payments' && <PaymentsTab data={data} />}
    </div>
  )
}
