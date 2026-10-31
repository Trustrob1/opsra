/**
 * frontend/src/modules/billing/BillingModule.jsx
 * ACCOUNT-PLANS AP-3 — the organisation-wide Billing area (owner / ops manager / admin).
 * Tabs: Plan · Team · Usage · Credits · Payments. Backend: routers/account_plan.py and routers/credits.py.
 */
import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import {
  getPlan, previewPlan, startPlanCheckout, verifyPlanPayment, clearPendingPlanChange, ngn, planError, PENDING_PLAN_KEY,
  previewSeats, startSeatsCheckout, setNextSeats,
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
const STATUS = { active: ['Active', '#00A896'], grace: ['Ended, still on for a few days', '#F4A261'], paused: ['Paused', '#FFB4B4'], pending: ['Not paid yet', '#9FB6C4'] }
const ACTION = { new: 'Choose', renewal: 'Renew', upgrade: 'Upgrade', switch: 'Switch to this', downgrade_renewal: 'Renew at this price', downgrade: 'Switch at next renewal' }
const ORDER_KIND = { seats: 'Extra users', new: 'New plan', renewal: 'Renewal', upgrade: 'Upgrade', switch: 'Switch', downgrade_renewal: 'Renewal (lower plan)' }
const CAP_LABEL = { ai_messages: 'AI replies this month', bulk_recipients: 'Bulk message recipients this month', bookings: 'Bookings this month' }

const FONT = ds.fontSyne
const TIER_LOOK = {
  // Capture sits quiet on white, Convert gets a teal edge, Grow is the dark card: the ladder reads at a glance.
  capture: { bg: '#fff', fg: ds.dark, sub: ds.gray, edge: ds.border, tick: ds.teal, tickBg: ds.mint },
  convert: { bg: '#fff', fg: ds.dark, sub: ds.gray, edge: ds.teal, tick: ds.teal, tickBg: ds.mint },
  grow: { bg: ds.dark, fg: '#fff', sub: '#9FB6C4', edge: ds.dark, tick: '#fff', tickBg: 'rgba(255,255,255,0.14)' },
}
const lookOf = (key) => TIER_LOOK[key] || TIER_LOOK.capture
const FEATURES_SHOWN = 6

const STYLES = `
.bp-hero{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:center}
.bp-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:stretch}
@media (max-width: 900px){.bp-grid{grid-template-columns:1fr}.bp-hero{grid-template-columns:1fr}}
.bp-card:focus-within{outline:2px solid ${ds.teal};outline-offset:2px}
.bp-link{background:none;border:0;padding:6px 0;font:inherit;font-size:13px;font-weight:600;cursor:pointer;min-height:36px}
.bp-link:focus-visible,.bp-cta:focus-visible{outline:2px solid ${ds.teal};outline-offset:2px}
.bp-cta{transition:background .15s,transform .15s}
.bp-cta:not(:disabled):hover{transform:translateY(-1px)}
@media (prefers-reduced-motion: reduce){.bp-cta{transition:none}.bp-cta:not(:disabled):hover{transform:none}}
`

function Tick({ look }) {
  return (
    <span aria-hidden style={{ flexShrink: 0, width: 18, height: 18, borderRadius: '50%', background: look.tickBg, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
      <Check size={11} color={look.tick} strokeWidth={3} />
    </span>
  )
}

function Ring({ days, total, label }) {
  const r = 44
  const c = 2 * Math.PI * r
  const frac = Math.max(0, Math.min(1, total ? days / total : 0))
  return (
    <div role="img" aria-label={`${days} days left`} style={{ position: 'relative', width: 112, height: 112 }}>
      <svg width="112" height="112" viewBox="0 0 112 112" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="56" cy="56" r={r} fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="8" />
        <circle cx="56" cy="56" r={r} fill="none" stroke={ds.tealLight} strokeWidth="8" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - frac)} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>
        <span style={{ fontFamily: FONT, fontSize: 28, fontWeight: 700, lineHeight: 1 }}>{days}</span>
        <span style={{ fontSize: 11, color: '#9FB6C4', marginTop: 2 }}>{label}</span>
      </div>
    </div>
  )
}

function PlanCard({ plan, index, plans, busy, onPay }) {
  const [code, setCode] = useState('')
  const [pv, setPv] = useState(null)
  const [err, setErr] = useState('')
  const [all, setAll] = useState(false)
  const look = lookOf(plan.key)
  const dark = plan.key === 'grow'
  const prev = index > 0 ? plans[index - 1] : null
  // Show only what this plan ADDS to the one below it, so the three cards compare at a glance.
  const prevSet = new Set(prev ? prev.includes : [])
  const items = [
    ...plan.includes.filter((f) => !prevSet.has(f)),
    ...Object.entries(plan.caps || {}).filter(([, v]) => v > 0).map(([k, v]) => (
      k === 'reps' ? `Up to ${v} team members` : CAP_LABEL[k] ? `${CAP_LABEL[k].replace(' this month', '')}: ${v.toLocaleString()} a month` : `${k}: ${v}`)),
  ]
  const shown = all ? items : items.slice(0, FEATURES_SHOWN)
  const canCode = plan.action === 'new'
  const due = pv && !pv.discount_error ? pv.amount_due : plan.amount_due
  const apply = async () => {
    setErr('')
    try { setPv(await previewPlan(plan.key, code)) } catch (e) { setErr(planError(e)) }
  }
  const cta = plan.is_current && plan.action === 'renewal' ? 'Renew plan' : (ACTION[plan.action] || 'Choose')
  return (
    <section className="bp-card" aria-label={`${plan.label} plan`} style={{
      background: look.bg, color: look.fg, border: `${plan.key === 'convert' ? 2 : 1}px solid ${look.edge}`, borderRadius: ds.radius.xl,
      padding: 22, display: 'flex', flexDirection: 'column', boxShadow: dark ? '0 10px 30px rgba(13,27,42,0.25)' : ds.cardShadow, position: 'relative',
    }}>
      {plan.is_current && (
        <span style={{ position: 'absolute', top: 14, right: 14, fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 999, background: dark ? 'rgba(255,255,255,0.16)' : ds.mint, color: dark ? '#fff' : ds.tealDark }}>Your plan</span>
      )}
      <h4 style={{ margin: 0, fontFamily: FONT, fontSize: 19, fontWeight: 600 }}>{plan.label}</h4>
      <div style={{ margin: '10px 0 16px', minHeight: 50 }}>
        {plan.monthly_ngn > 0 ? (
          <>
            <span style={{ fontFamily: FONT, fontSize: 32, fontWeight: 700, letterSpacing: '-0.5px', fontVariantNumeric: 'tabular-nums' }}>{ngn(plan.monthly_ngn)}</span>
            <span style={{ fontSize: 13, color: look.sub }}> a month</span>
          </>
        ) : <span style={{ fontSize: 15, color: look.sub }}>Price coming soon</span>}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>{prev ? `Everything in ${prev.label}, plus` : 'What you get'}</div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 9, fontSize: 13.5, lineHeight: 1.4 }}>
        {shown.map((f) => (
          <li key={f} style={{ display: 'flex', gap: 10 }}><Tick look={look} /><span>{f}</span></li>
        ))}
      </ul>
      {items.length > FEATURES_SHOWN && (
        <button type="button" className="bp-link" aria-expanded={all} onClick={() => setAll(!all)}
          style={{ color: dark ? '#fff' : ds.teal, textAlign: 'left', marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {all ? 'Show fewer' : `Show ${items.length - FEATURES_SHOWN} more`}
          <ChevronDown size={14} style={{ transform: all ? 'rotate(180deg)' : 'none' }} />
        </button>
      )}
      <div style={{ flex: 1 }} />
      <div style={{ marginTop: 18 }}>
        {plan.for_sale && canCode && (
          <div style={{ marginBottom: 12 }}>
            <label htmlFor={`code-${plan.key}`} style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Discount code</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input id={`code-${plan.key}`} value={code} onChange={(e) => { setCode(e.target.value); setPv(null); setErr('') }}
                style={{ flex: 1, minWidth: 0, minHeight: 40, padding: '6px 10px', border: `1px solid ${dark ? 'rgba(255,255,255,0.3)' : ds.border}`, borderRadius: ds.radius.sm, fontFamily: ds.fontDm, background: dark ? 'rgba(255,255,255,0.08)' : '#fff', color: look.fg }} />
              <button type="button" disabled={!code.trim()} onClick={apply}
                style={{ minHeight: 40, padding: '0 14px', borderRadius: ds.radius.sm, border: `1px solid ${dark ? '#fff' : ds.teal}`, background: 'transparent', color: dark ? '#fff' : ds.teal, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontDm }}>Apply</button>
            </div>
            {pv?.discount && <div style={{ fontSize: 12, color: dark ? ds.tealLight : ds.tealDark, marginTop: 4 }}>Code {pv.discount.code} saves you {ngn(pv.discount.discount)}.</div>}
            {(err || pv?.discount_error) && <div role="alert" style={{ fontSize: 12, color: dark ? '#FFB4B4' : ds.red, marginTop: 4 }}>{err || pv.discount_error}</div>}
          </div>
        )}
        {!plan.for_sale ? (
          <p style={{ fontSize: 13, color: look.sub, margin: 0 }}>Not on sale yet.</p>
        ) : (
          <>
            <p style={{ fontSize: 12.5, color: look.sub, margin: '0 0 8px' }}>
              {plan.action === 'downgrade' ? 'Nothing to pay now. This starts when your current plan ends.'
                : plan.action === 'upgrade' ? `Pay ${ngn(due)} today. Your unused days are taken off, and it starts at once.`
                  : `Pay ${ngn(due)} for 30 days.`}
            </p>
            <button type="button" className="bp-cta" disabled={busy} onClick={() => onPay(plan, canCode ? code : '')}
              style={{ width: '100%', minHeight: 46, borderRadius: ds.radius.md, border: 0, cursor: busy ? 'default' : 'pointer', fontWeight: 600, fontSize: 14.5, fontFamily: ds.fontDm,
                background: dark ? '#fff' : ds.teal, color: dark ? ds.dark : '#fff', opacity: busy ? 0.7 : 1 }}>
              {busy ? 'Please wait…' : cta}
            </button>
          </>
        )}
      </div>
    </section>
  )
}

function PlanHero({ cur, enforced, periodDays, onCancelChange }) {
  const [open, setOpen] = useState(false)
  if (!cur) {
    return (
      <div style={{ background: ds.mint, border: `1px solid ${ds.border}`, borderRadius: ds.radius.xl, padding: 22, marginBottom: 20 }}>
        <div style={{ fontFamily: FONT, fontSize: 18, fontWeight: 600, color: ds.dark }}>You are not on a paid plan</div>
        <p style={{ fontSize: 13.5, color: ds.gray, margin: '6px 0 0', maxWidth: 560 }}>
          {enforced ? 'Choose a plan below to switch your tools on.' : 'Everything in your account is on for now. Choose a plan below whenever you are ready.'}
        </p>
      </div>
    )
  }
  const [label, tone] = STATUS[cur.status] || [cur.status, '#9FB6C4']
  const paid = cur.source === 'paid'
  return (
    <div style={{ background: ds.dark, color: '#fff', borderRadius: ds.radius.xl, padding: 24, marginBottom: 20, boxShadow: '0 10px 30px rgba(13,27,42,0.22)' }}>
      <div className="bp-hero">
        <div style={{ minWidth: 0 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12.5, fontWeight: 600, padding: '4px 12px', borderRadius: 999, background: 'rgba(255,255,255,0.1)' }}>
            <span aria-hidden style={{ width: 8, height: 8, borderRadius: '50%', background: cur.status === 'active' ? ds.tealLight : tone }} />{label}
          </span>
          <div style={{ fontFamily: FONT, fontSize: 30, fontWeight: 700, margin: '12px 0 4px', letterSpacing: '-0.3px' }}>{cur.label}</div>
          <div style={{ fontSize: 14, color: '#9FB6C4' }}>
            {paid
              ? `${ngn(cur.monthly_ngn)} a month. ${cur.status === 'active' ? `Renews by ${day(cur.paid_until)}.` : `Ended on ${day(cur.paid_until)}.`}`
              : `${cur.source === 'staff' ? 'Set up by Opsra.' : 'Included with your account.'} ${cur.paid_until ? `Runs until ${day(cur.paid_until)}.` : 'No end date.'}`}
          </div>
          {cur.status === 'grace' && <div role="alert" style={{ marginTop: 12, fontSize: 13.5, color: ds.accent }}>Your plan has ended. Renew below to keep everything on.</div>}
          {cur.status === 'paused' && <div role="alert" style={{ marginTop: 12, fontSize: 13.5, color: '#FFB4B4' }}>Your plan is paused and its tools are off. Your data and login are safe. Renew below to switch it back on.</div>}
          {cur.pending_change && (
            <div style={{ marginTop: 12, fontSize: 13.5 }}>
              Moving to <b>{cur.pending_change.label}</b> when this plan ends.{' '}
              <button type="button" className="bp-link" onClick={onCancelChange} style={{ color: '#fff', textDecoration: 'underline', display: 'inline' }}>Cancel this change</button>
            </div>
          )}
          {cur.includes?.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <button type="button" className="bp-link" aria-expanded={open} onClick={() => setOpen(!open)} style={{ color: '#fff', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {open ? 'Hide what is included' : `See all ${cur.includes.length} things included`}
                <ChevronDown size={14} style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
              </button>
              {open && (
                <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: '8px 18px', fontSize: 13.5 }}>
                  {cur.includes.map((f) => <li key={f} style={{ display: 'flex', gap: 10 }}><Tick look={lookOf('grow')} /><span>{f}</span></li>)}
                </ul>
              )}
            </div>
          )}
        </div>
        {paid && cur.status === 'active' && <Ring days={cur.days_left} total={periodDays} label="days left" />}
      </div>
    </div>
  )
}

function PlanTab({ data, reload, setMsg }) {
  const [busy, setBusy] = useState(false)
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
  return (
    <>
      <style>{STYLES}</style>
      <PlanHero cur={data.current} enforced={data.enforced} periodDays={data.billing?.period_days || 30} onCancelChange={cancelChange} />
      <h3 style={{ ...h3, fontFamily: FONT, fontSize: 17, margin: '0 0 12px' }}>Compare plans</h3>
      {data.plans.length === 0
        ? <div style={card}><p style={{ margin: 0, fontSize: 13, color: ds.gray }}>No plans have been set up yet. Please check back soon.</p></div>
        : <div className="bp-grid" style={{ marginBottom: 16 }}>
            {data.plans.map((p, i) => <PlanCard key={p.key} plan={p} index={i} plans={data.plans} busy={busy} onPay={pay} />)}
          </div>}
      {(data.addons || []).length > 0 && (
        <>
          <h3 style={{ ...h3, fontFamily: FONT, fontSize: 17, margin: '8px 0 12px' }}>Add what you need</h3>
          <div style={{ ...card, padding: '4px 16px' }}>
            {data.addons.map((a, i) => (
              <div key={a.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '14px 0', borderTop: i ? `1px solid ${ds.border}` : 0 }}>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: ds.dark }}>{a.label}</div>
                  <div style={{ fontSize: 13, color: ds.gray }}>{ngn(a.monthly_ngn)} a month</div>
                  {a.caps?.bookings > 0 && (
                    <div style={{ fontSize: 12.5, color: ds.gray, marginTop: 2 }}>
                      Includes {a.caps.bookings} bookings a month{a.overage_ngn > 0 ? `, then ${ngn(a.overage_ngn)} from your credit for each extra` : ''}.
                    </div>
                  )}
                </div>
                <span style={{ fontSize: 13, fontWeight: 600, color: a.active || a.included ? ds.teal : ds.gray, textAlign: 'right' }}>
                  {a.included ? 'Included in your plan' : a.active ? 'On' : 'Ask us to switch it on'}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
      <p style={{ fontSize: 12.5, color: ds.gray, maxWidth: 640 }}>Plans are paid monthly with Paystack and are not refundable. Credits are separate. Buy them in the Credits tab.</p>
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

const TABS = [['plan', 'Plan'], ['team', 'Team'], ['usage', 'Usage'], ['credits', 'Credits'], ['payments', 'Payments']]

function TeamTab({ data, reload, setMsg, onOpenAdmin }) {
  const t = data.team
  const [add, setAdd] = useState(1)
  const [quote, setQuote] = useState(null)
  const [busy, setBusy] = useState(false)
  const [next, setNext] = useState(t ? t.seats_next : 0)
  useEffect(() => { if (t) setNext(t.seats_next) }, [t])
  useEffect(() => {
    if (!t?.can_buy) { setQuote(null); return undefined }
    let live = true
    previewSeats(add).then((q) => { if (live) setQuote(q) }).catch(() => { if (live) setQuote(null) })
    return () => { live = false }
  }, [add, t?.can_buy])
  if (!t) return <div style={card}><p style={{ margin: 0, fontSize: 13, color: ds.gray }}>Team details are not available right now.</p></div>
  const buy = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await startSeatsCheckout(add)
      lsSet(r.reference)
      window.location.assign(r.checkout_url)
    } catch (e) { setMsg(planError(e)); setBusy(false) }
  }
  const saveNext = async () => {
    setBusy(true); setMsg('')
    try { await setNextSeats(next); setMsg('Saved. Your next renewal will use this number of extra users.'); reload() } catch (e) { setMsg(planError(e)) }
    setBusy(false)
  }
  const stat = (label, value) => (
    <div style={{ flex: '1 1 140px' }}>
      <div style={{ fontSize: 12, color: ds.gray }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: ds.dark, fontFamily: ds.fontSyne }}>{value}</div>
    </div>
  )
  return (
    <>
      <div style={card}>
        <h3 style={h3}>Users</h3>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {stat('Users now', t.used)}
          {stat('Users your plan allows', t.enforced ? t.allowed : 'No limit')}
          {stat('Included with every plan', t.included)}
          {stat('Extra users bought', t.seats)}
        </div>
        <p style={{ fontSize: 13, color: ds.gray, margin: '12px 0 0' }}>
          Every plan includes {t.included} users (an admin and one staff member). Each extra user is {ngn(t.price_ngn)} a month.
          {t.paid_until && t.seats > 0 ? ` Your extra users run until ${day(t.paid_until)} and renew with your plan.` : ''}
        </p>
        {!t.enforced && <p style={{ fontSize: 13, color: ds.gray, margin: '8px 0 0' }}>Your account has no user limit at the moment.</p>}
        {onOpenAdmin && (
          <div style={{ marginTop: 12 }}>
            <button type="button" style={btn(false)} onClick={onOpenAdmin}>Manage users</button>
            <span style={{ fontSize: 12.5, color: ds.gray, marginLeft: 10 }}>New users are added in Admin Dashboard &gt; Users.</span>
          </div>
        )}
        {t.over_by > 0 && (
          <div role="alert" style={{ marginTop: 12, padding: 12, borderRadius: ds.radius.sm, background: '#FFF4E5', color: ds.dark, fontSize: 13 }}>
            {t.seats_lapsed ? 'Your extra users have ended. ' : ''}You have {t.over_by} more user{t.over_by === 1 ? '' : 's'} than your plan allows. Nobody has been removed,
            but you cannot add new users until you buy extra users or renew.
          </div>
        )}
      </div>
      <div style={card}>
        <h3 style={h3}>Add users</h3>
        {!t.can_buy
          ? <p style={{ margin: 0, fontSize: 13, color: ds.gray }}>{t.reason}</p>
          : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <button type="button" aria-label="One fewer user" style={btn(false)} disabled={add <= 1 || busy} onClick={() => setAdd((a) => Math.max(1, a - 1))}>−</button>
                <strong aria-live="polite" style={{ minWidth: 32, textAlign: 'center', fontSize: 18 }}>{add}</strong>
                <button type="button" aria-label="One more user" style={btn(false)} disabled={add >= 50 || busy} onClick={() => setAdd((a) => Math.min(50, a + 1))}>+</button>
                <span style={{ fontSize: 13, color: ds.gray }}>extra user{add === 1 ? '' : 's'}</span>
              </div>
              <p style={{ fontSize: 13, color: ds.dark, margin: '12px 0' }}>
                {quote
                  ? `${ngn(quote.total)} today, for the ${quote.days} day${quote.days === 1 ? '' : 's'} left on your plan (until ${day(quote.paid_until)}). After that they renew with your plan at ${ngn(t.price_ngn)} each a month.`
                  : 'Working out the price…'}
              </p>
              <button type="button" className="bp-cta" style={btn(true)} disabled={busy || !quote} onClick={buy}>{busy ? 'Opening Paystack…' : 'Pay and add users'}</button>
            </>
          )}
      </div>
      {t.seats > 0 && !t.free_seats && (
        <div style={card}>
          <h3 style={h3}>At your next renewal</h3>
          <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 10px' }}>Need fewer extra users next month? Choose how many to keep. They stay on until your plan ends.</p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" aria-label="Keep one fewer" style={btn(false)} disabled={next <= 0 || busy} onClick={() => setNext((n) => Math.max(0, n - 1))}>−</button>
            <strong aria-live="polite" style={{ minWidth: 32, textAlign: 'center', fontSize: 18 }}>{next}</strong>
            <button type="button" aria-label="Keep one more" style={btn(false)} disabled={next >= t.seats || busy} onClick={() => setNext((n) => Math.min(t.seats, n + 1))}>+</button>
            <button type="button" style={btn(false)} disabled={busy || next === t.seats_next} onClick={saveNext}>Save</button>
          </div>
        </div>
      )}
    </>
  )
}

export default function BillingModule({ onOpenAdmin }) {
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
    <div style={{ maxWidth: 1600, fontFamily: ds.fontDm }}>
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
      {data && tab === 'team' && <TeamTab data={data} reload={load} setMsg={setMsg} onOpenAdmin={onOpenAdmin} />}
      {data && tab === 'usage' && <UsageTab data={data} />}
      {data && tab === 'payments' && <PaymentsTab data={data} />}
    </div>
  )
}
