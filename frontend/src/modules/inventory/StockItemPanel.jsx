/**
 * frontend/src/modules/inventory/StockItemPanel.jsx
 * STOCK-1 — one product + size: numbers per location, its recent history, and (managers) cost price, reorder level
 * and SKU, plus shortcuts to Receive and Adjust for it.
 */
import { useEffect, useState } from 'react'
import { Package } from 'lucide-react'
import { ds } from '../../utils/ds'
import { getStockHistory, updateStockItem, stockError } from '../../services/inventory.service'
import StockModal from './StockModal'
import { lab, inp, btnP, btnG, disabled, errBox, units, signed, dateTime, naira, th, td } from './stockUi'

export default function StockItemPanel({ row, locations, canManage, onClose, onChanged, onReceive, onAdjust }) {
  const [moves, setMoves] = useState(null)
  const [cost, setCost] = useState(row.cost_price != null ? String(row.cost_price) : '')
  const [reorder, setReorder] = useState(String(row.reorder_level ?? ''))
  const [sku, setSku] = useState(row.sku || '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    let live = true
    getStockHistory({ product_id: row.product_id, variant: row.variant, limit: 10 })
      .then((r) => { if (live) setMoves(r?.items || []) }).catch(() => { if (live) setMoves([]) })
    return () => { live = false }
  }, [row.product_id, row.variant])

  const names = Object.fromEntries((locations || []).map((l) => [l.id, l.name]))
  const costOk = cost === '' || /^\d+(\.\d{1,2})?$/.test(cost)
  const reorderOk = reorder === '' || /^\d+$/.test(reorder)
  const save = async () => {
    if (!costOk || !reorderOk || busy) return
    setBusy(true); setErr(''); setMsg('')
    try {
      await updateStockItem({ product_id: row.product_id, variant: row.variant || null, cost_price: cost === '' ? null : cost,
        reorder_level: reorder === '' ? null : Number(reorder), sku: sku.trim() || null })
      setMsg('Saved.')
      onChanged?.()
    } catch (e) {
      setErr(stockError(e, 'Could not save. Please try again.'))
    } finally { setBusy(false) }
  }

  const preset = { product_id: row.product_id, title: row.title, variant: row.variant, sizes: row.variant ? [row.variant] : [] }
  return (
    <StockModal title={`${row.title}${row.variant ? ` · ${row.variant}` : ''}`} icon={Package} onClose={onClose} busy={busy} width={760}
      footer={canManage ? <>
        <button type="button" style={btnG} onClick={() => onAdjust(preset)}>Adjust</button>
        <button type="button" style={btnP} onClick={() => onReceive(preset)}>Receive stock</button>
      </> : null}>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {!row.product_active && <p style={{ color: ds.gray, marginTop: 0 }}>This product is archived in your catalogue but still has stock.</p>}
      {row.old_size && <p style={{ color: ds.gray, marginTop: 0 }}>This size is no longer on the product but still has stock.</p>}

      <div style={{ border: `1px solid ${ds.border}`, borderRadius: 12, overflowX: 'auto', marginBottom: 18 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr style={{ background: ds.light, color: ds.gray, textAlign: 'right' }}>
            <th style={{ ...th, textAlign: 'left' }}>Location</th><th style={th}>On hand</th><th style={th}>Held</th>
            <th style={th}>To deliver</th><th style={th}>Coming in</th><th style={th}>Available</th>
          </tr></thead>
          <tbody>
            {row.locations.length === 0 && <tr><td colSpan={6} style={{ ...td, color: ds.gray }}>No stock recorded yet.</td></tr>}
            {row.locations.map((l) => (
              <tr key={l.location_id} style={{ borderTop: `1px solid ${ds.border}`, textAlign: 'right' }}>
                <td style={{ ...td, textAlign: 'left' }}>{names[l.location_id] || 'Location'}</td>
                <td style={td}>{units(l.on_hand)}</td><td style={td}>{units(l.held)}</td><td style={td}>{units(l.sold_pending)}</td>
                <td style={td}>{units(l.in_transit_in)}</td><td style={{ ...td, fontWeight: 700 }}>{units(l.available)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canManage && (
        <div style={{ border: `1px solid ${ds.border}`, borderRadius: 12, padding: 14, marginBottom: 18 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
            <div><label style={lab} htmlFor="it-cost">Cost price per unit ₦</label>
              <input id="it-cost" style={{ ...inp, borderColor: costOk ? ds.border : ds.red }} inputMode="decimal" maxLength={14} value={cost} onChange={(e) => setCost(e.target.value.replace(/[^\d.]/g, ''))} /></div>
            <div><label style={lab} htmlFor="it-reorder">Low stock at</label>
              <input id="it-reorder" style={inp} inputMode="numeric" maxLength={7} value={reorder} onChange={(e) => setReorder(e.target.value.replace(/\D/g, ''))} /></div>
            <div><label style={lab} htmlFor="it-sku">SKU</label>
              <input id="it-sku" style={inp} maxLength={100} value={sku} onChange={(e) => setSku(e.target.value)} /></div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
            <button type="button" style={disabled(btnG, busy || !costOk || !reorderOk)} disabled={busy || !costOk || !reorderOk} onClick={save}>{busy ? 'Saving…' : 'Save details'}</button>
            {msg && <span role="status" style={{ color: ds.green, fontSize: 13.5 }}>{msg}</span>}
            {row.cost_price != null && <span style={{ color: ds.gray, fontSize: 13.5, marginLeft: 'auto' }}>Value on hand {naira(row.cost_price * row.on_hand)}</span>}
          </div>
          <p style={{ color: ds.gray, fontSize: 12.5, margin: '8px 0 0' }}>Leave "Low stock at" empty to use the business default. Only managers see cost prices.</p>
        </div>
      )}

      <div style={{ fontWeight: 700, color: ds.dark, marginBottom: 8 }}>Recent changes</div>
      {moves === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {moves && moves.length === 0 && <p style={{ color: ds.gray }}>No changes yet.</p>}
      {moves && moves.length > 0 && (
        <div style={{ display: 'grid', gap: 8 }}>
          {moves.map((m) => (
            <div key={m.id} style={{ display: 'flex', gap: 12, alignItems: 'baseline', borderBottom: `1px solid ${ds.border}`, paddingBottom: 8, fontSize: 13.5 }}>
              <span style={{ color: ds.gray, whiteSpace: 'nowrap', minWidth: 130 }}>{dateTime(m.created_at)}</span>
              <span style={{ flex: 1, color: ds.dark }}>{m.kind_label} · {m.location}{m.reason ? ` · ${m.reason}` : ''}{m.by ? ` · ${m.by}` : ''}</span>
              <b style={{ color: m.change < 0 ? ds.red : m.change > 0 ? ds.green : ds.gray, whiteSpace: 'nowrap' }}>{m.change ? signed(m.change) : '—'}</b>
            </div>
          ))}
        </div>
      )}
    </StockModal>
  )
}
