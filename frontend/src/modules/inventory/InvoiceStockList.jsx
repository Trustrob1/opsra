/**
 * frontend/src/modules/inventory/InvoiceStockList.jsx
 * STOCK-2 — the Inventory page's "To deliver" (paid, goods still in the store) and "Held" (issued, not yet paid) lists.
 * Clicking an invoice opens it; paid ones can be marked delivered from there.
 * STOCK-4 — goods in a warehouse need the owner's approval before delivery: "Ask to deliver" sends the request,
 * "Deliver" marks goods delivered (approved, showroom or the owner's own). The Inventory Manager can't open invoices,
 * so for that role every row opens the delivery panel instead.
 */
import { useCallback, useEffect, useState } from 'react'
import { Truck, Clock } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getHeld, getToDeliver, askToDeliver, deliverFromStock, stockError } from '../../services/inventory.service'
import useAuthStore from '../../store/authStore'
import StockModal from './StockModal'
import InvoiceEditor from '../invoices/InvoiceEditor'
import { niceDate } from '../invoices/invoiceUi'
import { card, inp, lab, btnP, btnG, disabled, units, nairaShort, errBox } from './stockUi'
import { deliverState } from './moveRequestUi'

function DeliverPanel({ row, isOwner, onClose, onDone }) {
  const st = deliverState(row, isOwner)
  const [qty, setQty] = useState(() => Object.fromEntries((row.lines || []).map((l) => [l.item_id, String(l.units)])))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const lines = (row.lines || []).map((l) => ({ item_id: l.item_id, quantity: Number(qty[l.item_id] || 0) })).filter((l) => l.quantity > 0)
  const valid = (row.lines || []).every((l) => /^\d*$/.test(qty[l.item_id] ?? '') && Number(qty[l.item_id] || 0) <= l.units)
  const wareLines = lines.filter((x) => (row.lines || []).find((l) => l.item_id === x.item_id)?.warehouse)
  const run = async (kind) => {
    setBusy(kind); setErr('')
    try {
      if (kind === 'ask') {
        await askToDeliver(row.id, { lines: wareLines, note: note.trim() || null })
        onDone('Sent to the owner for approval. You\'ll be notified when it\'s approved.')
      } else {
        await deliverFromStock(row.id, { lines, note: note.trim() || null })
        onDone('Marked delivered. The goods are off the count.')
      }
    } catch (e) { setErr(stockError(e, 'Could not save. Please try again.')); setBusy('') }
  }
  return (
    <StockModal title={`Deliver ${row.number || ''} · ${row.customer_name || ''}`} icon={Truck} onClose={onClose} busy={!!busy} width={620}
      footer={<>
        <button type="button" style={btnG} onClick={onClose} disabled={!!busy}>Close</button>
        {st.action === 'ask' && <button type="button" style={disabled(btnP, !!busy || !valid || !wareLines.length)} disabled={!!busy || !valid || !wareLines.length} onClick={() => run('ask')}>{busy === 'ask' ? 'Sending…' : 'Ask the owner to approve'}</button>}
        {st.action === 'deliver' && <button type="button" style={disabled(btnP, !!busy || !valid || !lines.length)} disabled={!!busy || !valid || !lines.length} onClick={() => run('deliver')}>{busy === 'deliver' ? 'Saving…' : 'Mark delivered'}</button>}
      </>}>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {st.text && <p style={{ margin: '0 0 12px', color: st.action === 'deliver' ? '#1A7A40' : '#C05A00', fontWeight: 600, fontSize: 14 }}>{st.text}</p>}
      {st.action === 'wait' && <p style={{ margin: '0 0 12px', color: ds.gray, fontSize: 13.5 }}>The goods stay held for this customer. You can deliver them as soon as the owner approves.</p>}
      <div style={{ display: 'grid', gap: 10 }}>
        {(row.lines || []).map((l) => (
          <div key={l.item_id} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ flex: '1 1 220px', color: ds.dark, fontSize: 14 }}>{l.description}{l.warehouse ? <span style={{ color: ds.gray }}> · warehouse</span> : null}</span>
            <span style={{ color: ds.gray, fontSize: 13 }}>{units(l.units)} to deliver</span>
            {st.action !== 'wait' && <input aria-label={`Units of ${l.description}`} style={{ ...inp, width: 90 }} inputMode="numeric" maxLength={7}
              value={qty[l.item_id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.item_id]: e.target.value.replace(/\D/g, '') }))} />}
          </div>
        ))}
      </div>
      {!valid && <p role="alert" style={{ color: ds.red, fontSize: 13 }}>A number is more than what's left to deliver.</p>}
      {st.action !== 'wait' && <div style={{ marginTop: 14 }}><label style={lab} htmlFor="dl-note">Note (optional)</label>
        <input id="dl-note" style={inp} maxLength={300} placeholder="e.g. driver's name" value={note} onChange={(e) => setNote(e.target.value)} /></div>}
    </StockModal>
  )
}

export default function InvoiceStockList({ kind, locations, onChanged }) {
  const isMobile = useIsMobile()
  const [locationId, setLocationId] = useState('')
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)
  const [panel, setPanel] = useState(null)       // STOCK-4: a row in the delivery panel
  const [flags, setFlags] = useState({ can: false, owner: false })
  const [done, setDone] = useState('')
  const toDeliver = kind === 'deliver'
  const invManager = useAuthStore((st) => st.user?.roles?.template) === 'inventory_manager'

  const load = useCallback(() => (toDeliver ? getToDeliver : getHeld)(locationId ? { location_id: locationId } : {})
    .then((r) => { setRows(r?.items || []); setFlags({ can: !!r?.can_deliver, owner: !!r?.is_owner }); setErr('') })
    .catch((e) => { setErr(stockError(e, 'Could not load this list. Please refresh.')); setRows([]) }), [toDeliver, locationId])
  useEffect(() => { load() }, [load])

  const Icon = toDeliver ? Truck : Clock
  const openRow = (r) => (invManager ? (toDeliver ? setPanel(r) : null) : setOpen(r.id))
  const action = (r) => {
    if (!toDeliver) return null
    const st = deliverState(r, flags.owner)
    const label = st.action === 'ask' ? 'Ask to deliver' : st.action === 'wait' ? 'Waiting for approval' : 'Deliver'
    return (
      <div style={{ display: 'grid', gap: 4, justifyItems: 'start' }} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
        {(flags.can || st.action !== 'deliver') && (
          <button type="button" style={{ ...(st.action === 'deliver' ? btnP : btnG), minHeight: 34, padding: '0 12px', fontSize: 13 }} onClick={() => setPanel(r)}>{label}</button>
        )}
        {st.text && st.action !== 'wait' && <span style={{ fontSize: 12, color: st.action === 'deliver' ? '#1A7A40' : '#C05A00' }}>{st.text}</span>}
      </div>
    )
  }
  const linesText = (r) => (r.lines || []).map((l) => `${l.units} × ${l.description}`).join(', ')
  const th = { padding: '8px 10px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px' }
  const td = { padding: '10px', fontSize: 14, color: ds.dark, verticalAlign: 'top' }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <p style={{ margin: 0, color: ds.gray, fontSize: 14, flex: 1, minWidth: 220 }}>
          {toDeliver ? 'Paid invoices whose goods are still in stock. They stay on the count, held for the customer, until delivered. Goods in a warehouse need the owner\'s approval before they go.'
            : 'Issued invoices not yet paid. Their goods are held until they are paid or voided.'}
        </p>
        {locations.length > 1 && (
          <select style={{ ...inp, width: 'auto', minWidth: 180 }} aria-label="Location" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            <option value="">All locations</option>
            {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        )}
      </div>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {done && <div role="status" style={{ ...errBox, background: '#EEF9F1', borderColor: '#BFE5CB', color: '#1A7A40' }}>{done}</div>}
      {rows === null ? <p style={{ color: ds.gray }}>Loading…</p>
        : rows.length === 0 ? (
          <div style={{ ...card, textAlign: 'center', color: ds.gray }}>
            <Icon size={26} color={ds.teal} />
            <p style={{ margin: '8px 0 0' }}>{toDeliver ? 'Nothing waiting to be delivered.' : 'No invoices are holding stock.'}</p>
          </div>
        ) : isMobile ? (
          <div style={{ display: 'grid', gap: 10 }}>
            {rows.map((r) => (
              <div key={r.id} role="button" tabIndex={0} onClick={() => openRow(r)} onKeyDown={(e) => { if (e.key === 'Enter') openRow(r) }}
                style={{ ...card, textAlign: 'left', cursor: 'pointer', fontFamily: ds.fontDm, display: 'grid', gap: 4 }}>
                <div style={{ display: 'flex', gap: 8 }}><b style={{ flex: 1, color: ds.dark }}>{r.number} · {r.customer_name}</b><span>{units(r.units)} units</span></div>
                <div style={{ color: ds.gray, fontSize: 13.5 }}>{linesText(r)}</div>
                <div style={{ color: ds.gray, fontSize: 13 }}>{[r.location, r.rep_name, niceDate(r.issue_date)].filter(Boolean).join(' · ')}</div>
                {!toDeliver && Number(r.balance) > 0 && <div style={{ fontSize: 13, color: '#C05A00' }}>{nairaShort(r.balance)} still to pay</div>}
                {action(r)}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: `1px solid ${ds.border}` }}>
                <th style={th}>Invoice</th><th style={th}>Customer</th><th style={th}>Goods</th><th style={th}>Location</th><th style={th}>Rep</th>
                <th style={th}>Date</th>{!toDeliver && <th style={{ ...th, textAlign: 'right' }}>To pay</th>}{toDeliver && <th style={th}>Delivery</th>}
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} onClick={() => openRow(r)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') openRow(r) }}
                    style={{ borderTop: `1px solid ${ds.border}`, cursor: 'pointer' }}>
                    <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>{r.number}</td>
                    <td style={td}>{r.customer_name}</td>
                    <td style={td}>{linesText(r)}</td>
                    <td style={td}>{r.location || '—'}</td>
                    <td style={td}>{r.rep_name || '—'}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>{niceDate(r.issue_date)}</td>
                    {!toDeliver && <td style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>{nairaShort(r.balance)}</td>}
                    {toDeliver && <td style={td}>{action(r)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {panel && <DeliverPanel row={panel} isOwner={flags.owner} onClose={() => setPanel(null)}
        onDone={(text) => { setPanel(null); setDone(text); load(); onChanged?.() }} />}
      {open && <InvoiceEditor docId={open} onClose={() => setOpen(null)} onChanged={() => { load(); onChanged?.() }} />}
    </div>
  )
}
