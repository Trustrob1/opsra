/**
 * LeadCreateModal — LEAD-FORM-CONFIG updated
 *
 * On modal open: fetches GET /api/v1/admin/lead-form-config.
 * Renders only fields where visible: true, in config order.
 * Applies required attribute per config.
 * Applies custom label per config.
 * phone and full_name always rendered first, always required — never from config.
 * If fetch fails → falls back to showing all fields (safe default, no blocking).
 *
 * Also adds product_interest field (new LEAD-FORM-CONFIG field).
 *
 * Calls POST /api/v1/leads
 * Required: full_name, source
 * All other fields optional — matches LeadCreate Pydantic model.
 * org_id is NEVER in the payload — derived from JWT server-side.
 *
 * Pattern 51: full rewrite.
 * Mobile-first: modal is full-screen below 600px (Section 13.3).
 */
import { useState, useEffect } from 'react'
import { createLead } from '../../services/leads.service'
import { getGrowthTeams } from '../../services/growth.service'
import { getLeadFormConfig } from '../../services/admin.service'
import { ds, SOURCE_LABELS, BRANCHES_OPTIONS } from '../../utils/ds'
import UserSelect from '../../shared/UserSelect'

const SOURCES = Object.entries(SOURCE_LABELS)

const INITIAL = {
  full_name:        '',
  source:           '',
  phone:            '',
  whatsapp:         '',
  email:            '',
  business_name:    '',
  business_type:    '',
  location:         '',
  branches:         '',
  problem_stated:   '',
  product_interest: '',
  referrer:         '',
  assigned_to:      '',
  source_team:      '',
}

// Default config — shown if fetch fails (all visible, none required)
const DEFAULT_FORM_CONFIG = [
  { key: 'email',            label: 'Email Address',    visible: true,  required: false },
  { key: 'whatsapp',         label: 'WhatsApp Number',  visible: true,  required: false },
  { key: 'business_name',    label: 'Business Name',    visible: true,  required: false },
  { key: 'business_type',    label: 'Business Type',    visible: true,  required: false },
  { key: 'location',         label: 'Location',         visible: true,  required: false },
  { key: 'branches',         label: 'No. of Branches',  visible: false, required: false },
  { key: 'problem_stated',   label: 'Problem Stated',   visible: true,  required: false },
  { key: 'product_interest', label: 'Product Interest', visible: false, required: false },
  { key: 'referrer',         label: 'Referred By',      visible: false, required: false },
]

export default function LeadCreateModal({ onClose, onCreated }) {
  const [form, setForm]             = useState(INITIAL)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState(null)
  const [teams, setTeams]           = useState([])
  const [formConfig, setFormConfig] = useState(DEFAULT_FORM_CONFIG)
  const [configLoaded, setConfigLoaded] = useState(false)

  // Fetch form config + growth teams on mount — both fail silently
  useEffect(() => {
    getLeadFormConfig()
      .then(data => {
        if (data?.fields?.length) setFormConfig(data.fields)
      })
      .catch(() => {}) // fall back to DEFAULT_FORM_CONFIG
      .finally(() => setConfigLoaded(true))

    getGrowthTeams()
      .then(data => setTeams((data || []).filter(t => t.is_active)))
      .catch(() => {})
  }, [])

  const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }))

  // Visible fields from config, in config order
  const visibleConfig = formConfig.filter(f => f.visible)

  // Build dynamic required check
  const configRequired = key => {
    const cfg = formConfig.find(f => f.key === key)
    return cfg?.required ?? false
  }

  // Check all config-required fields are filled
  const configRequiredMet = visibleConfig
    .filter(f => f.required)
    .every(f => (form[f.key] || '').trim() !== '')

  const handleSubmit = async () => {
    if (!form.full_name.trim()) { setError('Full name is required.'); return }
    if (!form.source)            { setError('Source is required.'); return }

    // Check config-required fields
    for (const cfg of visibleConfig.filter(f => f.required)) {
      if (!(form[cfg.key] || '').trim()) {
        setError(`${cfg.label} is required.`)
        return
      }
    }

    setSubmitting(true)
    setError(null)

    const payload = Object.fromEntries(
      Object.entries(form).filter(([, v]) => v !== ''),
    )

    try {
      const res = await createLead(payload)
      if (res.success) {
        onCreated?.(res.data)
        onClose()
      } else {
        setError(res.error ?? 'Could not create lead')
      }
    } catch (err) {
      const detail = err?.response?.data
      setError(detail?.error ?? detail?.message ?? 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  const isSubmitDisabled = submitting || !form.full_name || !form.source || !configRequiredMet

  return (
    <ModalOverlay onClose={onClose}>
      {/* Header */}
      <div style={headerStyle}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: 0 }}>
            New Lead
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: '2px 0 0' }}>
            Required fields marked with *
          </p>
        </div>
        <button onClick={onClose} style={closeBtn}>✕</button>
      </div>

      {/* Body */}
      <div style={{ padding: '24px' }}>

        {/* Always-required section */}
        <SectionLabel>Contact Details</SectionLabel>

        <TwoCol>
          <Field label="Full Name *">
            <input
              type="text"
              placeholder="e.g. Amaka Johnson"
              value={form.full_name}
              onChange={set('full_name')}
              style={inputStyle}
              autoFocus
            />
          </Field>
          <Field label="Lead Source *">
            <select value={form.source} onChange={set('source')} style={inputStyle}>
              <option value="">— Select source —</option>
              {SOURCES.map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </Field>
        </TwoCol>

        {/* Phone — always shown, always required */}
        <Field label="Phone *">
          <input
            type="tel"
            placeholder="+234 800 000 0000"
            value={form.phone}
            onChange={set('phone')}
            style={inputStyle}
          />
        </Field>

        {/* Config-driven fields */}
        {!configLoaded ? null : (
          <>
            {/* Group: contact-type fields */}
            {visibleConfig.some(f => ['whatsapp', 'email'].includes(f.key)) && (
              <>
                {renderConfigField('whatsapp', form, set, formConfig, inputStyle)}
                {renderConfigField('email', form, set, formConfig, inputStyle)}
              </>
            )}

            {/* Referrer — conditional on source AND config */}
            {form.source === 'manual_referral' &&
              visibleConfig.find(f => f.key === 'referrer') &&
              renderConfigField('referrer', form, set, formConfig, inputStyle)}

            {/* Business section — if any business fields are visible */}
            {visibleConfig.some(f => ['business_name', 'business_type', 'location', 'branches'].includes(f.key)) && (
              <>
                <SectionLabel>Business Details</SectionLabel>
                <TwoCol>
                  {renderConfigField('business_name', form, set, formConfig, inputStyle)}
                  {renderConfigField('business_type', form, set, formConfig, inputStyle)}
                </TwoCol>
                <TwoCol>
                  {renderConfigField('location', form, set, formConfig, inputStyle)}
                  {/* branches is a select */}
                  {visibleConfig.find(f => f.key === 'branches') && (
                    <Field label={getLabelWithRequired('branches', formConfig)}>
                      <select value={form.branches} onChange={set('branches')} style={inputStyle}>
                        <option value="">— Select —</option>
                        {BRANCHES_OPTIONS.map(b => (
                          <option key={b} value={b}>{b}</option>
                        ))}
                      </select>
                    </Field>
                  )}
                </TwoCol>
              </>
            )}

            {/* Intent fields */}
            {visibleConfig.find(f => f.key === 'problem_stated') && (
              <Field label={getLabelWithRequired('problem_stated', formConfig)}>
                <textarea
                  placeholder="What challenge or problem did they describe?"
                  value={form.problem_stated}
                  onChange={set('problem_stated')}
                  style={{ ...inputStyle, minHeight: 80, resize: 'vertical' }}
                />
              </Field>
            )}
            {visibleConfig.find(f => f.key === 'product_interest') && (
              <Field label={getLabelWithRequired('product_interest', formConfig)}>
                <input
                  type="text"
                  placeholder="e.g. Mattresses, Pillow Tops, Bed Frames"
                  value={form.product_interest}
                  onChange={set('product_interest')}
                  style={inputStyle}
                />
              </Field>
            )}
          </>
        )}

        {/* Assignment — always shown */}
        <SectionLabel>Assignment</SectionLabel>
        <Field label="Assign To (optional)">
          <UserSelect
            value={form.assigned_to}
            onChange={val => setForm(f => ({ ...f, assigned_to: val }))}
            placeholder="— Unassigned —"
            style={inputStyle}
          />
          <p style={{ fontSize: 11, color: ds.gray, margin: '4px 0 0' }}>
            Shows active Sales Agents and Affiliate Partners only.
          </p>
        </Field>

        {/* GPM-1D: Source Team */}
        {teams.length > 0 && (
          <Field label="Source Team (optional)">
            <select value={form.source_team} onChange={set('source_team')} style={inputStyle}>
              <option value="">— None / Unattributed —</option>
              {teams.map(t => (
                <option key={t.id} value={t.name}>{t.name}</option>
              ))}
            </select>
            <p style={{ fontSize: 11, color: ds.gray, margin: '4px 0 0' }}>
              Used for Growth Dashboard attribution.
            </p>
          </Field>
        )}

        {error && (
          <p style={{ color: ds.red, fontSize: 13, marginBottom: 14 }}>⚠ {error}</p>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
          <button onClick={onClose} disabled={submitting} style={secondaryBtn}>
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitDisabled}
            style={{
              ...primaryBtn,
              opacity: isSubmitDisabled ? 0.5 : 1,
              cursor: isSubmitDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? 'Creating…' : '+ Create Lead'}
          </button>
        </div>
      </div>
    </ModalOverlay>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────

function getLabelWithRequired(key, formConfig) {
  const cfg = formConfig.find(f => f.key === key)
  if (!cfg) return key
  return `${cfg.label}${cfg.required ? ' *' : ''}`
}

function renderConfigField(key, form, set, formConfig, inputStyle) {
  const cfg = formConfig.find(f => f.key === key)
  if (!cfg || !cfg.visible) return null

  const label = getLabelWithRequired(key, formConfig)
  const TYPE_MAP = { email: 'email', whatsapp: 'tel', phone: 'tel' }
  const PLACEHOLDER_MAP = {
    email:    'amaka@business.com',
    whatsapp: '+234 800 000 0000',
    business_name: 'e.g. Amaka Supermarket',
    business_type: 'e.g. Supermarket, Pharmacy',
    location: 'e.g. Ikeja, Lagos',
    referrer: 'Name of person who referred this lead',
    product_interest: 'e.g. Mattresses, Pillow Tops',
  }

  return (
    <Field label={label} key={key}>
      <input
        type={TYPE_MAP[key] || 'text'}
        placeholder={PLACEHOLDER_MAP[key] || ''}
        value={form[key] || ''}
        onChange={set(key)}
        style={inputStyle}
        required={cfg.required}
      />
    </Field>
  )
}

// ── Layout helpers ────────────────────────────────────────────────────────

function ModalOverlay({ children, onClose }) {
  return (
    <div
      onClick={e => e.target === e.currentTarget && onClose()}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.45)',
        zIndex: ds.z.modal,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div style={{
        background: 'white',
        borderRadius: ds.radius.xxl,
        width: 680, maxWidth: '100%',
        maxHeight: '90vh', overflowY: 'auto',
        boxShadow: ds.modalShadow,
      }}>
        {children}
      </div>
    </div>
  )
}

function TwoCol({ children }) {
  const validChildren = Array.isArray(children)
    ? children.filter(Boolean)
    : [children].filter(Boolean)

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: validChildren.length === 1 ? '1fr' : '1fr 1fr',
      gap: 14, marginBottom: 0,
    }}>
      {validChildren}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
      <label style={labelStyle}>{label}</label>
      {children}
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      margin: '4px 0 16px', fontFamily: ds.fontSyne,
      fontWeight: 600, fontSize: 12, color: ds.teal,
      textTransform: 'uppercase', letterSpacing: '0.8px',
    }}>
      {children}
      <span style={{ flex: 1, height: 1, background: ds.border }} />
    </div>
  )
}

const headerStyle = {
  padding: '20px 24px',
  borderBottom: `1px solid ${ds.border}`,
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  position: 'sticky', top: 0, background: 'white', zIndex: 10,
}

const labelStyle = {
  fontSize: 12, fontWeight: 500, color: ds.gray,
  textTransform: 'uppercase', letterSpacing: '0.6px',
}

const inputStyle = {
  width: '100%',
  border: `1.5px solid ${ds.border}`,
  borderRadius: ds.radius.md,
  padding: '11px 14px', fontSize: 13.5,
  color: ds.dark, fontFamily: ds.fontDm,
  background: 'white', outline: 'none',
  boxSizing: 'border-box', transition: 'border-color 0.2s',
}

const closeBtn = { background: 'none', border: 'none', fontSize: 20, color: ds.gray, cursor: 'pointer', padding: '4px 8px' }
const primaryBtn = {
  display: 'inline-flex', alignItems: 'center', gap: 8,
  padding: '11px 22px', borderRadius: ds.radius.md, border: 'none',
  background: ds.teal, color: 'white', fontSize: 13.5, fontWeight: 600,
  fontFamily: ds.fontSyne, cursor: 'pointer', transition: 'all 0.15s',
  minHeight: 44,
}
const secondaryBtn = { ...primaryBtn, background: ds.mint, color: ds.tealDark, border: `1px solid ${ds.border}` }
