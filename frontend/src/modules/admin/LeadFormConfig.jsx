/**
 * frontend/src/modules/admin/LeadFormConfig.jsx
 * LEAD-FORM-CONFIG — Admin settings panel for configurable lead capture form.
 *
 * Lists all 9 configurable fields. Per field:
 *   - Visible / Hidden toggle
 *   - When visible: Required / Optional toggle
 *   - Label: editable text input (max 50 chars, saves on blur)
 * Always-mandatory fields (full_name, phone) shown greyed-out at top of preview.
 * Live preview panel on right: shows what LeadCreateModal will look like.
 * Reset to defaults button.
 * Save → PATCH /api/v1/admin/lead-form-config
 *
 * Pattern 50: axios + _h() + ${BASE} prefix.
 * Pattern 51: full rewrite only.
 * Mobile-first: stacks to single column below 768px (Section 13.3).
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getLeadFormConfig, updateLeadFormConfig } from '../../services/admin.service'

const DEFAULT_FIELDS = [
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

const FIELD_KEY_LABELS = {
  email:            'Email Address',
  whatsapp:         'WhatsApp Number',
  business_name:    'Business Name',
  business_type:    'Business Type',
  location:         'Location',
  branches:         'No. of Branches',
  problem_stated:   'Problem Stated',
  product_interest: 'Product Interest',
  referrer:         'Referred By',
}

export default function LeadFormConfig() {
  const [fields, setFields]   = useState(DEFAULT_FIELDS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [saved, setSaved]     = useState(false)
  const [error, setError]     = useState(null)

  useEffect(() => {
    getLeadFormConfig()
      .then(data => {
        if (data?.fields?.length) setFields(data.fields)
      })
      .catch(() => {}) // fail silently — default fields shown
      .finally(() => setLoading(false))
  }, [])

  const updateField = useCallback((key, updates) => {
    setFields(prev => prev.map(f =>
      f.key === key
        ? {
            ...f,
            ...updates,
            // If hiding a field, also clear required
            ...(updates.visible === false ? { required: false } : {}),
          }
        : f
    ))
    setSaved(false)
  }, [])

  const resetToDefaults = () => {
    setFields(DEFAULT_FIELDS)
    setSaved(false)
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      await updateLeadFormConfig({ fields })
      setSaved(true)
    } catch (err) {
      const msg = err?.response?.data?.detail?.message
        || err?.response?.data?.detail
        || 'Failed to save. Please try again.'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: ds.gray, fontSize: 14 }}>
        Loading form configuration…
      </div>
    )
  }

  const visibleFields = fields.filter(f => f.visible)

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: '0 0 6px' }}>
          📋 Lead Form Configuration
        </h2>
        <p style={{ fontSize: 13.5, color: ds.gray, margin: 0, lineHeight: 1.5 }}>
          Control which fields appear on the lead capture form for your organisation.
          <strong style={{ color: ds.dark }}> Full Name</strong> and <strong style={{ color: ds.dark }}>Phone</strong> are always required and cannot be hidden.
        </p>
      </div>

      {/* Main layout: config + preview */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) minmax(0,380px)',
        gap: 24,
        alignItems: 'start',
      }}
        className="lead-form-config-grid"
      >
        {/* ── Left: field configurator ── */}
        <div>
          {/* Always-on fields (informational) */}
          <div style={sectionCard}>
            <div style={sectionTitle}>Always Required</div>
            <p style={sectionDesc}>These fields cannot be hidden or made optional.</p>
            {['full_name', 'phone'].map(key => (
              <div key={key} style={{ ...fieldRow, opacity: 0.55 }}>
                <div style={{ flex: 1 }}>
                  <div style={fieldKeyLabel}>{FIELD_KEY_LABELS[key] || key}</div>
                </div>
                <div style={pillGroup}>
                  <span style={{ ...pill, background: '#e8f5e9', color: '#2e7d32' }}>Visible</span>
                  <span style={{ ...pill, background: '#e8f5e9', color: '#2e7d32' }}>Required</span>
                </div>
              </div>
            ))}
          </div>

          {/* Configurable fields */}
          <div style={sectionCard}>
            <div style={sectionTitle}>Configurable Fields</div>
            <p style={sectionDesc}>Toggle visibility and required status. Edit labels to match your business language.</p>

            {fields.map(field => (
              <FieldRow
                key={field.key}
                field={field}
                onChange={updates => updateField(field.key, updates)}
              />
            ))}
          </div>

          {/* Actions */}
          {error && (
            <div style={{ background: '#fff5f5', border: '1px solid #fed7d7', borderRadius: 8, padding: '10px 14px', marginBottom: 14, fontSize: 13, color: ds.red }}>
              ⚠ {error}
            </div>
          )}
          {saved && (
            <div style={{ background: '#f0fff4', border: '1px solid #9ae6b4', borderRadius: 8, padding: '10px 14px', marginBottom: 14, fontSize: 13, color: '#276749' }}>
              ✓ Configuration saved successfully
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button onClick={resetToDefaults} style={secondaryBtn}>
              Reset to Defaults
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{ ...primaryBtn, opacity: saving ? 0.6 : 1, cursor: saving ? 'not-allowed' : 'pointer' }}
            >
              {saving ? 'Saving…' : 'Save Configuration'}
            </button>
          </div>
        </div>

        {/* ── Right: live preview ── */}
        <div style={{ position: 'sticky', top: 20 }}>
          <div style={sectionCard}>
            <div style={sectionTitle}>Live Preview</div>
            <p style={sectionDesc}>Shows how the lead creation form will look with current settings.</p>

            <div style={{ background: ds.light, borderRadius: 10, padding: '16px 20px' }}>
              {/* Always-on preview fields */}
              <PreviewField label="Full Name *" required />
              <PreviewField label="Lead Source *" required isSelect />

              {visibleFields.length === 0 && (
                <p style={{ fontSize: 12.5, color: ds.gray, textAlign: 'center', margin: '12px 0' }}>
                  No optional fields visible
                </p>
              )}

              {visibleFields.map(f => (
                <PreviewField
                  key={f.key}
                  label={`${f.label}${f.required ? ' *' : ''}`}
                  required={f.required}
                  isTextarea={f.key === 'problem_stated' || f.key === 'product_interest'}
                />
              ))}

              <div style={{ marginTop: 14, padding: '10px 14px', background: ds.teal, borderRadius: 8, textAlign: 'center', fontSize: 13, fontFamily: ds.fontSyne, fontWeight: 600, color: 'white' }}>
                + Create Lead
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Mobile responsiveness */}
      <style>{`
        @media (max-width: 768px) {
          .lead-form-config-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  )
}

// ── Field row component ────────────────────────────────────────────────────

function FieldRow({ field, onChange }) {
  const [labelValue, setLabelValue] = useState(field.label)

  // Sync when parent resets
  useEffect(() => { setLabelValue(field.label) }, [field.label])

  const handleLabelBlur = () => {
    const trimmed = labelValue.trim().slice(0, 50)
    if (!trimmed) { setLabelValue(field.label); return }
    if (trimmed !== field.label) onChange({ label: trimmed })
  }

  return (
    <div style={fieldRow}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={fieldKeyLabel}>{field.key.replace(/_/g, ' ')}</div>
        <input
          type="text"
          value={labelValue}
          maxLength={50}
          onChange={e => setLabelValue(e.target.value)}
          onBlur={handleLabelBlur}
          onKeyDown={e => e.key === 'Enter' && e.target.blur()}
          placeholder="Field label"
          style={labelInput}
        />
      </div>
      <div style={pillGroup}>
        {/* Visible toggle */}
        <Toggle
          active={field.visible}
          onLabel="Visible"
          offLabel="Hidden"
          activeColor={ds.teal}
          inactiveColor={ds.gray}
          onToggle={() => onChange({ visible: !field.visible })}
        />
        {/* Required toggle — only when visible */}
        {field.visible && (
          <Toggle
            active={field.required}
            onLabel="Required"
            offLabel="Optional"
            activeColor="#d97706"
            inactiveColor={ds.gray}
            onToggle={() => onChange({ required: !field.required })}
          />
        )}
      </div>
    </div>
  )
}

function Toggle({ active, onLabel, offLabel, activeColor, inactiveColor, onToggle }) {
  return (
    <button
      onClick={onToggle}
      style={{
        ...pill,
        background: active ? activeColor + '18' : '#f1f5f9',
        color: active ? activeColor : inactiveColor,
        border: `1.5px solid ${active ? activeColor : ds.border}`,
        cursor: 'pointer',
        fontWeight: 600,
        minWidth: 72,
        transition: 'all 0.15s',
      }}
    >
      {active ? onLabel : offLabel}
    </button>
  )
}

function PreviewField({ label, required, isSelect, isTextarea }) {
  const S = {
    wrapper: { marginBottom: 12 },
    label: { display: 'block', fontSize: 11, fontWeight: 600, color: ds.dark, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' },
    input: { width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: 7, padding: '9px 11px', fontSize: 12.5, color: ds.gray, background: 'white', boxSizing: 'border-box', fontFamily: ds.fontDm },
  }
  return (
    <div style={S.wrapper}>
      <label style={S.label}>{label}</label>
      {isTextarea
        ? <textarea style={{ ...S.input, minHeight: 56, resize: 'none' }} disabled />
        : isSelect
          ? <select style={S.input} disabled><option>— Select —</option></select>
          : <input type="text" style={S.input} disabled />
      }
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────

const sectionCard = {
  background: 'white',
  border: `1px solid ${ds.border}`,
  borderRadius: 12,
  padding: '18px 20px',
  marginBottom: 16,
}

const sectionTitle = {
  fontFamily: ds.fontSyne,
  fontWeight: 700,
  fontSize: 13,
  color: ds.dark,
  marginBottom: 4,
}

const sectionDesc = {
  fontSize: 12.5,
  color: ds.gray,
  marginBottom: 16,
  lineHeight: 1.5,
}

const fieldRow = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '10px 0',
  borderBottom: `1px solid ${ds.border}`,
}

const fieldKeyLabel = {
  fontSize: 11,
  color: ds.gray,
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  marginBottom: 4,
}

const labelInput = {
  width: '100%',
  border: `1.5px solid ${ds.border}`,
  borderRadius: 7,
  padding: '7px 10px',
  fontSize: 13,
  fontFamily: ds.fontDm,
  color: ds.dark,
  background: 'white',
  outline: 'none',
  boxSizing: 'border-box',
}

const pillGroup = {
  display: 'flex',
  gap: 6,
  flexShrink: 0,
}

const pill = {
  padding: '4px 10px',
  borderRadius: 20,
  fontSize: 12,
  border: 'none',
  fontFamily: ds.fontDm,
  whiteSpace: 'nowrap',
}

const primaryBtn = {
  padding: '10px 22px',
  background: ds.teal,
  color: 'white',
  border: 'none',
  borderRadius: 8,
  fontFamily: ds.fontSyne,
  fontWeight: 600,
  fontSize: 13.5,
  cursor: 'pointer',
  minHeight: 44,
}

const secondaryBtn = {
  ...primaryBtn,
  background: 'white',
  color: ds.gray,
  border: `1.5px solid ${ds.border}`,
}
