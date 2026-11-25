/**
 * frontend/src/modules/sales/SaleForm.jsx
 * SALE-1 — Make a sale: customer, where the goods come from, products, and what the customer paid. Saving makes the
 * invoice, issues it (holding the stock), records the payment and, if the customer took the goods, marks them
 * delivered. When the business wants payments confirmed, a rep's payment waits for an admin instead.
 * Not enough stock -> the same "take it from another location / ask an admin" dialog as the invoice editor.
 */
import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock, Minus, Plus, ShoppingCart, Trash2, X } from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  makeSale, finishSale, getStockCheck, issueDoc, requestStock, getInvoiceSettings, apiError, errorCode, errorData,
} from '../../services/invoices.service'
import { naira, METHOD_LABEL, card, lab, inp, btnP, btnG, disabled, todayYmd } from '../invoices/invoiceUi'
import { ContactSearch, ProductPicker } from '../invoices/InvoiceEditor'
import RegionSelect from '../invoices/RegionSelect'
import { useRegions, lastRegion } from '../invoices/useRegions'
import { useStock, startLocation, rememberLocation, useAvailability } from '../invoices/useStock'
import ShortStockDialog from '../invoices/ShortStockDialog'

const MANUAL = ['bank_transfer', 'cash', 'pos', 'ussd', 'other']
const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) ? n : 0 }
const blank = () => ({ lead_id: null, customer_name: '', customer_phone: '', region: '', location_id: '', items: [], discount: '',
  pay: 'paid', amount: '', method: 'bank_transfer', reference: '', paid_at: todayYmd(), delivered: false })

export default function SaleForm({ onOpenInvoice, onSaved }) {
  const regions = useRegions()
  const stock = useStock()
  const [f, setF] = useState(blank)
  const [vat, setVat] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [short, setShort] = useState(null)   // { check, docId }
  const [done, setDone] = useState(null)
  const set = (patch) => setF((x) => ({ ...x, ...patch }))

  useEffect(() => {
    getInvoiceSettings().then((s) => setVat(s?.vat_enabled ? Number(s.vat_rate || 0) : 0)).catch(() => setVat(0))
  }, [])
  useEffect(() => { if (regions.length) setF((x) => (x.region ? x : { ...x, region: lastRegion(regions) })) }, [regions])
  useEffect(() => {
    if (stock.locations.length) setF((x) => (x.location_id ? x : { ...x, location_id: startLocation(stock.locations, x.region) }))
  }, [stock.locations])

  const left = useAvailability(stock.enabled, f.location_id, f.items.map((l) => l.product_id))
  const leftFor = (l) => (left ? (left[l.product_id]?.[l.sizes?.length ? l.variant : ''] ?? 0) : null)

  const totals = useMemo(() => {
    const sub = f.items.reduce((s, l) => s + num(l.unit_price) * num(l.quantity), 0)
    const net = Math.max(0, sub - num(f.discount))
    const tax = Math.round(net * vat) / 100
    return { sub, tax, total: net + tax }
  }, [f.items, f.discount, vat])

  const addLine = (p) => {
    const sizes = p.sizes || []
    const only = sizes.length === 1 ? sizes[0] : null
    set({ items: [...f.items, { key: `${p.id}-${Date.now()}`, product_id: p.id, description: p.title, sizes, quantity: 1,
      variant: only ? only.title : '', unit_price: only && only.price != null ? only.price : (sizes.length ? '' : (p.price ?? '')) }] })
  }
  const setLine = (i, patch) => set({ items: f.items.map((l, n) => (n === i ? { ...l, ...patch } : l)) })
  const pickSize = (i, title) => {
    const size = (f.items[i].sizes || []).find((s) => s.title === title)
    setLine(i, { variant: title, ...(size && size.price != null ? { unit_price: size.price } : {}) })
  }

  const problem = () => {
    if (!f.customer_name.trim()) return "Add the customer's name."
    if (!f.items.length) return 'Add at least one product.'
    const noSize = f.items.find((l) => l.sizes?.length && !l.variant)
    if (noSize) return `Choose the size for ${noSize.description}.`
    if (f.items.some((l) => num(l.quantity) < 1 || !Number.isInteger(num(l.quantity)))) return 'Quantities must be whole numbers.'
    if (totals.total <= 0) return 'The total must be more than ₦0.'
    if (regions.length && !f.region) return 'Choose the region.'
    if (!f.location_id) return 'Choose where the goods come from.'
    if (f.pay === 'part' && (num(f.amount) <= 0 || num(f.amount) >= totals.total)) return 'Enter what the customer paid, less than the total.'
    return ''
  }

  const payment = () => (f.pay === 'unpaid' ? { status: 'unpaid' } : {
    status: f.pay, method: f.method, paid_at: f.paid_at || null, reference: f.reference.trim() || null,
    ...(f.pay === 'part' ? { amount: String(num(f.amount)) } : {}),
  })

  const finished = (out) => { setDone(out); setShort(null); setF(blank()); onSaved?.() }

  const save = async () => {
    const p = problem()
    if (p) { setErr(p); return }
    setBusy(true); setErr('')
    rememberLocation(f.location_id)
    try {
      finished(await makeSale({
        ...(f.lead_id ? { lead_id: f.lead_id } : {}), customer_name: f.customer_name.trim(),
        ...(f.customer_phone.trim() ? { customer_phone: f.customer_phone.trim() } : {}),
        location_id: f.location_id, ...(f.region ? { region: f.region } : {}),
        ...(num(f.discount) > 0 ? { discount: String(num(f.discount)) } : {}),
        items: f.items.map((l) => ({ product_id: l.product_id, quantity: String(num(l.quantity)),
          ...(l.unit_price !== '' ? { unit_price: String(num(l.unit_price)) } : {}), ...(l.variant ? { variant: l.variant } : {}) })),
        payment: payment(), delivered: f.pay === 'paid' && f.delivered,
      }))
    } catch (e) {
      const docId = errorData(e)?.doc_id
      if (errorCode(e) === 'STOCK_SHORT' && docId) {
        try {
          const check = await getStockCheck(docId)
          if (check?.short) setShort({ check, docId }); else setErr(apiError(e))
        } catch { setErr(apiError(e)) }
      } else setErr(apiError(e, 'Could not save the sale. Please try again.'))
    } finally { setBusy(false) }
  }

  const issueFrom = async (sources) => {
    setBusy(true); setErr('')
    try {
      await issueDoc(short.docId, sources)
      finished(await finishSale(short.docId, { payment: payment(), delivered: f.pay === 'paid' && f.delivered }))
    } catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }
  const requestFrom = async (sources, note) => {
    setBusy(true); setErr('')
    try {
      const d = await requestStock(short.docId, sources, note || null)
      finished({ invoice: d, receipt: null, pending_payment: null, delivered: false, stock_request: true })
    } catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }

  if (done) return <Done out={done} onOpen={() => onOpenInvoice(done.invoice.id)} onAgain={() => setDone(null)} />

  if (stock.ready && !stock.enabled) {
    return (
      <div style={{ ...card, color: ds.gray }}>
        Make a sale takes the goods from your stock. Turn stock on in Inventory &gt; Settings and add your locations first.
        Until then, make an invoice in Invoices.
      </div>
    )
  }

  const radio = (value, label) => (
    <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', border: `1.5px solid ${f.pay === value ? ds.teal : ds.border}`,
      background: f.pay === value ? ds.mint : '#fff', borderRadius: ds.radius.md, padding: '0 14px', minHeight: 42, color: ds.dark, fontWeight: 600, fontSize: 14 }}>
      <input type="radio" name="sale-pay" checked={f.pay === value} onChange={() => set({ pay: value, ...(value !== 'paid' ? { delivered: false } : {}) })} />
      {label}
    </label>
  )

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <section style={{ ...card, display: 'grid', gap: 12 }}>
        <b style={{ color: ds.dark }}>Customer</b>
        <ContactSearch onPick={(c) => set({ lead_id: c.id, customer_name: c.full_name || '', customer_phone: c.whatsapp || c.phone || '' })} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          <div><label style={lab} htmlFor="sale-name">Name</label>
            <input id="sale-name" style={inp} maxLength={200} value={f.customer_name} onChange={(e) => set({ customer_name: e.target.value, lead_id: null })} /></div>
          <div><label style={lab} htmlFor="sale-phone">Phone (optional)</label>
            <input id="sale-phone" style={inp} maxLength={30} inputMode="tel" value={f.customer_phone} onChange={(e) => set({ customer_phone: e.target.value })} /></div>
          <RegionSelect id="sale-region" regions={regions} value={f.region} onChange={(v) => set({ region: v })} />
          <div><label style={lab} htmlFor="sale-loc">Goods come from</label>
            <select id="sale-loc" style={inp} value={f.location_id} onChange={(e) => set({ location_id: e.target.value })}>
              <option value="">Choose a location</option>
              {stock.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select></div>
        </div>
        {f.lead_id && <small style={{ color: ds.gray }}>Linked to the contact in Opsra. Change the name to type a new customer instead.</small>}
      </section>

      <section style={{ ...card, display: 'grid', gap: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><ShoppingCart size={16} color={ds.tealDark} /><b style={{ color: ds.dark }}>Products</b></div>
        {f.items.length === 0 && <div style={{ color: ds.gray, fontSize: 14 }}>No products yet. Add what the customer is buying.</div>}
        {f.items.map((l, i) => {
          const have = l.sizes?.length && !l.variant ? null : leftFor(l)
          const over = have !== null && num(l.quantity) > have
          return (
            <div key={l.key} style={{ borderTop: i ? `1px solid ${ds.border}` : 'none', paddingTop: i ? 10 : 0, display: 'grid', gap: 8 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <b style={{ color: ds.dark, flex: '1 1 160px' }}>{l.description}</b>
                {l.sizes?.length > 0 && (
                  <select aria-label={`Size of ${l.description}`} style={{ ...inp, width: 'auto', minWidth: 130 }} value={l.variant} onChange={(e) => pickSize(i, e.target.value)}>
                    <option value="">Choose size</option>
                    {l.sizes.map((s) => <option key={s.title} value={s.title}>{s.title}</option>)}
                  </select>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <button type="button" aria-label="One less" style={{ ...btnG, padding: '0 10px' }} onClick={() => setLine(i, { quantity: Math.max(1, num(l.quantity) - 1) })}><Minus size={14} /></button>
                  <input aria-label={`Quantity of ${l.description}`} style={{ ...inp, width: 60, textAlign: 'center' }} inputMode="numeric" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} />
                  <button type="button" aria-label="One more" style={{ ...btnG, padding: '0 10px' }} onClick={() => setLine(i, { quantity: num(l.quantity) + 1 })}><Plus size={14} /></button>
                </div>
                <input aria-label={`Price of ${l.description}`} style={{ ...inp, width: 130 }} inputMode="decimal" placeholder="Price" value={l.unit_price} onChange={(e) => setLine(i, { unit_price: e.target.value })} />
                <b style={{ minWidth: 110, textAlign: 'right', color: ds.dark }}>{naira(num(l.unit_price) * num(l.quantity))}</b>
                <button type="button" aria-label={`Remove ${l.description}`} style={{ ...btnG, padding: '0 10px', color: ds.red }} onClick={() => set({ items: f.items.filter((_, n) => n !== i) })}><Trash2 size={15} /></button>
              </div>
              {have !== null && <small style={{ color: over ? ds.red : ds.gray }}>{over ? `Only ${have} left here. Saving will offer another location.` : `${have} left here`}</small>}
            </div>
          )
        })}
        <div><ProductPicker onPick={addLine} /></div>
        <div style={{ display: 'grid', gap: 4, justifyContent: 'end', textAlign: 'right', fontSize: 14, color: ds.gray }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'flex-end' }}>
            <label htmlFor="sale-disc">Discount (₦)</label>
            <input id="sale-disc" style={{ ...inp, width: 130 }} inputMode="decimal" value={f.discount} onChange={(e) => set({ discount: e.target.value })} />
          </div>
          {totals.tax > 0 && <span>VAT {naira(totals.tax)}</span>}
          <b style={{ fontSize: 18, color: ds.dark }}>Total {naira(totals.total)}</b>
        </div>
      </section>

      <section style={{ ...card, display: 'grid', gap: 12 }}>
        <b style={{ color: ds.dark }}>Payment</b>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }} role="radiogroup" aria-label="Did the customer pay?">
          {radio('paid', 'Paid in full')}{radio('part', 'Part paid')}{radio('unpaid', 'Not paid yet')}
        </div>
        {f.pay !== 'unpaid' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
            {f.pay === 'part' && <div><label style={lab} htmlFor="sale-amt">Amount paid (₦)</label>
              <input id="sale-amt" style={inp} inputMode="decimal" value={f.amount} onChange={(e) => set({ amount: e.target.value })} />
              <small style={{ color: ds.gray }}>Balance after: {naira(Math.max(0, totals.total - num(f.amount)))}</small></div>}
            <div><label style={lab} htmlFor="sale-method">How they paid</label>
              <select id="sale-method" style={inp} value={f.method} onChange={(e) => set({ method: e.target.value })}>
                {MANUAL.map((m) => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
              </select></div>
            <div><label style={lab} htmlFor="sale-date">Date paid</label>
              <input id="sale-date" type="date" style={inp} max={todayYmd()} value={f.paid_at} onChange={(e) => set({ paid_at: e.target.value })} /></div>
            <div><label style={lab} htmlFor="sale-ref">Reference (optional)</label>
              <input id="sale-ref" style={inp} maxLength={200} placeholder="e.g. transfer reference" value={f.reference} onChange={(e) => set({ reference: e.target.value })} /></div>
          </div>
        )}
        {f.pay === 'paid' && (
          <label style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: 'pointer', color: ds.dark }}>
            <input type="checkbox" checked={f.delivered} onChange={(e) => set({ delivered: e.target.checked })} style={{ width: 18, height: 18 }} />
            The customer took the goods now
          </label>
        )}
      </section>

      {err && <div role="alert" style={{ color: ds.red, fontSize: 14 }}>{err}</div>}
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button type="button" style={btnG} disabled={busy} onClick={() => { setF(blank()); setErr('') }}><X size={16} />Clear</button>
        <button type="button" style={disabled(btnP, busy)} disabled={busy} onClick={save}>{busy ? 'Saving…' : `Record sale · ${naira(totals.total)}`}</button>
      </div>

      {short && <ShortStockDialog check={short.check} busy={busy} error={err} onIssue={issueFrom} onRequest={requestFrom}
        onClose={() => { setShort(null); setErr('') }} />}
    </div>
  )
}

function Done({ out, onOpen, onAgain }) {
  const d = out.invoice || {}
  const lines = []
  if (out.stock_request) lines.push('Sent to an admin to approve taking the goods from another location. They are held for this customer. Once approved, open the invoice from My sales to record the payment.')
  else {
    lines.push(`Invoice ${d.number || ''} made for ${d.customer_name || 'the customer'} (${naira(d.total)}).`)
    if (out.receipt) lines.push(`Receipt ${out.receipt.number} made for ${naira(out.receipt.amount)}.`)
    if (out.pending_payment) lines.push(`The payment of ${naira(out.pending_payment.amount)} is waiting for an admin to confirm it. The receipt is made once they approve.`)
    if (out.delivered) lines.push('The goods are marked delivered.')
    else if (out.pending_payment?.deliver) lines.push('The goods are marked delivered when the payment is approved.')
  }
  const waiting = out.stock_request || out.pending_payment
  return (
    <div style={{ ...card, display: 'grid', gap: 12, justifyItems: 'start' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        {waiting ? <Clock size={22} color="#C05A00" /> : <CheckCircle2 size={22} color={ds.green} />}
        <b style={{ fontSize: 17, color: ds.dark }}>{waiting ? 'Sale saved, waiting for an admin' : 'Sale recorded'}</b>
      </div>
      {lines.map((t) => <div key={t} style={{ color: ds.dark, fontSize: 14.5 }}>{t}</div>)}
      {!out.stock_request && <small style={{ color: ds.gray }}>Open the invoice to send it{out.receipt ? ' and the receipt' : ''} to the customer.</small>}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" style={btnG} onClick={onOpen}>Open invoice</button>
        <button type="button" style={btnP} onClick={onAgain}><Plus size={16} />Make another sale</button>
      </div>
    </div>
  )
}
