/**
 * frontend/src/modules/admin/CommissionSettings.jsx
 * Commission Settings — Phase 9C
 *
 * Allows Owner/Admin to configure how commissions work for their org:
 *   1. Enable / disable commission tracking
 *   2. Which role templates earn commission (multi-select checkboxes)
 *   3. Rate type: flat NGN amount or percentage of deal value
 *   4. Rate value: the numeric amount
 *   5. Payment trigger: every payment or first payment only
 *   6. WhatsApp notification: on/off when commission approved/paid
 *
 * Reads from and writes to GET/PATCH /api/v1/admin/commission-settings
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

const ALL_TEMPLATES = [
  { value: 'affiliate_partner', label: 'Affiliate Partner' },
  { value: 'sales_agent',       label: 'Sales Agent' },
  { value: 'customer_success',  label: 'Customer Success' },
  { value: 'ops_manager',       label: 'Operations Manager' },
]

const LABEL = {
  display: 'block', fontSize: 11, fontWeight: 600, color: '#4a7a8a',
  textTransform: 'uppercase', letterSpacing: '0.7px', marginTop: 20, marginBottom: 6,
}
const INPUT = {
  width: '100%', padding: '9px 12px', border: '1px solid #D4E6EC',
  borderRadius: 8, fontSize: 13.5, fontFamily: 'inherit',
  color: '#0a1a24', background: 'white', boxSizing: 'border-box',
}
const TOGGLE_ROW = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '14px 0', borderBottom: '1px solid #F0F7FA',
}

export default function CommissionSettings() {
  const [settings, setSettings]   = useState(null)
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)
  const [error, setError]         = useState(null)

  useEffect(() => {
    adminSvc.getCommissionSettings()
      .then(data => {
        setSettings({
          commission_enabled:             data.commission_enabled             ?? false,
          commission_eligible_templates:  data.commission_eligible_templates  ?? ['affiliate_partner'],
          commission_rate_type:           data.commission_rate_type           ?? 'flat',
          commission_rate_value:          data.commission_rate_value          ?? 0,
          commission_trigger:             data.commission_trigger             ?? 'every_payment',
          commission_whatsapp_notify:     data.commission_whatsapp_notify     ?? false,
        })
        setLoading(false)
      })
      .catch(() => { setError('Failed to load settings.'); setLoading(false) })
  }, [])

  const set = (key, value) => setSettings(s => ({ ...s, [key]: value }))

  const toggleTemplate = (tmpl) => {
    const current = settings.commission_eligible_templates ?? []
    const updated = current.includes(tmpl)
      ? current.filter(t => t !== tmpl)
      : [...current, tmpl]
    set('commission_eligible_templates', updated)
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await adminSvc.updateCommissionSettings(settings)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Failed to save settings. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading settings…</div>
  if (!settings) return null

  return (
    <div style={{ maxWidth: 620 }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>
          Commission Settings
        </h2>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: '6px 0 0', lineHeight: 1.5 }}>
          Configure how commissions are tracked and paid out to your team and affiliates.
        </p>
      </div>

      <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', padding: '4px 24px 24px' }}>

        {/* Master switch */}
        <div style={TOGGLE_ROW}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#0a1a24' }}>Enable Commission Tracking</div>
            <div style={{ fontSize: 12, color: '#7A9BAD', marginTop: 2 }}>
              When disabled, commission rows are still created but with ₦0 amount for manual review
            </div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={settings.commission_enabled}
              onChange={e => set('commission_enabled', e.target.checked)}
              style={{ width: 18, height: 18 }}
            />
            <span style={{ fontSize: 13, color: settings.commission_enabled ? ds.teal : '#7A9BAD', fontWeight: 600 }}>
              {settings.commission_enabled ? 'On' : 'Off'}
            </span>
          </label>
        </div>

        {/* Eligible roles */}
        <label style={LABEL}>Who earns commission</label>
        <p style={{ fontSize: 12, color: '#7A9BAD', margin: '0 0 10px' }}>
          Select which role templates are eligible. Only users with these roles will have commission rows created automatically.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {ALL_TEMPLATES.map(tmpl => {
            const checked = (settings.commission_eligible_templates ?? []).includes(tmpl.value)
            return (
              <label key={tmpl.value} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
                background: checked ? '#EEF8FA' : '#F8FAFC',
                border: `1.5px solid ${checked ? ds.teal : '#E4EEF2'}`,
                fontSize: 13, color: checked ? ds.teal : '#4a7a8a', fontWeight: checked ? 600 : 400,
                transition: 'all 0.15s',
              }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleTemplate(tmpl.value)}
                  style={{ display: 'none' }}
                />
                {checked ? '✓ ' : ''}{tmpl.label}
              </label>
            )
          })}
        </div>

        {/* Rate type */}
        <label style={LABEL}>Commission rate type</label>
        <div style={{ display: 'flex', gap: 12 }}>
          {[
            { value: 'flat',       label: 'Flat amount (₦)',       hint: 'Same NGN amount per event' },
            { value: 'percentage', label: 'Percentage (%)',         hint: '% of the deal/payment value' },
          ].map(opt => {
            const selected = settings.commission_rate_type === opt.value
            return (
              <div
                key={opt.value}
                onClick={() => set('commission_rate_type', opt.value)}
                style={{
                  flex: 1, padding: '12px 16px', borderRadius: 10, cursor: 'pointer',
                  border: `2px solid ${selected ? ds.teal : '#E4EEF2'}`,
                  background: selected ? '#EEF8FA' : 'white',
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ fontSize: 13.5, fontWeight: 600, color: selected ? ds.teal : '#0a1a24', marginBottom: 3 }}>
                  {opt.label}
                </div>
                <div style={{ fontSize: 11.5, color: '#7A9BAD' }}>{opt.hint}</div>
              </div>
            )
          })}
        </div>

        {/* Rate value */}
        <label style={LABEL}>
          {settings.commission_rate_type === 'flat' ? 'Commission amount (₦)' : 'Commission rate (%)'}
        </label>
        <input
          type="number"
          min={0}
          step={settings.commission_rate_type === 'percentage' ? 0.1 : 100}
          value={settings.commission_rate_value}
          onChange={e => set('commission_rate_value', Number(e.target.value))}
          style={INPUT}
          placeholder={settings.commission_rate_type === 'flat' ? 'e.g. 10000' : 'e.g. 5'}
        />
        <p style={{ fontSize: 12, color: '#7A9BAD', margin: '4px 0 0' }}>
          {settings.commission_rate_type === 'flat'
            ? 'Leave at 0 to disable automatic amount calculation (manager sets amount manually)'
            : 'Percentage of the payment or deal amount. Leave at 0 to disable automatic calculation.'}
        </p>

        {/* Payment trigger */}
        <label style={LABEL}>When to pay commission on payments</label>
        <select
          value={settings.commission_trigger}
          onChange={e => set('commission_trigger', e.target.value)}
          style={INPUT}
        >
          <option value="every_payment">Every confirmed payment (recurring commissions)</option>
          <option value="first_payment">First payment only (acquisition commission only)</option>
        </select>
        <p style={{ fontSize: 12, color: '#7A9BAD', margin: '4px 0 0' }}>
          This only affects payment_confirmed events. Lead conversion commissions always trigger once.
        </p>

        {/* WhatsApp notification */}
        <div style={{ ...TOGGLE_ROW, marginTop: 20, borderBottom: 'none' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#0a1a24' }}>WhatsApp notification on approval/payment</div>
            <div style={{ fontSize: 12, color: '#7A9BAD', marginTop: 2 }}>
              Send a WhatsApp message to the affiliate when their commission is approved or marked as paid.
              Requires the user to have a WhatsApp number set on their profile.
            </div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginLeft: 20, flexShrink: 0 }}>
            <input
              type="checkbox"
              checked={settings.commission_whatsapp_notify}
              onChange={e => set('commission_whatsapp_notify', e.target.checked)}
              style={{ width: 18, height: 18 }}
            />
            <span style={{ fontSize: 13, color: settings.commission_whatsapp_notify ? ds.teal : '#7A9BAD', fontWeight: 600 }}>
              {settings.commission_whatsapp_notify ? 'On' : 'Off'}
            </span>
          </label>
        </div>
      </div>

      {/* Error / success */}
      {error  && <p style={{ fontSize: 13, color: '#DC2626', marginTop: 12 }}>⚠ {error}</p>}
      {saved  && <p style={{ fontSize: 13, color: '#059669', marginTop: 12 }}>✓ Settings saved successfully</p>}

      {/* Save */}
      <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: saving ? '#aaa' : ds.teal, color: 'white',
            border: 'none', borderRadius: 9, padding: '11px 28px',
            fontSize: 14, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer',
            fontFamily: ds.fontSyne,
          }}
        >
          {saving ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
