/**
 * frontend/src/modules/admin/CreditsPanel.jsx
 * CREDITS-2 — Admin > Credits. Balance, what it was spent on, and Buy credits (Paystack).
 * Backend: routers/credits.py (owner / ops manager only).
 */
import { useCallback, useEffect, useState } from 'react'
import {
  getCreditSummary, getCreditUsage, getCreditLedger, getCreditPacks, getCreditOrders,
  startCreditCheckout, verifyCreditPayment, naira, creditError,
} from '../../services/credits.service'
import { ds } from '../../utils/ds'

const PENDING_KEY = 'opsra_pending_credit_ref'
const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const h3 = { fontSize: 15, fontWeight: 600, color: ds.dark, margin: '0 0 10px', fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 44, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
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

export default function CreditsPanel() {
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

  const load = useCallback(async () => {
    try {
      const [s, p, o, l] = await Promise.all([getCreditSummary(), getCreditPacks(), getCreditOrders(), getCreditLedger()])
      setSum(s); setPacks(p.packs); setOrders(o.orders); setLedger(l)
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
  const more = async () => {
    try { const l = await getCreditLedger(ledger.next); setLedger({ entries: [...ledger.entries, ...l.entries], next: l.next }) } catch { /* ignore */ }
  }

  if (denied) return <div style={{ padding: 20, color: ds.gray, fontFamily: ds.fontDm }}>Only the owner or an operations manager can see credits.</div>
  if (!sum) return <div style={{ padding: 20, color: ds.gray, fontFamily: ds.fontDm }}>{msg || 'Loading…'}</div>

  const low = sum.low_balance_kobo > 0 && sum.balance_kobo <= sum.low_balance_kobo
  return (
    <div style={{ maxWidth: 1600, fontFamily: ds.fontDm }}>
      <h2 style={{ fontSize: 20, color: ds.dark, margin: '0 0 4px' }}>Credits</h2>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 16px' }}>Prepaid credit pays for AI replies and, where applicable, WhatsApp message fees. Credit lasts 12 months from purchase.</p>
      {msg && <div role="status" style={{ ...card, padding: 12, color: ds.dark }}>{msg}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 16, alignItems: 'start' }}>
      <div>
      <div style={card}>
        <div style={{ fontSize: 12, color: ds.gray }}>Balance</div>
        <div style={{ fontSize: 30, fontWeight: 700, color: low ? ds.red : ds.dark }}>{naira(sum.balance_kobo)}</div>
        {low && <div style={{ color: ds.red, fontSize: 13 }}>Your balance is low. Top up so AI replies keep working.</div>}
        {sum.expiring && <div style={{ fontSize: 12, color: ds.gray }}>{naira(sum.expiring.kobo)} expires on {String(sum.expiring.at).slice(0, 10)}</div>}
        {!sum.metering_enabled && <div style={{ fontSize: 12, color: ds.gray, marginTop: 6 }}>Usage is not being charged to your balance yet.</div>}
        <div style={{ fontSize: 13, color: ds.dark, marginTop: 8 }}>Spent this month: {naira(sum.month_spend_total_kobo)}</div>
      </div>

      <div style={card}>
        <h3 style={h3}>Buy credits</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
          {packs.map((p) => (
            <button key={p.id} type="button" style={btn(false)} disabled={busy} onClick={() => buy({ pack_id: p.id })}>Buy {naira(p.price_kobo)}</button>
          ))}
        </div>
        <label htmlFor="cr-custom" style={{ display: 'block', fontSize: 12, fontWeight: 600, color: ds.dark, margin: '12px 0 4px' }}>
          Or enter an amount (₦{(sum.min_custom_kobo / 100).toLocaleString()} to ₦{(sum.max_order_kobo / 100).toLocaleString()})
        </label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input id="cr-custom" inputMode="numeric" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="e.g. 15000"
            style={{ flex: 1, minHeight: 44, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }} />
          <button type="button" style={btn(true)} disabled={busy} onClick={buyCustom}>{busy ? 'Opening…' : 'Pay with Paystack'}</button>
        </div>
        <p style={{ fontSize: 12, color: ds.gray, margin: '8px 0 0' }}>You get exactly what you pay. Credit is not refundable and expires 12 months after purchase.</p>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ ...h3, margin: 0 }}>Usage</h3>
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}
            style={{ minHeight: 40, border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, padding: '0 8px', fontFamily: ds.fontDm }}>
            <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
          </select>
        </div>
        {use && (use.spent_kobo === 0
          ? <p style={{ fontSize: 13, color: ds.gray }}>Nothing has been spent in this period.</p>
          : <>
              <div style={{ margin: '12px 0 8px' }}><Bars series={use.series} /></div>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: ds.dark }}>
                {['ai', 'meta', 'fee'].map((k) => (
                  <span key={k}><span aria-hidden style={{ display: 'inline-block', width: 10, height: 10, background: SHADE[k], marginRight: 6 }} />{KINDS[k]}: {naira(use.totals_kobo[k])}</span>
                ))}
              </div>
            </>)}
      </div>

      </div>
      <div>
      <div style={card}>
        <h3 style={h3}>Transactions</h3>
        {ledger.entries.length === 0 ? <p style={{ fontSize: 13, color: ds.gray }}>No transactions yet.</p> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: ds.gray }}><th scope="col">Date</th><th scope="col">What</th><th scope="col" style={{ textAlign: 'right' }}>Amount</th><th scope="col" style={{ textAlign: 'right' }}>Balance</th></tr></thead>
              <tbody>
                {ledger.entries.map((e) => (
                  <tr key={e.id} style={{ borderTop: `1px solid ${ds.border}` }}>
                    <td style={{ padding: '6px 0' }}>{String(e.created_at).slice(0, 10)}</td>
                    <td>{KINDS[e.kind] || e.kind}</td>
                    <td style={{ textAlign: 'right', color: e.amount_kobo < 0 ? ds.dark : ds.teal }}>{e.amount_kobo < 0 ? '-' : '+'}{naira(Math.abs(e.amount_kobo))}</td>
                    <td style={{ textAlign: 'right' }}>{naira(e.balance_after_kobo)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {ledger.next && <button type="button" style={{ ...btn(false), marginTop: 10 }} onClick={more}>Show more</button>}
      </div>

      {orders.length > 0 && (
        <div style={card}>
          <h3 style={h3}>Recent top-ups</h3>
          {orders.map((o) => (
            <div key={o.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0', borderTop: `1px solid ${ds.border}` }}>
              <span>{String(o.created_at).slice(0, 10)}</span><span>{naira(o.amount_kobo)}</span>
              <span style={{ color: o.status === 'paid' ? ds.teal : ds.gray }}>{o.status === 'paid' ? 'Paid' : o.status === 'pending' ? 'Not completed' : 'Failed'}</span>
            </div>
          ))}
        </div>
      )}
      </div>
      </div>
    </div>
  )
}
