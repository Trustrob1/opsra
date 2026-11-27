/**
 * frontend/src/modules/invoices/InvoiceSettings.jsx
 * INV-2 — what prints on the business's quotes, invoices and receipts (admin only; the server checks again).
 * Changes apply to documents issued from now on; issued ones keep the details they were issued with.
 * REPORT-1 — which reps' payments wait, who else may confirm them, and the emailed reports (daily sales, weekly).
 * BANK-1 — several bank accounts; each can be linked to a region (picked automatically on invoices) and one is the default.
 * REVISE-1 — a region can have several accounts; each sales rep can have a home region (their invoices use it and they
 *   choose only from that region's accounts).
 */
import { useEffect, useRef, useState } from 'react'
import { Upload, Trash2 } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getInvoiceSettings, saveInvoiceSettings, uploadInvoiceLogo, removeInvoiceLogo, apiError, getSettingsPeople,
  sendTestReport, saveRepRegions } from '../../services/invoices.service'
import { card, lab, inp, btnP, btnG, disabled } from './invoiceUi'
import { useRegions } from './useRegions'   // BANK-1

const TEXT = ['business_name', 'address', 'phone', 'email', 'rc_number', 'tin',
  'quote_prefix', 'invoice_prefix', 'receipt_prefix', 'default_terms', 'footer', 'email_reply_to']

export default function InvoiceSettings() {
  const isMobile = useIsMobile()
  const [s, setS] = useState(null)
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)   // { ok: bool, text }
  const fileRef = useRef(null)
  const [people, setPeople] = useState([])   // REPORT-1
  const regions = useRegions()   // BANK-1

  const adopt = (d) => {
    setS(d)
    const f = {}
    TEXT.forEach((k) => { f[k] = d[k] ?? '' })
    setForm({ ...f, vat_enabled: !!d.vat_enabled, vat_rate: String(d.vat_rate ?? 7.5), default_due_days: String(d.default_due_days ?? 7),
      default_quote_valid_days: String(d.default_quote_valid_days ?? 14), brand_colour: d.brand_colour || '#0d9488',
      reminders_enabled: !!d.reminders_enabled, sales_record_enabled: !!d.sales_record_enabled,
      payments_need_approval: !!d.payments_need_approval,   // SALE-1
      payment_confirm_reps: d.payment_confirm_reps || [], payment_confirmers: d.payment_confirmers || [],   // REPORT-1
      report_emails: (d.report_emails || []).join(', '), daily_sales_report: !!d.daily_sales_report, weekly_reports: !!d.weekly_reports,
      bank_accounts: (d.bank_accounts || []).map((a) => ({ id: a.id, label: a.label || '', bank_name: a.bank_name || '',
        account_name: a.account_name || '', account_number: a.account_number || '', region: a.region || '', is_default: !!a.is_default })) })
  }
  useEffect(() => { getInvoiceSettings().then(adopt).catch((e) => setMsg({ ok: false, text: apiError(e) })) }, [])
  useEffect(() => { getSettingsPeople().then((p) => setPeople(p || [])).catch(() => setPeople([])) }, [])

  if (!form) return <p style={{ color: msg ? ds.red : ds.gray }}>{msg?.text || 'Loading…'}</p>
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const toggleIn = (k, id) => setForm((f) => ({ ...f, [k]: f[k].includes(id) ? f[k].filter((x) => x !== id) : [...f[k], id] }))
  const reps = people.filter((p) => !p.manager)
  // BANK-1: bank account rows
  const setAcct = (i, patch) => setForm((f) => ({ ...f, bank_accounts: f.bank_accounts.map((a, j) => (j === i ? { ...a, ...patch }
    : patch.is_default ? { ...a, is_default: false } : patch.region && a.region === patch.region ? { ...a, region: '' } : a)) }))
  const addAcct = () => setForm((f) => ({ ...f, bank_accounts: [...f.bank_accounts,
    { id: '', label: '', bank_name: '', account_name: '', account_number: '', region: '', is_default: f.bank_accounts.length === 0 }] }))
  const dropAcct = (i) => setForm((f) => {
    const left = f.bank_accounts.filter((_, j) => j !== i)
    if (left.length && !left.some((a) => a.is_default)) left[0] = { ...left[0], is_default: true }
    return { ...f, bank_accounts: left }
  })
  const sendTest = async (kind) => {
    setBusy(kind); setMsg(null)
    try {
      const r = await sendTestReport(kind)
      setMsg({ ok: true, text: `Sent to ${r.sent_to.join(', ')}.` })
    } catch (e) { setMsg({ ok: false, text: apiError(e, 'The email did not go out. Please try again.') }) }
    finally { setBusy('') }
  }

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
    body.sales_record_enabled = !!form.sales_record_enabled
    body.payments_need_approval = !!form.payments_need_approval   // SALE-1
    body.payment_confirm_reps = form.payment_confirm_reps   // REPORT-1
    body.payment_confirmers = form.payment_confirmers
    body.report_emails = form.report_emails.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean)
    body.daily_sales_report = !!form.daily_sales_report
    body.weekly_reports = !!form.weekly_reports
    const accts = form.bank_accounts.filter((a) => a.bank_name.trim() || a.account_number.trim() || a.account_name.trim())   // BANK-1
    const bad = accts.find((a) => !a.bank_name.trim() || !/^[0-9]{6,20}$/.test(a.account_number.replace(/\s+/g, '')))
    if (bad) { setBusy(''); setMsg({ ok: false, text: 'Each bank account needs the bank name and an account number of 6 to 20 digits.' }); return }
    body.bank_accounts = accts.map((a) => ({ ...(a.id ? { id: a.id } : {}), label: a.label.trim() || null, bank_name: a.bank_name.trim(),
      account_name: a.account_name.trim() || null, account_number: a.account_number.replace(/\s+/g, ''), region: a.region || null,
      is_default: !!a.is_default }))
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
        <h3 style={h}>Bank accounts (printed on invoices)</h3>
        <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 12px' }}>
          {regions.length ? 'Link accounts to a region (a region can have several). Invoices for that region show its first account automatically; sales reps can choose only between that region\'s accounts, while admins and managers can choose any. The default is used when no account matches.'
            : 'Add each account customers can pay into. The person making an invoice chooses which one it shows; the default is picked first.'}
        </p>
        <div style={{ display: 'grid', gap: 12 }}>
          {form.bank_accounts.map((a, i) => (
            <div key={i} style={{ border: `1px solid ${ds.border}`, borderRadius: 10, padding: 12, display: 'grid', gap: 10 }}>
              <div style={grid}>
                <div><label style={lab} htmlFor={`ba-label-${i}`}>Name for this account</label>
                  <input id={`ba-label-${i}`} style={inp} maxLength={60} placeholder="For example: Lagos account" value={a.label} onChange={(e) => setAcct(i, { label: e.target.value })} /></div>
                <div><label style={lab} htmlFor={`ba-bank-${i}`}>Bank</label>
                  <input id={`ba-bank-${i}`} style={inp} maxLength={100} value={a.bank_name} onChange={(e) => setAcct(i, { bank_name: e.target.value })} /></div>
                <div><label style={lab} htmlFor={`ba-no-${i}`}>Account number</label>
                  <input id={`ba-no-${i}`} style={inp} maxLength={20} inputMode="numeric" value={a.account_number} onChange={(e) => setAcct(i, { account_number: e.target.value })} /></div>
                <div><label style={lab} htmlFor={`ba-name-${i}`}>Account name</label>
                  <input id={`ba-name-${i}`} style={inp} maxLength={200} value={a.account_name} onChange={(e) => setAcct(i, { account_name: e.target.value })} /></div>
                {regions.length > 0 && (
                  <div><label style={lab} htmlFor={`ba-region-${i}`}>Use for region</label>
                    <select id={`ba-region-${i}`} style={inp} value={a.region} onChange={(e) => setAcct(i, { region: e.target.value })}>
                      <option value="">No region</option>
                      {regions.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select></div>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, cursor: 'pointer' }}>
                  <input type="radio" name="ba-default" checked={a.is_default} onChange={() => setAcct(i, { is_default: true })} />Default account
                </label>
                <button type="button" style={{ ...btnG, marginLeft: 'auto' }} onClick={() => dropAcct(i)}><Trash2 size={16} />Remove</button>
              </div>
            </div>
          ))}
          {form.bank_accounts.length < 10
            ? <button type="button" style={{ ...btnG, justifySelf: 'start' }} onClick={addAcct}>+ Add a bank account</button>
            : <small style={{ color: ds.gray }}>You can have up to 10 bank accounts.</small>}
        </div>
      </section>

      {regions.length > 0 && <RepRegions people={people} regions={regions} onSaved={setPeople} h={h} />}

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
        <h3 style={h}>Sales Record</h3>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', color: ds.dark }}>
          <input type="checkbox" checked={!!form.sales_record_enabled} onChange={set('sales_record_enabled')} style={{ width: 18, height: 18, marginTop: 2 }} />
          <span>Add paid invoices to Sales Record
            <small style={{ display: 'block', color: ds.gray, marginTop: 4 }}>
              When an invoice is fully paid, each line goes into Business Activities &gt; Sales Record with the rep who made
              the invoice, its region, product, size and units, so commissions count it. A receipt with no invoice goes in
              as one sale. Part-paid invoices show in their own card there and count once they are fully paid. Only invoices
              paid after you turn this on are added. If you also type sales into the Google Sheet, leave invoiced sales out
              of it, or they will be counted twice.
            </small>
          </span>
        </label>
      </section>

      <section style={card}>
        <h3 style={h}>Payments</h3>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', color: ds.dark }}>
          <input type="checkbox" checked={!!form.payments_need_approval} onChange={set('payments_need_approval')} style={{ width: 18, height: 18, marginTop: 2 }} />
          <span>An admin confirms payments recorded by reps
            <small style={{ display: 'block', color: ds.gray, marginTop: 4 }}>
              When a rep marks an invoice paid or part paid, or makes a receipt, it waits as "Waiting for an admin". It
              doesn't count as paid, no receipt is made and nothing goes to the customer until an owner, operations
              manager or admin approves it in Sales &gt; Payments to confirm. Rejecting needs a reason and the rep is told.
              Payments recorded by owners, operations managers and admins, and online Paystack payments, are always
              accepted at once. Turn this off and every payment is accepted at once.
            </small>
          </span>
        </label>
        {reps.length > 0 && <>
          <PeopleChecks title="Only some reps' payments wait"
            help={form.payments_need_approval ? 'Every rep\'s payments wait while the box above is ticked.'
              : 'Tick reps whose payments should wait, for example remote reps without a POS. Everyone else is accepted at once.'}
            people={reps} chosen={form.payment_confirm_reps} off={form.payments_need_approval}
            onToggle={(id) => toggleIn('payment_confirm_reps', id)} />
          <PeopleChecks title="Can also confirm payments"
            help="Owners, operations managers and admins can always confirm. Tick anyone else who may, such as the person who checks the bank for remote reps. Their own payments are never held, and nobody can confirm a payment they recorded."
            people={reps} chosen={form.payment_confirmers} onToggle={(id) => toggleIn('payment_confirmers', id)} />
        </>}
      </section>

      <section style={card}>
        <h3 style={h}>Emailed reports</h3>
        <label style={{ display: 'block', marginBottom: 12 }}><span style={lab}>Send reports to</span>
          <input style={inp} value={form.report_emails} onChange={set('report_emails')} placeholder="owner@business.com" />
          <small style={{ display: 'block', color: ds.gray, marginTop: 4 }}>Separate addresses with commas (up to 10). Leave empty to use the owner's login email.</small>
        </label>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', color: ds.dark, marginBottom: 10 }}>
          <input type="checkbox" checked={!!form.daily_sales_report} onChange={set('daily_sales_report')} style={{ width: 18, height: 18, marginTop: 2 }} />
          <span>Daily sales report<small style={{ display: 'block', color: ds.gray, marginTop: 4 }}>Every morning at 7am, yesterday's sales report as a PDF and a CSV.</small></span>
        </label>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', color: ds.dark }}>
          <input type="checkbox" checked={!!form.weekly_reports} onChange={set('weekly_reports')} style={{ width: 18, height: 18, marginTop: 2 }} />
          <span>Weekly reports<small style={{ display: 'block', color: ds.gray, marginTop: 4 }}>Every Monday at 7am, last week's sales report, plus the inventory report when stock is on.</small></span>
        </label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12, alignItems: 'center' }}>
          <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => sendTest('daily')}>{busy === 'daily' ? 'Sending…' : 'Send yesterday\'s report now'}</button>
          <button type="button" style={disabled(btnG, !!busy)} disabled={!!busy} onClick={() => sendTest('weekly')}>{busy === 'weekly' ? 'Sending…' : 'Send last week\'s report now'}</button>
          <small style={{ color: ds.gray }}>Uses the saved addresses. Save first if you changed them.</small>
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

// REVISE-1: each sales rep's home region. Saved on its own (not with the rest of the settings).
function RepRegions({ people, regions, onSaved, h }) {
  const reps = people.filter((p) => !p.manager)
  const [pick, setPick] = useState({})
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)   // { ok, text }
  const valueOf = (p) => (p.id in pick ? pick[p.id] : (p.region || ''))
  const changed = reps.filter((p) => valueOf(p) !== (p.region || ''))
  const save = async () => {
    setBusy(true); setNote(null)
    try {
      const out = await saveRepRegions(Object.fromEntries(changed.map((p) => [p.id, valueOf(p) || null])))
      onSaved(people.map((p) => (p.id in (out || {}) ? { ...p, region: out[p.id] } : p)))
      setPick({}); setNote({ ok: true, text: 'Regions saved.' })
    } catch (err) { setNote({ ok: false, text: apiError(err) }) } finally { setBusy(false) }
  }
  return (
    <section style={card}>
      <h3 style={h}>Sales reps' regions</h3>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 12px' }}>
        A rep with a region always makes invoices for it and chooses only from its bank accounts. Leave it blank to let them pick the region on each invoice.
      </p>
      {!reps.length && <small style={{ color: ds.gray }}>No sales reps yet.</small>}
      <div style={{ display: 'grid', gap: 8 }}>
        {reps.map((p) => (
          <div key={p.id} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 10, alignItems: 'center' }}>
            <label htmlFor={`rr-${p.id}`} style={{ fontSize: 14, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</label>
            <select id={`rr-${p.id}`} style={inp} value={valueOf(p)} onChange={(e) => setPick((m) => ({ ...m, [p.id]: e.target.value }))}>
              <option value="">No region (picks on each invoice)</option>
              {regions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
        ))}
      </div>
      {reps.length > 0 && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
          <button type="button" style={disabled(btnP, busy || !changed.length)} disabled={busy || !changed.length} onClick={save}>{busy ? 'Saving…' : 'Save regions'}</button>
          {note && <small role="status" style={{ color: note.ok ? ds.teal : ds.red }}>{note.text}</small>}
        </div>
      )}
    </section>
  )
}

function PeopleChecks({ title, help, people, chosen, onToggle, off = false }) {
  return (
    <fieldset style={{ border: `1px solid ${ds.border}`, borderRadius: 10, padding: '10px 14px', marginTop: 14, opacity: off ? 0.55 : 1 }} disabled={off}>
      <legend style={{ fontSize: 14, fontWeight: 600, color: ds.dark, padding: '0 6px' }}>{title}</legend>
      <small style={{ display: 'block', color: ds.gray, marginBottom: 8 }}>{help}</small>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 6 }}>
        {people.map((p) => (
          <label key={p.id} style={{ display: 'flex', gap: 8, alignItems: 'center', minHeight: 36, cursor: off ? 'default' : 'pointer', color: ds.dark, fontSize: 14 }}>
            <input type="checkbox" checked={chosen.includes(p.id)} onChange={() => onToggle(p.id)} style={{ width: 18, height: 18 }} />
            {p.name}
          </label>
        ))}
      </div>
    </fieldset>
  )
}
