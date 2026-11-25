/**
 * frontend/src/modules/inventory/StockApprovals.jsx
 * STOCK-2b — draft invoices whose rep asked to take stock from another location. Opening one lets an
 * owner / ops manager / admin approve (the invoice is issued) or reject it.
 */
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { ds } from '../../utils/ds'
import { getApprovals, stockError } from '../../services/inventory.service'
import InvoiceEditor from '../invoices/InvoiceEditor'
import { card, nairaShort, errBox, dateTime } from './stockUi'

export default function StockApprovals({ onChanged }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)
  const load = useCallback(() => getApprovals()
    .then((r) => { setRows(r?.items || []); setErr('') })
    .catch((e) => { setErr(stockError(e, 'Could not load the approvals. Please refresh.')); setRows([]) }), [])
  useEffect(() => { load() }, [load])

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <p style={{ margin: 0, color: ds.gray, fontSize: 14 }}>Reps asking to sell stock from a location other than their invoice's. The goods are already held for these customers.</p>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {rows === null ? <p style={{ color: ds.gray }}>Loading…</p>
        : rows.length === 0 ? (
          <div style={{ ...card, textAlign: 'center', color: ds.gray }}>
            <CheckCircle2 size={26} color={ds.teal} />
            <p style={{ margin: '8px 0 0' }}>Nothing waiting for approval.</p>
          </div>
        ) : rows.map((r) => (
          <button key={r.id} type="button" onClick={() => setOpen(r.id)}
            style={{ ...card, textAlign: 'left', cursor: 'pointer', fontFamily: ds.fontDm, display: 'grid', gap: 6, width: '100%' }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <b style={{ flex: 1, color: ds.dark }}>{r.customer_name || 'No name'}</b>
              <span style={{ color: ds.dark, fontWeight: 600 }}>{nairaShort(r.total)}</span>
            </div>
            <div style={{ color: ds.gray, fontSize: 13.5 }}>{[r.rep_name, `sells from ${r.location || '—'}`, dateTime(r.requested_at)].filter(Boolean).join(' · ')}</div>
            <div style={{ fontSize: 13.5, color: ds.dark }}>
              {r.lines.map((l, i) => (
                <span key={i}>{i > 0 ? ', ' : ''}{l.units} × {l.description}{l.elsewhere ? <b style={{ color: '#C05A00' }}> from {l.from}</b> : ''}</span>
              ))}
            </div>
            {r.note && <div style={{ fontSize: 13, color: ds.gray }}>“{r.note}”</div>}
          </button>
        ))}
      {open && <InvoiceEditor docId={open} onClose={() => setOpen(null)} onChanged={() => { load(); onChanged?.() }} />}
    </div>
  )
}
