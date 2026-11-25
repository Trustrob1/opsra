/**
 * frontend/src/modules/invoices/PendingPayments.jsx
 * SALE-1 — payments a rep recorded that wait for an owner, operations manager or admin to confirm them (turned on in
 * Invoices > Settings > Payments). Admins approve (the receipt is made then) or reject with a reason; the rep who
 * recorded one can take it back while it waits. Used on the invoice and in Sales > Payments to confirm.
 */
import { useState } from 'react'
import { Check, Clock, X } from 'lucide-react'
import { ds } from '../../utils/ds'
import { approvePayment, rejectPayment, cancelPayment, apiError } from '../../services/invoices.service'
import useAuthStore from '../../store/authStore'
import { naira, niceDate, METHOD_LABEL, inp, btnP, btnG, btnDanger, disabled } from './invoiceUi'
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1

export function PendingPaymentRow({ p, canConfirm, showInvoice = false, onChanged }) {
  const me = useAuthStore((s) => s.user?.id)
  const [busy, setBusy] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  const run = (label, fn) => async () => {
    setBusy(label); setErr('')
    try { await fn(); onChanged?.() } catch (e) { setErr(apiError(e)) } finally { setBusy('') }
  }
  const mine = p.requested_by === me
  return (
    <div style={{ borderTop: `1px solid ${ds.border}`, paddingTop: 10, display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <Clock size={15} color="#C05A00" style={{ alignSelf: 'center' }} />
        <b style={{ color: ds.dark }}>{showInvoice ? (p.invoice_number ? `Invoice ${p.invoice_number}` : 'Receipt, no invoice') : 'Waiting for an admin'}</b>
        <span style={{ color: ds.gray, fontSize: 13.5 }}>
          {[showInvoice && p.customer_name, niceDate(p.paid_at || p.requested_at), METHOD_LABEL[p.method] || p.method, p.reference,
            p.requested_by_name && `recorded by ${p.requested_by_name}`].filter(Boolean).join(' · ')}
        </span>
        <b style={{ marginLeft: 'auto', color: ds.dark }}>{naira(p.amount)}</b>
      </div>
      {p.description && <small style={{ color: ds.gray }}>{p.description}</small>}
      {p.deliver && <small style={{ color: ds.gray }}>The customer took the goods: they are marked delivered when this is approved.</small>}
      {p.status === 'pending' && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {canConfirm && !rejecting && <>
            <button type="button" style={disabled(btnDanger, !!busy)} disabled={!!busy} onClick={() => setRejecting(true)}><X size={16} />Reject</button>
            <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={run('approve', () => approvePayment(p.id))}>
              <Check size={16} />{busy === 'approve' ? 'Approving…' : 'Approve and make receipt'}</button>
          </>}
          {!canConfirm && mine && (
            <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={run('cancel', () => cancelPayment(p.id))}>
              {busy === 'cancel' ? 'Taking back…' : 'Take it back'}</button>
          )}
        </div>
      )}
      {rejecting && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input style={{ ...inp, flex: '1 1 220px' }} maxLength={500} autoFocus aria-label="Why is it rejected?"
            placeholder="Why? e.g. No transfer in the bank account" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button type="button" style={btnG} disabled={!!busy} onClick={() => { setRejecting(false); setReason('') }}>Cancel</button>
          <button type="button" style={disabled(btnDanger, !!busy || reason.trim().length < 3)} disabled={!!busy || reason.trim().length < 3}
            onClick={run('reject', () => rejectPayment(p.id, reason.trim()))}>{busy === 'reject' ? 'Rejecting…' : 'Reject payment'}</button>
          <WhyDisabled reason={!busy && reason.trim().length < 3 ? 'Write the reason (at least 3 letters).' : ''} style={{ flexBasis: '100%', margin: 0 }} />
        </div>
      )}
      {p.status === 'rejected' && <small style={{ color: ds.red }}>Rejected{p.decided_by_name ? ` by ${p.decided_by_name}` : ''}: {p.decision_note}</small>}
      {err && <div role="alert" style={{ color: ds.red, fontSize: 14 }}>{err}</div>}
    </div>
  )
}
