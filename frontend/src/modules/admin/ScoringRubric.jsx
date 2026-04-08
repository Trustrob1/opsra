/**
 * frontend/src/modules/admin/ScoringRubric.jsx
 * Admin panel for configuring the org-level AI lead scoring rubric.
 * Feature 4 — Module 01 gaps.
 *
 * Reads from  GET  /api/v1/admin/scoring-rubric
 * Saves to    PATCH /api/v1/admin/scoring-rubric
 *
 * When all fields are blank, the AI falls back to its generic scoring prompt
 * (backward compatible — Ovaloop works before they fill this in).
 *
 * Rubric fields:
 *   scoring_business_context        — what does this org sell? who is the ideal lead?
 *   scoring_hot_criteria            — what makes a lead immediately ready to buy?
 *   scoring_warm_criteria           — what makes a lead interested but not urgent?
 *   scoring_cold_criteria           — what makes a lead unlikely or not yet ready?
 *   scoring_qualification_questions — WhatsApp follow-up questions for thin leads
 */
import { useState, useEffect } from 'react'
import { getScoringRubric, updateScoringRubric } from '../../services/admin.service'
import { ds } from '../../utils/ds'

const FIELDS = [
  {
    key:         'scoring_business_context',
    label:       'Business Context',
    hint:        'Describe what your business sells and who the ideal customer is. The AI uses this to understand what "a good lead" means for your org.',
    placeholder: 'e.g. We sell POS and inventory management software to Nigerian retailers with 1–20 branches. An ideal lead is a retailer actively managing stock manually who is ready to adopt software.',
    rows:        4,
  },
  {
    key:         'scoring_hot_criteria',
    label:       'Hot Lead Criteria',
    hint:        'What signals make a lead immediately sales-ready? Be specific.',
    placeholder: 'e.g. 3+ branches, actively losing stock due to poor tracking, has a budget, ready to demo within the week.',
    rows:        3,
  },
  {
    key:         'scoring_warm_criteria',
    label:       'Warm Lead Criteria',
    hint:        'What signals indicate interest but not immediate urgency?',
    placeholder: 'e.g. 1–2 branches, interested in solving the problem but not in a rush, gathering information.',
    rows:        3,
  },
  {
    key:         'scoring_cold_criteria',
    label:       'Cold Lead Criteria',
    hint:        'What signals suggest the lead is unlikely to convert soon?',
    placeholder: 'e.g. No clear problem stated, very small operation (single shop), just browsing with no timeline.',
    rows:        3,
  },
  {
    key:         'scoring_qualification_questions',
    label:       'Qualification Questions',
    hint:        'Optional. When a WhatsApp lead arrives with limited info, these questions help the AI gather what it needs to score accurately.',
    placeholder: 'e.g.\n1. How many branches or locations do you currently manage?\n2. Are you using any software to track your stock right now?\n3. What is your biggest challenge with inventory today?',
    rows:        4,
  },
]

export default function ScoringRubric() {
  const [form, setForm]       = useState({
    scoring_business_context:        '',
    scoring_hot_criteria:            '',
    scoring_warm_criteria:           '',
    scoring_cold_criteria:           '',
    scoring_qualification_questions: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    getScoringRubric()
      .then(res => {
        // getScoringRubric returns r.data.data — the rubric fields directly
        if (res) {
          setForm(prev => ({
            ...prev,
            scoring_business_context:        res.scoring_business_context        ?? '',
            scoring_hot_criteria:            res.scoring_hot_criteria            ?? '',
            scoring_warm_criteria:           res.scoring_warm_criteria           ?? '',
            scoring_cold_criteria:           res.scoring_cold_criteria           ?? '',
            scoring_qualification_questions: res.scoring_qualification_questions ?? '',
          }))
        }
      })
      .catch(() => setError('Failed to load scoring rubric.'))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      await updateScoringRubric(form)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return (
    <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
      Loading scoring rubric…
    </div>
  )

  return (
    <div style={{ maxWidth: 780 }}>

      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 8px' }}>
          AI Lead Scoring Rubric
        </h2>
        <p style={{ fontSize: 13.5, color: '#5a8a9f', margin: 0, lineHeight: 1.6 }}>
          Define how the AI should score leads for your organisation. When these fields are filled in, the AI
          scores against your specific criteria instead of its generic defaults.
          Leave blank to use the built-in scoring behaviour.
        </p>
      </div>

      {/* Fields */}
      {FIELDS.map(f => (
        <div key={f.key} style={{ marginBottom: 24 }}>
          <label style={{
            display:      'block',
            fontSize:     13,
            fontWeight:   600,
            color:        '#0a1a24',
            marginBottom: 4,
            fontFamily:   ds.fontDm,
          }}>
            {f.label}
          </label>
          <p style={{ fontSize: 12, color: '#5a8a9f', margin: '0 0 6px', lineHeight: 1.5 }}>
            {f.hint}
          </p>
          <textarea
            rows={f.rows}
            value={form[f.key]}
            onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
            placeholder={f.placeholder}
            style={{
              width:        '100%',
              border:       '1.5px solid #d1e0ea',
              borderRadius: 8,
              padding:      '10px 12px',
              fontSize:     13,
              color:        '#0a1a24',
              fontFamily:   ds.fontDm,
              lineHeight:   1.6,
              resize:       'vertical',
              outline:      'none',
              boxSizing:    'border-box',
              background:   'white',
            }}
          />
        </div>
      ))}

      {/* Footer */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, paddingTop: 8 }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background:   saving ? '#015F6B' : ds.teal,
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '10px 24px',
            fontSize:     14,
            fontWeight:   600,
            fontFamily:   ds.fontSyne,
            cursor:       saving ? 'not-allowed' : 'pointer',
            transition:   'background 0.2s',
          }}
        >
          {saving ? 'Saving…' : 'Save Rubric'}
        </button>

        {saved && (
          <span style={{ fontSize: 13, color: '#059669', fontWeight: 600 }}>
            ✓ Saved
          </span>
        )}
        {error && (
          <span style={{ fontSize: 13, color: '#DC2626' }}>
            ⚠ {error}
          </span>
        )}
      </div>

      {/* Info box */}
      <div style={{
        marginTop:    28,
        background:   '#f0f8fb',
        border:       '1px solid #bcd8e4',
        borderRadius: 10,
        padding:      '14px 16px',
        fontSize:     12.5,
        color:        '#375a6a',
        lineHeight:   1.6,
      }}>
        <strong>How this works:</strong> When a lead is scored (automatically on arrival or via the
        "Score with AI" button), the AI receives your rubric as context before making its decision.
        Changes here take effect immediately on the next scoring request — existing scores are not
        retroactively updated.
      </div>
    </div>
  )
}
