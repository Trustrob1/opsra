/**
 * frontend/src/modules/invoices/ReceiptsList.jsx
 * INV-4 — the Receipts tab: every receipt the business has given (against an invoice, paid online, or a sale with no
 * invoice), and New receipt for a sale that never had an invoice.
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus, Search, ReceiptText } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { listReceipts, createReceipt, pickContacts, apiError } from '../../services/invoices.service'
import { naira, niceDate, todayYmd, METHOD_LABEL, card, lab, inp, btnP, btnG, disabled } from './invoiceUi'
import ReceiptActions from './ReceiptActions'
import RegionSelect from './RegionSelect'   // INV-SALES-2
import { useRegions, lastRegion } from './useRegions'

const PAGE = 50
const MANUAL = ['bank_transfer', 'cash', 'pos', 'ussd', 'other']

export default function ReceiptsList({ isAdmin, onChanged }) {
  const isMobile = useIsMobile()
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [rows, setRows] = useState(null)
  const [more, setMore] = useState(false)
  const [err, setErr] = useState('')
  const [adding, setAdding] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [note, setNote] = useState('')   // SALE-1

  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t) }, [q])
  const load = useCallback((offset = 0) => listReceipts({ limit: PAGE, offset, ...(dq ? { q: dq } : {}) }).then((r) => {
    const items = r?.items || []
    setErr(''); setRows((prev) => (offset ? [...(prev || []), ...items] : items)); setMore(items.length === PAGE)
  }).catch((e) => { setErr(apiError(e, 'Could not load receipts. Please refresh.')); setRows([]) }), [dq])
  useEffect(() => { load(0) }, [load])
  const changed = () => { load(0); onChanged?.() }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: '1 1 240px' }}>
          <Search size={16} color={ds.gray} style={{ position: 'absolute', left: 12, top: 13 }} />
          <input style={{ ...inp, paddingLeft: 34 }} placeholder="Search by customer, number or reference" aria-label="Search receipts" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100} />
        </div>
        {!adding && <button type="button" style={btnP} onClick={() => { setAdding(true); setNote('') }}><Plus size={16} />New receipt</button>}
      </div>

      {adding && <NewReceipt onCancel={() => setAdding(false)} onDone={(m) => { setAdding(false); setNote(m || ''); changed() }} />}
      {note && <p role="status" style={{ color: ds.tealDark, margin: 0 }}>{note}</p>}

      {err && <p role="alert" style={{ color: ds.red, margin: 0 }}>{err}</p>}
      {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {rows && rows.length === 0 && !err && (
        <div style={{ ...card, textAlign: 'center', padding: 36 }}>
          <ReceiptText size={30} color={ds.teal} />
          <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>{dq ? 'No receipts match' : 'No receipts yet'}</p>
          <p style={{ color: ds.gray, margin: 0 }}>{dq ? 'Try another search.' : 'Record a payment on an invoice, or use New receipt for a sale with no invoice.'}</p>
        </div>
      )}
      {rows && rows.length > 0 && (
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          {rows.map((r, i) => (
            <div key={r.id} style={{ borderTop: i ? `1px solid ${ds.border}` : 'none', opacity: r.voided_at ? 0.7 : 1 }}>
              <button type="button" onClick={() => setOpenId(openId === r.id ? null : r.id)} aria-expanded={openId === r.id}
                style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: '12px 14px', fontFamily: ds.fontDm,
                  display: 'grid', gridTemplateColumns: isMobile ? '1fr auto' : '110px 1fr 160px 140px 130px', gap: 10, alignItems: 'center', fontSize: 14 }}>
                <b style={{ color: ds.dark }}>{r.number}</b>
                {isMobile ? <b style={{ textAlign: 'right', textDecoration: r.voided_at ? 'line-through' : 'none' }}>{naira(r.amount)}</b> : <span>{r.customer_name || '—'}</span>}
                {isMobile ? <span style={{ color: ds.gray, fontSize: 13, gridColumn: '1 / -1' }}>{r.customer_name} · {niceDate(r.paid_at)} · {METHOD_LABEL[r.method] || r.method}{r.invoice_number ? ` · ${r.invoice_number}` : ''}{r.voided_at ? ' · Void' : ''}</span>
                  : <span style={{ color: ds.gray }}>{r.invoice_number ? `Invoice ${r.invoice_number}` : 'No invoice'}{r.voided_at ? ' · Void' : ''}</span>}
                {!isMobile && <span style={{ color: ds.gray }}>{niceDate(r.paid_at)} · {METHOD_LABEL[r.method] || r.method}</span>}
                {!isMobile && <b style={{ textAlign: 'right', textDecoration: r.voided_at ? 'line-through' : 'none' }}>{naira(r.amount)}</b>}
              </button>
              {openId === r.id && (
                <div style={{ padding: '0 14px 14px', display: 'grid', gap: 6 }}>
                  {r.description && <div style={{ color: ds.gray, fontSize: 13.5 }}>{r.description}</div>}
                  {r.voided_at && <small style={{ color: ds.red }}>Voided {niceDate(r.voided_at)}{r.void_reason ? `: ${r.void_reason}` : ''}</small>}
                  <ReceiptActions receipt={r} isAdmin={isAdmin} onChanged={changed} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {more && <div style={{ textAlign: 'center' }}><button type="button" style={btnG} onClick={() => load(rows.length)}>Show more</button></div>}
    </div>
  )
}

function NewReceipt({ onCancel, onDone }) {
  const regions = useRegions()
  const [f, setF] = useState({ lead_id: null, customer_name: '', amount: '', method: 'cash', paid_at: todayYmd(), reference: '', description: '', region: '' })
  useEffect(() => { if (regions.length) setF((x) => (x.region ? x : { ...x, region: lastRegion(regions) })) }, [regions])
  const [found, setFound] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (patch) => setF((x) => ({ ...x, ...patch }))

  useEffect(() => {
    const name = f.customer_name.trim()
    if (f.lead_id || name.length < 2) return undefined
    let live = true
    const t = setTimeout(() => { pickContacts(name).then((r) => { if (live) setFound((r?.items || r || []).slice(0, 5)) }).catch(() => {}) }, 300)
    return () => { live = false; clearTimeout(t) }
  }, [f.customer_name, f.lead_id])

  const amount = String(f.amount).replace(/,/g, '').trim()
  const ok = /^\d+(\.\d{1,2})?$/.test(amount) && Number(amount) > 0 && f.customer_name.trim() && f.description.trim() && (!regions.length || f.region)
  const save = async () => {
    setBusy(true); setErr('')
    try {
      const out = await createReceipt({
        ...(f.lead_id ? { lead_id: f.lead_id } : {}), customer_name: f.customer_name.trim(), amount, method: f.method,
        paid_at: f.paid_at || null, reference: f.reference.trim() || null, description: f.description.trim(),
        ...(f.region ? { region: f.region } : {}),
      })
      onDone(out?.pending_payment   // SALE-1
        ? 'Saved. It is waiting for an admin to confirm it. The receipt is made once they approve.' : '')
    } catch (e) { setErr(apiError(e, 'Could not make the receipt. Please try again.')) } finally { setBusy(false) }
  }

  return (
    <div style={{ ...card, display: 'grid', gap: 10 }}>
      <b style={{ color: ds.dark }}>New receipt (no invoice)</b>
      <div style={{ position: 'relative' }}>
        <label style={lab} htmlFor="rc-name">Customer</label>
        <input id="rc-name" style={inp} maxLength={200} placeholder="Type a name to find a lead, or just type the name"
          value={f.customer_name} onChange={(e) => { setFound([]); set({ customer_name: e.target.value, lead_id: null }) }} />
        {f.lead_id && <small style={{ color: ds.green }}>Linked to the lead in Opsra.</small>}
        {!f.lead_id && found.length > 0 && (
          <div style={{ position: 'absolute', zIndex: 5, left: 0, right: 0, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 10, marginTop: 4, boxShadow: ds.cardShadow }}>
            {found.map((c) => (
              <button key={c.id} type="button" onClick={() => { setFound([]); set({ lead_id: c.id, customer_name: c.full_name || f.customer_name }) }}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', border: 'none', background: 'none', cursor: 'pointer', fontFamily: ds.fontDm, minHeight: 44 }}>
                <b>{c.full_name}</b> <span style={{ color: ds.gray }}>{c.whatsapp || c.phone || c.email || ''}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
        <div><label style={lab} htmlFor="rc-amt">Amount (₦)</label><input id="rc-amt" style={inp} inputMode="decimal" value={f.amount} onChange={(e) => set({ amount: e.target.value })} /></div>
        <div><label style={lab} htmlFor="rc-method">How they paid</label>
          <select id="rc-method" style={inp} value={f.method} onChange={(e) => set({ method: e.target.value })}>
            {MANUAL.map((m) => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
          </select></div>
        <div><label style={lab} htmlFor="rc-date">Date paid</label><input id="rc-date" type="date" style={inp} max={todayYmd()} value={f.paid_at} onChange={(e) => set({ paid_at: e.target.value })} /></div>
        <div><label style={lab} htmlFor="rc-ref">Reference (optional)</label><input id="rc-ref" style={inp} maxLength={200} value={f.reference} onChange={(e) => set({ reference: e.target.value })} /></div>
        <RegionSelect id="rc-region" regions={regions} value={f.region} onChange={(v) => set({ region: v })} />
      </div>
      <div><label style={lab} htmlFor="rc-desc">What it was for</label><input id="rc-desc" style={inp} maxLength={500} placeholder="e.g. 2 pillows" value={f.description} onChange={(e) => set({ description: e.target.value })} /></div>
      {err && <div role="alert" style={{ color: ds.red, fontSize: 14 }}>{err}</div>}
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button type="button" style={btnG} onClick={onCancel}>Cancel</button>
        <button type="button" style={disabled(btnP, !ok || busy)} disabled={!ok || busy} onClick={save}>{busy ? 'Saving…' : 'Make receipt'}</button>
      </div>
    </div>
  )
}
