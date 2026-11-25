/**
 * frontend/src/modules/invoices/InvoiceEditor.jsx
 * INV-2 — make or change a draft quote / invoice, and act on an issued one.
 *
 * Props
 *   docId      open this document (draft = editable form, issued = read-only view with actions)
 *   initial    for a new document: { doc_type: 'quote' | 'invoice', lead_id? }
 *              With a lead_id a draft is made at once so the customer's details come from the lead;
 *              if the person closes without changing anything that empty draft is deleted again.
 *   onClose()  onChanged()  (the list refreshes)
 *
 * Totals shown while typing are a preview; the server works out the real ones on every save.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { X, Plus, Trash2, Download, Search, Package, CheckCircle2, XCircle, FileText, Ban, Sparkles } from 'lucide-react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import { useIsMobile } from '../../hooks/useIsMobile'
import {
  getInvoiceSettings, getDoc, createDoc, updateDoc, deleteDoc, issueDoc, voidDoc, acceptQuote, declineQuote,
  convertQuote, pickContacts, pickProducts, downloadDocPdf, apiError, aiDraftLines,
  errorCode, getStockCheck, requestStock,   // STOCK-2b
} from '../../services/invoices.service'
import { naira, niceDate, todayYmd, TYPE_LABEL, lab, inp, btnP, btnG, btnDanger, disabled } from './invoiceUi'
import StatusPill from './StatusPill'
import SendPanel from './SendPanel'   // INV-3
import PaymentsPanel from './PaymentsPanel'   // INV-4
import RegionSelect from './RegionSelect'   // INV-SALES-2
import { useRegions, lastRegion } from './useRegions'
import StockPanel from './StockPanel'   // STOCK-2
import { useStock, startLocation, rememberLocation, useAvailability } from './useStock'
import ShortStockDialog from './ShortStockDialog'   // STOCK-2b
import PendingStock from './PendingStock'

let _key = 0
const newKey = () => `l${++_key}`
const toLine = (it) => ({ key: newKey(), product_id: it.product_id || null, description: it.description || '', quantity: String(it.quantity ?? 1), unit_price: it.unit_price == null ? '' : String(it.unit_price),
  variant: it.variant || '', sizes: Array.isArray(it.sizes) ? it.sizes : null })   // INV-SALES-2: size picked + the product's sizes
const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) ? n : 0 }
const round2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100

function fromDoc(doc) {
  return {
    doc_type: doc.doc_type, lead_id: doc.lead_id || null,
    customer_name: doc.customer_name || '', customer_phone: doc.customer_phone || '',
    customer_email: doc.customer_email || '', customer_address: doc.customer_address || '',
    items: (doc.items || []).map(toLine),
    discount: doc.discount ? String(doc.discount) : '',
    apply_vat: Number(doc.vat_rate || 0) > 0,
    issue_date: doc.issue_date || '', due_date: doc.due_date || '',
    notes: doc.notes || '', terms: doc.terms || '',
    region: doc.region || '',
    location_id: doc.location_id || '', loc_picked: !!doc.location_id,   // STOCK-2
  }
}

function payload(f) {
  const opt = (v) => (v && String(v).trim() ? String(v).trim() : null)
  return {
    lead_id: f.lead_id || null,
    customer_name: opt(f.customer_name), customer_phone: opt(f.customer_phone),
    customer_email: opt(f.customer_email), customer_address: opt(f.customer_address),
    items: f.items.filter((l) => l.description.trim() || l.product_id || num(l.unit_price) > 0).map((l) => ({
      ...(l.product_id ? { product_id: l.product_id } : {}),
      description: l.description.trim() || null,
      quantity: String(num(l.quantity) || 0),
      unit_price: l.unit_price === '' ? null : String(num(l.unit_price)),
      ...(l.variant ? { variant: l.variant } : {}),
    })),
    discount: String(num(f.discount)),
    apply_vat: !!f.apply_vat,
    issue_date: f.issue_date || null, due_date: f.due_date || null,
    notes: opt(f.notes), terms: opt(f.terms),
    region: f.region || null,
    ...(f.doc_type === 'invoice' ? { location_id: f.location_id || null } : {}),   // STOCK-2
  }
}

export default function InvoiceEditor({ docId: startId = null, initial = null, onClose, onChanged }) {
  const isMobile = useIsMobile()
  const isAdmin = useAuthStore((s) => s.hasPermission)('is_admin')
  const [docId, setDocId] = useState(startId)
  const [doc, setDoc] = useState(null)
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [voiding, setVoiding] = useState(false)
  const [voidReason, setVoidReason] = useState('')
  const [short, setShort] = useState(null)   // STOCK-2b: stock check when the location is short
  const autoMade = useRef(false)
  const dirty = useRef(false)
  const regions = useRegions()   // INV-SALES-2
  const stock = useStock()         // STOCK-2

  // A draft with no region starts on the region this person used last (not counted as a change).
  useEffect(() => {
    if (!regions.length) return
    setForm((f) => (f && !f.region && (!doc || doc.status === 'draft') ? { ...f, region: lastRegion(regions) } : f))
  }, [regions, doc])

  // STOCK-2: until the person picks a location, a draft invoice follows the region's location (else last used, else main).
  useEffect(() => {
    if (!stock.enabled || !stock.locations.length) return
    setForm((f) => {
      if (!f || f.doc_type !== 'invoice' || f.loc_picked || (doc && doc.status !== 'draft')) return f
      const want = startLocation(stock.locations, f.region)
      return want === f.location_id ? f : { ...f, location_id: want }
    })
  }, [stock, doc, form?.region, form?.doc_type])

  const set = (patch) => { dirty.current = true; setForm((f) => ({ ...f, ...patch })) }

  const load = useCallback(async (id) => {
    const d = await getDoc(id)
    setDoc(d); setForm(fromDoc(d))
  }, [])

  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const s = await getInvoiceSettings()
        if (!live) return
        setSettings(s)
        if (startId) { await load(startId); return }
        const type = initial?.doc_type || 'invoice'
        if (initial?.lead_id) {
          const d = await createDoc({ doc_type: type, lead_id: initial.lead_id })
          if (!live) return
          autoMade.current = true
          setDocId(d.id); setDoc(d); setForm(fromDoc(d))
          onChanged?.()
        } else {
          setForm({ doc_type: type, lead_id: null, customer_name: '', customer_phone: '', customer_email: '', customer_address: '',
            items: [toLine({ quantity: 1 })], discount: '', apply_vat: !!s.vat_enabled, issue_date: '', due_date: '',
            notes: '', terms: s.default_terms || '', region: '', location_id: '', loc_picked: false })
        }
      } catch (e) { if (live) setErr(apiError(e, 'Could not open this document. Please try again.')) }
    })()
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const close = async () => {
    if (autoMade.current && !dirty.current && docId && doc?.status === 'draft') {
      try { await deleteDoc(docId); onChanged?.() } catch { /* leave the draft; harmless */ }
    }
    onClose?.()
  }

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const preview = useMemo(() => {
    if (!form) return null
    const sub = round2(form.items.reduce((t, l) => t + round2(num(l.quantity) * num(l.unit_price)), 0))
    const disc = round2(num(form.discount))
    const rate = form.apply_vat ? Number(settings?.vat_rate || 0) : 0
    const vat = round2(Math.max(sub - disc, 0) * rate / 100)
    return { sub, disc, rate, vat, total: round2(sub - disc + vat) }
  }, [form, settings])

  const run = async (label, fn) => {
    setBusy(label); setErr('')
    try { await fn() } catch (e) { setErr(apiError(e)) } finally { setBusy('') }
  }

  const saveDraft = async () => {
    const body = payload(form)
    if (docId) {
      const d = await updateDoc(docId, body)
      setDoc(d); setForm(fromDoc(d))
      return d
    }
    const d = await createDoc({ doc_type: form.doc_type, ...body })
    setDocId(d.id); setDoc(d); setForm(fromDoc(d))
    return d
  }

  const onSave = () => run('save', async () => { await saveDraft(); dirty.current = false; autoMade.current = false; onChanged?.() })
  const onIssue = () => {
    if (!form.customer_name.trim()) { setErr("Add the customer's name first."); return }
    if (!form.items.some((l) => l.description.trim() && num(l.quantity) > 0)) { setErr('Add at least one line first.'); return }
    if (preview.total <= 0) { setErr('The total must be more than ₦0.'); return }
    if (regions.length && !form.region) { setErr('Choose the region first.'); return }
    const noSize = form.items.find((l) => l.sizes?.length && !l.variant)
    if (noSize) { setErr(`Choose the size for ${noSize.description || 'each product'}.`); return }
    if (kind === 'invoice' && stock.enabled && form.items.some((l) => l.product_id) && !form.location_id) {
      setErr('Choose where the stock comes from first.'); return
    }
    if (form.location_id) rememberLocation(form.location_id)
    ;(async () => {
      setBusy('issue'); setErr('')
      let saved = null
      try {
        saved = await saveDraft()
        const issued = await issueDoc(saved.id)
        autoMade.current = false; dirty.current = false
        setDoc(issued); setForm(fromDoc(issued)); onChanged?.()
      } catch (e) {
        // STOCK-2b: not enough at this location -> show where else has it
        if (errorCode(e) === 'STOCK_SHORT' && saved) {
          try {
            const chk = await getStockCheck(saved.id)
            if (chk?.short) setShort(chk); else setErr(apiError(e))
          } catch { setErr(apiError(e)) }
        } else setErr(apiError(e))
      } finally { setBusy('') }
    })()
  }
  const afterStock = async (d) => {
    autoMade.current = false; dirty.current = false; setShort(null)
    try { await load(d.id) } catch { setDoc(d); setForm(fromDoc(d)) }
    onChanged?.()
  }
  const issueFrom = (sources) => run('issue', async () => { await afterStock(await issueDoc(docId, sources)) })
  const requestFrom = (sources, note) => run('issue', async () => { await afterStock(await requestStock(docId, sources, note || null)) })
  const onDelete = () => run('delete', async () => {
    if (!window.confirm(`Delete this draft ${TYPE_LABEL[form.doc_type].toLowerCase()}? This can't be undone.`)) return
    if (docId) await deleteDoc(docId)
    onChanged?.(); onClose?.()
  })
  const act = (label, fn) => run(label, async () => { const d = await fn(docId); setDoc(d); setForm(fromDoc(d)); onChanged?.() })
  const onConvert = () => run('convert', async () => {
    const inv = await convertQuote(docId)
    onChanged?.()
    autoMade.current = false; dirty.current = false
    setDocId(inv.id); setDoc(inv); setForm(fromDoc(inv))
  })
  const onVoid = () => {
    if (voidReason.trim().length < 3) { setErr('Say briefly why it is being voided.'); return }
    act('void', (id) => voidDoc(id, voidReason.trim())).then(() => { setVoiding(false); setVoidReason('') })
  }
  const onPdf = () => run('pdf', () => downloadDocPdf(docId))

  const shell = {
    position: 'fixed', inset: 0, background: 'rgba(15,20,30,0.45)', zIndex: ds.z.modal,
    display: 'flex', alignItems: isMobile ? 'stretch' : 'center', justifyContent: 'center', padding: isMobile ? 0 : 20,
  }
  const panel = {
    background: '#fff', width: '100%', maxWidth: 860, maxHeight: isMobile ? '100%' : '92vh', height: isMobile ? '100%' : 'auto',
    borderRadius: isMobile ? 0 : ds.radius.xxl, boxShadow: ds.modalShadow, display: 'flex', flexDirection: 'column', fontFamily: ds.fontDm,
  }
  const pending = doc?.status === 'draft' && doc?.stock_approval === 'pending'   // STOCK-2b
  const editable = (!doc || doc.status === 'draft') && !pending
  const kind = form?.doc_type || initial?.doc_type || 'invoice'
  const title = doc?.number ? `${TYPE_LABEL[kind]} ${doc.number}` : `New ${TYPE_LABEL[kind].toLowerCase()}`

  return (
    <div style={shell} onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) close() }}>
      <div style={panel} role="dialog" aria-modal="true" aria-label={title}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 20px', borderBottom: `1px solid ${ds.border}` }}>
          <FileText size={20} color={ds.teal} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 17, color: ds.dark }}>{title}</div>
            {doc && <div style={{ marginTop: 3 }}><StatusPill status={doc.display_status || doc.status} /></div>}
          </div>
          <button type="button" onClick={close} disabled={!!busy} aria-label="Close" style={{ ...btnG, minHeight: 40, padding: '0 10px' }}><X size={18} /></button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? 16 : 22 }}>
          {err && <div role="alert" style={{ background: '#FFF5F5', border: '1px solid #F5C2C2', color: '#9B2C2C', borderRadius: 10, padding: '10px 14px', marginBottom: 14, fontSize: 14 }}>{err}</div>}
          {!form && !err && <p style={{ color: ds.gray }}>Loading…</p>}
          {form && editable && doc?.stock_approval === 'rejected' && (
            <div role="status" style={{ background: '#FFF5F5', border: '1px solid #F5C2C2', color: '#9B2C2C', borderRadius: 10, padding: '10px 14px', marginBottom: 14, fontSize: 14 }}>
              Taking stock from another location was not approved{doc.stock_decision_note ? `: ${doc.stock_decision_note}` : '.'} Change the invoice and issue it again.
            </div>
          )}
          {form && pending && <PendingStock doc={doc} onChanged={afterStock} />}
          {form && editable && <DraftForm form={form} set={set} settings={settings} preview={preview} isNew={!doc} isMobile={isMobile} regions={regions} stock={stock} />}
          {form && !editable && !pending && <IssuedView doc={doc} isAdmin={isAdmin} onPaid={() => { load(doc.id).catch(() => {}); onChanged?.() }} />}
        </div>

        {form && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '12px 20px', borderTop: `1px solid ${ds.border}`, justifyContent: 'flex-end', alignItems: 'center' }}>
            {editable ? (
              <>
                {doc && <button type="button" style={{ ...disabled(btnDanger, !!busy), marginRight: 'auto' }} disabled={!!busy} onClick={onDelete}><Trash2 size={16} />Delete draft</button>}
                {doc && <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={onPdf}><Download size={16} />Preview PDF</button>}
                <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={onSave}>{busy === 'save' ? 'Saving…' : 'Save draft'}</button>
                <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={onIssue}>{busy === 'issue' ? 'Issuing…' : `Issue ${TYPE_LABEL[kind].toLowerCase()}`}</button>
              </>
            ) : voiding ? (
              <div style={{ display: 'flex', gap: 10, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                <input style={{ ...inp, flex: 1, minWidth: 200 }} autoFocus maxLength={500} placeholder="Why is it being voided? e.g. wrong price"
                  value={voidReason} onChange={(e) => setVoidReason(e.target.value)} aria-label="Reason for voiding" />
                <button type="button" style={btnG} onClick={() => { setVoiding(false); setVoidReason('') }}>Keep it</button>
                <button type="button" style={disabled({ ...btnP, background: ds.red }, !!busy)} disabled={!!busy} onClick={onVoid}>{busy === 'void' ? 'Voiding…' : 'Void it'}</button>
              </div>
            ) : (
              <>
                {isAdmin && ['issued', 'accepted', 'declined'].includes(doc.status) && Number(doc.amount_paid || 0) === 0 &&
                  <button type="button" style={{ ...btnDanger, marginRight: 'auto' }} onClick={() => setVoiding(true)}><Ban size={16} />Void</button>}
                <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={onPdf}><Download size={16} />{busy === 'pdf' ? 'Preparing…' : 'Download PDF'}</button>
                {kind === 'quote' && doc.status === 'issued' && <>
                  <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => act('decline', declineQuote)}><XCircle size={16} />Mark declined</button>
                  <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => act('accept', acceptQuote)}><CheckCircle2 size={16} />Mark accepted</button>
                </>}
                {kind === 'quote' && ['issued', 'accepted'].includes(doc.status) &&
                  <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={onConvert}>{busy === 'convert' ? 'Making invoice…' : 'Turn into invoice'}</button>}
              </>
            )}
          </div>
        )}
      </div>
      {short && <ShortStockDialog check={short} busy={busy === 'issue'} error={err} onIssue={issueFrom} onRequest={requestFrom}
        onClose={() => { setShort(null); setErr(`Not enough stock at ${short.location?.name || 'this location'}. Lower the quantity or choose another location.`) }} />}
    </div>
  )
}

// ───────────────────────────── draft form ─────────────────────────────

function DraftForm({ form, set, settings, preview, isNew, isMobile, regions, stock }) {
  // STOCK-2: what is left at the chosen location, per size, for the products on this invoice
  const kind0 = form.doc_type
  const stockOn = kind0 === 'invoice' && !!stock?.enabled && stock.locations.length > 0
  const avail = useAvailability(stockOn, form.location_id, form.items.filter((l) => l.product_id).map((l) => l.product_id))
  const leftFor = (l, size) => (avail ? Number(avail[l.product_id]?.[size ?? ''] ?? 0) : null)
  const locName = stock?.locations.find((x) => x.id === form.location_id)?.name || 'this location'
  const grid2 = { display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12 }
  const setLine = (key, patch) => set({ items: form.items.map((l) => (l.key === key ? { ...l, ...patch } : l)) })
  const removeLine = (key) => set({ items: form.items.filter((l) => l.key !== key) })
  const addLine = (it = { quantity: 1 }) => set({ items: [...form.items.filter((l) => l.description.trim() || l.product_id || l.unit_price !== ''), toLine(it)] })
  // INV-SALES-2: picking a size sets its price and swaps the size at the end of the line text
  const pickSize = (l, title) => {
    const size = (l.sizes || []).find((s) => s.title === title)
    let desc = l.description
    if (l.variant && desc.endsWith(` - ${l.variant}`)) desc = desc.slice(0, -(l.variant.length + 3))
    setLine(l.key, { variant: title, description: desc, ...(size && size.price != null ? { unit_price: String(size.price) } : {}) })
  }
  const kind = form.doc_type

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      {isNew && (
        <div style={{ display: 'flex', gap: 8 }} role="radiogroup" aria-label="Document type">
          {['invoice', 'quote'].map((t) => (
            <button key={t} type="button" role="radio" aria-checked={kind === t} onClick={() => set({ doc_type: t })}
              style={{ ...btnG, background: kind === t ? ds.mint : '#fff', borderColor: kind === t ? ds.teal : ds.border }}>{TYPE_LABEL[t]}</button>
          ))}
        </div>
      )}

      <section>
        <h3 style={{ fontSize: 15, margin: '0 0 10px', color: ds.dark }}>Customer</h3>
        <ContactSearch onPick={(c) => set({ lead_id: c.id, customer_name: c.full_name || '', customer_phone: c.whatsapp || c.phone || '', customer_email: c.email || '', customer_address: c.location || '' })} />
        {(regions?.length > 0 || stockOn) && (
          <div style={{ ...grid2, marginTop: 10 }}>
            {regions?.length > 0 && <RegionSelect regions={regions} value={form.region} onChange={(v) => set({ region: v })} />}
            {stockOn && (
              <div><label style={lab} htmlFor="inv-loc">Stock comes from</label>
                <select id="inv-loc" style={{ ...inp, borderColor: form.location_id ? ds.border : ds.accent }} value={form.location_id}
                  onChange={(e) => set({ location_id: e.target.value, loc_picked: true })}>
                  <option value="">Choose a location</option>
                  {stock.locations.map((x) => <option key={x.id} value={x.id}>{x.name}{x.region ? ` (${x.region})` : ''}</option>)}
                </select>
                <small style={{ color: ds.gray }}>Issuing holds the goods here until the invoice is paid or voided.</small>
              </div>
            )}
          </div>
        )}
        <div style={{ ...grid2, marginTop: 10 }}>
          <div><label style={lab} htmlFor="inv-cn">Name</label><input id="inv-cn" style={inp} maxLength={200} value={form.customer_name} onChange={(e) => set({ customer_name: e.target.value })} /></div>
          <div><label style={lab} htmlFor="inv-cp">Phone</label><input id="inv-cp" style={inp} maxLength={30} inputMode="tel" value={form.customer_phone} onChange={(e) => set({ customer_phone: e.target.value })} /></div>
          <div><label style={lab} htmlFor="inv-ce">Email</label><input id="inv-ce" style={inp} maxLength={254} type="email" value={form.customer_email} onChange={(e) => set({ customer_email: e.target.value })} /></div>
          <div><label style={lab} htmlFor="inv-ca">Address</label><input id="inv-ca" style={inp} maxLength={500} value={form.customer_address} onChange={(e) => set({ customer_address: e.target.value })} /></div>
        </div>
      </section>

      <section>
        <h3 style={{ fontSize: 15, margin: '0 0 10px', color: ds.dark }}>Items</h3>
        {!isMobile && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 140px 130px 40px', gap: 8, ...lab, marginBottom: 6 }}>
            <span>Description</span><span>Qty</span><span>Unit price (₦)</span><span style={{ textAlign: 'right' }}>Amount</span><span />
          </div>
        )}
        {form.items.map((l, i) => (
          <div key={l.key} style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : '1fr 80px 140px 130px 40px', gap: 8, marginBottom: 8, alignItems: 'center', ...(isMobile ? { padding: 10, border: `1px solid ${ds.border}`, borderRadius: 10 } : {}) }}>
            <div style={{ display: 'grid', gap: 6, ...(isMobile ? { gridColumn: '1 / -1' } : {}) }}>
              <input style={inp} maxLength={500} placeholder="What you are selling" aria-label={`Line ${i + 1} description`}
                value={l.description} onChange={(e) => setLine(l.key, { description: e.target.value })} />
              {l.sizes?.length > 0 && (
                <select style={{ ...inp, borderColor: l.variant ? ds.border : ds.accent }} aria-label={`Line ${i + 1} size`}
                  value={l.variant} onChange={(e) => pickSize(l, e.target.value)}>
                  <option value="">Choose the size</option>
                  {l.sizes.map((s) => {
                    const left = stockOn ? leftFor(l, s.title) : null
                    return <option key={s.title} value={s.title} disabled={left !== null && left <= 0 && s.title !== l.variant}>
                      {s.title}{s.price != null ? ` · ${naira(s.price)}` : ''}{left === null ? '' : left > 0 ? ` · ${left} left` : ' · sold out'}
                    </option>
                  })}
                </select>
              )}
              {stockOn && l.product_id && (!l.sizes?.length || l.variant) && leftFor(l, l.sizes?.length ? l.variant : '') !== null && (() => {
                const left = leftFor(l, l.sizes?.length ? l.variant : '')
                const short = num(l.quantity) > left
                return <small style={{ color: short ? ds.red : ds.gray }}>
                  {left <= 0 ? `None left at ${locName}` : short ? `Only ${left} left at ${locName}` : `${left} left at ${locName}`}
                </small>
              })()}
            </div>
            <input style={inp} inputMode="decimal" aria-label={`Line ${i + 1} quantity`} value={l.quantity} onChange={(e) => setLine(l.key, { quantity: e.target.value })} />
            <input style={inp} inputMode="decimal" placeholder="0.00" aria-label={`Line ${i + 1} unit price`} value={l.unit_price} onChange={(e) => setLine(l.key, { unit_price: e.target.value })} />
            <div style={{ textAlign: 'right', fontWeight: 600, color: ds.dark, fontSize: 14 }}>{naira(round2(num(l.quantity) * num(l.unit_price)))}</div>
            <button type="button" onClick={() => removeLine(l.key)} aria-label={`Remove line ${i + 1}`} style={{ ...btnG, padding: 0, minWidth: 40, color: ds.gray }}><Trash2 size={16} /></button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
          <button type="button" style={btnG} onClick={() => addLine()}><Plus size={16} />Add line</button>
          <ProductPicker onPick={(p) => {
            const sizes = p.sizes || []
            const only = sizes.length === 1 ? sizes[0] : null
            addLine({ product_id: p.id, description: p.title, quantity: 1, sizes, variant: only ? only.title : '',
              unit_price: only && only.price != null ? only.price : (sizes.length ? '' : (p.price ?? '')) })
          }} />
          {form.lead_id && <FillFromChat leadId={form.lead_id} onLines={(lines) => set({
            items: [...form.items.filter((l) => l.description.trim() || l.product_id || l.unit_price !== ''), ...lines.map(toLine)],
          })} />}
        </div>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 300px', gap: 18, alignItems: 'start' }}>
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={grid2}>
            <div><label style={lab} htmlFor="inv-id">Date</label><input id="inv-id" type="date" style={inp} value={form.issue_date} onChange={(e) => set({ issue_date: e.target.value })} /><small style={{ color: ds.gray }}>Blank = the day you issue it</small></div>
            <div><label style={lab} htmlFor="inv-dd">{kind === 'quote' ? 'Valid until' : 'Due date'}</label><input id="inv-dd" type="date" min={form.issue_date || todayYmd()} style={inp} value={form.due_date} onChange={(e) => set({ due_date: e.target.value })} />
              <small style={{ color: ds.gray }}>Blank = {kind === 'quote' ? settings?.default_quote_valid_days : settings?.default_due_days} days after the date</small></div>
          </div>
          <div><label style={lab} htmlFor="inv-notes">Note to the customer</label><textarea id="inv-notes" rows={2} maxLength={5000} style={{ ...inp, resize: 'vertical' }} value={form.notes} onChange={(e) => set({ notes: e.target.value })} /></div>
          <div><label style={lab} htmlFor="inv-terms">Terms</label><textarea id="inv-terms" rows={2} maxLength={5000} style={{ ...inp, resize: 'vertical' }} value={form.terms} onChange={(e) => set({ terms: e.target.value })} /></div>
        </div>
        <div style={{ background: ds.light, borderRadius: 12, padding: 16, display: 'grid', gap: 8, fontSize: 14 }}>
          <Row k="Subtotal" v={naira(preview.sub)} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label htmlFor="inv-disc" style={{ flex: 1, color: ds.gray }}>Discount (₦)</label>
            <input id="inv-disc" style={{ ...inp, width: 130, minHeight: 38, textAlign: 'right' }} inputMode="decimal" placeholder="0" value={form.discount} onChange={(e) => set({ discount: e.target.value })} />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: ds.gray, cursor: 'pointer', minHeight: 32 }}>
            <input type="checkbox" checked={form.apply_vat} onChange={(e) => set({ apply_vat: e.target.checked })} style={{ width: 18, height: 18 }} />
            <span style={{ flex: 1 }}>Add VAT ({Number(settings?.vat_rate || 0)}%)</span>
            <span style={{ color: ds.dark }}>{naira(preview.vat)}</span>
          </label>
          <div style={{ borderTop: `2px solid ${ds.teal}`, paddingTop: 8 }}><Row k={<b>Total</b>} v={<b style={{ fontSize: 17 }}>{naira(preview.total)}</b>} /></div>
          {preview.disc > preview.sub && <div style={{ color: ds.red, fontSize: 13 }}>The discount is more than the subtotal.</div>}
        </div>
      </section>
    </div>
  )
}

const Row = ({ k, v }) => <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}><span style={{ color: ds.gray }}>{k}</span><span style={{ color: ds.dark }}>{v}</span></div>

function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

function ContactSearch({ onPick }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState([])
  const dq = useDebounced(q)
  useEffect(() => {
    if (!open || dq.trim().length < 2) return undefined
    let live = true
    pickContacts(dq.trim()).then((r) => { if (live) setRows(r || []) }).catch(() => { if (live) setRows([]) })
    return () => { live = false }
  }, [dq, open])
  return (
    <div style={{ position: 'relative' }}>
      <Search size={16} color={ds.gray} style={{ position: 'absolute', left: 12, top: 13 }} />
      <input style={{ ...inp, paddingLeft: 34 }} placeholder="Find a contact by name, phone or email" aria-label="Find a contact"
        value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} />
      {open && dq.trim().length >= 2 && rows.length > 0 && (
        <ul role="listbox" style={{ position: 'absolute', zIndex: 5, left: 0, right: 0, top: 46, margin: 0, padding: 4, listStyle: 'none', background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 10, boxShadow: ds.hoverShadow, maxHeight: 240, overflowY: 'auto' }}>
          {rows.map((c) => (
            <li key={c.id} role="option" aria-selected="false">
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => { onPick(c); setQ(''); setOpen(false) }}
                style={{ width: '100%', textAlign: 'left', border: 'none', background: 'none', padding: '9px 10px', borderRadius: 8, cursor: 'pointer', fontFamily: ds.fontDm, minHeight: 44 }}>
                <div style={{ fontWeight: 600, color: ds.dark }}>{c.full_name || 'No name'}</div>
                <div style={{ fontSize: 12.5, color: ds.gray }}>{[c.whatsapp || c.phone, c.email].filter(Boolean).join(' · ')}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ProductPicker({ onPick }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [rows, setRows] = useState(null)
  const dq = useDebounced(q)
  useEffect(() => {
    if (!open) return undefined
    let live = true
    pickProducts(dq.trim()).then((r) => { if (live) setRows(r || []) }).catch(() => { if (live) setRows([]) })
    return () => { live = false }
  }, [dq, open])
  if (!open) return <button type="button" style={btnG} onClick={() => setOpen(true)}><Package size={16} />Add from catalogue</button>
  return (
    <div style={{ width: '100%', border: `1px solid ${ds.border}`, borderRadius: 12, padding: 10, background: ds.light }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <input style={inp} autoFocus placeholder="Search your products" aria-label="Search your products" value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="button" style={btnG} onClick={() => { setOpen(false); setQ('') }}>Done</button>
      </div>
      <div style={{ maxHeight: 220, overflowY: 'auto', marginTop: 8 }}>
        {rows === null && <p style={{ color: ds.gray, fontSize: 14, margin: 6 }}>Loading…</p>}
        {rows && rows.length === 0 && <p style={{ color: ds.gray, fontSize: 14, margin: 6 }}>No products found. Type the line yourself with Add line.</p>}
        {rows && rows.map((p) => (
          <button key={p.id} type="button" onClick={() => onPick(p)}
            style={{ display: 'flex', width: '100%', gap: 10, alignItems: 'center', border: 'none', background: '#fff', borderRadius: 8, padding: '8px 10px', marginBottom: 4, cursor: 'pointer', fontFamily: ds.fontDm, minHeight: 44, textAlign: 'left' }}>
            <span style={{ flex: 1, color: ds.dark, fontWeight: 600 }}>{p.title}</span>
            <span style={{ color: ds.gray }}>{p.sizes?.length > 1 ? `${p.sizes.length} sizes` : (p.price != null ? naira(p.price) : 'No price')}</span>
            <Plus size={16} color={ds.teal} />
          </button>
        ))}
      </div>
    </div>
  )
}

// ───────────────────────────── issued (read-only) ─────────────────────────────

function IssuedView({ doc, isAdmin, onPaid }) {
  const kind = doc.doc_type
  return (
    <div style={{ display: 'grid', gap: 16, fontSize: 14 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
        <div><div style={lab}>{kind === 'quote' ? 'Quote for' : 'Bill to'}</div>
          <div style={{ fontWeight: 700, color: ds.dark }}>{doc.customer_name}</div>
          {[doc.customer_phone, doc.customer_email, doc.customer_address].filter(Boolean).map((t) => <div key={t} style={{ color: ds.gray }}>{t}</div>)}
        </div>
        <div><div style={lab}>Date</div><div>{niceDate(doc.issue_date)}</div></div>
        <div><div style={lab}>{kind === 'quote' ? 'Valid until' : 'Due date'}</div><div>{niceDate(doc.due_date)}</div></div>
        {doc.region && <div><div style={lab}>Region</div><div>{doc.region}</div></div>}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ textAlign: 'left', ...lab }}><th style={{ padding: 6 }}>Description</th><th style={{ padding: 6, textAlign: 'right' }}>Qty</th><th style={{ padding: 6, textAlign: 'right' }}>Unit price</th><th style={{ padding: 6, textAlign: 'right' }}>Amount</th></tr></thead>
        <tbody>
          {(doc.items || []).map((it) => (
            <tr key={it.id} style={{ borderTop: `1px solid ${ds.border}` }}>
              <td style={{ padding: 6 }}>{it.description}</td>
              <td style={{ padding: 6, textAlign: 'right' }}>{Number(it.quantity)}</td>
              <td style={{ padding: 6, textAlign: 'right', whiteSpace: 'nowrap' }}>{naira(it.unit_price)}</td>
              <td style={{ padding: 6, textAlign: 'right', whiteSpace: 'nowrap' }}>{naira(it.line_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginLeft: 'auto', minWidth: 260, display: 'grid', gap: 6 }}>
        <Row k="Subtotal" v={naira(doc.subtotal)} />
        {Number(doc.discount) > 0 && <Row k="Discount" v={`-${naira(doc.discount)}`} />}
        {Number(doc.vat_amount) > 0 && <Row k={`VAT (${Number(doc.vat_rate)}%)`} v={naira(doc.vat_amount)} />}
        <div style={{ borderTop: `2px solid ${ds.teal}`, paddingTop: 6 }}><Row k={<b>Total</b>} v={<b>{naira(doc.total)}</b>} /></div>
        {kind === 'invoice' && Number(doc.amount_paid) > 0 && <><Row k="Paid" v={naira(doc.amount_paid)} /><Row k={<b>Balance due</b>} v={<b>{naira(doc.balance_due)}</b>} /></>}
      </div>
      {doc.notes && <div><div style={lab}>Note</div><div style={{ whiteSpace: 'pre-wrap' }}>{doc.notes}</div></div>}
      {doc.terms && <div><div style={lab}>Terms</div><div style={{ whiteSpace: 'pre-wrap' }}>{doc.terms}</div></div>}
      {doc.status === 'void' && <div style={{ background: '#F3F4F6', borderRadius: 10, padding: 12, color: ds.gray }}>Voided {niceDate(doc.voided_at)}{doc.void_reason ? `: ${doc.void_reason}` : ''}</div>}
      {doc.converted_from_id && <div style={{ color: ds.gray, fontSize: 13 }}>Made from a quote.</div>}
      {kind === 'invoice' && <PaymentsPanel doc={doc} isAdmin={isAdmin} onChanged={onPaid} />}
      {kind === 'invoice' && doc.stock_tracked && <StockPanel doc={doc} onChanged={onPaid} />}
      {doc.status !== 'void' && <SendPanel doc={doc} />}
      <p style={{ color: ds.gray, fontSize: 13, margin: 0 }}>Issued documents can't be changed. To fix a mistake, void it and make a new one.</p>
    </div>
  )
}

// INV-5: suggest lines from this customer's WhatsApp / web chat. Nothing is saved until the person saves the draft.
function FillFromChat({ leadId, onLines }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const go = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await aiDraftLines(leadId)
      const lines = r?.lines || []
      if (lines.length) onLines(lines)
      const blanks = lines.filter((l) => l.unit_price == null).length
      setMsg({ ok: lines.length > 0, text: lines.length
        ? `Added ${lines.length} line${lines.length === 1 ? '' : 's'} from the chat. Check them before you issue.${blanks ? ` ${blanks} need a price.` : ''}${r.note ? ` ${r.note}` : ''}`
        : (r?.note || 'Nothing in the chat looks like an agreed order.') })
    } catch (e) { setMsg({ ok: false, text: apiError(e, 'Could not read the chat. Please add the lines yourself.') }) } finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <button type="button" style={disabled(btnG, busy)} disabled={busy} onClick={go}><Sparkles size={16} />{busy ? 'Reading the chat…' : 'Fill from chat'}</button>
      {msg && <small role="status" style={{ color: msg.ok ? ds.gray : ds.red, maxWidth: 360 }}>{msg.text}</small>}
    </div>
  )
}
