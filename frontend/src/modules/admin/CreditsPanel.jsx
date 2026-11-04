/**
 * frontend/src/modules/admin/CreditsPanel.jsx
 * CREDITS-2 — Admin > Credits. Balance, what it was spent on, and Buy credits (Paystack).
 * Backend: routers/credits.py (owner / ops manager only).
 */
import { useCallback, useEffect, useState } from 'react'
import {
  getCreditSummary, getCreditUsage, getCreditLedger, getCreditPacks, getCreditOrders,
  startCreditCheckout, verifyCreditPayment, setWhatsappBudget, naira, creditError,
} from '../../services/credits.service'
import { ds } from '../../utils/ds'
import { B, panel, panelTitle, panelSub, button, tile, tileDark, tileLabel, tileValue, emptyBox, BILLING_CSS } from '../billing/billingUi'

const PENDING_KEY = 'opsra_pending_credit_ref'
const card = panel
const h3 = { ...panelTitle, margin: 0 }
const btn = button
const KINDS = { ai: 'AI replies', meta: 'WhatsApp fees', fee: 'Automation fees', topup: 'Top-up', adjust: 'Adjustment', refund: 'Refund', expiry: 'Expired credit' }
const SHADE = { ai: ds.teal, meta: '#0D1B2A', fee: '#9AA9B8' }

const lsGet = () => { try { return localStorage.getItem(PENDING_KEY) } catch { return null } }
const lsSet = (v) => { try { v ? localStorage.setItem(PENDING_KEY, v) : localStorage.removeItem(PENDING_KEY) } catch { /* private mode */ } }

function Bars({ series }) {
  const max = Math.max(1, ...series.map((d) => d.ai + d.meta + d.fee))
  return (
    <div role="img" aria-label="Credit spend per day" style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 90 }}>
      {series.map((d) => {
        const total = d.ai + d.meta + d.fee
        return (
          <div key={d.day} title={`${d.day}: ${naira(total)}`} style={{ flex: 1, minWidth: 2, display: 'flex', flexDirection: 'column-reverse', height: '100%', justifyContent: 'flex-start' }}>
            {['ai', 'meta', 'fee'].map((k) => d[k] > 0 && <div key={k} style={{ height: `${(d[k] / max) * 100}%`, background: SHADE[k], borderRadius: 1 }} />)}
          </div>
        )
      })}
    </div>
  )
}

export default function CreditsPanel({ embedded = false }) {
  const [sum, setSum] = useState(null)
  const [use, setUse] = useState(null)
  const [days, setDays] = useState(30)
  const [packs, setPacks] = useState([])
  const [orders, setOrders] = useState([])
  const [ledger, setLedger] = useState({ entries: [], next: null })
  const [custom, setCustom] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [denied, setDenied] = useState(false)
  const [waBudget, setWaBudget] = useState('')
  const [waAction, setWaAction] = useState('chat')
  const [waSaved, setWaSaved] = useState(false)

  const load = useCallback(async () => {
    try {
      const [s, p, o, l] = await Promise.all([getCreditSummary(), getCreditPacks(), getCreditOrders(), getCreditLedger()])
      setSum(s); setPacks(p.packs); setOrders(o.orders); setLedger(l)
      setWaBudget(s.wa_monthly_budget_kobo ? String(s.wa_monthly_budget_kobo / 100) : '')
      setWaAction(s.wa_over_budget_action === 'continue' ? 'continue' : 'chat')
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true)
      else setMsg(creditError(e, 'Could not load your credits.'))
    }
  }, [])
  useEffect(() => { load() }, [load])
  // Coming back with the browser's Back button restores this page as it was (button still saying "Opening…"). Reset it.
  useEffect(() => {
    const reset = () => setBusy(false)
    window.addEventListener('pageshow', reset)
    document.addEventListener('visibilitychange', reset)
    return () => { window.removeEventListener('pageshow', reset); document.removeEventListener('visibilitychange', reset) }
  }, [])
  useEffect(() => { getCreditUsage(days).then(setUse).catch(() => {}) }, [days])

  // Coming back from Paystack: confirm the payment we were waiting for.
  useEffect(() => {
    const ref = lsGet()
    if (!ref) return
    let tries = 0
    const check = async () => {
      try {
        const r = await verifyCreditPayment(ref)
        if (r.status === 'paid') { lsSet(null); setMsg('Payment received. Your credits have been added.'); load(); return }
        if (r.status === 'failed') { lsSet(null); setMsg('That payment did not go through. You have not been charged.'); return }
      } catch { lsSet(null); return }
      if (++tries < 6) setTimeout(check, 4000)
      else setMsg('We have not received that payment yet. It will be added automatically once Paystack confirms it.')
    }
    check()
  }, [load])

  const buy = async (body) => {
    setBusy(true); setMsg('')
    try {
      const r = await startCreditCheckout(body)
      lsSet(r.reference)
      window.location.assign(r.checkout_url)
    } catch (e) { setMsg(creditError(e)); setBusy(false) }
  }
  const buyCustom = () => {
    const n = Number(String(custom).replace(/[, ]/g, ''))
    if (!Number.isInteger(n) || n <= 0) { setMsg('Enter a whole number of naira.'); return }
    buy({ amount_naira: n })
  }
  const saveWaBudget = async () => {
    const raw = String(waBudget).replace(/[, ]/g, '')
    const n = raw === '' ? 0 : Number(raw)
    if (!Number.isInteger(n) || n < 0) { setMsg('Enter a whole number of naira, or leave it empty for no limit.'); return }
    setBusy(true); setMsg(''); setWaSaved(false)
    try { setSum(await setWhatsappBudget(n, waAction)); setWaSaved(true) } catch (e) { setMsg(creditError(e)) }
    setBusy(false)
  }
  const more = async () => {
    try { const l = await getCreditLedger(ledger.next); setLedger({ entries: [...ledger.entries, ...l.entries], next: l.next }) } catch { /* ignore */ }
  }

  if (denied) return <div style={{ padding: 20, color: ds.gray, fontFamily: ds.fontDm }}>Only the owner or an operations manager can see credits.</div>
  if (!sum) return <div style={{ padding: 20, color: ds.gray, fontFamily: ds.fontDm }}>{msg || 'Loading…'}</div>

  const low = sum.low_balance_kobo > 0 && sum.balance_kobo <= sum.low_balance_kobo
  const waBudgetKobo = Number(sum.wa_monthly_budget_kobo || 0)
  const waSpent = Number(sum.month_wa_spend_kobo || 0)
  const waPct = waBudgetKobo ? Math.min(100, Math.round((waSpent / waBudgetKobo) * 100)) : 0
  const waOver = waBudgetKobo > 0 && waSpent >= waBudgetKobo
  const bonus = (p) => (p.credit_kobo > p.price_kobo ? `Get ${naira(p.credit_kobo)}` : 'No bonus')
  return (
    <div style={{ maxWidth: embedded ? undefined : 1100, fontFamily: ds.fontDm }}>
      <style>{BILLING_CSS}</style>
      {!embedded && (
        <div style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em', color: ds.dark, margin: 0 }}>Credits</h2>
          <p style={{ fontSize: 13.5, color: B.muted, margin: '4px 0 0' }}>Prepaid credit pays for AI replies and, where applicable, WhatsApp message fees. Credit lasts 12 months from purchase.</p>
        </div>
      )}
      {msg && <div role="status" style={{ ...card, padding: 14, color: ds.dark, fontSize: 13.5 }}>{msg}</div>}

      <div className="bl-bento">
        <div className="bl-bento-hero" style={{ ...tileDark, minHeight: 190 }}>
          <div style={{ ...tileLabel, color: '#B8D6D4' }}>Credit balance</div>
          <div>
            <div style={{ fontSize: 52, fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1, color: low ? '#FFB4B4' : '#fff' }}>{naira(sum.balance_kobo)}</div>
            {low && <div style={{ fontSize: 13.5, color: '#FFB4B4', marginTop: 8 }}>Your balance is low. Top up so AI replies keep working.</div>}
            {!sum.metering_enabled && <div style={{ fontSize: 13, color: '#B8D6D4', marginTop: 8 }}>Usage is not being charged to your balance yet.</div>}
          </div>
        </div>
        <div style={tile}>
          <div style={tileLabel}>Spent this month</div>
          <div style={tileValue}>{naira(sum.month_spend_total_kobo)}</div>
        </div>
        <div style={tile}>
          <div style={tileLabel}>Next to expire</div>
          {sum.expiring
            ? <div><div style={tileValue}>{naira(sum.expiring.kobo)}</div><div style={{ fontSize: 12.5, color: B.muted, marginTop: 6 }}>on {String(sum.expiring.at).slice(0, 10)}</div></div>
            : <div><div style={tileValue}>None</div><div style={{ fontSize: 12.5, color: B.muted, marginTop: 6 }}>Credit lasts 12 months</div></div>}
        </div>
      </div>

      <div className="bl-split">
        <div className="bl-main">
          <section style={card} aria-label="Top up credits">
            <h3 style={h3}>Top up credits</h3>
            <p style={{ ...panelSub, marginBottom: 18 }}>Pays for AI replies and WhatsApp message fees.</p>
            <div className="bl-packs">
              {packs.map((p) => (
                <button key={p.id} type="button" className="bl-pack" disabled={busy} onClick={() => buy({ pack_id: p.id })}>
                  <span style={{ fontSize: 17, fontWeight: 700 }}>{naira(p.price_kobo)}</span>
                  <span style={{ fontSize: 12, color: p.credit_kobo > p.price_kobo ? ds.tealDark : B.muted, fontWeight: p.credit_kobo > p.price_kobo ? 600 : 400 }}>{bonus(p)}</span>
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginTop: 20 }}>
              <div style={{ flex: '1 1 220px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label htmlFor="cr-custom" style={{ fontSize: 13, fontWeight: 600, color: ds.dark }}>
                  Custom amount <span style={{ fontWeight: 400, color: B.muted }}>(₦{(sum.min_custom_kobo / 100).toLocaleString()} to ₦{(sum.max_order_kobo / 100).toLocaleString()})</span>
                </label>
                <input id="cr-custom" inputMode="numeric" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="e.g. 15000"
                  style={{ minHeight: 40, boxSizing: 'border-box', padding: '0 14px', border: '1px solid #CFDCDA', borderRadius: 12, fontSize: 14, fontFamily: ds.fontDm, color: ds.dark }} />
              </div>
              <button type="button" className="bl-btn" style={btn(true)} disabled={busy} onClick={buyCustom}>{busy ? 'Opening…' : 'Pay with Paystack'}</button>
            </div>
            <p style={{ fontSize: 12.5, color: B.muted, margin: '14px 0 0', lineHeight: 1.5 }}>You get exactly what you pay. Credit is not refundable and expires 12 months after purchase.</p>
          </section>

          <section style={card} aria-label="WhatsApp budget">
            <h3 style={h3}>WhatsApp budget</h3>
            <p style={{ ...panelSub, marginBottom: 16 }}>Set how much you are happy to spend on WhatsApp messages each month. When it is used up, Opsra can send customers to your web chat instead.</p>
            {waBudgetKobo > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13.5, color: ds.dark, marginBottom: 6 }}>
                  <span>{naira(waSpent)} used</span><span style={{ color: B.muted }}>of {naira(waBudgetKobo)}</span>
                </div>
                <div role="progressbar" aria-valuenow={waPct} aria-valuemin={0} aria-valuemax={100} aria-label="WhatsApp budget used"
                  style={{ height: 8, borderRadius: 99, background: B.soft, overflow: 'hidden' }}>
                  <div style={{ width: `${waPct}%`, height: '100%', background: waOver ? '#C0392B' : waPct >= 80 ? '#D98A1F' : ds.teal }} />
                </div>
                {waOver && waAction === 'chat' && <p style={{ fontSize: 13.5, color: '#8A2A1F', margin: '10px 0 0' }}>Budget used up. Customers who message you on WhatsApp now get a link to your web chat, and marketing messages are paused. Raise the budget to switch back.</p>}
                {!waOver && waPct >= 80 && <p style={{ fontSize: 13.5, color: '#8A4A05', margin: '10px 0 0' }}>You have used {waPct}% of your WhatsApp budget. {waAction === 'chat' ? 'Customers will be sent to web chat when it runs out.' : 'Messages will keep going and use your credit.'}</p>}
              </div>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
              <div style={{ flex: '1 1 200px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label htmlFor="wa-budget" style={{ fontSize: 13, fontWeight: 600, color: ds.dark }}>Monthly WhatsApp budget (₦) <span style={{ fontWeight: 400, color: B.muted }}>empty = no limit</span></label>
                <input id="wa-budget" inputMode="numeric" value={waBudget} onChange={(e) => { setWaBudget(e.target.value); setWaSaved(false) }} placeholder="e.g. 20000"
                  style={{ minHeight: 40, boxSizing: 'border-box', padding: '0 14px', border: '1px solid #CFDCDA', borderRadius: 12, fontSize: 14, fontFamily: ds.fontDm, color: ds.dark }} />
              </div>
              <div style={{ flex: '1 1 240px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label htmlFor="wa-action" style={{ fontSize: 13, fontWeight: 600, color: ds.dark }}>When it is used up</label>
                <select id="wa-action" value={waAction} onChange={(e) => { setWaAction(e.target.value); setWaSaved(false) }}
                  style={{ minHeight: 40, border: '1px solid #CFDCDA', borderRadius: 12, padding: '0 12px', fontFamily: ds.fontDm, fontSize: 14, background: '#fff', color: ds.dark }}>
                  <option value="chat">Switch customers to web chat</option>
                  <option value="continue">Keep sending and use my credit</option>
                </select>
              </div>
              <button type="button" className="bl-btn" style={btn(true)} disabled={busy} onClick={saveWaBudget}>{waSaved ? 'Saved' : 'Save budget'}</button>
            </div>
            <p style={{ fontSize: 12.5, color: B.muted, margin: '14px 0 0', lineHeight: 1.5 }}>Replies to customers who message you stay free for the first 1,000 a month. Each web chat conversation costs ₦20.</p>
          </section>

          <section style={card} aria-label="Usage">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <h3 style={h3}>Where credit goes</h3>
              <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}
                style={{ minHeight: 36, border: `1px solid ${B.line}`, borderRadius: 999, padding: '0 14px', fontFamily: ds.fontDm, fontSize: 13, background: B.soft, color: ds.dark }}>
                <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
              </select>
            </div>
            {use && (use.spent_kobo === 0
              ? <div style={{ ...emptyBox, marginTop: 16 }}>Nothing has been spent in this period.</div>
              : <>
                  <div style={{ margin: '16px 0 12px' }}><Bars series={use.series} /></div>
                  <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13, color: ds.dark }}>
                    {['ai', 'meta', 'fee'].map((k) => (
                      <span key={k}><span aria-hidden style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, background: SHADE[k], marginRight: 6 }} />{KINDS[k]}: {naira(use.totals_kobo[k])}</span>
                    ))}
                  </div>
                </>)}
          </section>
        </div>

        <div className="bl-side">
          <section style={card} aria-label="Transactions">
            <h3 style={{ ...h3, marginBottom: 16 }}>Recent activity</h3>
            {ledger.entries.length === 0 ? (
              <div style={emptyBox}><strong style={{ fontSize: 15, color: ds.dark }}>Nothing yet</strong><span>Top-ups and message charges will appear here.</span></div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
                  <thead><tr style={{ textAlign: 'left', color: B.muted, fontSize: 12.5 }}><th scope="col">Date</th><th scope="col">What</th><th scope="col" style={{ textAlign: 'right' }}>Amount</th><th scope="col" style={{ textAlign: 'right' }}>Balance</th></tr></thead>
                  <tbody>
                    {ledger.entries.map((e) => (
                      <tr key={e.id} style={{ borderTop: `1px solid ${B.soft}` }}>
                        <td style={{ padding: '10px 0' }}>{String(e.created_at).slice(0, 10)}</td>
                        <td>{KINDS[e.kind] || e.kind}</td>
                        <td style={{ textAlign: 'right', color: e.amount_kobo < 0 ? ds.dark : ds.teal }}>{e.amount_kobo < 0 ? '-' : '+'}{naira(Math.abs(e.amount_kobo))}</td>
                        <td style={{ textAlign: 'right' }}>{naira(e.balance_after_kobo)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {ledger.next && <button type="button" className="bl-btn" style={{ ...btn(false), marginTop: 12 }} onClick={more}>Show more</button>}
          </section>

          {orders.length > 0 && (
            <section style={card} aria-label="Recent top-ups">
              <h3 style={{ ...h3, marginBottom: 12 }}>Recent top-ups</h3>
              {orders.map((o) => (
                <div key={o.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13.5, padding: '10px 0', borderTop: `1px solid ${B.soft}` }}>
                  <span>{String(o.created_at).slice(0, 10)}</span><span>{naira(o.amount_kobo)}</span>
                  <span style={{ color: o.status === 'paid' ? ds.teal : B.muted }}>{o.status === 'paid' ? 'Paid' : o.status === 'pending' ? 'Not completed' : 'Failed'}</span>
                </div>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
