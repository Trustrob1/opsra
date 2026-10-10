/**
 * frontend/src/modules/sites/TiersCard.jsx
 * SITE-ADDONS A0-3 - Settings: the Capture / Convert / Grow plans and the optional add-ons.
 * Prices, set-up fees, monthly allowances, what each plan includes, and the billing rules (period, grace, reminders).
 * Everything starts at 0 = "not for sale yet": a plan with no monthly price cannot be bought, though staff can still grant it.
 * Saves the whole pricing blob with its other keys kept, through PATCH /sites/settings (the server checks the numbers).
 */
import { useCallback, useEffect, useState } from 'react'
import { Save, Info } from 'lucide-react'
import { getSiteAddonsCatalog, updateSiteSettings, errorMessage } from '../../services/sites.service'
import { Card, SectionTitle, Button, Notice, Spinner, Field, Badge } from './sitesUi'
import { T, INPUT } from './sitesKit'

const CAP_LABELS = {
  ai_messages: 'AI replies per month',
  bulk_recipients: 'Bulk message recipients per month',
  reps: 'Team members (reps)',
}
const GROUP_LABELS = { capture: 'Capture', convert: 'Convert', grow: 'Grow' }

const toInt = (v) => {
  const n = Math.floor(Number(String(v).replace(/[^\d]/g, '')))
  return Number.isFinite(n) ? n : 0
}

function NumInput({ value, onChange, disabled, ariaLabel, prefix }) {
  return (
    <div style={{ position: 'relative' }}>
      {prefix && <span aria-hidden="true" style={{ position: 'absolute', left: 11, top: 10, fontSize: 13.5, color: T.muted }}>{prefix}</span>}
      <input type="text" inputMode="numeric" className="tnum" aria-label={ariaLabel} disabled={disabled}
        value={value === 0 ? '' : Number(value).toLocaleString('en-NG')} placeholder="0"
        onChange={(e) => onChange(toInt(e.target.value))}
        style={{ ...INPUT, paddingLeft: prefix ? 24 : 11, textAlign: 'right' }} />
    </div>
  )
}

function startState(cat) {
  const tiers = {}
  cat.tiers.forEach((t) => {
    tiers[t.key] = { label: t.label, monthly_ngn: t.monthly_ngn, setup_fee_ngn: t.setup_fee_ngn,
      features: [...t.features], pick_one: t.pick_one, caps: { ...(t.caps || {}) } }
  })
  const addons = {}
  cat.addons.forEach((a) => {
    addons[a.key] = { label: a.label, monthly_ngn: a.monthly_ngn, features: [...a.features], caps: { ...(a.caps || {}) } }
  })
  return {
    tiers, addons,
    billing: { period_days: cat.billing.period_days, grace_days: cat.billing.grace_days,
      reminder_days: (cat.billing.reminder_days || []).join(', ') },
  }
}

export default function TiersCard({ pricing, canEdit, onSaved, showToast }) {
  const [cat, setCat] = useState(null)
  const [form, setForm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setLoadError(null)
    try {
      const c = await getSiteAddonsCatalog()
      setCat(c); setForm(startState(c))
    } catch (e) {
      setLoadError(errorMessage(e, 'Could not load the plans.'))
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { load() }, [load])

  if (loading) return <Card><Spinner /></Card>
  if (loadError) return <Card><Notice tone="bad">{loadError}</Notice></Card>

  const setTier = (key, patch) => setForm((f) => ({ ...f, tiers: { ...f.tiers, [key]: { ...f.tiers[key], ...patch } } }))
  const setAddon = (key, patch) => setForm((f) => ({ ...f, addons: { ...f.addons, [key]: { ...f.addons[key], ...patch } } }))
  const setBilling = (patch) => setForm((f) => ({ ...f, billing: { ...f.billing, ...patch } }))
  const setCap = (setter, key, capKey, v) => setter(key, { caps: { ...form[setter === setTier ? 'tiers' : 'addons'][key].caps, [capKey]: v } })

  const addonKeys = new Set(cat.addons.map((a) => a.key))
  const featuresByGroup = (cat.features || []).filter((f) => !addonKeys.has(f.key))
  const labelOf = (k) => (cat.features.find((f) => f.key === k) || {}).label || k

  const toggleFeature = (tierKey, fKey, on) => {
    const cur = form.tiers[tierKey].features
    setTier(tierKey, { features: on ? [...new Set([...cur, fKey])] : cur.filter((k) => k !== fKey) })
  }

  const save = async () => {
    setError(null)
    const rd = form.billing.reminder_days.split(',').map((s) => s.trim()).filter(Boolean)
    if (rd.some((s) => !/^\d+$/.test(s))) { setError('Reminder days must be whole numbers separated by commas, for example 5, 1.'); return }
    const tiers = {}
    Object.entries(form.tiers).forEach(([k, t]) => {
      const keep = new Set((t.pick_one || []).flat())
      tiers[k] = { label: t.label, monthly_ngn: t.monthly_ngn, setup_fee_ngn: t.setup_fee_ngn, caps: t.caps,
        features: t.features.filter((f) => !keep.has(f)), pick_one: t.pick_one }
    })
    const addons = {}
    Object.entries(form.addons).forEach(([k, a]) => {
      addons[k] = { label: a.label, monthly_ngn: a.monthly_ngn, features: a.features, caps: a.caps }
    })
    const next = { ...(pricing || {}), tiers, addons,
      tier_billing: { period_days: form.billing.period_days, grace_days: form.billing.grace_days, reminder_days: rd.map(Number) } }
    setSaving(true)
    try {
      const row = await updateSiteSettings({ pricing: next })
      onSaved?.(row)
      showToast?.('Plans and prices saved')
      await load()
    } catch (e) {
      setError(errorMessage(e, 'Could not save the plans.'))
    } finally {
      setSaving(false)
    }
  }

  const disabled = !canEdit || saving

  return (
    <Card>
      <SectionTitle title="Plans and add-ons"
        hint="What each plan costs and includes. A plan with no monthly price is not for sale yet; you can still switch it on for a site from the site's page." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <Notice tone="info" icon={Info}>
          Clients pay these monthly through a private payment link. The set-up fee is charged once per plan. Features marked
          “not live yet” are part of the plan but switch on as they are built.
        </Notice>

        {cat.tiers.map((t) => {
          const f = form.tiers[t.key]
          const pickKeys = new Set((f.pick_one || []).flat())
          return (
            <div key={t.key} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <h4 style={{ margin: 0, fontSize: 14, color: T.ink }}>{f.label}</h4>
                {f.monthly_ngn > 0 ? <Badge tone="good">For sale</Badge> : <Badge tone="neutral">Not for sale yet</Badge>}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
                <Field label="Monthly price (₦)"><NumInput prefix="₦" ariaLabel={`${f.label} monthly price`} value={f.monthly_ngn} disabled={disabled}
                  onChange={(v) => setTier(t.key, { monthly_ngn: v })} /></Field>
                <Field label="One-time set-up fee (₦)" hint="Charged once, with the first payment."><NumInput prefix="₦" ariaLabel={`${f.label} set-up fee`} value={f.setup_fee_ngn} disabled={disabled}
                  onChange={(v) => setTier(t.key, { setup_fee_ngn: v })} /></Field>
                {['ai_messages', 'bulk_recipients', 'reps'].map((c) => (
                  <Field key={c} label={CAP_LABELS[c]} hint={c === 'reps' ? undefined : 'Blank or 0 means none included.'}>
                    <NumInput ariaLabel={`${f.label} ${CAP_LABELS[c]}`} value={f.caps[c] || 0} disabled={disabled}
                      onChange={(v) => setCap(setTier, t.key, c, v)} />
                  </Field>
                ))}
              </div>
              {pickKeys.size > 0 && (
                <p style={{ margin: 0, fontSize: 12.5, color: T.soft }}>
                  Each site picks one of: {[...pickKeys].map(labelOf).join(' or ')}.
                </p>
              )}
              <details>
                <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: T.ink }}>
                  What {f.label} includes ({f.features.filter((k) => !pickKeys.has(k)).length} features)
                </summary>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 10 }}>
                  {Object.keys(GROUP_LABELS).map((g) => {
                    const rows = featuresByGroup.filter((x) => x.group === g && !pickKeys.has(x.key))
                    if (!rows.length) return null
                    return (
                      <fieldset key={g} style={{ border: 'none', margin: '0 0 8px', padding: 0 }}>
                        <legend style={{ fontSize: 11.5, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '0.6px', padding: 0, marginBottom: 4 }}>
                          {GROUP_LABELS[g]} features
                        </legend>
                        {rows.map((x) => (
                          <label key={x.key} style={{ display: 'flex', alignItems: 'center', gap: 9, minHeight: 34, fontSize: 13, color: T.ink }}>
                            <input type="checkbox" disabled={disabled} checked={f.features.includes(x.key)}
                              onChange={(e) => toggleFeature(t.key, x.key, e.target.checked)} />
                            <span>{x.label}</span>
                            {!x.built && <span style={{ fontSize: 11, color: T.muted }}>not live yet</span>}
                          </label>
                        ))}
                      </fieldset>
                    )
                  })}
                </div>
              </details>
            </div>
          )
        })}

        <div style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h4 style={{ margin: 0, fontSize: 14, color: T.ink }}>Add-ons</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
            {cat.addons.map((a) => {
              const f = form.addons[a.key]
              return (
                <div key={a.key} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <Field label={`${f.label} · monthly price (₦)`} hint={f.monthly_ngn > 0 ? 'For sale' : 'Not for sale yet'}>
                    <NumInput prefix="₦" ariaLabel={`${f.label} monthly price`} value={f.monthly_ngn} disabled={disabled}
                      onChange={(v) => setAddon(a.key, { monthly_ngn: v })} />
                  </Field>
                  {Object.keys(f.caps || {}).map((c) => (
                    <Field key={c} label={CAP_LABELS[c] || c} hint="Added to the plan's own allowance.">
                      <NumInput ariaLabel={`${f.label} ${CAP_LABELS[c] || c}`} value={f.caps[c] || 0} disabled={disabled}
                        onChange={(v) => setCap(setAddon, a.key, c, v)} />
                    </Field>
                  ))}
                </div>
              )
            })}
          </div>
        </div>

        <div style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h4 style={{ margin: 0, fontSize: 14, color: T.ink }}>Billing rules</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
            <Field label="Days in one paid period"><NumInput ariaLabel="Days in one paid period" value={form.billing.period_days} disabled={disabled}
              onChange={(v) => setBilling({ period_days: v })} /></Field>
            <Field label="Grace days after it ends" hint="The plan keeps working while the client pays late."><NumInput ariaLabel="Grace days" value={form.billing.grace_days} disabled={disabled}
              onChange={(v) => setBilling({ grace_days: v })} /></Field>
            <Field label="Remind the client (days before the end)" hint="Separate with commas, for example 5, 1.">
              <input style={INPUT} value={form.billing.reminder_days} disabled={disabled} aria-label="Reminder days"
                onChange={(e) => setBilling({ reminder_days: e.target.value })} />
            </Field>
          </div>
        </div>

        {error && <Notice tone="bad">{error}</Notice>}
        {canEdit
          ? <div><Button variant="primary" icon={Save} loading={saving} onClick={save}>Save plans and prices</Button></div>
          : <p style={{ margin: 0, fontSize: 12, color: T.muted }}>Only an owner or ops manager can change this.</p>}
      </div>
    </Card>
  )
}
