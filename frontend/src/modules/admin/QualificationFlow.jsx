/**
 * frontend/src/modules/admin/QualificationFlow.jsx
 * WH-1b — Structured WhatsApp Qualification Flow builder.
 * QUAL-RECOMMEND — Post-qualification recommendation message config added.
 *
 * Sections:
 *   1. Opening Message      — textarea, max 500 chars, required
 *   2. Handoff Message      — textarea, max 500 chars, required
 *   3. Question Builder     — up to 5 questions, drag/reorder via up/down buttons
 *   4. Post-Qual Messages   — NEW: configurable strings for recommendation flow
 *   5. Save button
 *   6. WhatsApp Preview     — live preview panel (right column, unchanged)
 *
 * ds.teal for all accents.
 * Pattern 51: full rewrite required for any future edit — never sed.
 * Pattern 50: admin.service.js axios + _h() only.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

// ── Constants — all unchanged ─────────────────────────────────────────────────
const QUESTION_TYPES = [
  { value: 'multiple_choice', label: '🔘 Multiple Choice', desc: 'Up to 3 button options' },
  { value: 'list_select',     label: '📋 List Select',     desc: 'Up to 10 list options' },
  { value: 'free_text',       label: '✏️ Free Text',       desc: 'Lead types a response' },
  { value: 'yes_no',          label: '✅ Yes / No',        desc: '2-button Yes/No question' },
]

const LEAD_FIELD_OPTIONS = [
  { value: '',               label: '— None —' },
  { value: 'business_name',  label: 'Business Name' },
  { value: 'business_type',  label: 'Business Type' },
  { value: 'location',       label: 'Location' },
  { value: 'problem_stated', label: 'Problem / Need Stated' },
  { value: 'branches',       label: 'Branches / Locations' },
]

const EMPTY_QUESTION = () => ({
  id: `q${Date.now()}`,
  text: '',
  type: 'free_text',
  answer_key: '',
  map_to_lead_field: '',
  map_to_catalog_tag: '',
  options: [],
  required: true,
})

const MAX_QUESTIONS = 5

// ── QUAL-RECOMMEND: default text shown as placeholders ────────────────────────
// These match the hardcoded fallbacks in whatsapp_service.py exactly.
// When a field is left blank, the backend uses these same values.
const REC_DEFAULTS = {
  recommendation_intro:        '🛏️ Based on what you\'ve shared with us, we recommend:',
  pillow_upsell_message:       'We also carry a premium range of pillows that pair perfectly with your mattress. Would you like to see our pillow recommendations? 🛏️',
  pillow_recommendation_intro: 'Great choice! 🌟 Here\'s our pillow recommendation:',
  pillow_not_found_message:    'Our pillow range isn\'t listed online yet, but we carry them in-store. Our team will be happy to walk you through the options when you visit! 🛏️',
  post_qual_cta_text:          'What would you like to do next?',
  showroom_button_label:       '🏪 Visit Showroom',
  invoice_button_label:        '💳 Get Invoice',
  talk_to_sales_button_label:  '💬 Talk to Sales',
  showroom_confirmation:       'Perfect! Our team will be in touch shortly to confirm your showroom visit. We look forward to seeing you! 🏡',
  invoice_confirmation:        'Great choice! Our team will send your invoice and payment details shortly. 💳',
  talk_to_sales_confirmation:  'Our team will be in touch with you shortly! 😊',
}

export default function QualificationFlow() {
  // ── Existing state — all preserved exactly ───────────────────────────────
  const [opening, setOpening]     = useState('')
  const [handoff, setHandoff]     = useState('')
  const [questions, setQuestions] = useState([EMPTY_QUESTION()])
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)
  const [error, setError]         = useState(null)
  const [preview, setPreview]     = useState(0)

  // ── QUAL-RECOMMEND state — new, all optional ─────────────────────────────
  const [recIntro,       setRecIntro]       = useState('')
  const [pillowUpsell,   setPillowUpsell]   = useState('')
  const [pillowRecIntro, setPillowRecIntro] = useState('')
  const [pillowNotFound, setPillowNotFound] = useState('')
  const [ctaText,        setCtaText]        = useState('')
  const [showroomLabel,  setShowroomLabel]  = useState('')
  const [showroomEnabled, setShowroomEnabled] = useState(true)
  const [invoiceLabel,   setInvoiceLabel]   = useState('')
  const [talkSalesLabel, setTalkSalesLabel] = useState('')
  const [showroomConf,   setShowroomConf]   = useState('')
  const [invoiceConf,    setInvoiceConf]    = useState('')
  const [talkSalesConf,  setTalkSalesConf]  = useState('')

  // ── Collapsible for new section — collapsed by default unless values set ─
  const [recOpen, setRecOpen] = useState(false)

  // ── Load — existing logic preserved, new fields appended ─────────────────
  useEffect(() => {
    adminSvc.getQualificationFlow()
      .then(data => {
        const flow = (data || {}).qualification_flow || {}

        // Existing fields — unchanged
        setOpening(flow.opening_message || '')
        setHandoff(flow.handoff_message || '')
        if (flow.questions && flow.questions.length > 0) {
          setQuestions(flow.questions.map(q => ({
            ...q,
            map_to_lead_field: q.map_to_lead_field || '',
            map_to_catalog_tag: q.map_to_catalog_tag || '',
            required: q.required !== false,
            options: (q.options || []).map(opt => ({
              ...opt,
              tag_value: opt.tag_value || '',
            })),
          })))
        }

        // QUAL-RECOMMEND fields — new
        setRecIntro(flow.recommendation_intro              || '')
        setPillowUpsell(flow.pillow_upsell_message         || '')
        setPillowRecIntro(flow.pillow_recommendation_intro  || '')
        setPillowNotFound(flow.pillow_not_found_message     || '')
        setCtaText(flow.post_qual_cta_text                 || '')
        setShowroomLabel(flow.showroom_button_label         || '')
        setShowroomEnabled(flow.showroom_button_enabled !== false)
        setInvoiceLabel(flow.invoice_button_label           || '')
        setTalkSalesLabel(flow.talk_to_sales_button_label   || '')
        setShowroomConf(flow.showroom_confirmation          || '')
        setInvoiceConf(flow.invoice_confirmation            || '')
        setTalkSalesConf(flow.talk_to_sales_confirmation    || '')

        // Auto-expand if any rec fields are already saved
        const hasRecConfig = [
          flow.recommendation_intro, flow.pillow_upsell_message,
          flow.pillow_recommendation_intro, flow.pillow_not_found_message,
          flow.post_qual_cta_text, flow.showroom_button_label,
          flow.invoice_button_label, flow.talk_to_sales_button_label,
          flow.showroom_confirmation, flow.invoice_confirmation,
          flow.talk_to_sales_confirmation,
        ].some(v => v && v.trim())
        if (hasRecConfig) setRecOpen(true)
      })
      .catch(() => setError('Failed to load qualification flow settings.'))
      .finally(() => setLoading(false))
  }, [])

  // ── Validation — existing rules preserved, button label max-20 added ─────
  const validate = () => {
    if (!opening.trim()) return 'Opening message is required.'
    if (opening.length > 500) return 'Opening message must be 500 characters or fewer.'
    if (!handoff.trim()) return 'Handoff message is required.'
    if (handoff.length > 500) return 'Handoff message must be 500 characters or fewer.'
    if (questions.length === 0) return 'At least one question is required.'
    for (let i = 0; i < questions.length; i++) {
      const q = questions[i]
      if (!q.text.trim()) return `Question ${i + 1}: text is required.`
      if (q.text.length > 300) return `Question ${i + 1}: text must be 300 chars or fewer.`
      if (!q.answer_key.trim()) return `Question ${i + 1}: answer key is required.`
      if (!/^[a-zA-Z0-9_]+$/.test(q.answer_key)) return `Question ${i + 1}: answer key must be alphanumeric + underscore only.`
      if (q.answer_key.length > 50) return `Question ${i + 1}: answer key must be 50 chars or fewer.`
      if (q.type !== 'free_text') {
        if (!q.options || q.options.length === 0) return `Question ${i + 1}: options are required for ${q.type}.`
        const maxOpts = q.type === 'list_select' ? 10 : 3
        const maxLen  = q.type === 'list_select' ? 24 : 20
        if (q.options.length > maxOpts) return `Question ${i + 1}: maximum ${maxOpts} options allowed.`
        for (let j = 0; j < q.options.length; j++) {
          if (!q.options[j].label.trim()) return `Question ${i + 1}, option ${j + 1}: label is required.`
          if (q.options[j].label.length > maxLen) return `Question ${i + 1}, option ${j + 1}: label max ${maxLen} chars.`
        }
      }
    }
    // QUAL-RECOMMEND: button label length — WhatsApp hard limit is 20 chars
    if (showroomLabel.length  > 20) return 'Showroom button label must be 20 characters or fewer.'
    if (invoiceLabel.length   > 20) return 'Invoice button label must be 20 characters or fewer.'
    if (talkSalesLabel.length > 20) return 'Talk to Sales button label must be 20 characters or fewer.'
    return null
  }

  // ── Save — existing payload preserved, new fields appended ───────────────
  const handleSave = async () => {
    const err = validate()
    if (err) { setError(err); return }
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await adminSvc.updateQualificationFlow({
        // Existing fields — unchanged
        opening_message: opening,
        handoff_message: handoff,
        questions: questions.map((q, idx) => ({
          id: q.id || `q${idx}`,
          text: q.text,
          type: q.type,
          answer_key: q.answer_key,
          map_to_lead_field: q.map_to_lead_field || null,
          map_to_catalog_tag: q.map_to_catalog_tag?.trim() || null,
          required: q.required !== false,
          options: q.type === 'free_text' ? null : (q.options || []).map(opt => ({
            id: opt.id,
            label: opt.label,
            tag_value: (q.map_to_catalog_tag?.trim() && opt.tag_value?.trim())
              ? opt.tag_value.trim()
              : undefined,
          })),
        })),
        // QUAL-RECOMMEND fields — null when blank so backend uses hardcoded default
        recommendation_intro:        recIntro.trim()       || null,
        pillow_upsell_message:       pillowUpsell.trim()   || null,
        pillow_recommendation_intro: pillowRecIntro.trim() || null,
        pillow_not_found_message:    pillowNotFound.trim() || null,
        post_qual_cta_text:          ctaText.trim()        || null,
        showroom_button_label:       showroomLabel.trim()  || null,
        showroom_button_enabled:     showroomEnabled,
        invoice_button_label:        invoiceLabel.trim()   || null,
        talk_to_sales_button_label:  talkSalesLabel.trim() || null,
        showroom_confirmation:       showroomConf.trim()   || null,
        invoice_confirmation:        invoiceConf.trim()    || null,
        talk_to_sales_confirmation:  talkSalesConf.trim()  || null,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      const msg = e?.response?.data?.error || 'Failed to save. Please try again.'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  // ── Question mutations — all unchanged ────────────────────────────────────
  const addQuestion = () => {
    if (questions.length >= MAX_QUESTIONS) return
    setQuestions(prev => [...prev, EMPTY_QUESTION()])
    setPreview(questions.length)
  }

  const removeQuestion = (idx) => {
    setQuestions(prev => prev.filter((_, i) => i !== idx))
    setPreview(p => Math.min(p, questions.length - 2))
  }

  const updateQuestion = (idx, patch) => {
    setQuestions(prev => prev.map((q, i) => i === idx ? { ...q, ...patch } : q))
  }

  const moveUp = (idx) => {
    if (idx === 0) return
    setQuestions(prev => {
      const next = [...prev]
      ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
      return next
    })
    setPreview(idx - 1)
  }

  const moveDown = (idx) => {
    if (idx === questions.length - 1) return
    setQuestions(prev => {
      const next = [...prev]
      ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
      return next
    })
    setPreview(idx + 1)
  }

  const addOption = (qIdx) => {
    const q = questions[qIdx]
    const maxOpts = q.type === 'list_select' ? 10 : 3
    if ((q.options || []).length >= maxOpts) return
    updateQuestion(qIdx, {
      options: [...(q.options || []), { id: `opt${Date.now()}`, label: '' }]
    })
  }

  const updateOption = (qIdx, oIdx, label) => {
    const opts = [...(questions[qIdx].options || [])]
    opts[oIdx] = { ...opts[oIdx], label }
    updateQuestion(qIdx, { options: opts })
  }

  const updateOptionTagValue = (qIdx, oIdx, tag_value) => {
    const opts = [...(questions[qIdx].options || [])]
    opts[oIdx] = { ...opts[oIdx], tag_value }
    updateQuestion(qIdx, { options: opts })
  }

  const removeOption = (qIdx, oIdx) => {
    updateQuestion(qIdx, {
      options: (questions[qIdx].options || []).filter((_, i) => i !== oIdx)
    })
  }

  const handleTypeChange = (qIdx, newType) => {
    const updates = { type: newType, options: [] }
    if (newType === 'yes_no') {
      updates.options = [
        { id: 'yes', label: 'Yes' },
        { id: 'no',  label: 'No'  },
      ]
    }
    updateQuestion(qIdx, updates)
  }

  // ── Styles — all existing styles preserved, new ones appended ────────────
  const S = {
    section: {
      background: '#fff',
      border: `1px solid ${ds.border}`,
      borderRadius: 12,
      padding: '20px 24px',
      marginBottom: 16,
    },
    sectionTitle: {
      fontFamily: ds.fontSyne,
      fontWeight: 700,
      fontSize: 14,
      color: ds.dark,
      marginBottom: 4,
    },
    sectionDesc: {
      fontSize: 12.5,
      color: ds.gray,
      marginBottom: 16,
      lineHeight: 1.5,
    },
    label: {
      display: 'block',
      fontSize: 12.5,
      fontWeight: 600,
      color: ds.dark,
      marginBottom: 6,
    },
    input: {
      width: '100%',
      border: `1.5px solid ${ds.border}`,
      borderRadius: 8,
      padding: '9px 12px',
      fontSize: 13,
      fontFamily: ds.fontBody,
      outline: 'none',
      boxSizing: 'border-box',
    },
    textarea: {
      width: '100%',
      border: `1.5px solid ${ds.border}`,
      borderRadius: 8,
      padding: '9px 12px',
      fontSize: 13,
      fontFamily: ds.fontBody,
      resize: 'vertical',
      minHeight: 80,
      outline: 'none',
      lineHeight: 1.5,
      boxSizing: 'border-box',
    },
    select: {
      width: '100%',
      border: `1.5px solid ${ds.border}`,
      borderRadius: 8,
      padding: '9px 12px',
      fontSize: 13,
      fontFamily: ds.fontBody,
      outline: 'none',
      background: '#fff',
      cursor: 'pointer',
    },
    qCard: (active) => ({
      border: `2px solid ${active ? ds.teal : ds.border}`,
      borderRadius: 12,
      padding: '16px 18px',
      marginBottom: 12,
      cursor: 'pointer',
      background: active ? '#f0fafa' : '#fff',
      transition: 'border-color 0.15s',
    }),
    pill: {
      display: 'inline-block',
      padding: '3px 10px',
      borderRadius: 20,
      background: ds.mint,
      color: ds.teal,
      fontSize: 11.5,
      fontWeight: 600,
      marginRight: 6,
    },
    iconBtn: {
      background: 'none',
      border: `1px solid ${ds.border}`,
      borderRadius: 6,
      padding: '4px 8px',
      cursor: 'pointer',
      fontSize: 12,
      color: ds.gray,
    },
    saveBtn: (disabled) => ({
      padding: '10px 24px',
      background: disabled ? '#9ca3af' : ds.teal,
      color: '#fff',
      border: 'none',
      borderRadius: 8,
      fontFamily: ds.fontSyne,
      fontWeight: 600,
      fontSize: 13,
      cursor: disabled ? 'not-allowed' : 'pointer',
    }),
    // QUAL-RECOMMEND: new styles
    subLabel: {
      display: 'block',
      fontSize: 12.5,
      fontWeight: 600,
      color: ds.dark,
      marginBottom: 4,
    },
    subDesc: {
      fontSize: 11.5,
      color: ds.gray,
      marginBottom: 8,
      lineHeight: 1.4,
    },
    fieldGroup: {
      marginBottom: 18,
    },
    divider: {
      borderTop: `1px solid ${ds.border}`,
      margin: '18px 0',
    },
    groupHeading: {
      fontSize: 11.5,
      fontWeight: 700,
      color: ds.teal,
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
      marginBottom: 12,
    },
    charCount: (len, warn) => ({
      fontSize: 11,
      color: len > warn ? '#e53e3e' : ds.gray,
      textAlign: 'right',
      marginTop: 3,
    }),
    optionalBadge: {
      display: 'inline-block',
      fontSize: 10.5,
      background: '#f0fafa',
      color: ds.teal,
      border: `1px solid ${ds.mint}`,
      borderRadius: 4,
      padding: '1px 6px',
      marginLeft: 8,
      fontWeight: 500,
      verticalAlign: 'middle',
    },
    collapseHeader: {
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      width: '100%',
      textAlign: 'left',
    },
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
        Loading qualification flow…
      </div>
    )
  }

  const pq = questions[preview] || questions[0]

  return (
    <div>
      {/* Header — unchanged */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: '0 0 4px' }}>
          📋 Qualification Flow
        </h2>
        <p style={{ fontSize: 13, color: ds.gray, margin: 0, lineHeight: 1.5 }}>
          Design the structured question flow that fires when a lead taps &quot;Interested&quot; on the WhatsApp triage menu.
          The AI is only called once at handoff to generate a rep summary.
        </p>
      </div>

      {error && (
        <div style={{
          background: '#fff5f5', border: '1px solid #fc8181', borderRadius: 8,
          padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#c53030',
        }}>
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20, alignItems: 'start' }}>

        {/* Left column */}
        <div>

          {/* ── 1. Opening Message — unchanged ────────────────────────────── */}
          <div style={S.section}>
            <div style={S.sectionTitle}>👋 Opening Message</div>
            <div style={S.sectionDesc}>
              Sent to the lead immediately when they select &quot;Interested&quot;, prepended before the first question.
            </div>
            <textarea
              style={S.textarea}
              maxLength={500}
              placeholder="e.g. Hi there! 👋 Before we connect you with our team, we'd love to learn a bit about you."
              value={opening}
              onChange={e => setOpening(e.target.value)}
            />
            <div style={{ fontSize: 11.5, color: opening.length > 480 ? '#e53e3e' : ds.gray, textAlign: 'right' }}>
              {opening.length}/500
            </div>
          </div>

          {/* ── 2. Handoff Message — unchanged ────────────────────────────── */}
          <div style={S.section}>
            <div style={S.sectionTitle}>🙏 Handoff Message</div>
            <div style={S.sectionDesc}>
              Sent to the lead after all questions are answered, before the rep receives the summary.
            </div>
            <textarea
              style={S.textarea}
              maxLength={500}
              placeholder="e.g. Thanks so much! A member of our team will reach out to you shortly. 🙏"
              value={handoff}
              onChange={e => setHandoff(e.target.value)}
            />
            <div style={{ fontSize: 11.5, color: handoff.length > 480 ? '#e53e3e' : ds.gray, textAlign: 'right' }}>
              {handoff.length}/500
            </div>
          </div>

          {/* ── 3. Question Builder — unchanged ───────────────────────────── */}
          <div style={S.section}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <div style={S.sectionTitle}>❓ Questions ({questions.length}/{MAX_QUESTIONS})</div>
              <button
                style={{
                  ...S.iconBtn,
                  background: questions.length >= MAX_QUESTIONS ? '#f1f5f9' : ds.teal,
                  color: questions.length >= MAX_QUESTIONS ? ds.gray : '#fff',
                  border: 'none',
                  padding: '6px 14px',
                  fontFamily: ds.fontSyne,
                  fontWeight: 600,
                  fontSize: 12,
                  borderRadius: 8,
                  cursor: questions.length >= MAX_QUESTIONS ? 'not-allowed' : 'pointer',
                  opacity: questions.length >= MAX_QUESTIONS ? 0.5 : 1,
                }}
                onClick={addQuestion}
                disabled={questions.length >= MAX_QUESTIONS}
              >
                + Add Question
              </button>
            </div>
            <div style={S.sectionDesc}>
              Build the questions leads will answer. Click a question to edit it and preview how it looks.
            </div>

            {questions.map((q, idx) => (
              <div
                key={q.id || idx}
                style={S.qCard(preview === idx)}
                onClick={() => setPreview(idx)}
              >
                {/* Question header row */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      background: ds.teal, color: '#fff', borderRadius: '50%',
                      width: 22, height: 22, display: 'flex', alignItems: 'center',
                      justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0,
                    }}>
                      {idx + 1}
                    </span>
                    <span style={S.pill}>
                      {QUESTION_TYPES.find(t => t.value === q.type)?.label || q.type}
                    </span>
                    <span
                      onClick={e => { e.stopPropagation(); updateQuestion(idx, { required: q.required === false }) }}
                      title="Click to toggle whether the AI Agent must establish this before confidently recommending"
                      style={{
                        ...S.pill,
                        cursor: 'pointer',
                        background: q.required !== false ? '#FEF3E2' : '#F0F0F0',
                        color: q.required !== false ? '#B7791F' : '#888888',
                      }}
                    >
                      {q.required !== false ? '● Required' : '○ Optional'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button style={S.iconBtn} onClick={e => { e.stopPropagation(); moveUp(idx) }} disabled={idx === 0} title="Move up">↑</button>
                    <button style={S.iconBtn} onClick={e => { e.stopPropagation(); moveDown(idx) }} disabled={idx === questions.length - 1} title="Move down">↓</button>
                    {questions.length > 1 && (
                      <button
                        style={{ ...S.iconBtn, color: '#e53e3e', borderColor: '#fc8181' }}
                        onClick={e => { e.stopPropagation(); removeQuestion(idx) }}
                        title="Remove question"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>

                {/* Question text */}
                <div style={{ marginBottom: 10 }} onClick={e => e.stopPropagation()}>
                  <label style={S.label}>Question Text</label>
                  <textarea
                    style={{ ...S.textarea, minHeight: 56 }}
                    maxLength={300}
                    placeholder="e.g. What brings you to us today?"
                    value={q.text}
                    onChange={e => updateQuestion(idx, { text: e.target.value })}
                  />
                </div>

                {/* Type + Answer key row */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }} onClick={e => e.stopPropagation()}>
                  <div>
                    <label style={S.label}>Question Type</label>
                    <select
                      style={S.select}
                      value={q.type}
                      onChange={e => handleTypeChange(idx, e.target.value)}
                    >
                      {QUESTION_TYPES.map(t => (
                        <option key={t.value} value={t.value}>{t.label} — {t.desc}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label style={S.label}>Answer Key <span style={{ fontWeight: 400, color: ds.gray }}>(e.g. company_size)</span></label>
                    <input
                      style={S.input}
                      maxLength={50}
                      placeholder="e.g. inquiry_reason"
                      value={q.answer_key}
                      onChange={e => updateQuestion(idx, { answer_key: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') })}
                    />
                  </div>
                </div>

                {/* Map to lead field + catalog tag — two-column row */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: q.type !== 'free_text' ? 10 : 0 }} onClick={e => e.stopPropagation()}>
                  <div>
                    <label style={S.label}>Map Answer to Lead Field <span style={{ fontWeight: 400, color: ds.gray }}>(optional)</span></label>
                    <select
                      style={S.select}
                      value={q.map_to_lead_field || ''}
                      onChange={e => updateQuestion(idx, { map_to_lead_field: e.target.value || '' })}
                    >
                      {LEAD_FIELD_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                  {q.type !== 'free_text' && q.type !== 'yes_no' && (
                    <div>
                      <label style={S.label}>
                        Catalog Tag Dimension
                        <span style={{ fontWeight: 400, color: ds.gray }}> (optional, e.g. firmness)</span>
                      </label>
                      <input
                        style={S.input}
                        maxLength={50}
                        placeholder="e.g. firmness, size, health_condition"
                        value={q.map_to_catalog_tag || ''}
                        onChange={e => updateQuestion(idx, { map_to_catalog_tag: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') })}
                      />
                    </div>
                  )}
                </div>

                {/* Options editor */}
                {q.type !== 'free_text' && (
                  <div onClick={e => e.stopPropagation()}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, marginTop: 10 }}>
                      <label style={{ ...S.label, margin: 0 }}>
                        Options
                        <span style={{ fontWeight: 400, color: ds.gray, marginLeft: 4 }}>
                          (max {q.type === 'list_select' ? 10 : 3}, label max {q.type === 'list_select' ? 24 : 20} chars)
                        </span>
                      </label>
                      {q.type !== 'yes_no' && (
                        <button
                          style={{ ...S.iconBtn, fontSize: 11 }}
                          onClick={() => addOption(idx)}
                          disabled={(q.options || []).length >= (q.type === 'list_select' ? 10 : 3)}
                        >
                          + Option
                        </button>
                      )}
                    </div>
                    {(q.options || []).map((opt, oIdx) => (
                      <div key={opt.id || oIdx} style={{ marginBottom: 6 }}>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <input
                            style={{ ...S.input, flex: 1 }}
                            maxLength={q.type === 'list_select' ? 24 : 20}
                            placeholder={`Option ${oIdx + 1} label`}
                            value={opt.label}
                            onChange={e => updateOption(idx, oIdx, e.target.value)}
                            disabled={q.type === 'yes_no'}
                          />
                          {q.map_to_catalog_tag?.trim() && (
                            <input
                              style={{ ...S.input, flex: 1, borderColor: ds.mint }}
                              maxLength={100}
                              placeholder={`Tag value (e.g. ${q.map_to_catalog_tag})`}
                              value={opt.tag_value || ''}
                              onChange={e => updateOptionTagValue(idx, oIdx, e.target.value)}
                            />
                          )}
                          {q.type !== 'yes_no' && (
                            <button
                              style={{ ...S.iconBtn, color: '#e53e3e', borderColor: '#fc8181', flexShrink: 0 }}
                              onClick={() => removeOption(idx, oIdx)}
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* ── 4. Post-Qualification Messages — NEW (QUAL-RECOMMEND) ──────── */}
          <div style={S.section}>

            {/* Collapsible header */}
            <button style={S.collapseHeader} onClick={() => setRecOpen(o => !o)}>
              <div>
                <div style={{ ...S.sectionTitle, marginBottom: 0 }}>
                  🎯 Post-Qualification Messages
                  <span style={S.optionalBadge}>Optional</span>
                </div>
                {!recOpen && (
                  <div style={{ fontSize: 12, color: ds.gray, marginTop: 4 }}>
                    Customise recommendation text, pillow upsell, CTA buttons and confirmations.
                    Defaults apply when left blank.
                  </div>
                )}
              </div>
              <span style={{
                fontSize: 18,
                color: ds.gray,
                marginLeft: 12,
                flexShrink: 0,
                transition: 'transform 0.2s',
                display: 'inline-block',
                transform: recOpen ? 'rotate(180deg)' : 'none',
              }}>
                ▾
              </span>
            </button>

            {/* Expanded content */}
            {recOpen && (
              <div style={{ marginTop: 20 }}>
                <div style={S.sectionDesc}>
                  These messages are sent after the lead completes all qualification questions —
                  after the handoff message above. Leave any field blank to use the system default
                  shown in the placeholder text.
                </div>

                {/* ── Mattress Recommendation ── */}
                <div style={S.groupHeading}>Mattress Recommendation</div>

                <div style={S.fieldGroup}>
                  <label style={S.subLabel}>Recommendation Intro</label>
                  <div style={S.subDesc}>
                    Text sent before the recommended product name and price.
                  </div>
                  <textarea
                    style={{ ...S.textarea, minHeight: 56 }}
                    maxLength={200}
                    placeholder={REC_DEFAULTS.recommendation_intro}
                    value={recIntro}
                    onChange={e => setRecIntro(e.target.value)}
                  />
                  <div style={S.charCount(recIntro.length, 190)}>{recIntro.length}/200</div>
                </div>

                <div style={S.divider} />

                {/* ── Pillow Upsell ── */}
                <div style={S.groupHeading}>Pillow Upsell</div>

                <div style={S.fieldGroup}>
                  <label style={S.subLabel}>Pillow Upsell Question</label>
                  <div style={S.subDesc}>
                    Sent after the mattress recommendation — asks if the lead wants to see pillows.
                  </div>
                  <textarea
                    style={S.textarea}
                    maxLength={500}
                    placeholder={REC_DEFAULTS.pillow_upsell_message}
                    value={pillowUpsell}
                    onChange={e => setPillowUpsell(e.target.value)}
                  />
                  <div style={S.charCount(pillowUpsell.length, 480)}>{pillowUpsell.length}/500</div>
                </div>

                <div style={S.fieldGroup}>
                  <label style={S.subLabel}>Pillow Recommendation Intro</label>
                  <div style={S.subDesc}>
                    Text sent before the recommended pillow name and price (when lead taps &quot;Yes, show me&quot;).
                  </div>
                  <textarea
                    style={{ ...S.textarea, minHeight: 56 }}
                    maxLength={200}
                    placeholder={REC_DEFAULTS.pillow_recommendation_intro}
                    value={pillowRecIntro}
                    onChange={e => setPillowRecIntro(e.target.value)}
                  />
                  <div style={S.charCount(pillowRecIntro.length, 190)}>{pillowRecIntro.length}/200</div>
                </div>

                <div style={S.fieldGroup}>
                  <label style={S.subLabel}>Pillow Not Found Message</label>
                  <div style={S.subDesc}>
                    Sent when no pillow products exist in your product list (e.g. in-store only inventory).
                  </div>
                  <textarea
                    style={S.textarea}
                    maxLength={500}
                    placeholder={REC_DEFAULTS.pillow_not_found_message}
                    value={pillowNotFound}
                    onChange={e => setPillowNotFound(e.target.value)}
                  />
                  <div style={S.charCount(pillowNotFound.length, 480)}>{pillowNotFound.length}/500</div>
                </div>

                <div style={S.divider} />

                {/* ── CTA Buttons ── */}
                <div style={S.groupHeading}>Action Buttons</div>

                <div style={S.fieldGroup}>
                  <label style={S.subLabel}>CTA Body Text</label>
                  <div style={S.subDesc}>
                    Text displayed above the three action buttons.
                  </div>
                  <input
                    style={S.input}
                    maxLength={100}
                    placeholder={REC_DEFAULTS.post_qual_cta_text}
                    value={ctaText}
                    onChange={e => setCtaText(e.target.value)}
                  />
                </div>

                <div style={S.fieldGroup}>
                  <label style={S.subLabel}>
                    Button Labels
                    <span style={{ fontWeight: 400, color: ds.gray, marginLeft: 4 }}>
                      (max 20 chars — WhatsApp limit)
                    </span>
                  </label>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    <input
                      type="checkbox"
                      id="showroom_enabled"
                      checked={showroomEnabled}
                      onChange={e => setShowroomEnabled(e.target.checked)}
                      style={{ width: 15, height: 15, cursor: 'pointer', accentColor: ds.teal }}
                    />
                    <label htmlFor="showroom_enabled" style={{ fontSize: 12.5, color: ds.dark, cursor: 'pointer', userSelect: 'none' }}>
                      Show &quot;Visit Showroom&quot; button
                    </label>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                    {[
                      { key: 'showroom', label: '🏪 Showroom',     val: showroomLabel,  set: setShowroomLabel,  def: REC_DEFAULTS.showroom_button_label,      enabled: showroomEnabled },
                      { key: 'invoice',  label: '💳 Invoice',       val: invoiceLabel,   set: setInvoiceLabel,   def: REC_DEFAULTS.invoice_button_label,       enabled: true },
                      { key: 'sales',    label: '💬 Talk to Sales', val: talkSalesLabel, set: setTalkSalesLabel, def: REC_DEFAULTS.talk_to_sales_button_label, enabled: true },
                    ].map(({ key, label, val, set, def, enabled }) => (
                      <div key={key} style={{ opacity: enabled ? 1 : 0.4, transition: 'opacity 0.2s' }}>
                        <div style={{ fontSize: 11.5, color: ds.gray, marginBottom: 4 }}>{label}</div>
                        <input
                          style={{
                            ...S.input,
                            borderColor: val.length > 20 ? '#fc8181' : ds.border,
                            cursor: enabled ? 'text' : 'not-allowed',
                          }}
                          maxLength={20}
                          placeholder={def}
                          value={val}
                          onChange={e => enabled && set(e.target.value)}
                          disabled={!enabled}
                        />
                        <div style={S.charCount(val.length, 18)}>{val.length}/20</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={S.divider} />

                {/* ── Confirmation Messages ── */}
                <div style={S.groupHeading}>Confirmation Messages</div>
                <div style={{ ...S.sectionDesc, marginBottom: 16 }}>
                  Sent to the lead immediately after they tap one of the three action buttons.
                </div>

                {[
                  { icon: '🏪', title: 'After "Visit Showroom"', val: showroomConf, set: setShowroomConf, def: REC_DEFAULTS.showroom_confirmation },
                  { icon: '💳', title: 'After "Get Invoice"',    val: invoiceConf,  set: setInvoiceConf,  def: REC_DEFAULTS.invoice_confirmation },
                  { icon: '💬', title: 'After "Talk to Sales"',  val: talkSalesConf, set: setTalkSalesConf, def: REC_DEFAULTS.talk_to_sales_confirmation },
                ].map(({ icon, title, val, set, def }) => (
                  <div style={S.fieldGroup} key={title}>
                    <label style={S.subLabel}>{icon} {title}</label>
                    <textarea
                      style={{ ...S.textarea, minHeight: 64 }}
                      maxLength={500}
                      placeholder={def}
                      value={val}
                      onChange={e => set(e.target.value)}
                    />
                    <div style={S.charCount(val.length, 480)}>{val.length}/500</div>
                  </div>
                ))}

              </div>
            )}
          </div>

          {/* ── Save — unchanged ──────────────────────────────────────────── */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button style={S.saveBtn(saving)} onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : '💾 Save Flow'}
            </button>
            {saved && (
              <span style={{ fontSize: 13, color: '#27ae60', fontWeight: 500 }}>
                ✓ Saved successfully
              </span>
            )}
          </div>
        </div>

        {/* ── Right column: WhatsApp Preview — completely unchanged ─────── */}
        <div style={{ position: 'sticky', top: 24 }}>
          <div style={{
            background: '#e5ddd5',
            borderRadius: 16,
            padding: 16,
            minHeight: 400,
          }}>
            <div style={{
              background: '#128C7E',
              borderRadius: '12px 12px 0 0',
              padding: '10px 14px',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 2,
            }}>
              <div style={{ width: 30, height: 30, borderRadius: '50%', background: '#25D366', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>💼</div>
              <div>
                <div style={{ color: '#fff', fontSize: 13, fontWeight: 600 }}>Your Business</div>
                <div style={{ color: '#9de1d4', fontSize: 11 }}>WhatsApp Business</div>
              </div>
            </div>

            <div style={{ padding: '10px 4px' }}>
              <div style={{ display: 'flex', gap: 4, marginBottom: 10, flexWrap: 'wrap' }}>
                {questions.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => setPreview(i)}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 12,
                      border: 'none',
                      background: preview === i ? ds.teal : '#ccc',
                      color: '#fff',
                      fontSize: 11,
                      cursor: 'pointer',
                      fontWeight: 600,
                    }}
                  >
                    Q{i + 1}
                  </button>
                ))}
              </div>

              {preview === 0 && opening && (
                <div style={{
                  background: '#fff',
                  borderRadius: '0 10px 10px 10px',
                  padding: '8px 12px',
                  marginBottom: 8,
                  fontSize: 13,
                  color: '#111',
                  maxWidth: '90%',
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
                }}>
                  {opening}
                </div>
              )}

              {pq && (
                <div>
                  <div style={{
                    background: '#fff',
                    borderRadius: pq.type !== 'free_text' ? '0 10px 0 10px' : '0 10px 10px 10px',
                    padding: '8px 12px',
                    marginBottom: 4,
                    fontSize: 13,
                    color: '#111',
                    maxWidth: '90%',
                    lineHeight: 1.5,
                    whiteSpace: 'pre-wrap',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
                  }}>
                    {pq.text || <span style={{ color: '#aaa' }}>Question text appears here…</span>}
                  </div>

                  {(pq.type === 'multiple_choice' || pq.type === 'yes_no') && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 2 }}>
                      {(pq.options || []).slice(0, 3).map((opt, i) => (
                        <div key={i} style={{
                          background: '#fff',
                          border: '1px solid #25D366',
                          borderRadius: 8,
                          padding: '7px 12px',
                          fontSize: 12.5,
                          color: '#128C7E',
                          fontWeight: 600,
                          textAlign: 'center',
                          maxWidth: '90%',
                          cursor: 'default',
                        }}>
                          {opt.label || <span style={{ color: '#aaa' }}>Option {i + 1}</span>}
                        </div>
                      ))}
                      {(!pq.options || pq.options.length === 0) && (
                        <div style={{ color: '#aaa', fontSize: 12, fontStyle: 'italic' }}>Add options to preview buttons</div>
                      )}
                    </div>
                  )}

                  {pq.type === 'list_select' && (
                    <div>
                      <div style={{
                        background: '#fff',
                        borderRadius: 8,
                        padding: '7px 12px',
                        fontSize: 12.5,
                        color: '#128C7E',
                        fontWeight: 600,
                        textAlign: 'center',
                        maxWidth: '90%',
                        cursor: 'default',
                        border: '1px solid #25D366',
                      }}>
                        ☰ Choose an option
                      </div>
                      {(pq.options || []).length > 0 && (
                        <div style={{
                          background: '#fff',
                          borderRadius: 8,
                          marginTop: 4,
                          padding: '4px 0',
                          maxWidth: '90%',
                          boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
                          fontSize: 12.5,
                        }}>
                          {(pq.options || []).slice(0, 5).map((opt, i) => (
                            <div key={i} style={{ padding: '6px 12px', borderBottom: i < (pq.options || []).length - 1 ? '1px solid #f0f0f0' : 'none', color: '#111' }}>
                              {opt.label || <span style={{ color: '#aaa' }}>Option {i + 1}</span>}
                            </div>
                          ))}
                          {(pq.options || []).length > 5 && (
                            <div style={{ padding: '4px 12px', color: ds.gray, fontSize: 11 }}>+ {(pq.options || []).length - 5} more…</div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {pq.type === 'free_text' && (
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      marginTop: 8,
                      background: '#fff',
                      borderRadius: 20,
                      padding: '6px 12px',
                      maxWidth: '90%',
                      border: '1px solid #ddd',
                    }}>
                      <span style={{ fontSize: 11.5, color: '#aaa', flex: 1 }}>Type a reply…</span>
                      <span style={{ color: '#25D366', fontSize: 16 }}>➤</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          <div style={{ fontSize: 11.5, color: ds.gray, textAlign: 'center', marginTop: 6 }}>
            Live WhatsApp preview — updates as you type
          </div>
        </div>

      </div>
    </div>
  )
}
