/**
 * frontend/src/modules/inventory/InventorySettings.jsx
 * STOCK-1 — managers: turn stock on (the first time copies today's numbers in once), the default "low stock at"
 * number, and locations (add, rename, link to a region, make main, turn off when empty).
 */
import { useCallback, useEffect, useState } from 'react'
import { MapPin, Star } from 'lucide-react'
import { ds } from '../../utils/ds'
import { getStockSettings, saveStockSettings, getLocations, createLocation, updateLocation, stockError } from '../../services/inventory.service'
import { card, lab, inp, btnP, btnG, disabled, errBox, units } from './stockUi'

const h = { margin: '0 0 12px', fontSize: 16, color: ds.dark }

function LocationRow({ loc, regions, onSaved, onError }) {
  const [name, setName] = useState(loc.name)
  const [region, setRegion] = useState(loc.region || '')
  const [busy, setBusy] = useState(false)
  const changed = name.trim() !== loc.name || (region || null) !== (loc.region || null)
  const run = async (body) => {
    setBusy(true); onError('')
    try { await updateLocation(loc.id, body); onSaved() } catch (e) { onError(stockError(e, 'Could not save the location.')) } finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10, alignItems: 'end', padding: '12px 0', borderTop: `1px solid ${ds.border}`, opacity: loc.is_active ? 1 : 0.6 }}>
      <div><label style={lab} htmlFor={`loc-n-${loc.id}`}>Name</label>
        <input id={`loc-n-${loc.id}`} style={inp} maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></div>
      {regions.length > 0 && (
        <div><label style={lab} htmlFor={`loc-r-${loc.id}`}>Region</label>
          <select id={`loc-r-${loc.id}`} style={inp} value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">No region</option>
            {regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select></div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {changed && <button type="button" style={disabled(btnP, busy || !name.trim())} disabled={busy || !name.trim()} onClick={() => run({ name: name.trim(), region: region || null })}>Save</button>}
        {loc.is_default
          ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: ds.tealDark, fontWeight: 600, fontSize: 13.5, minHeight: 42 }}><Star size={15} />Main location</span>
          : loc.is_active && <button type="button" style={btnG} disabled={busy} onClick={() => run({ is_default: true })}>Make main</button>}
        {!loc.is_default && (loc.is_active
          ? <button type="button" style={btnG} disabled={busy} onClick={() => run({ is_active: false })}>Turn off</button>
          : <button type="button" style={btnG} disabled={busy} onClick={() => run({ is_active: true })}>Turn on</button>)}
      </div>
    </div>
  )
}

export default function InventorySettings({ onChanged }) {
  const [settings, setSettings] = useState(null)
  const [locs, setLocs] = useState({ locations: [], regions: [] })
  const [reorder, setReorder] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newRegion, setNewRegion] = useState('')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const loadLocs = useCallback(() => getLocations().then((r) => setLocs({ locations: r?.locations || [], regions: r?.regions || [] })).catch(() => {}), [])
  useEffect(() => {
    getStockSettings().then((s) => { setSettings(s); setReorder(String(s.default_reorder_level ?? 5)) })
      .catch((e) => setErr(stockError(e, 'Could not load the settings. Please refresh.')))
    loadLocs()
  }, [loadLocs])

  const save = async (body, note) => {
    setBusy('settings'); setErr(''); setMsg('')
    try {
      const s = await saveStockSettings(body)
      setSettings(s); setReorder(String(s.default_reorder_level ?? 5)); setConfirm(false)
      setMsg(s.import ? `Stock is on. Copied ${units(s.import.units)} units for ${units(s.import.lines)} product sizes into ${locs.locations.find((l) => l.is_default)?.name || 'Main store'}.` : note)
      loadLocs(); onChanged?.()
    } catch (e) { setErr(stockError(e, 'Could not save. Please try again.')) } finally { setBusy('') }
  }
  const addLocation = async () => {
    setBusy('loc'); setErr(''); setMsg('')
    try {
      await createLocation({ name: newName.trim(), region: newRegion || null })
      setNewName(''); setNewRegion(''); loadLocs(); onChanged?.()
    } catch (e) { setErr(stockError(e, 'Could not add the location.')) } finally { setBusy('') }
  }

  if (!settings) return err ? <p role="alert" style={{ color: ds.red }}>{err}</p> : <p style={{ color: ds.gray }}>Loading…</p>
  const reorderOk = /^\d+$/.test(reorder)
  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 820 }}>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {msg && <div role="status" style={{ ...errBox, background: '#EEF9F1', borderColor: '#BFE5CB', color: '#1A7A40' }}>{msg}</div>}

      <section style={card}>
        <h3 style={h}>Stock</h3>
        {settings.enabled ? (
          <>
            <p style={{ margin: '0 0 12px', color: ds.dark }}>Stock is <b>on</b>. Opsra holds your true stock numbers{settings.imported_at ? '; today\'s numbers were copied in when you turned it on' : ''}.</p>
            <button type="button" style={btnG} disabled={!!busy} onClick={() => save({ enabled: false }, 'Stock is off. Your numbers are kept and come back when you turn it on.')}>Turn off</button>
          </>
        ) : (
          <>
            <p style={{ margin: '0 0 10px', color: ds.dark }}>Turn this on to keep your stock in Opsra: per location, with every change recorded.</p>
            <ul style={{ margin: '0 0 12px', paddingLeft: 18, color: ds.gray, fontSize: 13.5, lineHeight: 1.6 }}>
              {!settings.imported_at && <li>The first time, today's numbers are copied in once, into your main location (each size's Shopify quantity, or the product's stock number).</li>}
              <li>From then on Opsra's numbers are the true ones. Shopify sync keeps titles, prices and photos up to date but stops changing stock.</li>
              <li>Next phase: issuing an invoice holds stock and blocks the sale when there isn't enough.</li>
            </ul>
            {confirm ? (
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ color: ds.dark, fontWeight: 600 }}>Turn stock on now?</span>
                <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={() => save({ enabled: true })}>{busy ? 'Turning on…' : 'Yes, turn on'}</button>
                <button type="button" style={btnG} disabled={!!busy} onClick={() => setConfirm(false)}>Cancel</button>
              </div>
            ) : <button type="button" style={btnP} onClick={() => setConfirm(true)}>Turn on stock</button>}
          </>
        )}
      </section>

      <section style={card}>
        <h3 style={h}>Low stock</h3>
        <div style={{ display: 'flex', gap: 10, alignItems: 'end', flexWrap: 'wrap' }}>
          <div style={{ width: 180 }}><label style={lab} htmlFor="st-reorder">Low stock at (units)</label>
            <input id="st-reorder" style={inp} inputMode="numeric" maxLength={7} value={reorder} onChange={(e) => setReorder(e.target.value.replace(/\D/g, ''))} /></div>
          <button type="button" style={disabled(btnG, !!busy || !reorderOk)} disabled={!!busy || !reorderOk}
            onClick={() => save({ default_reorder_level: Number(reorder) }, 'Saved.')}>Save</button>
        </div>
        <p style={{ color: ds.gray, fontSize: 12.5, margin: '8px 0 0' }}>A product size shows as low when what's available across your locations is at or below this. You can set a different number per product size.</p>
      </section>

      <section style={card}>
        <h3 style={{ ...h, display: 'flex', alignItems: 'center', gap: 8 }}><MapPin size={17} color={ds.teal} />Locations</h3>
        <p style={{ color: ds.gray, fontSize: 13.5, margin: '0 0 4px' }}>Stores or warehouses where you keep stock. The main location is used for the starting numbers. A location can be turned off once it has no stock.</p>
        {locs.locations.map((l) => (
          <LocationRow key={`${l.id}-${l.name}-${l.region}-${l.is_default}-${l.is_active}`} loc={l} regions={locs.regions}
            onSaved={() => { loadLocs(); onChanged?.() }} onError={setErr} />
        ))}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10, alignItems: 'end', paddingTop: 12, borderTop: `1px solid ${ds.border}` }}>
          <div><label style={lab} htmlFor="loc-new">New location</label>
            <input id="loc-new" style={inp} maxLength={100} placeholder="e.g. Lekki showroom" value={newName} onChange={(e) => setNewName(e.target.value)} /></div>
          {locs.regions.length > 0 && (
            <div><label style={lab} htmlFor="loc-new-r">Region</label>
              <select id="loc-new-r" style={inp} value={newRegion} onChange={(e) => setNewRegion(e.target.value)}>
                <option value="">No region</option>
                {locs.regions.map((r) => <option key={r} value={r}>{r}</option>)}
              </select></div>
          )}
          <div><button type="button" style={disabled(btnP, !!busy || !newName.trim())} disabled={!!busy || !newName.trim()} onClick={addLocation}>Add location</button></div>
        </div>
      </section>
    </div>
  )
}
