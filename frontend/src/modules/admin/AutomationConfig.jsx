/**
 * frontend/src/modules/admin/AutomationConfig.jsx
 * Automation Config — configures automated actions that fire on pipeline events.
 *
 * Currently: Payment confirmation template auto-sent on lead conversion.
 * Pattern 51: full rewrite only — never sed.
 * Pattern 50: service calls via admin.service.js only.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getConversionTemplate, updateConversionTemplate } from '../../services/admin.service'

export default function AutomationConfig() {
  const [templateName,  setTemplateName]  = useState('')
  const [savedTemplate, setSavedTemplate] = useState('')
  const [loading,       setLoading]       = useState(true)
  const [saving,        setSaving]        = useState(false)
  const [saveMsg,       setSaveMsg]       = useState('')
  const [saveErr,       setSaveErr]       = useState('')

  const isDirty = templateName !== savedTemplate

  useEffect(() => {
    getConversionTemplate()
      .then(data => {
        const name = data?.template_name ?? ''
        setTemplateName(name)
        setSavedTemplate(name)
      })
      .catch(() => setSaveErr('Failed to load settings'))
      .finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setSaveMsg('')
    setSaveErr('')
    try {
      await updateConversionTemplate(templateName.trim())
      setSavedTemplate(templateName.trim())
      setSaveMsg('Automation settings saved')
      setTimeout(() => setSaveMsg(''), 3000)
    } catch (err) {
      const detail = err?.response?.data?.detail
      setSaveErr(
        (typeof detail === 'object' ? detail?.message : detail) ?? 'Failed to save'
      )
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 13 }}>
        Loading…
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 6px' }}>
          Automation Config
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0, lineHeight: 1.6 }}>
          Configure automated actions that fire on key events across your pipeline.
        </p>
      </div>

      {/* Conversion template card */}
      <div style={{
        background: '#F5FAFB', border: '1px solid #D6E8EC',
        borderRadius: 12, padding: '20px 22px', marginBottom: 24,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 16 }}>
          <div style={{ fontSize: 24, flexShrink: 0 }}>✅</div>
          <div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', marginBottom: 4 }}>
              Payment Confirmation Template
            </div>
            <div style={{ fontSize: 12.5, color: '#4a7a8a', lineHeight: 1.55 }}>
              Auto-sent via WhatsApp the moment a rep converts a lead to customer.
              Enter the template name exactly as it appears in Meta Business Manager.
              Leave blank to disable.
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            type="text"
            value={templateName}
            onChange={e => { setTemplateName(e.target.value); setSaveErr('') }}
            placeholder="e.g. payment_confirmation"
            style={{
              flex: 1, padding: '9px 13px', fontSize: 13.5,
              border: `1.5px solid ${isDirty ? ds.teal : '#D6E8EC'}`,
              borderRadius: 8, outline: 'none',
              fontFamily: ds.fontDm, color: '#0a1a24',
              background: 'white', transition: 'border-color 0.15s',
            }}
          />
          {isDirty && (
            <button
              onClick={() => { setTemplateName(savedTemplate); setSaveErr('') }}
              style={{
                padding: '9px 14px', background: 'white',
                border: '1.5px solid #D6E8EC', borderRadius: 8,
                fontSize: 13, color: '#7A9BAD', cursor: 'pointer',
                fontFamily: ds.fontDm,
              }}
            >
              Discard
            </button>
          )}
        </div>
      </div>

      {/* Unsaved changes banner */}
      {isDirty && (
        <div style={{
          background: '#FFFBEB', border: '1px solid #FDE68A',
          borderRadius: 8, padding: '10px 14px', marginBottom: 16,
          fontSize: 13, color: '#92400E',
        }}>
          ⚠ You have unsaved changes. Click Save to apply.
        </div>
      )}

      {/* Save */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleSave}
          disabled={saving || !isDirty}
          style={{
            padding: '10px 24px', background: ds.teal, color: 'white',
            border: 'none', borderRadius: 9, fontSize: 13.5, fontWeight: 600,
            fontFamily: ds.fontSyne,
            cursor: (saving || !isDirty) ? 'not-allowed' : 'pointer',
            opacity: (saving || !isDirty) ? 0.55 : 1,
          }}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        {saveMsg && <span style={{ fontSize: 13, color: '#27AE60' }}>✓ {saveMsg}</span>}
        {saveErr && <span style={{ fontSize: 13, color: '#C0392B' }}>⚠ {saveErr}</span>}
      </div>
    </div>
  )
}