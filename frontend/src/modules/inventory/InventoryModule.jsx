/**
 * frontend/src/modules/inventory/InventoryModule.jsx
 * STOCK-1 — the Inventory page: stock per product + size (all locations or one), low-stock filter, Receive stock and
 * Adjust (managers), each product's panel, the full history, and (managers) the settings and locations.
 * Shown to every product mode, like Invoices.
 * STOCK-3 — Moves tab and Move stock (managers): stock sent between locations, received when it arrives.
 * REPORT-1 — Report tab (owners and admins): the inventory report with PDF / CSV downloads.
 * STOCK-4 — Requests tab (stock leaving a warehouse waits for the owner) and Records tab (approved movements by week,
 * month or dates). The Inventory Manager works the stock (receive, adjust, move, deliver); settings stay with managers.
 */
import { useCallback, useEffect, useState } from 'react'
import { Boxes, PackagePlus, Search, SlidersHorizontal, Truck } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import useAuthStore from '../../store/authStore'
import { getStock, stockError, isPlanBlocked } from '../../services/inventory.service'
import { card, inp, btnP, btnG, units, nairaShort, sizeText, th, td } from './stockUi'
import { ReceiveStock, AdjustStock } from './StockForms'
import StockItemPanel from './StockItemPanel'
import StockHistory from './StockHistory'
import InventorySettings from './InventorySettings'
import InvoiceStockList from './InvoiceStockList'   // STOCK-2
import StockApprovals from './StockApprovals'       // STOCK-2b
import StockTransfers, { MoveStock } from './StockTransfers'   // STOCK-3
import InventoryReport from './InventoryReport'                 // REPORT-1
import StockRequests from './StockRequests'                     // STOCK-4
import MoveRecords from './MoveRecords'                         // STOCK-4

export default function InventoryModule() {
  const isMobile = useIsMobile()
  const isAdmin = useAuthStore((st) => st.hasPermission)('is_admin')   // owners count as admins
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
  const [moved, setMoved] = useState(0)           // bumps the Moves list after Move stock

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

  const canManage = !!data?.can_manage          // STOCK-4: managers and the Inventory Manager
  const canSettings = !!data?.can_settings
  const isOwner = !!data?.is_owner
  const waiting = data?.requests?.pending || 0
  const toSend = data?.requests?.approved || 0
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
  const done = (text) => { setForm(null); setPanel(null); setNote(text); setMoved((n) => n + 1); load() }
  const filtered = !!(dq || locationId || low)

  return (
    <div style={{ padding: isMobile ? 16 : 28, fontFamily: ds.fontDm }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 22, color: ds.dark, flex: 1 }}>Inventory</h1>
        {canManage && enabled && <>
          <button type="button" style={btnG} onClick={() => setForm({ kind: 'adjust' })}><SlidersHorizontal size={16} />Adjust</button>
          {locations.filter((l) => l.is_active).length > 1 && <button type="button" style={btnG} onClick={() => setForm({ kind: 'move' })}><Truck size={16} />Move stock</button>}
          <button type="button" style={btnP} onClick={() => setForm({ kind: 'receive' })}><PackagePlus size={16} />Receive stock</button>
        </>}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, overflowX: 'auto' }}>
        {chip(tab === 'stock', 'Stock', () => setTab('stock'))}
        {enabled && chip(tab === 'deliver', 'To deliver', () => setTab('deliver'))}
        {enabled && chip(tab === 'held', 'Held', () => setTab('held'))}
        {enabled && (canManage || isOwner) && chip(tab === 'requests', `Requests${(isOwner ? waiting : toSend) ? ` (${isOwner ? waiting : toSend})` : ''}`, () => setTab('requests'))}
        {enabled && canSettings && chip(tab === 'approvals', 'Approvals', () => setTab('approvals'))}
        {enabled && locations.length > 1 && chip(tab === 'moves', 'Moves', () => setTab('moves'))}
        {enabled && chip(tab === 'history', 'History', () => setTab('history'))}
        {enabled && (canManage || isOwner) && chip(tab === 'records', 'Records', () => setTab('records'))}
        {enabled && isAdmin && chip(tab === 'report', 'Report', () => setTab('report'))}
        {canSettings && chip(tab === 'settings', 'Settings', () => setTab('settings'))}
      </div>
      {enabled && isOwner && waiting > 0 && tab !== 'requests' && (
        <button type="button" onClick={() => setTab('requests')}
          style={{ ...card, width: '100%', textAlign: 'left', cursor: 'pointer', marginBottom: 14, padding: '12px 16px', background: '#FFF8EE', borderColor: '#F3D2A6', color: '#8A4B00', fontWeight: 600, fontSize: 14, fontFamily: ds.fontDm }}>
          {waiting} stock request{waiting === 1 ? '' : 's'} waiting for your approval. Open Requests
        </button>
      )}
      {note && <div role="status" style={{ background: '#EEF9F1', border: '1px solid #BFE5CB', color: '#1A7A40', borderRadius: 10, padding: '10px 14px', marginBottom: 14, fontSize: 14, display: 'flex', gap: 10 }}>
        <span style={{ flex: 1 }}>{note}</span><button type="button" onClick={() => setNote('')} style={{ border: 'none', background: 'none', color: '#1A7A40', cursor: 'pointer', fontWeight: 600 }}>Close</button></div>}

      {tab === 'settings' && canSettings ? <InventorySettings onChanged={load} />
        : tab === 'requests' && enabled ? <StockRequests onChanged={load} reloadKey={moved} />
        : tab === 'records' && enabled ? <MoveRecords locations={locations} />
        : tab === 'history' && enabled ? <StockHistory locations={locations} />
        : tab === 'report' && enabled && isAdmin ? <InventoryReport locations={locations} />
        : tab === 'approvals' && enabled && canSettings ? <StockApprovals onChanged={load} />
        : tab === 'moves' && enabled ? <StockTransfers canManage={canManage} onChanged={load} reloadKey={moved} />
        : (tab === 'deliver' || tab === 'held') && enabled ? <InvoiceStockList key={tab} kind={tab} locations={locations} onChanged={load} />
        : data && !enabled ? (
          <div style={{ ...card, maxWidth: 620 }}>
            <Boxes size={30} color={ds.teal} />
            <h2 style={{ margin: '10px 0 6px', fontSize: 18, color: ds.dark }}>Keep your stock in Opsra</h2>
            <p style={{ color: ds.gray, margin: '0 0 14px' }}>Track stock per store or warehouse, receive deliveries, record damage and stock counts, and see what is running low.
              {canSettings ? ' Turn it on in Settings; today\'s numbers are copied in for you.' : ' Ask your business owner or operations manager to turn it on.'}</p>
            {canSettings && <button type="button" style={btnP} onClick={() => setTab('settings')}>Set up stock</button>}
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
                  <div style={{ color: ds.gray, fontSize: 13.5 }}>{sizeText(r.variant)} · {units(r.on_hand)} on hand{r.held ? ` · ${units(r.held)} held` : ''}{r.sold_pending ? ` · ${units(r.sold_pending)} to deliver` : ''}{r.in_transit_in ? ` · ${units(r.in_transit_in)} on the way` : ''}</div>
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
                      <td style={{ ...td, textAlign: 'right' }}>{units(r.on_hand)}{r.in_transit_in ? <div style={{ color: ds.gray, fontSize: 12 }}>+{units(r.in_transit_in)} on the way</div> : null}</td>
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
      {form?.kind === 'move' && <MoveStock locations={locations} isOwner={isOwner} onClose={() => setForm(null)} onDone={(text, asked) => { done(text); setTab(asked ? 'requests' : 'moves') }} />}
      {form?.kind === 'adjust' && <AdjustStock locations={locations} preset={form.preset} onClose={() => setForm(null)} onDone={done} />}
    </div>
  )
}
