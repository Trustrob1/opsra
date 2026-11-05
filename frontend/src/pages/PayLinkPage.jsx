/**
 * frontend/src/pages/PayLinkPage.jsx
 * BILL-4 — /pay/<token>: an invoice-style page for one business. Shows the plan, the credit left, and lets whoever holds the
 * link renew the plan or top up credit through Paystack. No login, no settings, nothing else.
 */
import { useCallback, useEffect, useState } from 'react'
import { ds } from '../utils/ds'
import { naira } from '../services/credits.service'
import { ngn } from '../services/accountPlan.service'
import { getPayView, payRenew, payTopup, payVerify, payError } from '../services/billingPublic.service'
import { B, button, tile, tileDark, tileLabel, tileValue, panel, panelTitle, panelSub, BILLING_CSS } from '../modules/billing/billingUi'

// End dates are stored as 23:59:59 UTC on the last day, so show the UTC date (same as Billing and the staff screen).
const day = (v) => (v ? new Date(v).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '')
const STATUS = { active: 'Active', grace: 'Ended, still on for a few days', paused: 'Paused', pending: 'Not paid yet' }

export default function PayLinkPage({ token }) {
  const [view, setView] = useState(null)
  const [gone, setGone] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [custom, setCustom] = useState('')

  const load = useCallback(async () => {
    try { setView(await getPayView(token)) } catch (e) {
      setGone(e?.response?.status === 404 ? (e.response.data?.detail || 'This link is not valid any more.') : payError(e, 'Could not load this page. Please try again.'))
    }
  }, [token])
  useEffect(() => { load() }, [load])

  // Coming back from Paystack: confirm the payment, then drop the reference from the address.
  useEffect(() => {
    const ref = new URLSearchParams(window.location.search).get('reference') || new URLSearchParams(window.location.search).get('trxref')
    if (!ref) return undefined
    let stop = false
    let tries = 0
    const check = async () => {
      if (stop) return
      try {
        const r = await payVerify(token, ref)
        if (r.status === 'paid') { setMsg('Payment received. Thank you.'); load(); window.history.replaceState({}, '', `/pay/${token}`); return }
        if (r.status === 'failed') { setMsg('That payment did not go through. You have not been charged.'); window.history.replaceState({}, '', `/pay/${token}`); return }
      } catch { window.history.replaceState({}, '', `/pay/${token}`); return }
      if (++tries < 6) setTimeout(check, 4000)
      else setMsg('We have not received that payment yet. It will show here once Paystack confirms it.')
    }
    check()
    return () => { stop = true }
  }, [token, load])
  useEffect(() => {
    const reset = () => setBusy(false)
    window.addEventListener('pageshow', reset)
    return () => window.removeEventListener('pageshow', reset)
  }, [])

  const go = async (fn) => {
    setBusy(true); setMsg('')
    try { const r = await fn(); window.location.assign(r.checkout_url) } catch (e) { setMsg(payError(e)); setBusy(false) }
  }
  const topCustom = () => {
    const n = Number(String(custom).replace(/[, ]/g, ''))
    if (!Number.isInteger(n) || n <= 0) { setMsg('Enter a whole number of naira.'); return }
    go(() => payTopup(token, { amount_naira: n }))
  }

  const shell = (children) => (
    <div style={{ minHeight: '100vh', background: B.page, fontFamily: ds.fontDm, color: ds.dark, padding: '40px 20px 64px', boxSizing: 'border-box' }}>
      <style>{BILLING_CSS}</style>
      <div style={{ maxWidth: 760, margin: '0 auto' }}>{children}</div>
    </div>
  )
  if (gone) {
    return shell(
      <div style={{ ...panel, textAlign: 'center', padding: 40 }}>
        <h1 style={{ ...panelTitle, fontSize: 20 }}>This link has ended</h1>
        <p style={{ ...panelSub, marginTop: 8 }}>{gone}</p>
      </div>,
    )
  }
  if (!view) return shell(<div style={{ color: B.muted, fontSize: 14 }}>Loading…</div>)

  const { plan, credit, renew, packs } = view
  const inc = credit?.included
  const left = inc && inc.granted ? inc.remaining_kobo : null
  return shell(
    <>
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 13, color: B.muted }}>Billing for</div>
        <h1 style={{ margin: '2px 0 0', fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em' }}>{view.business || 'Your business'}</h1>
      </div>
      {msg && <div role="status" style={{ ...panel, padding: 14, fontSize: 13.5, marginBottom: 16 }}>{msg}</div>}

      <section style={{ ...tileDark, borderRadius: 20, padding: 28, marginBottom: 16, gap: 22 }} aria-label="Your plan">
        {plan ? (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
              <div>
                <span style={{ display: 'inline-block', fontSize: 12.5, background: 'rgba(255,255,255,0.12)', padding: '4px 12px', borderRadius: 999 }}>{STATUS[plan.status] || plan.status}</span>
                <div style={{ fontSize: 32, fontWeight: 700, letterSpacing: '-0.02em', margin: '12px 0 4px' }}>{plan.label}</div>
                <div style={{ fontSize: 13.5, color: '#B8D6D4' }}>
                  {plan.monthly_ngn > 0 ? `${ngn(plan.monthly_ngn)} a month. ` : ''}{plan.paid_until ? `${plan.status === 'active' ? 'Renews by' : 'Ended on'} ${day(plan.paid_until)}.` : ''}
                </div>
              </div>
              {renew && (
                <button type="button" className="bl-btn" disabled={busy} onClick={() => go(() => payRenew(token))}
                  style={{ ...button(false), background: '#fff', color: B.deep, border: 0, minHeight: 44 }}>
                  {busy ? 'Opening Paystack…' : `Renew for ${ngn(renew.amount_ngn)}`}
                </button>
              )}
            </div>
            {inc && (
              <div style={{ background: 'rgba(255,255,255,0.08)', borderRadius: 16, padding: 16 }}>
                <div style={{ fontSize: 12.5, color: '#B8D6D4' }}>Included credit this month</div>
                {left !== null ? (
                  <>
                    <div style={{ margin: '6px 0 10px' }}><span style={{ fontSize: 24, fontWeight: 700 }}>{naira(left)}</span><span style={{ fontSize: 13, color: '#B8D6D4' }}> left of {naira(inc.granted_kobo)}</span></div>
                    <div role="progressbar" aria-label="Included credit left" aria-valuenow={Math.round((left / Math.max(inc.granted_kobo, 1)) * 100)} aria-valuemin={0} aria-valuemax={100}
                      style={{ height: 6, borderRadius: 999, background: 'rgba(255,255,255,0.16)', overflow: 'hidden' }}>
                      <div style={{ width: `${Math.round((left / Math.max(inc.granted_kobo, 1)) * 100)}%`, height: '100%', background: B.tick }} />
                    </div>
                    <div style={{ fontSize: 12, color: '#B8D6D4', marginTop: 8 }}>Resets {day(inc.resets_at)}. It does not roll over.</div>
                  </>
                ) : <div style={{ fontSize: 13, color: '#B8D6D4', marginTop: 6 }}>{naira(inc.monthly_kobo)} is added at the start of each month.</div>}
              </div>
            )}
          </>
        ) : <div style={{ fontSize: 16 }}>This business is not on a paid plan yet.</div>}
      </section>

      {credit && (
        <div className="bl-bento">
          <div style={tile}><div style={tileLabel}>Credit left</div><div style={{ ...tileValue, color: credit.low ? '#B3261E' : ds.dark }}>{naira(credit.balance_kobo)}</div></div>
          <div style={tile}><div style={tileLabel}>Used this month</div><div style={tileValue}>{naira(credit.month_spend_kobo)}</div></div>
        </div>
      )}

      <section style={panel} aria-label="Top up credit">
        <h2 style={panelTitle}>Top up credit</h2>
        <p style={{ ...panelSub, marginBottom: 18 }}>Pays for AI replies and WhatsApp message fees.</p>
        <div className="bl-packs">
          {packs.map((p) => (
            <button key={p.id} type="button" className="bl-pack" disabled={busy} onClick={() => go(() => payTopup(token, { pack_id: p.id }))}>
              <span style={{ fontSize: 17, fontWeight: 700 }}>{naira(p.price_kobo)}</span>
              <span style={{ fontSize: 12, color: p.credit_kobo > p.price_kobo ? ds.tealDark : B.muted, fontWeight: p.credit_kobo > p.price_kobo ? 600 : 400 }}>{p.credit_kobo > p.price_kobo ? `Get ${naira(p.credit_kobo)}` : 'No bonus'}</span>
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginTop: 20 }}>
          <div style={{ flex: '1 1 220px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label htmlFor="pl-custom" style={{ fontSize: 13, fontWeight: 600 }}>Custom amount <span style={{ fontWeight: 400, color: B.muted }}>(₦{(view.min_custom_kobo / 100).toLocaleString()} to ₦{(view.max_order_kobo / 100).toLocaleString()})</span></label>
            <input id="pl-custom" inputMode="numeric" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="e.g. 15000"
              style={{ minHeight: 40, boxSizing: 'border-box', padding: '0 14px', border: '1px solid #CFDCDA', borderRadius: 12, fontSize: 14, fontFamily: ds.fontDm }} />
          </div>
          <button type="button" className="bl-btn" style={button(true)} disabled={busy} onClick={topCustom}>{busy ? 'Opening…' : 'Pay with Paystack'}</button>
        </div>
        <p style={{ fontSize: 12.5, color: B.muted, margin: '14px 0 0', lineHeight: 1.5 }}>You get exactly what you pay. Credit is not refundable and expires 12 months after purchase.</p>
      </section>
      <p style={{ fontSize: 12.5, color: B.muted, textAlign: 'center', marginTop: 20 }}>This private link works until {day(view.expires_at)}. Anyone who has it can pay for this business, so please do not post it publicly.</p>
    </>,
  )
}
