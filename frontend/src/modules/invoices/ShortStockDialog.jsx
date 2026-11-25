/**
 * frontend/src/modules/invoices/ShortStockDialog.jsx
 * STOCK-2b — the invoice's location doesn't have enough. Shows each short item with the other locations that do,
 * and lets a manager take it from there and issue, or a rep ask an admin to approve (goods are held meanwhile).
 */
import { useState } from 'react'
import { AlertTriangle, Send } from 'lucide-react'
import { ds } from '../../utils/ds'
import { lab, inp, btnP, btnG, disabled } from './invoiceUi'
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1

export default function ShortStockDialog({ check, busy, error, onIssue, onRequest, onClose }) {
  const short = check.lines.filter((l) => l.short)
  const [pick, setPick] = useState(() => Object.fromEntries(short.map((l) => {
    const best = l.others.find((o) => o.available >= l.needed)
    return [l.item_id, best ? best.location_id : '']
  })))
  const [note, setNote] = useState('')
  const stuck = short.filter((l) => !l.others.some((o) => o.available >= l.needed))
  const ready = short.length > 0 && short.every((l) => pick[l.item_id])
  const sources = () => Object.fromEntries(Object.entries(pick).filter(([, v]) => v))

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,20,30,0.45)', zIndex: ds.z.modal + 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div role="dialog" aria-modal="true" aria-label="Not enough stock" style={{ background: '#fff', borderRadius: ds.radius.xxl, boxShadow: ds.modalShadow, width: '100%', maxWidth: 560, maxHeight: '90vh', overflowY: 'auto', padding: 20, fontFamily: ds.fontDm, display: 'grid', gap: 14 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <AlertTriangle size={20} color="#C05A00" />
          <b style={{ fontSize: 17, color: ds.dark }}>Not enough at {check.location?.name || 'this location'}</b>
        </div>
        {short.map((l) => (
          <div key={l.item_id} style={{ border: `1px solid ${ds.border}`, borderRadius: 10, padding: 12, display: 'grid', gap: 8 }}>
            <div style={{ color: ds.dark }}><b>{l.description}</b> <span style={{ color: ds.gray }}>· needs {l.needed}, {l.available_here} here</span></div>
            {l.others.some((o) => o.available >= l.needed) ? (
              <div><label style={lab} htmlFor={`src-${l.item_id}`}>Take it from</label>
                <select id={`src-${l.item_id}`} style={inp} value={pick[l.item_id] || ''} onChange={(e) => setPick((p) => ({ ...p, [l.item_id]: e.target.value }))}>
                  {l.others.filter((o) => o.available >= l.needed).map((o) => <option key={o.location_id} value={o.location_id}>{o.name} ({o.available} left)</option>)}
                </select></div>
            ) : (
              <div style={{ color: ds.red, fontSize: 13.5 }}>
                No location has {l.needed}.{l.others.length ? ` Most is ${l.others[0].available} at ${l.others[0].name}.` : ''} Lower the quantity or receive more stock.
              </div>
            )}
          </div>
        ))}
        {!check.can_approve && ready && (
          <div><label style={lab} htmlFor="src-note">Note for the admin (optional)</label>
            <input id="src-note" style={inp} maxLength={300} placeholder="e.g. Customer is at the showroom now" value={note} onChange={(e) => setNote(e.target.value)} /></div>
        )}
        {error && <div role="alert" style={{ color: ds.red, fontSize: 14 }}>{error}</div>}
        <small style={{ color: ds.gray }}>
          {check.can_approve
            ? 'The goods are held at the location you choose, and delivered from there.'
            : 'An owner, operations manager or admin must approve this. The goods are held for this customer while they decide, and the invoice is issued once approved.'}
        </small>
        <WhyDisabled style={{ textAlign: 'right' }} reason={!busy && short.length > 0 && !stuck.length && !ready ? 'Choose a location for every item that is short.' : ''} />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button type="button" style={btnG} disabled={busy} onClick={onClose}>{stuck.length ? 'Close' : 'Cancel'}</button>
          {check.can_approve
            ? <button type="button" style={disabled(btnP, busy || !ready)} disabled={busy || !ready} onClick={() => onIssue(sources())}>{busy ? 'Issuing…' : 'Take from there and issue'}</button>
            : <button type="button" style={disabled(btnP, busy || !ready)} disabled={busy || !ready} onClick={() => onRequest(sources(), note.trim())}><Send size={16} />{busy ? 'Sending…' : 'Ask an admin to approve'}</button>}
        </div>
      </div>
    </div>
  )
}
