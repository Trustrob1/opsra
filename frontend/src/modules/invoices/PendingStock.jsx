/**
 * frontend/src/modules/invoices/PendingStock.jsx
 * STOCK-2b — a draft invoice waiting for an admin to approve taking stock from another location.
 * Admins approve (the invoice is issued) or reject with a reason; the rep who asked can cancel.
 */
import { useState } from 'react'
import { Clock, CheckCircle2, XCircle } from 'lucide-react'
import { ds } from '../../utils/ds'
import { approveStock, rejectStock, cancelStockRequest, apiError } from '../../services/invoices.service'
import { naira, niceDate, lab, inp, btnP, btnG, btnDanger, disabled } from './invoiceUi'

export default function PendingStock({ doc, onChanged }) {
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const run = async (label, fn) => {
    setBusy(label); setErr('')
    try { onChanged(await fn()) } catch (e) { setErr(apiError(e)) } finally { setBusy('') }
  }
  const lines = (doc.items || []).filter((i) => i.product_id)

  return (
    <div style={{ display: 'grid', gap: 14, fontSize: 14 }}>
      <div style={{ background: '#FFF8EC', border: '1px solid #F5D9A8', borderRadius: 12, padding: 14, display: 'flex', gap: 10 }}>
        <Clock size={20} color="#C05A00" style={{ flexShrink: 0 }} />
        <div>
          <b style={{ color: ds.dark }}>Waiting for stock approval</b>
          <div style={{ color: ds.gray, marginTop: 2 }}>Asked {niceDate(doc.stock_requested_at)}. The goods are held for this customer until an admin decides. The invoice can't be changed meanwhile.</div>
          {doc.stock_request_note && <div style={{ marginTop: 6, color: ds.dark }}>Note: {doc.stock_request_note}</div>}
        </div>
      </div>
      <div>
        <div style={{ fontWeight: 700, color: ds.dark }}>{doc.customer_name}</div>
        <div style={{ color: ds.gray }}>Sold from {doc.location_name || '—'} · total {naira(doc.total)}</div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ textAlign: 'left', ...lab }}><th style={{ padding: 6 }}>Item</th><th style={{ padding: 6, textAlign: 'right' }}>Qty</th><th style={{ padding: 6 }}>Held at</th></tr></thead>
        <tbody>
          {lines.map((i) => (
            <tr key={i.id} style={{ borderTop: `1px solid ${ds.border}` }}>
              <td style={{ padding: 6 }}>{i.description}</td>
              <td style={{ padding: 6, textAlign: 'right' }}>{Number(i.quantity)}</td>
              <td style={{ padding: 6, fontWeight: i.stock_location_name ? 700 : 400, color: i.stock_location_name ? '#C05A00' : ds.dark }}>
                {i.stock_location_name || doc.location_name || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {err && <div role="alert" style={{ color: ds.red }}>{err}</div>}
      {rejecting ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <label style={lab} htmlFor="rej-note">Why not? (the rep sees this)</label>
          <input id="rej-note" style={inp} autoFocus maxLength={300} placeholder="e.g. Warehouse stock is promised to a dealer" value={note} onChange={(e) => setNote(e.target.value)} />
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" style={btnG} onClick={() => setRejecting(false)}>Back</button>
            <button type="button" style={disabled(btnDanger, !!busy)} disabled={!!busy} onClick={() => run('reject', () => rejectStock(doc.id, note.trim() || null))}>{busy === 'reject' ? 'Rejecting…' : 'Reject'}</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {doc.can_cancel_stock && !doc.can_approve_stock &&
            <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => run('cancel', () => cancelStockRequest(doc.id))}>{busy === 'cancel' ? 'Cancelling…' : 'Cancel request'}</button>}
          {doc.can_approve_stock && <>
            <button type="button" style={disabled(btnDanger, !!busy)} disabled={!!busy} onClick={() => setRejecting(true)}><XCircle size={16} />Reject</button>
            <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={() => run('approve', () => approveStock(doc.id))}><CheckCircle2 size={16} />{busy === 'approve' ? 'Approving…' : 'Approve and issue'}</button>
          </>}
        </div>
      )}
    </div>
  )
}
