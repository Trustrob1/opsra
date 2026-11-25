/**
 * frontend/src/modules/inventory/StockForms.jsx
 * STOCK-1 — Receive stock (one or more lines into one location, optional cost per unit) and Adjust (add, remove or set
 * the count for one product + size, with a reason). Managers only; the server checks again.
 */
import { useEffect, useState } from 'react'
import { PackagePlus, SlidersHorizontal, Plus, Trash2, Search } from 'lucide-react'
import { ds } from '../../utils/ds'
import { pickStockProducts, receiveStock, adjustStock, stockError } from '../../services/inventory.service'
import StockModal from './StockModal'
import { lab, inp, btnP, btnG, disabled, errBox, sizeText, units, ADJUST_REASONS } from './stockUi'
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1

let keySeq = 0
const newKey = () => `l${++keySeq}`
const activeLocations = (locations) => (locations || []).filter((l) => l.is_active)
const firstLocation = (locations, preferred) => {
  const act = activeLocations(locations)
  return (preferred && act.find((l) => l.id === preferred)?.id) || act.find((l) => l.is_default)?.id || act[0]?.id || ''
}

/** Search box that lists products; picking one returns {id, title, sizes}. */
export function ProductSearch({ onPick, autoFocus }) {
  const [q, setQ] = useState('')
  const [list, setList] = useState([])
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return undefined
    let live = true
    const t = setTimeout(() => {
      pickStockProducts(q.trim()).then((r) => { if (live) setList(r?.items || []) }).catch(() => { if (live) setList([]) })
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [q, open])
  return (
    <div style={{ position: 'relative' }}>
      <Search size={16} color={ds.gray} style={{ position: 'absolute', left: 12, top: 13 }} />
      <input style={{ ...inp, paddingLeft: 34 }} placeholder="Find a product" aria-label="Find a product" value={q} maxLength={100}
        autoFocus={autoFocus} onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true) }} />
      {open && list.length > 0 && (
        <div role="listbox" style={{ position: 'absolute', left: 0, right: 0, top: 46, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 10, boxShadow: ds.cardShadow, zIndex: 5, maxHeight: 260, overflowY: 'auto' }}>
          {list.map((p) => (
            <button key={p.id} type="button" role="option" aria-selected="false"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { onPick(p); setQ(''); setOpen(false) }}
              style={{ display: 'flex', justifyContent: 'space-between', gap: 10, width: '100%', padding: '10px 12px', minHeight: 44, border: 'none', background: '#fff', cursor: 'pointer', textAlign: 'left', fontSize: 14, color: ds.dark, fontFamily: ds.fontDm }}>
              <span>{p.title}</span>
              <span style={{ color: ds.gray, whiteSpace: 'nowrap' }}>{p.sizes.length ? `${p.sizes.length} sizes` : 'One size'}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function LocationSelect({ locations, value, onChange, id }) {
  return (
    <div>
      <label style={lab} htmlFor={id}>Location</label>
      <select id={id} style={inp} value={value} onChange={(e) => onChange(e.target.value)}>
        {activeLocations(locations).map((l) => <option key={l.id} value={l.id}>{l.name}{l.is_default ? ' (main)' : ''}</option>)}
      </select>
    </div>
  )
}

export function ReceiveStock({ locations, preset, onClose, onDone }) {
  const [locationId, setLocationId] = useState(() => firstLocation(locations, preset?.location_id))
  const [lines, setLines] = useState(() => (preset?.product_id
    ? [{ key: newKey(), product_id: preset.product_id, title: preset.title, sizes: preset.sizes || (preset.variant ? [preset.variant] : []), variant: preset.variant || '', quantity: '', unit_cost: '' }]
    : []))
  const [ref, setRef] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const setLine = (key, patch) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const add = (p) => setLines((ls) => [...ls, { key: newKey(), product_id: p.id, title: p.title, sizes: p.sizes, variant: p.sizes.length === 1 ? p.sizes[0] : '', quantity: '', unit_cost: '' }])
  const total = lines.reduce((s, l) => s + (parseInt(l.quantity, 10) || 0), 0)
  const ready = locationId && lines.length > 0 && lines.every((l) => /^\d+$/.test(l.quantity) && Number(l.quantity) > 0
    && (!l.sizes.length || l.variant) && (l.unit_cost === '' || /^\d+(\.\d{1,2})?$/.test(l.unit_cost)))
  const why = !locationId ? 'Choose the location to save.'   // HINT-1
    : !lines.length ? 'Add at least one product to save.'
    : lines.some((l) => l.sizes.length && !l.variant) ? 'Choose the size for every product to save.'
    : lines.some((l) => !/^\d+$/.test(l.quantity) || Number(l.quantity) <= 0) ? 'Enter how many units came in for every product (whole numbers above 0).'
    : lines.some((l) => l.unit_cost !== '' && !/^\d+(\.\d{1,2})?$/.test(l.unit_cost)) ? 'Unit cost must be a number, like 25000 or 25000.50.'
    : ''

  const save = async () => {
    if (!ready || busy) return
    setBusy(true); setErr('')
    try {
      const out = await receiveStock({
        location_id: locationId, ref: ref.trim() || null, note: note.trim() || null,
        lines: lines.map((l) => ({ product_id: l.product_id, variant: l.variant || null, quantity: Number(l.quantity), ...(l.unit_cost !== '' ? { unit_cost: l.unit_cost } : {}) })),
      })
      onDone?.(`Received ${units(out.units)} unit${out.units === 1 ? '' : 's'}.`)
    } catch (e) {
      setErr(stockError(e, 'Could not save. Please try again.'))
      setBusy(false)
    }
  }

  return (
    <StockModal title="Receive stock" icon={PackagePlus} onClose={onClose} busy={busy} width={760}
      footer={<>
        <span role="status" style={{ color: ds.gray, fontSize: 13.5, marginRight: 'auto' }}>{lines.length && why ? why : total ? `${units(total)} unit${total === 1 ? '' : 's'} in` : 'Add the products that came in'}</span>
        <button type="button" style={btnG} onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" style={disabled(btnP, !ready || busy)} disabled={!ready || busy} onClick={save}>{busy ? 'Saving…' : 'Add to stock'}</button>
      </>}>
      {err && <div role="alert" style={errBox}>{err}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 16 }}>
        <LocationSelect id="rcv-loc" locations={locations} value={locationId} onChange={setLocationId} />
        <div><label style={lab} htmlFor="rcv-ref">Supplier or waybill (optional)</label>
          <input id="rcv-ref" style={inp} maxLength={200} value={ref} onChange={(e) => setRef(e.target.value)} /></div>
      </div>

      <div style={{ display: 'grid', gap: 10, marginBottom: 12 }}>
        {lines.map((l, i) => (
          <div key={l.key} style={{ border: `1px solid ${ds.border}`, borderRadius: 12, padding: 12, display: 'grid', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <b style={{ flex: 1, color: ds.dark, fontSize: 14.5 }}>{l.title}</b>
              <button type="button" aria-label={`Remove ${l.title}`} onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                style={{ ...btnG, minHeight: 36, padding: '0 10px' }}><Trash2 size={16} /></button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
              {l.sizes.length > 0 && (
                <div><label style={lab} htmlFor={`rcv-size-${i}`}>Size</label>
                  <select id={`rcv-size-${i}`} style={{ ...inp, borderColor: l.variant ? ds.border : ds.accent }} value={l.variant} onChange={(e) => setLine(l.key, { variant: e.target.value })}>
                    <option value="">Choose the size</option>
                    {l.sizes.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select></div>
              )}
              <div><label style={lab} htmlFor={`rcv-qty-${i}`}>Units</label>
                <input id={`rcv-qty-${i}`} style={inp} inputMode="numeric" value={l.quantity} maxLength={7}
                  onChange={(e) => setLine(l.key, { quantity: e.target.value.replace(/\D/g, '') })} /></div>
              <div><label style={lab} htmlFor={`rcv-cost-${i}`}>Cost per unit ₦ (optional)</label>
                <input id={`rcv-cost-${i}`} style={inp} inputMode="decimal" value={l.unit_cost} maxLength={14}
                  onChange={(e) => setLine(l.key, { unit_cost: e.target.value.replace(/[^\d.]/g, '') })} /></div>
            </div>
          </div>
        ))}
      </div>
      <ProductSearch onPick={add} autoFocus={!lines.length} />
      <p style={{ color: ds.gray, fontSize: 12.5, margin: '6px 0 16px', display: 'flex', alignItems: 'center', gap: 6 }}><Plus size={14} />Pick each product that came in. A cost you enter becomes that size's cost price.</p>
      <div><label style={lab} htmlFor="rcv-note">Note (optional)</label>
        <input id="rcv-note" style={inp} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></div>
    </StockModal>
  )
}

export function AdjustStock({ locations, preset, onClose, onDone }) {
  const [locationId, setLocationId] = useState(() => firstLocation(locations, preset?.location_id))
  const [prod, setProd] = useState(preset?.product_id ? { id: preset.product_id, title: preset.title, sizes: preset.sizes || (preset.variant ? [preset.variant] : []) } : null)
  const [variant, setVariant] = useState(preset?.variant || '')
  const [mode, setMode] = useState('remove')
  const [qty, setQty] = useState('')
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const ready = locationId && prod && (!prod.sizes.length || variant) && /^\d+$/.test(qty)
    && (mode === 'set' || Number(qty) > 0) && reason && (reason !== 'other' || note.trim())
  const why = !locationId ? 'Choose the location to save.'   // HINT-1
    : !prod ? 'Choose the product to save.'
    : prod.sizes.length && !variant ? 'Choose the size to save.'
    : !/^\d+$/.test(qty) || (mode !== 'set' && Number(qty) <= 0) ? `Enter the number of units${mode === 'set' ? '' : ' (above 0)'} to save.`
    : !reason ? 'Choose the reason to save.'
    : reason === 'other' && !note.trim() ? 'Say what happened to save.'
    : ''

  const save = async () => {
    if (!ready || busy) return
    setBusy(true); setErr('')
    try {
      const out = await adjustStock({ location_id: locationId, product_id: prod.id, variant: variant || null, mode, quantity: Number(qty), reason, note: note.trim() || null })
      onDone?.(`Saved. ${units(out.on_hand)} on hand, ${units(out.available)} available.`)
    } catch (e) {
      setErr(stockError(e, 'Could not save. Please try again.'))
      setBusy(false)
    }
  }
  const modeBtn = (v, text) => (
    <button key={v} type="button" aria-pressed={mode === v} onClick={() => setMode(v)}
      style={{ ...btnG, flex: 1, minHeight: 40, borderColor: mode === v ? ds.teal : ds.border, background: mode === v ? ds.mint : '#fff', color: ds.dark }}>{text}</button>
  )

  return (
    <StockModal title="Adjust stock" icon={SlidersHorizontal} onClose={onClose} busy={busy} width={560}
      footer={<>
        <WhyDisabled reason={busy ? '' : why} style={{ margin: 0, marginRight: 'auto' }} />
        <button type="button" style={btnG} onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" style={disabled(btnP, !ready || busy)} disabled={!ready || busy} onClick={save}>{busy ? 'Saving…' : 'Save change'}</button>
      </>}>
      {err && <div role="alert" style={errBox}>{err}</div>}
      <div style={{ display: 'grid', gap: 14 }}>
        <LocationSelect id="adj-loc" locations={locations} value={locationId} onChange={setLocationId} />
        <div>
          <div style={lab}>Product</div>
          {prod ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <b style={{ flex: 1, color: ds.dark }}>{prod.title}</b>
              {!preset?.product_id && <button type="button" style={{ ...btnG, minHeight: 36 }} onClick={() => { setProd(null); setVariant('') }}>Change</button>}
            </div>
          ) : <ProductSearch autoFocus onPick={(p) => { setProd(p); setVariant(p.sizes.length === 1 ? p.sizes[0] : '') }} />}
        </div>
        {prod?.sizes.length > 0 && (
          <div><label style={lab} htmlFor="adj-size">Size</label>
            <select id="adj-size" style={inp} value={variant} onChange={(e) => setVariant(e.target.value)} disabled={!!preset?.variant}>
              <option value="">Choose the size</option>
              {prod.sizes.map((s) => <option key={s} value={s}>{sizeText(s)}</option>)}
            </select></div>
        )}
        <div>
          <div style={lab}>Change</div>
          <div style={{ display: 'flex', gap: 8 }}>{modeBtn('remove', 'Remove')}{modeBtn('add', 'Add')}{modeBtn('set', 'Set the count')}</div>
        </div>
        <div><label style={lab} htmlFor="adj-qty">{mode === 'set' ? 'Units counted' : 'Units'}</label>
          <input id="adj-qty" style={inp} inputMode="numeric" maxLength={7} value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ''))} /></div>
        <div><label style={lab} htmlFor="adj-reason">Reason</label>
          <select id="adj-reason" style={inp} value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Choose a reason</option>
            {ADJUST_REASONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select></div>
        <div><label style={lab} htmlFor="adj-note">{reason === 'other' ? 'What happened' : 'Note (optional)'}</label>
          <input id="adj-note" style={inp} maxLength={400} value={note} onChange={(e) => setNote(e.target.value)} /></div>
        <p style={{ color: ds.gray, fontSize: 12.5, margin: 0 }}>Stock held on unpaid invoices or sold and waiting for delivery can't be removed.</p>
      </div>
    </StockModal>
  )
}
