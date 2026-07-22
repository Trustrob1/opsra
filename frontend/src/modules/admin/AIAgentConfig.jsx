/**
 * frontend/src/modules/admin/AIAgentConfig.jsx
 * AI-AGENT-1C — AI Agent settings panel.
 *
 * Rendered inside WASalesModeConfig.jsx when a WhatsApp number's mode is
 * set (or being set) to 'ai_agent'. Self-contained — fetches and saves its
 * own org-level ai_agent_config independently of the parent's number list.
 *
 * Pattern 13: no react-router-dom — parent handles navigation.
 * Pattern 12: org_id never in payload — derived from JWT server-side.
 * All interactive elements >= 44px tap target (Section 13.3).
 */
import { useState, useEffect, useCallback } from 'react'
import { getAIAgentConfig, updateAIAgentConfig } from '../../services/admin.service'
import { useIsMobile } from '../../hooks/useIsMobile'
import { ds } from '../../utils/ds'

const BUSINESS_MODELS = [
  { value: 'physical_product', label: 'Physical Product' },
  { value: 'software',         label: 'Software' },
  { value: 'service',          label: 'Service' },
  { value: 'other',            label: 'Other' },
]

const CONVERSION_ACTIONS = [
  { value: 'checkout_link',     label: 'Send a checkout link' },
  { value: 'book_consultation', label: 'Book a consultation' },
  { value: 'request_quote',     label: 'Request a quote' },
  { value: 'demo_booking',      label: 'Book a demo' },
  { value: 'handoff_only',      label: 'Hand off to a rep only' },
]

// Same allow-list as qualification_flow (Technical Spec) — kept in sync with
// _VALID_LEAD_FIELDS in app/routers/admin.py.
const LEAD_FIELDS = [
  { value: 'business_name',  label: 'Business Name' },
  { value: 'business_type',  label: 'Business Type' },
  { value: 'location',       label: 'Location' },
  { value: 'problem_stated', label: 'Problem Stated' },
  { value: 'branches',       label: 'Branches' },
]

const EMPTY_CONFIG = {
  business_model: 'physical_product',
  conversion_action: 'checkout_link',
  qualifying_criteria: '',
  disqualification_criteria: '',
  fields_to_extract: [],
  tone_instructions: '',
  escalation: { value_threshold_enabled: false, value_threshold_amount: null },
  max_turns_before_escalation: 20,
  sales_methodology: 'none',
  custom_methodology_name: '',
  custom_methodology_instructions: '',
  expert_persona_name: '',
  expert_persona_bio: '',
  trust_proof_images: [],
}

const SALES_METHODOLOGIES = [
  { value: 'none',           label: 'No specific methodology (default)' },
  { value: 'rackham_spin',   label: 'The Rackham Method — SPIN Selling', desc: 'Situation → Problem → Implication → Need-payoff. Best for considered, higher-value purchases.' },
  { value: 'challenger',     label: 'The Challenger Method — Dixon & Adamson', desc: 'Teach, tailor, and take control of the conversation.' },
  { value: 'sandler',        label: 'The Sandler Method', desc: 'Get the customer to surface their own pain and budget early.' },
  { value: 'voss',           label: 'The Voss Method — Tactical Empathy', desc: 'Label emotions, ask calibrated questions, never rush the close.' },
  { value: 'gitomer_ziglar', label: 'The Gitomer-Ziglar Method', desc: 'Lead with emotional benefit, always end with a clear next step.' },
  { value: 'custom',         label: 'Custom — define your own' },
]

const inputStyle = {
  width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: 8,
  padding: '9px 12px', fontSize: 13.5, fontFamily: 'inherit',
  color: ds.dark, boxSizing: 'border-box', minHeight: 44,
}

const labelStyle = {
  fontSize: 12, fontWeight: 600, color: ds.gray,
  textTransform: 'uppercase', letterSpacing: '0.4px',
  margin: '0 0 6px', display: 'block',
}

function Field({ label, hint, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <label style={labelStyle}>{label}</label>
      {children}
      {hint && <p style={{ fontSize: 12, color: ds.gray, margin: '5px 0 0' }}>{hint}</p>}
    </div>
  )
}

export default function AIAgentConfig() {
  const isMobile = useIsMobile()
  const [config, setConfig]   = useState(EMPTY_CONFIG)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [saved, setSaved]     = useState(false)

  useEffect(() => {
    let mounted = true
    getAIAgentConfig()
      .then(data => {
        if (!mounted) return
        setConfig({ ...EMPTY_CONFIG, ...(data || {}) })
      })
      .catch(() => { if (mounted) setError('Could not load AI Agent settings.') })
      .finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [])

  const update = useCallback((patch) => {
    setConfig(prev => ({ ...prev, ...patch }))
    setSaved(false)
  }, [])

  const updateField = useCallback((idx, patch) => {
    setConfig(prev => {
      const next = [...(prev.fields_to_extract || [])]
      next[idx] = { ...next[idx], ...patch }
      return { ...prev, fields_to_extract: next }
    })
    setSaved(false)
  }, [])

  const addField = useCallback(() => {
    setConfig(prev => {
      const current = prev.fields_to_extract || []
      if (current.length >= 5) return prev
      return { ...prev, fields_to_extract: [...current, { answer_key: '', map_to_lead_field: null }] }
    })
  }, [])

  const removeField = useCallback((idx) => {
    setConfig(prev => {
      const next = [...(prev.fields_to_extract || [])]
      next.splice(idx, 1)
      return { ...prev, fields_to_extract: next }
    })
    setSaved(false)
  }, [])

  async function handleSave() {
    if (!config.qualifying_criteria?.trim()) {
      setError('Qualifying criteria is required before the AI Agent can be activated.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const saved_ = await updateAIAgentConfig(config)
      setConfig({ ...EMPTY_CONFIG, ...(saved_ || config) })
      setSaved(true)
    } catch (err) {
      const detail = err?.response?.data?.detail
      const msg = (typeof detail === 'object' ? detail?.message : detail) ?? 'Failed to save settings.'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '32px 0' }}>
        <div style={{
          width: 26, height: 26, borderRadius: '50%',
          border: `3px solid ${ds.teal}`, borderTopColor: 'transparent',
          animation: 'aiagentspin 0.7s linear infinite',
        }} />
        <style>{'@keyframes aiagentspin { to { transform: rotate(360deg); } }'}</style>
      </div>
    )
  }

  const escalation = config.escalation || {}
  const fields = config.fields_to_extract || []

  return (
    <div style={{
      marginTop: 20, paddingTop: 20, borderTop: `1px solid ${ds.border}`,
    }}>
      <h3 style={{
        fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15,
        color: '#d97706', margin: '0 0 4px',
      }}>
        AI Agent Settings
      </h3>
      <p style={{ fontSize: 12.5, color: ds.gray, margin: '0 0 18px' }}>
        These settings apply org-wide, to every number running in AI Agent mode.
      </p>

      <Field label="Business model">
        <select
          value={config.business_model}
          onChange={e => update({ business_model: e.target.value })}
          style={{ ...inputStyle, cursor: 'pointer' }}
        >
          {BUSINESS_MODELS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>

      <Field label="Conversion action" hint="What should the agent try to get the customer to do once qualified?">
        <select
          value={config.conversion_action}
          onChange={e => update({ conversion_action: e.target.value })}
          style={{ ...inputStyle, cursor: 'pointer' }}
        >
          {CONVERSION_ACTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>

      <Field label="Sales methodology" hint="Shapes how the agent structures the conversation — not just what it says.">
        <select
          value={config.sales_methodology || 'none'}
          onChange={e => update({ sales_methodology: e.target.value })}
          style={{ ...inputStyle, cursor: 'pointer' }}
        >
          {SALES_METHODOLOGIES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        {(() => {
          const selected = SALES_METHODOLOGIES.find(m => m.value === (config.sales_methodology || 'none'))
          return selected?.desc ? (
            <p style={{ fontSize: 12, color: ds.gray, margin: '5px 0 0' }}>{selected.desc}</p>
          ) : null
        })()}
      </Field>

      {config.sales_methodology === 'custom' && (
        <>
          <Field label="Methodology name" hint="E.g. name it after yourself or your own sales framework.">
            <input
              type="text"
              value={config.custom_methodology_name || ''}
              onChange={e => update({ custom_methodology_name: e.target.value.slice(0, 100) })}
              placeholder="e.g. The Robert Method"
              style={inputStyle}
            />
          </Field>
          <Field label="Methodology instructions" hint={`How should the agent structure conversations? (${(config.custom_methodology_instructions || '').length}/2000)`}>
            <textarea
              value={config.custom_methodology_instructions || ''}
              onChange={e => update({ custom_methodology_instructions: e.target.value.slice(0, 2000) })}
              rows={4}
              style={{ ...inputStyle, resize: 'vertical', minHeight: 100 }}
              placeholder="e.g. Always ask about their timeline before price. Never discount. Close by asking a direct yes/no question."
            />
          </Field>
        </>
      )}

      <Field label="Expert persona (optional)" hint="Give the agent a named identity and expertise — e.g. a 'Sleep Specialist' who shares genuine educational content, not just sales pitches.">
        <input
          type="text"
          value={config.expert_persona_name || ''}
          onChange={e => update({ expert_persona_name: e.target.value.slice(0, 100) })}
          placeholder="e.g. Comfort Advisor"
          style={{ ...inputStyle, marginBottom: 8 }}
        />
        <textarea
          value={config.expert_persona_bio || ''}
          onChange={e => update({ expert_persona_bio: e.target.value.slice(0, 1000) })}
          rows={3}
          style={{ ...inputStyle, resize: 'vertical', minHeight: 70 }}
          placeholder="e.g. in-house sleep and comfort specialist, sharing tips on sleep hygiene and choosing the right mattress firmness"
        />
      </Field>

      <Field label="Trust proof images (optional)" hint="Real image URLs only (certifications, storefront, registration docs) — sent automatically when a customer expresses skepticism. Never invented if left empty.">
        <textarea
          value={(config.trust_proof_images || []).join('\n')}
          onChange={e => update({ trust_proof_images: e.target.value.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 5) })}
          rows={2}
          style={{ ...inputStyle, resize: 'vertical', minHeight: 50 }}
          placeholder="One image URL per line, e.g. https://.../cac-certificate.jpg"
        />
      </Field>

      <Field
        label="Qualifying criteria *"
        hint={`What does a ready-to-close lead look like? Required before AI Agent can be activated. (${(config.qualifying_criteria || '').length}/1000)`}
      >
        <textarea
          value={config.qualifying_criteria || ''}
          onChange={e => update({ qualifying_criteria: e.target.value.slice(0, 1000) })}
          rows={3}
          style={{ ...inputStyle, resize: 'vertical', minHeight: 80 }}
          placeholder="e.g. Has a stated budget, a clear timeline, and confirmed exactly what they need."
        />
      </Field>

      <Field
        label="Disqualification criteria"
        hint={`Optional — signals that mean mark the lead lost immediately. (${(config.disqualification_criteria || '').length}/1000)`}
      >
        <textarea
          value={config.disqualification_criteria || ''}
          onChange={e => update({ disqualification_criteria: e.target.value.slice(0, 1000) })}
          rows={2}
          style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }}
          placeholder="e.g. Just browsing, no budget, or outside the area/market we serve."
        />
      </Field>

      <Field
        label="Tone & brand voice"
        hint={`Optional — this is a good place for detailed regional/brand style notes. (${(config.tone_instructions || '').length}/1500)`}
      >
        <textarea
          value={config.tone_instructions || ''}
          onChange={e => update({ tone_instructions: e.target.value.slice(0, 1500) })}
          rows={5}
          style={{ ...inputStyle, resize: 'vertical', minHeight: 130 }}
          placeholder="e.g. Warm, casual, uses first names, avoids heavy sales language."
        />
      </Field>

      <Field label="Fields to extract" hint="Up to 5 — what should the agent capture from the conversation onto the lead record?">
        {fields.map((f, idx) => (
          <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
            <input
              type="text"
              value={f.answer_key || ''}
              onChange={e => updateField(idx, { answer_key: e.target.value })}
              placeholder="answer_key (e.g. what_they_need)"
              style={{ ...inputStyle, flex: 1 }}
            />
            <select
              value={f.map_to_lead_field || ''}
              onChange={e => updateField(idx, { map_to_lead_field: e.target.value || null })}
              style={{ ...inputStyle, flex: 1, cursor: 'pointer' }}
            >
              <option value="">— Map to lead field —</option>
              {LEAD_FIELDS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <button
              type="button" onClick={() => removeField(idx)}
              style={{
                minHeight: 44, minWidth: 44, border: 'none', borderRadius: 8,
                background: '#fef2f2', color: ds.red, fontSize: 16, cursor: 'pointer',
              }}
              aria-label="Remove field"
            >
              ×
            </button>
          </div>
        ))}
        {fields.length < 5 && (
          <button
            type="button" onClick={addField}
            style={{
              minHeight: 44, padding: '0 16px', borderRadius: 8,
              border: `1.5px dashed ${ds.border}`, background: 'white',
              color: ds.teal, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            + Add field
          </button>
        )}
      </Field>

      <Field label="Max turns before escalation" hint="5–50. The agent force-escalates to a rep if this is exceeded, regardless of what it thinks it's doing.">
        <input
          type="number" min={5} max={50}
          value={config.max_turns_before_escalation ?? 20}
          onChange={e => update({ max_turns_before_escalation: Math.max(5, Math.min(50, Number(e.target.value) || 20)) })}
          style={{ ...inputStyle, maxWidth: 120 }}
        />
      </Field>

      <Field label="Escalate on high-value cart">
        <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', minHeight: 44 }}>
          <input
            type="checkbox"
            checked={!!escalation.value_threshold_enabled}
            onChange={e => update({
              escalation: { ...escalation, value_threshold_enabled: e.target.checked },
            })}
            style={{ width: 18, height: 18, cursor: 'pointer' }}
          />
          <span style={{ fontSize: 13.5, color: ds.dark }}>
            Automatically escalate when the cart exceeds a value threshold
          </span>
        </label>
        {escalation.value_threshold_enabled && (
          <input
            type="number" min={0}
            value={escalation.value_threshold_amount ?? ''}
            onChange={e => update({
              escalation: { ...escalation, value_threshold_amount: Number(e.target.value) || 0 },
            })}
            placeholder="Threshold amount"
            style={{ ...inputStyle, maxWidth: 200, marginTop: 8 }}
          />
        )}
      </Field>

      {error && <p style={{ color: ds.red, fontSize: 13, margin: '0 0 12px' }}>⚠ {error}</p>}
      {saved && !error && <p style={{ color: ds.teal, fontSize: 13, margin: '0 0 12px' }}>✓ Saved</p>}

      <button
        type="button" onClick={handleSave} disabled={saving}
        style={{
          minHeight: 44, padding: '0 22px', borderRadius: 8, border: 'none',
          background: saving ? '#9ca3af' : '#d97706', color: 'white',
          fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne,
          cursor: saving ? 'not-allowed' : 'pointer',
        }}
      >
        {saving ? 'Saving…' : 'Save AI Agent Settings'}
      </button>
    </div>
  )
}
