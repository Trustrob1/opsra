/**
 * frontend/src/modules/invoices/StockPanel.jsx
 * STOCK-2 — on an issued invoice that holds stock: where it comes from, what is held / to deliver / delivered per line,
 * and (paid invoices, managers or the invoice's rep) a form to mark goods delivered, in full or in part.
 */
import { useState } from 'react'
import { Truck, Boxes } from 'lucide-react'
import { ds } from '../../utils/ds'
import { deliverInvoice, apiError } from '../../services/invoices.service'
import { lab, inp, btnP, btnG, disabled } from './invoiceUi'

const n = (v) => Number(v || 0)

export default function StockPanel({ doc, onChanged }) {
  const lines = (doc.items || []).filter((it) => it.product_id)
  const toDeliver = lines.filter((it) => n(it.stock_sold) > 0)
  const canDeliver = !!doc.can_deliver && doc.status === 'paid' && toDeliver.length > 0
  const [open, setOpen] = useState(false)
  const [qty, setQty] = useState({})
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  if (!lines.length) return null

  const start = () => {
    setQty(Object.fromEntries(toDeliver.map((it) => [it.id, String(n(it.stock_sold))])))
    setNote(''); setMsg(null); setOpen(true)
  }
  const save = async () => {
    const picked = toDeliver.map((it) => ({ item_id: it.id, quantity: parseInt(qty[it.id] || '0', 10) || 0 }))
      .filter((l) => l.quantity > 0)
    const over = toDeliver.find((it) => (parseInt(qty[it.id] || '0', 10) || 0) > n(it.stock_sold))
    if (over) { setMsg({ ok: false, text: `Only ${n(over.stock_sold)} of ${over.description} are left to deliver.` }); return }
    if (!picked.length) { setMsg({ ok: false, text: 'Enter how many were delivered.' }); return }
    setBusy(true); setMsg(null)
    try {
      await deliverInvoice(doc.id, picked, note.trim() || null)
      setOpen(false)
      setMsg({ ok: true, text: 'Marked delivered. Stock is updated.' })
      onChanged?.()
    } catch (e) { setMsg({ ok: false, text: apiError(e, 'Could not mark it delivered. Please try again.') }) } finally { setBusy(false) }
  }

  const cell = { padding: 6, textAlign: 'right' }
  return (
    <section style={{ border: `1px solid ${ds.border}`, borderRadius: 12, padding: 14, display: 'grid', gap: 10 }} aria-label="Stock">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Boxes size={18} color={ds.teal} />
        <b style={{ color: ds.dark, flex: 1 }}>Stock{doc.location_name ? ` · from ${doc.location_name}` : ''}</b>
        {canDeliver && !open && <button type="button" style={btnP} onClick={start}><Truck size={16} />Mark delivered</button>}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
        <thead><tr style={{ textAlign: 'left', ...lab }}>
          <th style={{ padding: 6 }}>Item</th><th style={cell}>Held</th><th style={cell}>To deliver</th><th style={cell}>Delivered</th>
        </tr></thead>
        <tbody>
          {lines.map((it) => (
            <tr key={it.id} style={{ borderTop: `1px solid ${ds.border}` }}>
              <td style={{ padding: 6 }}>{it.description}</td>
              <td style={cell}>{n(it.stock_held)}</td>
              <td style={cell}>{n(it.stock_sold)}</td>
              <td style={cell}>{n(it.stock_delivered)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <small style={{ color: ds.gray }}>
        {doc.status === 'paid'
          ? 'Paid goods stay set aside until they are marked delivered.'
          : doc.status === 'void'
            ? 'Held goods went back on sale when this was voided. Anything already delivered stays out; use Adjust in Inventory to take returns back.'
            : 'These goods are held for this customer until the invoice is paid or voided.'}
      </small>
      {open && (
        <div style={{ background: ds.light, borderRadius: 10, padding: 12, display: 'grid', gap: 10 }}>
          {toDeliver.map((it) => (
            <div key={it.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label htmlFor={`dl-${it.id}`} style={{ flex: 1, color: ds.dark }}>{it.description} <span style={{ color: ds.gray }}>({n(it.stock_sold)} to deliver)</span></label>
              <input id={`dl-${it.id}`} style={{ ...inp, width: 90, textAlign: 'right' }} inputMode="numeric"
                value={qty[it.id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [it.id]: e.target.value.replace(/[^0-9]/g, '') }))} />
            </div>
          ))}
          <div><label style={lab} htmlFor="dl-note">Note (optional)</label>
            <input id="dl-note" style={inp} maxLength={300} placeholder="e.g. Driver Musa, picked up at the store" value={note} onChange={(e) => setNote(e.target.value)} /></div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" style={btnG} onClick={() => { setOpen(false); setMsg(null) }}>Cancel</button>
            <button type="button" style={disabled(btnP, busy)} disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Mark delivered'}</button>
          </div>
        </div>
      )}
      {msg && <div role="status" style={{ color: msg.ok ? ds.tealDark : ds.red, fontSize: 13.5 }}>{msg.text}</div>}
    </section>
  )
}
