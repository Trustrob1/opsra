/**
 * WebchatOrderBar.jsx
 * ORDER-PAID-1: shown above the reply box of a web chat that has an order waiting. The team sees the order and its state
 * (stock to confirm / receipt uploaded / paid) and can mark it as paid, with one clear confirmation step.
 */
import { useEffect, useState } from 'react'
import { getWebchatOrder, markWebchatOrderPaid } from '../../services/conversations.service'
import { ds } from '../../utils/ds'

const naira = (v) => `₦${Number(v || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`

const orderLine = (o) => {
  if (!o) return ''
  if (o.status === 'paid') return `Paid ${naira(o.total)}${o.paid_by_name ? `, confirmed by ${o.paid_by_name}` : ''}`
  if (o.status === 'receipt_uploaded') return `Receipt uploaded for ${naira(o.total)}. Check it, then mark as paid.`
  return `Order waiting ${naira(o.total)}. Confirm stock, then send the payment link or bank details.`
}

export default function WebchatOrderBar({ leadId, refreshKey, onChanged }) {
  const [order, setOrder] = useState(null)
  const [ask, setAsk] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    let dead = false
    getWebchatOrder(leadId).then((o) => { if (!dead) setOrder(o) })
    return () => { dead = true }
  }, [leadId, refreshKey])

  if (!order) return null
  const paid = order.status === 'paid'

  const confirm = async () => {
    setBusy(true); setErr('')
    try {
      const o = await markWebchatOrderPaid(leadId)
      setOrder(o || { ...order, status: 'paid' }); setAsk(false); onChanged?.()
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Could not mark this order as paid. Try again.')
    } finally { setBusy(false) }
  }

  return (
    <div role="status" style={{ flexShrink: 0, padding: '10px 16px', borderTop: `1px solid ${ds.border}`, background: paid ? '#EAF6EE' : '#EEF4FF', fontSize: 13 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ flex: 1, minWidth: 200, color: ds.dark, fontWeight: 600 }}>{orderLine(order)}</span>
        {!paid && !ask && (
          <button type="button" onClick={() => setAsk(true)} style={{ border: 0, borderRadius: 8, padding: '8px 14px', background: ds.teal || '#0E7C66', color: '#fff', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>Mark as paid</button>
        )}
        {!paid && ask && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>Payment received?</span>
            <button type="button" disabled={busy} onClick={confirm} style={{ border: 0, borderRadius: 8, padding: '8px 14px', background: ds.teal || '#0E7C66', color: '#fff', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>Yes, mark as paid</button>
            <button type="button" disabled={busy} onClick={() => setAsk(false)} style={{ border: `1px solid ${ds.border}`, borderRadius: 8, padding: '8px 14px', background: '#fff', cursor: 'pointer', fontFamily: 'inherit' }}>Cancel</button>
          </span>
        )}
      </div>
      {order.summary && !paid && <div style={{ marginTop: 6, color: ds.gray, whiteSpace: 'pre-line' }}>{order.summary}</div>}
      {err && <div role="alert" style={{ marginTop: 6, color: '#B3261E' }}>{err}</div>}
    </div>
  )
}
