/**
 * frontend/src/modules/sites/PricingForm.jsx
 * SITE-DISCOUNT — a proper form for site_builder_settings.pricing (spec §12.1), so prices
 * can be changed at any time without touching JSON. Domain endings and hosting items are
 * editable lists (add / remove / rename). Keys this form doesn't know about are kept as they
 * are when saving. The raw JSON editor stays below as an "Advanced" option.
 */
import { useEffect, useMemo, useState } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import { Card, SectionTitle, Button, Field, Notice, Toggle } from './sitesUi'
import { T, INPUT } from './sitesKit'

const GRID = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12 }
const ROW = { display: 'grid', gridTemplateColumns: 'minmax(90px, 1fr) minmax(110px, 1fr) minmax(110px, 1fr) auto auto', gap: 8, alignItems: 'end' }
const ROW_HOST = { display: 'grid', gridTemplateColumns: 'minmax(140px, 2fr) minmax(110px, 1fr) auto auto', gap: 8, alignItems: 'end' }
const HID = { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' }
const SUB = { margin: '18px 0 8px', fontSize: 12.5, fontWeight: 700, color: T.ink }

const get = (o, path, d = '') => {
  let cur = o
  for (const k of path) { if (cur == null) return d; cur = cur[k] }
  return cur == null ? d : cur
}
const setIn = (o, path, value) => {
  const next = { ...o }
  let cur = next
  path.forEach((k, i) => {
    if (i === path.length - 1) { cur[k] = value; return }
    cur[k] = { ...(cur[k] || {}) }
    cur = cur[k]
  })
  return next
}
const toNum = (v) => (v === '' ? '' : Number(v))
const isNum = (v) => v !== '' && v !== null && v !== undefined && !Number.isNaN(Number(v)) && Number(v) >= 0

function domainRows(obj) {
  return Object.entries(obj || {}).map(([tld, cfg]) => ({ tld, ...cfg }))
}
function hostingRows(list) {
  return (list || []).map((h) => ({ ...h }))
}

function NumField({ label, hint, value, onChange, disabled, step = 'any' }) {
  return (
    <Field label={label} hint={hint}>
      <input style={INPUT} type="number" inputMode="decimal" min="0" step={step} value={value} disabled={disabled}
        onChange={(e) => onChange(toNum(e.target.value))} />
    </Field>
  )
}

export default function PricingForm({ pricing, canEdit, saving, onSave }) {
  const [p, setP] = useState(pricing || {})
  const [std, setStd] = useState(() => domainRows(get(pricing, ['routes', 'standard', 'domains'], {})))
  const [host, setHost] = useState(() => hostingRows(get(pricing, ['routes', 'standard', 'hosting_items'], [])))
  const [exp, setExp] = useState(() => domainRows(get(pricing, ['routes', 'express', 'domains'], {})))
  const [error, setError] = useState(null)

  // Reload when the saved pricing changes (after a save or a raw-JSON save).
  useEffect(() => {
    setP(pricing || {})
    setStd(domainRows(get(pricing, ['routes', 'standard', 'domains'], {})))
    setHost(hostingRows(get(pricing, ['routes', 'standard', 'hosting_items'], [])))
    setExp(domainRows(get(pricing, ['routes', 'express', 'domains'], {})))
    setError(null)
  }, [pricing])

  const dis = !canEdit || saving
  const n = (path) => get(p, path)
  const setN = (path) => (v) => setP((cur) => setIn(cur, path, v))

  const hostingIsFree = useMemo(
    () => host.length > 0 && host.every((h) => Number(h.yearly_ngn || 0) === 0),
    [host],
  )

  const updRow = (setter) => (i, patch) => setter((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const delRow = (setter) => (i) => setter((rows) => rows.filter((_, idx) => idx !== i))

  function build() {
    // Every number field that is shown must be a number ≥ 0.
    const numbers = [
      ['service_fee', 'standard_ngn'], ['service_fee', 'express_ngn'], ['markup_pct', 'domain'], ['markup_pct', 'hosting'],
      ['floors_after_fees', 'initial_ngn'], ['floors_after_fees', 'renewal_ngn'], ['round_to_ngn'], ['vat_pct'],
      ['gateway', 'pct'], ['gateway', 'flat_ngn'], ['gateway', 'flat_waived_below_ngn'],
      ['fx', 'usd_ngn'], ['fx', 'buffer_pct'],
    ]
    for (const path of numbers) {
      const v = get(p, path, 0)
      if (v !== '' && !isNum(v)) return { error: 'Every amount must be a number, zero or more.' }
    }
    const out = JSON.parse(JSON.stringify(p))
    // Blank number boxes count as 0.
    for (const path of numbers) {
      if (get(out, path, 0) === '') Object.assign(path.length === 1 ? out : get(out, path.slice(0, -1), {}), { [path[path.length - 1]]: 0 })
    }
    if (out.gateway && (out.gateway.cap_ngn === '' || out.gateway.cap_ngn === undefined)) delete out.gateway.cap_ngn
    else if (out.gateway && !isNum(out.gateway.cap_ngn)) return { error: 'The payment fee cap must be a number, or left empty.' }
    if (out.routes?.express && out.routes.express.hosting_per_site_usd === '') delete out.routes.express.hosting_per_site_usd
    if (out.routes?.express && out.routes.express.hosting_per_site_usd !== undefined && !isNum(out.routes.express.hosting_per_site_usd)) {
      return { error: 'Express hosting per site must be a number, zero or more.' }
    }

    const buildDomains = (rows, label, kind) => {
      const obj = {}
      for (const r of rows) {
        let tld = String(r.tld || '').trim().toLowerCase()
        if (!tld) return { error: `A ${label} domain ending is blank — fill it in or remove the row.` }
        if (!tld.startsWith('.')) tld = `.${tld}`
        if (obj[tld]) return { error: `${tld} is listed twice under ${label}.` }
        const { tld: _t, ...rest } = r
        const keys = kind === 'ngn' ? ['first_ngn', 'renew_ngn'] : ['first_usd', 'renew_usd']
        for (const k of keys) {
          if (rest[k] === '' || rest[k] === undefined) rest[k] = 0
          if (!isNum(rest[k])) return { error: `${tld}: prices must be numbers, zero or more.` }
        }
        rest.vat = !!rest.vat
        obj[tld] = rest
      }
      return { value: obj }
    }
    const s = buildDomains(std, 'standard', 'ngn')
    if (s.error) return s
    const e = buildDomains(exp, 'express', 'usd')
    if (e.error) return e

    const items = []
    for (const h of host) {
      const name = String(h.name || '').trim()
      if (!name) return { error: 'A hosting item has no name — fill it in or remove the row.' }
      const yearly = h.yearly_ngn === '' || h.yearly_ngn === undefined ? 0 : h.yearly_ngn
      if (!isNum(yearly)) return { error: `${name}: the yearly price must be a number, zero or more.` }
      items.push({ ...h, name, yearly_ngn: Number(yearly), vat: !!h.vat })
    }

    out.routes = { ...(out.routes || {}) }
    out.routes.standard = { ...(out.routes.standard || {}), domains: s.value, hosting_items: items }
    if (Object.keys(e.value).length || out.routes.express) {
      out.routes.express = { ...(out.routes.express || {}), domains: e.value }
    }
    const cp = out.care_plan
    if (cp) {
      for (const k of Object.keys(cp)) {
        if (cp[k] === '') cp[k] = 0
        else if (!isNum(cp[k])) return { error: 'Care plan values must be numbers, zero or more.' }
      }
    }
    return { value: out }
  }

  function submit() {
    setError(null)
    const r = build()
    if (r.error) { setError(r.error); return }
    onSave(r.value)
  }

  const care = get(p, ['care_plan'], null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <Card>
        <SectionTitle title="What you charge" hint="Amounts in naira unless it says otherwise. Every order is priced from these numbers, so a change here applies to the next quote." />
        <div style={GRID}>
          <NumField label="Service fee, standard (₦)" hint="Added on top of domain + hosting for a first order." value={n(['service_fee', 'standard_ngn'])} onChange={setN(['service_fee', 'standard_ngn'])} disabled={dis} />
          <NumField label="Service fee, express (₦)" value={n(['service_fee', 'express_ngn'])} onChange={setN(['service_fee', 'express_ngn'])} disabled={dis} />
          <NumField label="Markup on domains (%)" hint="Added to what the domain costs you." value={n(['markup_pct', 'domain'])} onChange={setN(['markup_pct', 'domain'])} disabled={dis} />
          <NumField label="Markup on hosting (%)" value={n(['markup_pct', 'hosting'])} onChange={setN(['markup_pct', 'hosting'])} disabled={dis} />
          <NumField label="Minimum profit, first order (₦)" hint="If the price would earn less, the service fee is raised to reach it." value={n(['floors_after_fees', 'initial_ngn'])} onChange={setN(['floors_after_fees', 'initial_ngn'])} disabled={dis} />
          <NumField label="Minimum profit, renewal (₦)" value={n(['floors_after_fees', 'renewal_ngn'])} onChange={setN(['floors_after_fees', 'renewal_ngn'])} disabled={dis} />
          <NumField label="Round prices up to (₦)" hint="e.g. 500 rounds up to the next ₦500." value={n(['round_to_ngn'])} onChange={setN(['round_to_ngn'])} disabled={dis} />
        </div>
      </Card>

      <Card>
        <SectionTitle title="Domain endings" hint="What each domain ending costs you per year (standard hosting). Add any ending you sell; remove ones you don't."
          right={canEdit && <Button size="sm" icon={Plus} onClick={() => setStd((r) => [...r, { tld: '', first_ngn: '', renew_ngn: '', vat: false }])} disabled={saving}>Add ending</Button>} />
        {std.length === 0 && <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No domain endings yet. Builders can't get a price until you add at least one.</p>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {std.map((r, i) => (
            <div key={i} style={ROW}>
              <Field label={i === 0 ? 'Ending' : <span style={HID}>Ending</span>}>
                <input style={INPUT} value={r.tld} placeholder=".com.ng" disabled={dis} onChange={(e) => updRow(setStd)(i, { tld: e.target.value })} />
              </Field>
              <NumField label={i === 0 ? 'First year (₦)' : <span style={HID}>First year</span>} value={r.first_ngn ?? ''} onChange={(v) => updRow(setStd)(i, { first_ngn: v })} disabled={dis} />
              <NumField label={i === 0 ? 'Renewal (₦)' : <span style={HID}>Renewal</span>} value={r.renew_ngn ?? ''} onChange={(v) => updRow(setStd)(i, { renew_ngn: v })} disabled={dis} />
              <Toggle checked={!!r.vat} onChange={(v) => updRow(setStd)(i, { vat: v })} disabled={dis} label="+VAT" />
              {canEdit && <Button size="sm" icon={Trash2} aria-label={`Remove ${r.tld || 'row'}`} onClick={() => delRow(setStd)(i)} disabled={saving} />}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle title="Hosting" hint="What the hosting bundle costs you per year. Each item is added up. Got a free hosting deal? Set the yearly price to 0 (or remove the item) and builders are charged nothing for hosting."
          right={canEdit && <Button size="sm" icon={Plus} onClick={() => setHost((r) => [...r, { name: '', yearly_ngn: '', vat: false }])} disabled={saving}>Add hosting item</Button>} />
        {hostingIsFree && <Notice tone="info" style={{ marginBottom: 12 }}>Hosting is currently free: every item is set to ₦0.</Notice>}
        {host.length === 0 && <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No hosting items, so hosting adds ₦0 to the price.</p>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {host.map((h, i) => (
            <div key={i} style={ROW_HOST}>
              <Field label={i === 0 ? 'Item' : <span style={HID}>Item</span>}>
                <input style={INPUT} value={h.name} placeholder="Starter hosting" disabled={dis} onChange={(e) => updRow(setHost)(i, { name: e.target.value })} />
              </Field>
              <NumField label={i === 0 ? 'Per year (₦)' : <span style={HID}>Per year</span>} value={h.yearly_ngn ?? ''} onChange={(v) => updRow(setHost)(i, { yearly_ngn: v })} disabled={dis} />
              <Toggle checked={!!h.vat} onChange={(v) => updRow(setHost)(i, { vat: v })} disabled={dis} label="+VAT" />
              {canEdit && <Button size="sm" icon={Trash2} aria-label={`Remove ${h.name || 'item'}`} onClick={() => delRow(setHost)(i)} disabled={saving} />}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle title="Tax & payment fees" hint="Used to work out your profit on each order." />
        <div style={GRID}>
          <NumField label="VAT (%)" value={n(['vat_pct'])} onChange={setN(['vat_pct'])} disabled={dis} />
          <NumField label="Payment fee (%)" hint="Paystack's percentage." value={n(['gateway', 'pct'])} onChange={setN(['gateway', 'pct'])} disabled={dis} />
          <NumField label="Flat payment fee (₦)" value={n(['gateway', 'flat_ngn'])} onChange={setN(['gateway', 'flat_ngn'])} disabled={dis} />
          <NumField label="No flat fee below (₦)" value={n(['gateway', 'flat_waived_below_ngn'])} onChange={setN(['gateway', 'flat_waived_below_ngn'])} disabled={dis} />
          <NumField label="Payment fee cap (₦)" hint="Leave empty for no cap." value={n(['gateway', 'cap_ngn'])} onChange={setN(['gateway', 'cap_ngn'])} disabled={dis} />
        </div>
      </Card>

      {care && (
        <Card>
          <SectionTitle title="Care plan" hint="The monthly plan builders pay to keep editing their sites." />
          <div style={GRID}>
            <NumField label="Price per month (₦)" value={care.price_ngn ?? ''} onChange={setN(['care_plan', 'price_ngn'])} disabled={dis} />
            <NumField label="Edits per month" value={care.edits_per_month ?? ''} onChange={setN(['care_plan', 'edits_per_month'])} disabled={dis} />
            <NumField label="Extra edit pack price (₦)" value={care.pack_price_ngn ?? ''} onChange={setN(['care_plan', 'pack_price_ngn'])} disabled={dis} />
            <NumField label="Edits in a pack" value={care.pack_edits ?? ''} onChange={setN(['care_plan', 'pack_edits'])} disabled={dis} />
            <NumField label="Grace days after a missed payment" value={care.grace_days ?? ''} onChange={setN(['care_plan', 'grace_days'])} disabled={dis} />
            <NumField label="Reminder days before it ends" value={care.reminder_days ?? ''} onChange={setN(['care_plan', 'reminder_days'])} disabled={dis} />
          </div>
        </Card>
      )}

      <Card>
        <SectionTitle title="Express hosting (when it's switched on)" hint="Express prices are in US dollars and converted to naira at your exchange rate." />
        <div style={GRID}>
          <NumField label="Dollar to naira rate (₦ per $1)" value={n(['fx', 'usd_ngn'])} onChange={setN(['fx', 'usd_ngn'])} disabled={dis} />
          <NumField label="Safety buffer on the rate (%)" value={n(['fx', 'buffer_pct'])} onChange={setN(['fx', 'buffer_pct'])} disabled={dis} />
          <NumField label="Hosting per site ($/year)" value={get(p, ['routes', 'express', 'hosting_per_site_usd'], '')}
            onChange={(v) => setP((cur) => setIn(cur, ['routes', 'express', 'hosting_per_site_usd'], v))} disabled={dis} />
        </div>
        <div style={{ ...SUB, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>Express domain endings ($ per year)</span>
          {canEdit && <Button size="sm" icon={Plus} onClick={() => setExp((r) => [...r, { tld: '', first_usd: '', renew_usd: '' }])} disabled={saving}>Add ending</Button>}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {exp.map((r, i) => (
            <div key={i} style={{ ...ROW, gridTemplateColumns: 'minmax(90px, 1fr) minmax(110px, 1fr) minmax(110px, 1fr) auto' }}>
              <Field label={i === 0 ? 'Ending' : <span style={HID}>Ending</span>}>
                <input style={INPUT} value={r.tld} placeholder=".com" disabled={dis} onChange={(e) => updRow(setExp)(i, { tld: e.target.value })} />
              </Field>
              <NumField label={i === 0 ? 'First year ($)' : <span style={HID}>First year</span>} value={r.first_usd ?? ''} onChange={(v) => updRow(setExp)(i, { first_usd: v })} disabled={dis} />
              <NumField label={i === 0 ? 'Renewal ($)' : <span style={HID}>Renewal</span>} value={r.renew_usd ?? ''} onChange={(v) => updRow(setExp)(i, { renew_usd: v })} disabled={dis} />
              {canEdit && <Button size="sm" icon={Trash2} aria-label={`Remove ${r.tld || 'row'}`} onClick={() => delRow(setExp)(i)} disabled={saving} />}
            </div>
          ))}
        </div>
      </Card>

      {error && <Notice tone="bad">{error}</Notice>}
      {canEdit && (
        <div>
          <Button variant="primary" icon={Save} loading={saving} onClick={submit}>Save pricing</Button>
        </div>
      )}
    </div>
  )
}
