/**
 * frontend/src/modules/inventory/InvoiceStockList.jsx
 * STOCK-2 — the Inventory page's "To deliver" (paid, goods still in the store) and "Held" (issued, not yet paid) lists.
 * Clicking an invoice opens it; paid ones can be marked delivered from there.
 */
import { useCallback, useEffect, useState } from 'react'
import { Truck, Clock } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getHeld, getToDeliver, stockError } from '../../services/inventory.service'
import InvoiceEditor from '../invoices/InvoiceEditor'
import { niceDate } from '../invoices/invoiceUi'
import { card, inp, units, nairaShort, errBox } from './stockUi'

export default function InvoiceStockList({ kind, locations, onChanged }) {
  const isMobile = useIsMobile()
  const [locationId, setLocationId] = useState('')
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)
  const toDeliver = kind === 'deliver'

  const load = useCallback(() => (toDeliver ? getToDeliver : getHeld)(locationId ? { location_id: locationId } : {})
    .then((r) => { setRows(r?.items || []); setErr('') })
    .catch((e) => { setErr(stockError(e, 'Could not load this list. Please refresh.')); setRows([]) }), [toDeliver, locationId])
  useEffect(() => { load() }, [load])

  const Icon = toDeliver ? Truck : Clock
  const linesText = (r) => (r.lines || []).map((l) => `${l.units} × ${l.description}`).join(', ')
  const th = { padding: '8px 10px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px' }
  const td = { padding: '10px', fontSize: 14, color: ds.dark, verticalAlign: 'top' }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <p style={{ margin: 0, color: ds.gray, fontSize: 14, flex: 1, minWidth: 220 }}>
          {toDeliver ? 'Paid invoices whose goods are still in the store. They can\'t be sold to anyone else.'
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
      {rows === null ? <p style={{ color: ds.gray }}>Loading…</p>
        : rows.length === 0 ? (
          <div style={{ ...card, textAlign: 'center', color: ds.gray }}>
            <Icon size={26} color={ds.teal} />
            <p style={{ margin: '8px 0 0' }}>{toDeliver ? 'Nothing waiting to be delivered.' : 'No invoices are holding stock.'}</p>
          </div>
        ) : isMobile ? (
          <div style={{ display: 'grid', gap: 10 }}>
            {rows.map((r) => (
              <button key={r.id} type="button" onClick={() => setOpen(r.id)}
                style={{ ...card, textAlign: 'left', cursor: 'pointer', fontFamily: ds.fontDm, display: 'grid', gap: 4 }}>
                <div style={{ display: 'flex', gap: 8 }}><b style={{ flex: 1, color: ds.dark }}>{r.number} · {r.customer_name}</b><span>{units(r.units)} units</span></div>
                <div style={{ color: ds.gray, fontSize: 13.5 }}>{linesText(r)}</div>
                <div style={{ color: ds.gray, fontSize: 13 }}>{[r.location, r.rep_name, niceDate(r.issue_date)].filter(Boolean).join(' · ')}</div>
                {!toDeliver && Number(r.balance) > 0 && <div style={{ fontSize: 13, color: '#C05A00' }}>{nairaShort(r.balance)} still to pay</div>}
              </button>
            ))}
          </div>
        ) : (
          <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: `1px solid ${ds.border}` }}>
                <th style={th}>Invoice</th><th style={th}>Customer</th><th style={th}>Goods</th><th style={th}>Location</th><th style={th}>Rep</th>
                <th style={th}>Date</th>{!toDeliver && <th style={{ ...th, textAlign: 'right' }}>To pay</th>}
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} onClick={() => setOpen(r.id)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setOpen(r.id) }}
                    style={{ borderTop: `1px solid ${ds.border}`, cursor: 'pointer' }}>
                    <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>{r.number}</td>
                    <td style={td}>{r.customer_name}</td>
                    <td style={td}>{linesText(r)}</td>
                    <td style={td}>{r.location || '—'}</td>
                    <td style={td}>{r.rep_name || '—'}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>{niceDate(r.issue_date)}</td>
                    {!toDeliver && <td style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>{nairaShort(r.balance)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {open && <InvoiceEditor docId={open} onClose={() => setOpen(null)} onChanged={() => { load(); onChanged?.() }} />}
    </div>
  )
}
