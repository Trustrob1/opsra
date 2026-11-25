/**
 * frontend/src/modules/invoices/PaymentsPanel.jsx
 * INV-4 — the payments on an issued invoice: every receipt (download, send, void), and a form to record a bank transfer,
 * cash, POS, USSD or other payment. Part payments are fine: the invoice shows "Part paid" until the balance is 0.
 * Payments made online with Paystack appear here by themselves.
 */
import { useState } from 'react'
import { Plus, Wallet } from 'lucide-react'
import { ds } from '../../utils/ds'
import { recordPayment, apiError } from '../../services/invoices.service'
import { naira, niceDate, todayYmd, METHOD_LABEL, lab, inp, btnP, btnG, disabled } from './invoiceUi'
import ReceiptActions from './ReceiptActions'
import { PendingPaymentRow } from './PendingPayments'   // SALE-1
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1


const MANUAL = ['bank_transfer', 'cash', 'pos', 'ussd', 'other']

export default function PaymentsPanel({ doc, isAdmin, onChanged }) {
  const receipts = doc.receipts || []
  const pending = doc.pending_payments || []   // SALE-1: waiting for an admin; they count against the balance
  const left = Math.max(0, Number(doc.balance_due || 0) - pending.reduce((s, p) => s + Number(p.amount || 0), 0))
  const open = ['issued', 'part_paid'].includes(doc.status)
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ amount: '', method: 'bank_transfer', paid_at: todayYmd(), reference: '', note: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const set = (patch) => setF((x) => ({ ...x, ...patch }))

  const startAdd = () => { setAdding(true); setMsg(null); set({ amount: String(left), paid_at: todayYmd() }) }
  const amount = parseFloat(String(f.amount).replace(/,/g, ''))
  const amountOk = Number.isFinite(amount) && amount > 0 && amount <= left && /^\d+(\.\d{1,2})?$/.test(String(f.amount).replace(/,/g, '').trim())
  const amountWhy = amountOk ? '' : !String(f.amount).trim() ? 'Enter the amount paid.'   // HINT-1
    : !/^\d+(\.\d{1,2})?$/.test(String(f.amount).replace(/,/g, '').trim()) || !(amount > 0) ? 'The amount must be a number above 0, like 50000 or 50000.50.'
    : `The amount can't be more than the balance due (${naira(left)}).`

  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await recordPayment(doc.id, {
        amount: String(amount), method: f.method, paid_at: f.paid_at || null,
        reference: f.reference.trim() || null, note: f.note.trim() || null,
      })
      setAdding(false); setF({ amount: '', method: 'bank_transfer', paid_at: todayYmd(), reference: '', note: '' })
      setMsg({ ok: true, text: r?.pending_payment ? 'Saved. It is waiting for an admin to confirm it. The receipt is made once they approve.'
        : r?.fully_paid ? `Receipt ${r.receipt?.number} made. The invoice is now fully paid.` : `Receipt ${r?.receipt?.number} made.` })
      onChanged?.()
    } catch (e) { setMsg({ ok: false, text: apiError(e, 'Could not record the payment. Please try again.') }) } finally { setBusy(false) }
  }

  if (!open && receipts.length === 0 && pending.length === 0) return null
  return (
    <section style={{ border: `1px solid ${ds.border}`, borderRadius: 12, padding: 14, display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Wallet size={16} color={ds.tealDark} />
        <b style={{ color: ds.dark, flex: 1 }}>Payments</b>
        {open && !adding && left > 0 && <button type="button" style={btnG} onClick={startAdd}><Plus size={16} />Record payment</button>}
      </div>

      {pending.map((p) => <PendingPaymentRow key={p.id} p={p} canConfirm={!!doc.can_confirm_payments} onChanged={onChanged} />)}

      {receipts.length === 0 && pending.length === 0 && !adding && <div style={{ color: ds.gray, fontSize: 13.5 }}>No payments yet. When the customer pays, record it here and a receipt is made for them.</div>}

      {receipts.map((r) => (
        <div key={r.id} style={{ borderTop: `1px solid ${ds.border}`, paddingTop: 10, display: 'grid', gap: 6, opacity: r.voided_at ? 0.7 : 1 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <b style={{ color: ds.dark }}>{r.number}</b>
            <span style={{ color: ds.gray, fontSize: 13.5 }}>{niceDate(r.paid_at)} · {METHOD_LABEL[r.method] || r.method}{r.reference ? ` · ${r.reference}` : ''}</span>
            <b style={{ marginLeft: 'auto', color: ds.dark, textDecoration: r.voided_at ? 'line-through' : 'none' }}>{naira(r.amount)}</b>
          </div>
          {r.voided_at && <small style={{ color: ds.red }}>Voided {niceDate(r.voided_at)}{r.void_reason ? `: ${r.void_reason}` : ''}</small>}
          <ReceiptActions receipt={r} isAdmin={isAdmin} onChanged={onChanged} />
        </div>
      ))}

      {adding && (
        <div style={{ borderTop: `1px solid ${ds.border}`, paddingTop: 12, display: 'grid', gap: 10 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
            <div><label style={lab} htmlFor="pay-amt">Amount (₦)</label>
              <input id="pay-amt" style={inp} inputMode="decimal" value={f.amount} onChange={(e) => set({ amount: e.target.value })} />
              <small style={{ color: amountOk || !f.amount ? ds.gray : ds.red }}>Balance due: {naira(left)}{pending.length ? ' (after payments waiting for an admin)' : ''}</small></div>
            <div><label style={lab} htmlFor="pay-method">How they paid</label>
              <select id="pay-method" style={inp} value={f.method} onChange={(e) => set({ method: e.target.value })}>
                {MANUAL.map((m) => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
              </select></div>
            <div><label style={lab} htmlFor="pay-date">Date paid</label>
              <input id="pay-date" type="date" style={inp} max={todayYmd()} value={f.paid_at} onChange={(e) => set({ paid_at: e.target.value })} /></div>
            <div><label style={lab} htmlFor="pay-ref">Reference (optional)</label>
              <input id="pay-ref" style={inp} maxLength={200} placeholder="e.g. transfer reference" value={f.reference} onChange={(e) => set({ reference: e.target.value })} /></div>
          </div>
          <div><label style={lab} htmlFor="pay-note">Note on the receipt (optional)</label>
            <input id="pay-note" style={inp} maxLength={500} placeholder={`Payment for invoice ${doc.number}`} value={f.note} onChange={(e) => set({ note: e.target.value })} /></div>
          <WhyDisabled reason={busy ? '' : amountWhy} style={{ textAlign: 'right' }} />
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <button type="button" style={btnG} onClick={() => setAdding(false)}>Cancel</button>
            <button type="button" style={disabled(btnP, !amountOk || busy)} disabled={!amountOk || busy} onClick={save}>{busy ? 'Saving…' : doc.payments_need_approval ? 'Send for confirmation' : 'Save and make receipt'}</button>
          </div>
        </div>
      )}
      {msg && <div role="status" style={{ color: msg.ok ? ds.green : ds.red, fontSize: 14 }}>{msg.text}</div>}
    </section>
  )
}
