/**
 * frontend/src/modules/inventory/StockRequests.jsx
 * STOCK-4 — stock leaving a warehouse waits for the business owner. Moves (warehouse -> another location) and
 * deliveries (a paid invoice's goods from a warehouse) are asked for here or from Move stock / To deliver.
 * The owner approves or rejects; then the Inventory Manager (or a manager) sends the move or delivers the goods.
 * Goods on a move request are held at the warehouse from the moment it is asked for. The server checks every step.
 */
import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, CheckCircle2, ClipboardCheck, Truck } from 'lucide-react'
import { ds } from '../../utils/ds'
import { getMoveRequests, approveMove, rejectMove, sendApprovedMove, cancelMoveRequest, deliverFromStock, stockError } from '../../services/inventory.service'
import { card, inp, btnP, btnG, btnDanger, disabled, errBox, units, dateTime } from './stockUi'
import { REQ_STATUS, requestTitle, lineText } from './moveRequestUi'

const TONE = { pending: ['#FFF3E0', '#C05A00'], approved: ['#E6F4FF', '#1E5FA8'], done: ['#EEF9F1', '#1A7A40'], rejected: ['#FFF5F5', '#9B2C2C'], cancelled: [ds.light, ds.gray] }

function RequestCard({ r, isOwner, canHandle, me, onChanged, onError }) {
  const [busy, setBusy] = useState('')
  const [deciding, setDeciding] = useState('')   // 'approve' | 'reject'
  const [note, setNote] = useState('')
  const [bg, fg] = TONE[r.status] || TONE.cancelled
  const open = r.status === 'pending' || r.status === 'approved'
  const canCancel = open && (canHandle || r.requested_by === me) && !(r.kind === 'delivery' && (r.lines || []).some((l) => l.used))
  const run = async (kind, fn) => {
    setBusy(kind); onError('')
    try { const out = await fn(); setDeciding(''); setNote(''); onChanged(out, kind) } catch (e) { onError(stockError(e, 'Could not save. Please try again.')) } finally { setBusy('') }
  }
  const deliverLeft = () => run('deliver', () => deliverFromStock(r.invoice_id, {
    lines: (r.lines || []).filter((l) => l.left > 0).map((l) => ({ item_id: l.item_id, quantity: l.left })),
  }))

  return (
    <div style={{ ...card, padding: 16, display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {r.kind === 'transfer'
          ? <b style={{ color: ds.dark, display: 'inline-flex', alignItems: 'center', gap: 6 }}>{r.from_name}<ArrowRight size={15} color={ds.gray} />{r.to_name}</b>
          : <b style={{ color: ds.dark, display: 'inline-flex', alignItems: 'center', gap: 6 }}><Truck size={15} color={ds.gray} />{requestTitle(r)}</b>}
        <span style={{ padding: '2px 10px', borderRadius: 999, background: bg, color: fg, fontSize: 12, fontWeight: 700 }}>{REQ_STATUS[r.status] || r.status}</span>
        <span style={{ marginLeft: 'auto', color: ds.gray, fontSize: 13 }}>{units(r.units)} unit{r.units === 1 ? '' : 's'}</span>
      </div>
      <div style={{ display: 'grid', gap: 4, fontSize: 14, color: ds.dark }}>
        {(r.lines || []).map((l, i) => <div key={i}>{lineText(r, l)}{r.kind === 'delivery' && l.used ? <span style={{ color: ds.gray }}> · {units(l.used)} delivered</span> : null}</div>)}
      </div>
      {r.note && <div style={{ color: ds.gray, fontSize: 13.5 }}>“{r.note}”</div>}
      <div style={{ color: ds.gray, fontSize: 12.5, display: 'grid', gap: 2 }}>
        <span>Asked {dateTime(r.requested_at)}{r.requested_by_name ? ` by ${r.requested_by_name}` : ''}</span>
        {r.decided_at && <span>{r.status === 'rejected' ? 'Rejected' : 'Approved'} {dateTime(r.decided_at)}{r.decided_by_name ? ` by ${r.decided_by_name}` : ''}{r.decision_note ? `: “${r.decision_note}”` : ''}</span>}
        {r.done_at && r.status !== 'rejected' && <span>{r.status === 'cancelled' ? 'Cancelled' : r.kind === 'transfer' ? 'Sent' : 'Delivered'} {dateTime(r.done_at)}{r.done_by_name ? ` by ${r.done_by_name}` : ''}</span>}
      </div>
      {r.status === 'pending' && r.kind === 'transfer' && <div style={{ fontSize: 13, color: ds.gray }}>These goods are held at {r.from_name} and can't be sold until this is decided.</div>}

      {deciding ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <input aria-label="Note (optional)" style={inp} maxLength={300} placeholder={deciding === 'reject' ? 'Why? (optional)' : 'Note (optional)'} value={note} onChange={(e) => setNote(e.target.value)} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {deciding === 'approve'
              ? <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={() => run('approve', () => approveMove(r.id, note.trim()))}>{busy ? 'Saving…' : 'Yes, approve'}</button>
              : <button type="button" style={disabled(btnDanger, !!busy)} disabled={!!busy} onClick={() => run('reject', () => rejectMove(r.id, note.trim()))}>{busy ? 'Saving…' : 'Yes, reject'}</button>}
            <button type="button" style={btnG} disabled={!!busy} onClick={() => setDeciding('')}>Back</button>
          </div>
        </div>
      ) : (open && (isOwner || canHandle || canCancel)) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {r.status === 'pending' && isOwner && <>
            <button type="button" style={btnP} onClick={() => setDeciding('approve')}>Approve</button>
            <button type="button" style={btnDanger} onClick={() => setDeciding('reject')}>Reject</button>
          </>}
          {r.status === 'approved' && canHandle && r.kind === 'transfer' && (
            <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={() => run('send', () => sendApprovedMove(r.id))}>{busy === 'send' ? 'Sending…' : 'Send now'}</button>)}
          {r.status === 'approved' && canHandle && r.kind === 'delivery' && (
            <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={deliverLeft}>{busy === 'deliver' ? 'Saving…' : 'Mark delivered'}</button>)}
          {canCancel && <button type="button" style={btnG} disabled={!!busy} onClick={() => run('cancel', () => cancelMoveRequest(r.id))}>{busy === 'cancel' ? 'Saving…' : 'Cancel request'}</button>}
        </div>
      )}
    </div>
  )
}

export default function StockRequests({ onChanged, reloadKey }) {
  const [status, setStatus] = useState('open')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const load = useCallback(() => getMoveRequests(status || undefined)
    .then((r) => { setData(r); setErr('') })
    .catch((e) => { setErr(stockError(e, 'Could not load the requests. Please refresh.')); setData((d) => d || { requests: [] }) }), [status])
  useEffect(() => { load() }, [load, reloadKey])
  const list = data?.requests || []
  const chip = (v, text) => (
    <button key={v || 'all'} type="button" aria-pressed={status === v} onClick={() => setStatus(v)}
      style={{ padding: '0 12px', minHeight: 34, borderRadius: 999, border: `1.5px solid ${status === v ? ds.teal : ds.border}`, background: status === v ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13, cursor: 'pointer', fontFamily: ds.fontDm }}>{text}</button>
  )
  const done = (_out, kind) => {
    setNote({ approve: 'Approved. The team has been told it can go.', reject: 'Rejected. Anything held for it is free again.',
      send: 'Sent. The goods show as on the way until they are received.', deliver: 'Marked delivered. The goods are off the count.',
      cancel: 'Request cancelled.' }[kind] || '')
    load(); onChanged?.()
  }
  return (
    <div style={{ display: 'grid', gap: 12, maxWidth: 900 }}>
      <p style={{ margin: 0, color: ds.gray, fontSize: 14 }}>
        {data?.is_owner ? 'Stock leaving a warehouse waits for you. Approve it and your team can send or deliver it.'
          : 'Stock leaving a warehouse needs the business owner\'s approval. Once approved, send it or mark it delivered here.'}
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {chip('open', 'Open')}{chip('pending', 'Waiting')}{chip('approved', 'Approved')}{chip('done', 'Done')}{chip('rejected', 'Rejected')}{chip('', 'All')}
      </div>
      {note && <div role="status" style={{ ...errBox, background: '#EEF9F1', borderColor: '#BFE5CB', color: '#1A7A40' }}>{note}</div>}
      {err && <div role="alert" style={errBox}>{err}</div>}
      {!data && <p style={{ color: ds.gray }}>Loading…</p>}
      {data && list.length === 0 && !err && (
        <div style={{ ...card, textAlign: 'center', padding: 32 }}>
          {status === 'open' ? <CheckCircle2 size={28} color={ds.teal} /> : <ClipboardCheck size={28} color={ds.teal} />}
          <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>{status === 'open' ? 'Nothing waiting' : 'No requests here'}</p>
          <p style={{ color: ds.gray, margin: 0 }}>Moves out of a warehouse (Move stock) and deliveries from a warehouse (To deliver) show here.</p>
        </div>
      )}
      {list.map((r) => (
        <RequestCard key={`${r.id}-${r.status}-${r.units}`} r={r} isOwner={!!data?.is_owner} canHandle={!!data?.can_handle} me={data?.me}
          onError={setErr} onChanged={done} />
      ))}
    </div>
  )
}
