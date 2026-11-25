/**
 * frontend/src/modules/inventory/InventoryModule.jsx
 * STOCK-1 — the Inventory page: stock per product + size (all locations or one), low-stock filter, Receive stock and
 * Adjust (managers), each product's panel, the full history, and (managers) the settings and locations.
 * Shown to every product mode, like Invoices.
 */
import { useCallback, useEffect, useState } from 'react'
import { Boxes, PackagePlus, Search, SlidersHorizontal } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getStock, stockError, isPlanBlocked } from '../../services/inventory.service'
import { card, inp, btnP, btnG, units, nairaShort, sizeText, th, td } from './stockUi'
import { ReceiveStock, AdjustStock } from './StockForms'
import StockItemPanel from './StockItemPanel'
import StockHistory from './StockHistory'
import InventorySettings from './InventorySettings'

export default function InventoryModule() {
  const isMobile = useIsMobile()
  const [tab, setTab] = useState('stock')
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [locationId, setLocationId] = useState('')
  const [low, setLow] = useState(false)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [blocked, setBlocked] = useState(false)
  const [panel, setPanel] = useState(null)        // a row
  const [form, setForm] = useState(null)          // { kind: 'receive' | 'adjust', preset }
  const [note, setNote] = useState('')

  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t) }, [q])
  const load = useCallback(() => getStock({ ...(dq ? { q: dq } : {}), ...(locationId ? { location_id: locationId } : {}), ...(low ? { low: true } : {}) })
    .then((r) => { setData(r); setErr('') })
    .catch((e) => {
      if (isPlanBlocked(e)) setBlocked(true)
      setErr(stockError(e, 'Could not load your stock. Please refresh.'))
      setData((d) => d || { items: [], locations: [], settings: {}, summary: {} })
    }), [dq, locationId, low])
  useEffect(() => { load() }, [load])

  if (blocked) {
    return (
      <div style={{ padding: isMobile ? 16 : 28 }}>
        <div style={{ ...card, maxWidth: 560 }}>
          <h2 style={{ margin: '0 0 8px', fontSize: 19, color: ds.dark }}>Inventory</h2>
          <p style={{ color: ds.gray, margin: 0 }}>{err}</p>
        </div>
      </div>
    )
  }

  const canManage = !!data?.can_manage
  const enabled = !!data?.settings?.enabled
  const locations = data?.locations || []
  const s = data?.summary || {}
  const chip = (active, text, onClick) => (
    <button key={text} type="button" onClick={onClick} aria-pressed={active}
      style={{ padding: '0 14px', minHeight: 36, borderRadius: 999, border: `1.5px solid ${active ? ds.teal : ds.border}`, background: active ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13.5, cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: ds.fontDm }}>{text}</button>
  )
  const tile = (label, value, sub, tone) => (
    <div style={{ ...card, padding: '14px 16px', flex: '1 1 160px' }}>
      <div style={{ fontSize: 12.5, color: ds.gray, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone || ds.dark, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12.5, color: ds.gray, marginTop: 2 }}>{sub}</div>}
    </div>
  )
  const lowBadge = <span style={{ marginLeft: 8, padding: '2px 8px', borderRadius: 999, background: '#FFF3E0', color: '#C05A00', fontSize: 12, fontWeight: 700 }}>Low</span>
  const done = (text) => { setForm(null); setPanel(null); setNote(text); load() }
  const filtered = !!(dq || locationId || low)

  return (
    <div style={{ padding: isMobile ? 16 : 28, fontFamily: ds.fontDm }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 22, color: ds.dark, flex: 1 }}>Inventory</h1>
        {canManage && enabled && <>
          <button type="button" style={btnG} onClick={() => setForm({ kind: 'adjust' })}><SlidersHorizontal size={16} />Adjust</button>
          <button type="button" style={btnP} onClick={() => setForm({ kind: 'receive' })}><PackagePlus size={16} />Receive stock</button>
        </>}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {chip(tab === 'stock', 'Stock', () => setTab('stock'))}
        {enabled && chip(tab === 'history', 'History', () => setTab('history'))}
        {canManage && chip(tab === 'settings', 'Settings', () => setTab('settings'))}
      </div>
      {note && <div role="status" style={{ background: '#EEF9F1', border: '1px solid #BFE5CB', color: '#1A7A40', borderRadius: 10, padding: '10px 14px', marginBottom: 14, fontSize: 14, display: 'flex', gap: 10 }}>
        <span style={{ flex: 1 }}>{note}</span><button type="button" onClick={() => setNote('')} style={{ border: 'none', background: 'none', color: '#1A7A40', cursor: 'pointer', fontWeight: 600 }}>Close</button></div>}

      {tab === 'settings' && canManage ? <InventorySettings onChanged={load} />
        : tab === 'history' && enabled ? <StockHistory locations={locations} />
        : data && !enabled ? (
          <div style={{ ...card, maxWidth: 620 }}>
            <Boxes size={30} color={ds.teal} />
            <h2 style={{ margin: '10px 0 6px', fontSize: 18, color: ds.dark }}>Keep your stock in Opsra</h2>
            <p style={{ color: ds.gray, margin: '0 0 14px' }}>Track stock per store or warehouse, receive deliveries, record damage and stock counts, and see what is running low.
              {canManage ? ' Turn it on in Settings; today\'s numbers are copied in for you.' : ' Ask your business owner or operations manager to turn it on.'}</p>
            {canManage && <button type="button" style={btnP} onClick={() => setTab('settings')}>Set up stock</button>}
          </div>
        ) : (
        <>
          {data && (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
              {tile('Available to sell', units(s.units_available), `${units(s.units_on_hand)} on hand`)}
              {tile('Low stock', units(s.low), `product size${s.low === 1 ? '' : 's'} at or below the level`, s.low ? '#C05A00' : undefined)}
              {canManage && s.stock_value !== undefined && tile('Stock value', nairaShort(s.stock_value), s.missing_cost ? `${units(s.missing_cost)} without a cost price` : 'at cost price')}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ position: 'relative', flex: '1 1 240px' }}>
              <Search size={16} color={ds.gray} style={{ position: 'absolute', left: 12, top: 13 }} />
              <input style={{ ...inp, paddingLeft: 34 }} placeholder="Search product, size or SKU" aria-label="Search product, size or SKU" value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} />
            </div>
            <select aria-label="Location" style={{ ...inp, width: 'auto', minWidth: 180 }} value={locationId} onChange={(e) => setLocationId(e.target.value)}>
              <option value="">All locations</option>
              {locations.map((l) => <option key={l.id} value={l.id}>{l.name}{l.is_active ? '' : ' (off)'}</option>)}
            </select>
            {chip(low, 'Low stock only', () => setLow((v) => !v))}
          </div>

          {err && <p role="alert" style={{ color: ds.red }}>{err}</p>}
          {!data && <p style={{ color: ds.gray }}>Loading…</p>}
          {data && data.items.length === 0 && !err && (
            <div style={{ ...card, textAlign: 'center', padding: 36 }}>
              <Boxes size={30} color={ds.teal} />
              <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>{filtered ? 'Nothing matches these filters' : 'No products yet'}</p>
              <p style={{ color: ds.gray, margin: 0 }}>{filtered ? 'Try another filter or clear the search.' : 'Add products to your catalogue first, then receive stock for them.'}</p>
            </div>
          )}
          {data && data.items.length > 0 && (isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {data.items.map((r) => (
                <button key={`${r.product_id}|${r.variant}`} type="button" onClick={() => setPanel(r)}
                  style={{ ...card, padding: 14, textAlign: 'left', cursor: 'pointer', display: 'grid', gap: 6, fontFamily: ds.fontDm }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <b style={{ color: ds.dark }}>{r.title}</b>
                    <span style={{ whiteSpace: 'nowrap' }}><b style={{ color: ds.dark }}>{units(r.available)}</b>{r.low && lowBadge}</span>
                  </div>
                  <div style={{ color: ds.gray, fontSize: 13.5 }}>{sizeText(r.variant)} · {units(r.on_hand)} on hand{r.held ? ` · ${units(r.held)} held` : ''}{r.sold_pending ? ` · ${units(r.sold_pending)} to deliver` : ''}</div>
                </button>
              ))}
            </div>
          ) : (
            <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: ds.light, color: ds.gray, textAlign: 'left' }}>
                    <th style={th}>Product</th><th style={th}>Size</th><th style={th}>SKU</th>
                    {['On hand', 'Held', 'To deliver', 'Available', 'Low at'].map((h) => <th key={h} style={{ ...th, textAlign: 'right' }}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={`${r.product_id}|${r.variant}`} onClick={() => setPanel(r)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setPanel(r) }}
                      style={{ borderTop: `1px solid ${ds.border}`, cursor: 'pointer' }}>
                      <td style={{ ...td, fontWeight: 600, color: ds.dark }}>{r.title}{!r.product_active && <span style={{ color: ds.gray, fontWeight: 400 }}> (archived)</span>}</td>
                      <td style={td}>{sizeText(r.variant)}{r.old_size && <span style={{ color: ds.gray }}> (old size)</span>}</td>
                      <td style={{ ...td, color: ds.gray }}>{r.sku || '—'}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{units(r.on_hand)}</td>
                      <td style={{ ...td, textAlign: 'right', color: r.held ? ds.dark : ds.gray }}>{units(r.held)}</td>
                      <td style={{ ...td, textAlign: 'right', color: r.sold_pending ? ds.dark : ds.gray }}>{units(r.sold_pending)}</td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 700, whiteSpace: 'nowrap' }}>{units(r.available)}{r.low && lowBadge}</td>
                      <td style={{ ...td, textAlign: 'right', color: ds.gray }}>{units(r.reorder_level)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}

      {panel && <StockItemPanel row={panel} locations={locations} canManage={canManage && enabled} onClose={() => setPanel(null)} onChanged={load}
        onReceive={(preset) => { setPanel(null); setForm({ kind: 'receive', preset }) }}
        onAdjust={(preset) => { setPanel(null); setForm({ kind: 'adjust', preset }) }} />}
      {form?.kind === 'receive' && <ReceiveStock locations={locations} preset={form.preset} onClose={() => setForm(null)} onDone={done} />}
      {form?.kind === 'adjust' && <AdjustStock locations={locations} preset={form.preset} onClose={() => setForm(null)} onDone={done} />}
    </div>
  )
}
