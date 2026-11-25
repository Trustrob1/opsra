/**
 * frontend/src/modules/inventory/StockTransfers.jsx
 * STOCK-3 — moving stock between locations. Move stock (managers): the goods leave the sending location at once and
 * show as "on the way" at the receiving one. Receive all or part when it arrives; anything that won't arrive can be
 * sent back (cancel). Everyone can see the list; only managers act (the server checks again).
 */
import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, Trash2, Truck } from 'lucide-react'
import { ds } from '../../utils/ds'
import { getTransfers, sendTransfer, receiveTransfer, cancelTransfer, stockError } from '../../services/inventory.service'
import StockModal from './StockModal'
import { ProductSearch } from './StockForms'
import { card, lab, inp, btnP, btnG, disabled, errBox, units, sizeText, dateTime } from './stockUi'

let keySeq = 0
const newKey = () => `t${++keySeq}`
const STATUS = { in_transit: 'On the way', done: 'Arrived', cancelled: 'Cancelled' }
const TONE = { in_transit: ['#FFF3E0', '#C05A00'], done: ['#EEF9F1', '#1A7A40'], cancelled: [ds.light, ds.gray] }

export function MoveStock({ locations, onClose, onDone }) {
  const act = (locations || []).filter((l) => l.is_active)
  const [from, setFrom] = useState(() => act.find((l) => l.is_default)?.id || act[0]?.id || '')
  const [to, setTo] = useState(() => act.find((l) => !l.is_default)?.id || '')
  const [lines, setLines] = useState([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const setLine = (key, patch) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const add = (p) => setLines((ls) => [...ls, { key: newKey(), product_id: p.id, title: p.title, sizes: p.sizes, variant: p.sizes.length === 1 ? p.sizes[0] : '', quantity: '' }])
  const total = lines.reduce((s, l) => s + (parseInt(l.quantity, 10) || 0), 0)
  const ready = from && to && from !== to && lines.length > 0
    && lines.every((l) => /^\d+$/.test(l.quantity) && Number(l.quantity) > 0 && (!l.sizes.length || l.variant))

  const save = async () => {
    if (!ready || busy) return
    setBusy(true); setErr('')
    try {
      const t = await sendTransfer({
        from_location_id: from, to_location_id: to, note: note.trim() || null,
        lines: lines.map((l) => ({ product_id: l.product_id, variant: l.variant || null, quantity: Number(l.quantity) })),
      })
      onDone?.(`${units(t.units)} unit${t.units === 1 ? '' : 's'} on the way from ${t.from_name} to ${t.to_name}. Mark them received when they arrive.`)
    } catch (e) {
      setErr(stockError(e, 'Could not move the stock. Please try again.'))
      setBusy(false)
    }
  }
  const pick = (id, value, onChange, label) => (
    <div><label style={lab} htmlFor={id}>{label}</label>
      <select id={id} style={inp} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a location</option>
        {act.map((l) => <option key={l.id} value={l.id}>{l.name}{l.is_default ? ' (main)' : ''}</option>)}
      </select></div>
  )

  return (
    <StockModal title="Move stock" icon={Truck} onClose={onClose} busy={busy} width={720}
      footer={<>
        <span style={{ color: ds.gray, fontSize: 13.5, marginRight: 'auto' }}>{total ? `${units(total)} unit${total === 1 ? '' : 's'} to move` : 'Add what you are sending'}</span>
        <button type="button" style={btnG} onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" style={disabled(btnP, !ready || busy)} disabled={!ready || busy} onClick={save}>{busy ? 'Sending…' : 'Send stock'}</button>
      </>}>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {act.length < 2 ? <p style={{ color: ds.gray, margin: 0 }}>Add a second location in Settings to move stock between them.</p> : <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 6 }}>
          {pick('mv-from', from, setFrom, 'From')}
          {pick('mv-to', to, setTo, 'To')}
        </div>
        {from && from === to && <p role="alert" style={{ color: ds.red, fontSize: 13, margin: '0 0 8px' }}>Choose two different locations.</p>}
        <p style={{ color: ds.gray, fontSize: 12.5, margin: '0 0 14px' }}>The stock leaves {act.find((l) => l.id === from)?.name || 'the sending location'} now and shows as on the way until it is received.</p>
        <div style={{ display: 'grid', gap: 10, marginBottom: 12 }}>
          {lines.map((l, i) => (
            <div key={l.key} style={{ border: `1px solid ${ds.border}`, borderRadius: 12, padding: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, alignItems: 'end' }}>
              <b style={{ color: ds.dark, fontSize: 14.5, alignSelf: 'center' }}>{l.title}</b>
              {l.sizes.length > 0 && (
                <div><label style={lab} htmlFor={`mv-size-${i}`}>Size</label>
                  <select id={`mv-size-${i}`} style={{ ...inp, borderColor: l.variant ? ds.border : ds.accent }} value={l.variant} onChange={(e) => setLine(l.key, { variant: e.target.value })}>
                    <option value="">Choose the size</option>
                    {l.sizes.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select></div>
              )}
              <div><label style={lab} htmlFor={`mv-qty-${i}`}>Units</label>
                <input id={`mv-qty-${i}`} style={inp} inputMode="numeric" value={l.quantity} maxLength={7}
                  onChange={(e) => setLine(l.key, { quantity: e.target.value.replace(/\D/g, '') })} /></div>
              <button type="button" aria-label={`Remove ${l.title}`} onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                style={{ ...btnG, minHeight: 42, padding: '0 12px', justifySelf: 'start' }}><Trash2 size={16} /></button>
            </div>
          ))}
        </div>
        <ProductSearch onPick={add} autoFocus={!lines.length} />
        <div style={{ marginTop: 14 }}><label style={lab} htmlFor="mv-note">Note (optional)</label>
          <input id="mv-note" style={inp} maxLength={300} placeholder="e.g. driver's name or waybill" value={note} onChange={(e) => setNote(e.target.value)} /></div>
      </>}
    </StockModal>
  )
}

function TransferCard({ t, canManage, onChanged, onError }) {
  const [open, setOpen] = useState(false)
  const [qty, setQty] = useState({})
  const [busy, setBusy] = useState('')
  const [confirmCancel, setConfirmCancel] = useState(false)
  const live = t.status === 'in_transit'
  const [bg, fg] = TONE[t.status] || TONE.cancelled
  const startReceive = () => { setQty(Object.fromEntries(t.lines.map((l) => [l.id, String(l.left)]))); setOpen(true) }
  const entered = t.lines.map((l) => ({ line_id: l.id, quantity: Number(qty[l.id] || 0) }))
  const valid = t.lines.every((l) => /^\d*$/.test(qty[l.id] ?? '') && Number(qty[l.id] || 0) <= l.left)
  const any = entered.some((x) => x.quantity > 0)

  const run = async (kind, fn) => {
    setBusy(kind); onError('')
    try { await fn(); setOpen(false); setConfirmCancel(false); onChanged() } catch (e) { onError(stockError(e, 'Could not save. Please try again.')) } finally { setBusy('') }
  }
  return (
    <div style={{ ...card, padding: 16, display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <b style={{ color: ds.dark, display: 'inline-flex', alignItems: 'center', gap: 6 }}>{t.from_name}<ArrowRight size={15} color={ds.gray} />{t.to_name}</b>
        <span style={{ padding: '2px 10px', borderRadius: 999, background: bg, color: fg, fontSize: 12, fontWeight: 700 }}>{STATUS[t.status] || t.status}</span>
        <span style={{ marginLeft: 'auto', color: ds.gray, fontSize: 13 }}>Sent {dateTime(t.sent_at)}{t.sent_by_name ? ` by ${t.sent_by_name}` : ''}</span>
      </div>
      {t.note && <div style={{ color: ds.gray, fontSize: 13.5 }}>{t.note}</div>}
      <div style={{ display: 'grid', gap: 6 }}>
        {t.lines.map((l) => (
          <div key={l.id} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 14, color: ds.dark }}>
            <span style={{ flex: '1 1 200px' }}>{l.title} · {sizeText(l.variant)}</span>
            <span style={{ color: ds.gray }}>{units(l.quantity)} sent{l.received ? ` · ${units(l.received)} arrived` : ''}{l.cancelled ? ` · ${units(l.cancelled)} sent back` : ''}{live && l.left ? ` · ${units(l.left)} on the way` : ''}</span>
            {open && l.left > 0 && (
              <input aria-label={`Units of ${l.title} ${sizeText(l.variant)} that arrived`} style={{ ...inp, width: 90 }} inputMode="numeric" maxLength={7}
                value={qty[l.id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value.replace(/\D/g, '') }))} />
            )}
          </div>
        ))}
      </div>
      {!live && t.closed_at && <div style={{ color: ds.gray, fontSize: 12.5 }}>Closed {dateTime(t.closed_at)}{t.closed_by_name ? ` by ${t.closed_by_name}` : ''}</div>}
      {live && canManage && (
        open ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            {!valid && <span role="alert" style={{ color: ds.red, fontSize: 13, flexBasis: '100%' }}>A number is more than what's still on the way.</span>}
            <button type="button" style={disabled(btnP, !!busy || !valid || !any)} disabled={!!busy || !valid || !any}
              onClick={() => run('recv', () => receiveTransfer(t.id, { lines: entered }))}>{busy === 'recv' ? 'Saving…' : 'Mark received'}</button>
            <button type="button" style={disabled(btnG, !!busy || !valid)} disabled={!!busy || !valid}
              onClick={() => run('rest', () => receiveTransfer(t.id, { lines: entered, cancel_rest: true }))}>Received; send the rest back</button>
            <button type="button" style={btnG} disabled={!!busy} onClick={() => setOpen(false)}>Close</button>
          </div>
        ) : confirmCancel ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ color: ds.dark, fontWeight: 600 }}>Send the {units(t.units_left)} unit{t.units_left === 1 ? '' : 's'} still on the way back to {t.from_name}?</span>
            <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={() => run('cancel', () => cancelTransfer(t.id))}>{busy === 'cancel' ? 'Saving…' : 'Yes, cancel the move'}</button>
            <button type="button" style={btnG} disabled={!!busy} onClick={() => setConfirmCancel(false)}>Keep it</button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" style={btnP} onClick={startReceive}>Receive</button>
            <button type="button" style={btnG} onClick={() => setConfirmCancel(true)}>Cancel move</button>
          </div>
        )
      )}
    </div>
  )
}

export default function StockTransfers({ canManage, onChanged, reloadKey }) {
  const [status, setStatus] = useState('in_transit')
  const [list, setList] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(() => getTransfers(status || undefined)
    .then((r) => { setList(r?.transfers || []); setErr('') })
    .catch((e) => { setErr(stockError(e, 'Could not load stock moves. Please refresh.')); setList((l) => l || []) }), [status])
  useEffect(() => { load() }, [load, reloadKey])
  const chip = (v, text) => (
    <button key={v || 'all'} type="button" aria-pressed={status === v} onClick={() => setStatus(v)}
      style={{ padding: '0 12px', minHeight: 34, borderRadius: 999, border: `1.5px solid ${status === v ? ds.teal : ds.border}`, background: status === v ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13, cursor: 'pointer', fontFamily: ds.fontDm }}>{text}</button>
  )
  return (
    <div style={{ display: 'grid', gap: 12, maxWidth: 900 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {chip('in_transit', 'On the way')}{chip('done', 'Arrived')}{chip('cancelled', 'Cancelled')}{chip('', 'All')}
      </div>
      {err && <div role="alert" style={errBox}>{err}</div>}
      {!list && <p style={{ color: ds.gray }}>Loading…</p>}
      {list && list.length === 0 && !err && (
        <div style={{ ...card, textAlign: 'center', padding: 32 }}>
          <Truck size={28} color={ds.teal} />
          <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>{status === 'in_transit' ? 'Nothing on the way' : 'No stock moves here'}</p>
          <p style={{ color: ds.gray, margin: 0 }}>{canManage ? 'Use Move stock to send goods from one location to another, for example from the warehouse to a showroom.' : 'Stock moved between your locations shows here.'}</p>
        </div>
      )}
      {(list || []).map((t) => (
        <TransferCard key={`${t.id}-${t.status}-${t.units_left}`} t={t} canManage={canManage} onError={setErr}
          onChanged={() => { load(); onChanged?.() }} />
      ))}
    </div>
  )
}
