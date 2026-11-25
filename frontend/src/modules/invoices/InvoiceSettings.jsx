/**
 * frontend/src/modules/invoices/InvoiceSettings.jsx
 * INV-2 — what prints on the business's quotes, invoices and receipts (admin only; the server checks again).
 * Changes apply to documents issued from now on; issued ones keep the details they were issued with.
 */
import { useEffect, useRef, useState } from 'react'
import { Upload, Trash2 } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getInvoiceSettings, saveInvoiceSettings, uploadInvoiceLogo, removeInvoiceLogo, apiError } from '../../services/invoices.service'
import { card, lab, inp, btnP, btnG, disabled } from './invoiceUi'

const TEXT = ['business_name', 'address', 'phone', 'email', 'rc_number', 'tin', 'bank_name', 'account_name', 'account_number',
  'quote_prefix', 'invoice_prefix', 'receipt_prefix', 'default_terms', 'footer', 'email_reply_to']

export default function InvoiceSettings() {
  const isMobile = useIsMobile()
  const [s, setS] = useState(null)
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)   // { ok: bool, text }
  const fileRef = useRef(null)

  const adopt = (d) => {
    setS(d)
    const f = {}
    TEXT.forEach((k) => { f[k] = d[k] ?? '' })
    setForm({ ...f, vat_enabled: !!d.vat_enabled, vat_rate: String(d.vat_rate ?? 7.5), default_due_days: String(d.default_due_days ?? 7),
      default_quote_valid_days: String(d.default_quote_valid_days ?? 14), brand_colour: d.brand_colour || '#0d9488',
      reminders_enabled: !!d.reminders_enabled })
  }
  useEffect(() => { getInvoiceSettings().then(adopt).catch((e) => setMsg({ ok: false, text: apiError(e) })) }, [])

  if (!form) return <p style={{ color: msg ? ds.red : ds.gray }}>{msg?.text || 'Loading…'}</p>
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  const save = async () => {
    setBusy('save'); setMsg(null)
    const body = {}
    TEXT.forEach((k) => { body[k] = form[k].trim() ? form[k].trim() : null })
    ;['quote_prefix', 'invoice_prefix', 'receipt_prefix'].forEach((k) => { body[k] = form[k].trim() })
    body.vat_enabled = form.vat_enabled
    body.vat_rate = String(parseFloat(form.vat_rate) || 0)
    body.default_due_days = parseInt(form.default_due_days, 10) || 0
    body.default_quote_valid_days = parseInt(form.default_quote_valid_days, 10) || 14
    body.brand_colour = form.brand_colour
    body.reminders_enabled = !!form.reminders_enabled
    try { adopt(await saveInvoiceSettings(body)); setMsg({ ok: true, text: 'Saved. New documents will use these details.' }) }
    catch (e) { setMsg({ ok: false, text: apiError(e, 'Could not save. Check the details and try again.') }) }
    finally { setBusy('') }
  }
  const onLogo = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.size > 2 * 1024 * 1024) { setMsg({ ok: false, text: 'The logo must be under 2 MB.' }); return }
    setBusy('logo'); setMsg(null)
    try { adopt(await uploadInvoiceLogo(file)); setMsg({ ok: true, text: 'Logo saved.' }) }
    catch (err) { setMsg({ ok: false, text: apiError(err, 'Could not save the logo. Try a PNG or JPG.') }) }
    finally { setBusy('') }
  }
  const dropLogo = async () => {
    setBusy('logo')
    try { adopt(await removeInvoiceLogo()) } catch (err) { setMsg({ ok: false, text: apiError(err) }) } finally { setBusy('') }
  }

  const grid = { display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 12 }
  const field = (k, label, extra = {}) => (
    <div><label style={lab} htmlFor={`is-${k}`}>{label}</label><input id={`is-${k}`} style={inp} value={form[k]} onChange={set(k)} {...extra} /></div>
  )
  const h = { fontSize: 15, margin: '0 0 12px', color: ds.dark }

  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 860 }}>
      <section style={card}>
        <h3 style={h}>Business details</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ width: 120, height: 64, border: `1px dashed ${ds.border}`, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: ds.light, overflow: 'hidden' }}>
            {s.logo_url ? <img src={s.logo_url} alt="Your logo" style={{ maxWidth: '100%', maxHeight: '100%' }} /> : <span style={{ fontSize: 12.5, color: ds.gray }}>No logo</span>}
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={onLogo} />
          <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => fileRef.current?.click()}><Upload size={16} />{busy === 'logo' ? 'Uploading…' : s.logo_url ? 'Change logo' : 'Upload logo'}</button>
          {s.logo_url && <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={dropLogo}><Trash2 size={16} />Remove</button>}
          <small style={{ color: ds.gray }}>PNG, JPG or WebP, under 2 MB</small>
        </div>
        <div style={grid}>
          {field('business_name', 'Business name', { maxLength: 200 })}
          {field('phone', 'Phone', { maxLength: 30, inputMode: 'tel' })}
          {field('email', 'Email', { maxLength: 254, type: 'email' })}
          {field('address', 'Address', { maxLength: 500 })}
          {field('rc_number', 'RC / BN number', { maxLength: 50 })}
          {field('tin', 'TIN', { maxLength: 50 })}
        </div>
      </section>

      <section style={card}>
        <h3 style={h}>Bank details (printed on invoices)</h3>
        <div style={grid}>
          {field('bank_name', 'Bank', { maxLength: 100 })}
          {field('account_number', 'Account number', { maxLength: 20, inputMode: 'numeric' })}
          {field('account_name', 'Account name', { maxLength: 200 })}
        </div>
      </section>

      <section style={card}>
        <h3 style={h}>Numbers, dates and tax</h3>
        <div style={grid}>
          {field('invoice_prefix', 'Invoice number starts with', { maxLength: 10 })}
          {field('quote_prefix', 'Quote number starts with', { maxLength: 10 })}
          {field('receipt_prefix', 'Receipt number starts with', { maxLength: 10 })}
          {field('default_due_days', 'Invoices are due after (days)', { inputMode: 'numeric' })}
          {field('default_quote_valid_days', 'Quotes are valid for (days)', { inputMode: 'numeric' })}
          <div>
            <span style={lab}>VAT</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', minHeight: 42 }}>
                <input type="checkbox" checked={form.vat_enabled} onChange={set('vat_enabled')} style={{ width: 18, height: 18 }} />Add VAT by default
              </label>
              <input aria-label="VAT rate in percent" style={{ ...inp, width: 90 }} inputMode="decimal" value={form.vat_rate} onChange={set('vat_rate')} /><span>%</span>
            </div>
          </div>
        </div>
        <small style={{ color: ds.gray, display: 'block', marginTop: 8 }}>Example: {form.invoice_prefix || ''}0001. Numbers already given out never change.</small>
      </section>

      <section style={card}>
        <h3 style={h}>Wording and look</h3>
        <div style={{ display: 'grid', gap: 12 }}>
          <div><label style={lab} htmlFor="is-terms">Default terms</label><textarea id="is-terms" rows={3} maxLength={5000} style={{ ...inp, resize: 'vertical' }} value={form.default_terms} onChange={set('default_terms')} /></div>
          <div style={grid}>
            {field('footer', 'Footer line', { maxLength: 300, placeholder: 'Thank you for your business' })}
            {field('email_reply_to', 'Customers reply to (email)', { maxLength: 254, type: 'email' })}
            <div><label style={lab} htmlFor="is-col">Colour</label>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <input id="is-col" type="color" value={form.brand_colour} onChange={set('brand_colour')} style={{ width: 52, height: 42, border: `1.5px solid ${ds.border}`, borderRadius: 8, padding: 2, background: '#fff' }} />
                <span style={{ color: ds.gray }}>{form.brand_colour}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section style={card}>
        <h3 style={h}>Reminders</h3>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', color: ds.dark }}>
          <input type="checkbox" checked={!!form.reminders_enabled} onChange={set('reminders_enabled')} style={{ width: 18, height: 18, marginTop: 2 }} />
          <span>Remind customers about overdue invoices
            <small style={{ display: 'block', color: ds.gray, marginTop: 4 }}>
              At 10am, 1, 7 and 14 days after the due date, the customer gets the invoice again with a link to pay. It goes by
              WhatsApp if they messaged you in the last 24 hours, otherwise by email. If neither works, the person who made
              the invoice gets a task to chase it. Paid and void invoices are never reminded.
            </small>
          </span>
        </label>
        <small style={{ display: 'block', color: ds.gray, marginTop: 10 }}>When a quote passes its date without an answer, the person who made it always gets a task to follow up.</small>
      </section>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" style={disabled(btnP, !!busy)} disabled={!!busy} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save settings'}</button>
        {msg && <span role="status" style={{ color: msg.ok ? ds.green : ds.red, fontSize: 14 }}>{msg.text}</span>}
      </div>
    </div>
  )
}
