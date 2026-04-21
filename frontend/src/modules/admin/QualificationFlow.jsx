/**
 * frontend/src/modules/admin/QualificationFlow.jsx
 * WH-1b — Structured WhatsApp Qualification Flow builder.
 *
 * Replaces QualificationBot.jsx as the rendered tab in AdminModule.
 * QualificationBot.jsx remains in the file structure but is no longer rendered.
 *
 * Sections:
 *   1. Opening Message — textarea, max 500 chars, required
 *   2. Handoff Message — textarea, max 500 chars, required
 *   3. Question Builder — up to 5 questions, drag/reorder via up/down buttons
 *   4. WhatsApp Preview — live preview of how each question appears on WhatsApp
 *   5. Save button
 *
 * ds.teal for all accents.
 * Pattern 51: full rewrite required for any future edit — never sed.
 * Pattern 50: admin.service.js axios + _h() only.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

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
  options: [],
})

const MAX_QUESTIONS = 5

export default function QualificationFlow() {
  const [opening, setOpening]     = useState('')
  const [handoff, setHandoff]     = useState('')
  const [questions, setQuestions] = useState([EMPTY_QUESTION()])
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)
  const [error, setError]         = useState(null)
  const [preview, setPreview]     = useState(0)  // index of previewed question

  useEffect(() => {
    adminSvc.getQualificationFlow()
      .then(data => {
        const flow = (data || {}).qualification_flow || {}
        setOpening(flow.opening_message || '')
        setHandoff(flow.handoff_message || '')
        if (flow.questions && flow.questions.length > 0) {
          setQuestions(flow.questions.map(q => ({
            ...q,
            map_to_lead_field: q.map_to_lead_field || '',
            options: q.options || [],
          })))
        }
      })
      .catch(() => setError('Failed to load qualification flow settings.'))
      .finally(() => setLoading(false))
  }, [])

  // ── Validation ──────────────────────────────────────────────────────────
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
    return null
  }

  const handleSave = async () => {
    const err = validate()
    if (err) { setError(err); return }
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await adminSvc.updateQualificationFlow({
        opening_message: opening,
        handoff_message: handoff,
        questions: questions.map((q, idx) => ({
          id: q.id || `q${idx}`,
          text: q.text,
          type: q.type,
          answer_key: q.answer_key,
          map_to_lead_field: q.map_to_lead_field || null,
          options: q.type === 'free_text' ? null : q.options,
        })),
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

  // ── Question mutations ───────────────────────────────────────────────────
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

  // ── Styles ───────────────────────────────────────────────────────────────
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
      {/* Header */}
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

        {/* Left column: config */}
        <div>

          {/* Opening Message */}
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

          {/* Handoff Message */}
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

          {/* Question Builder */}
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
                      background: ds.teal,
                      color: '#fff',
                      borderRadius: '50%',
                      width: 22,
                      height: 22,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 11,
                      fontWeight: 700,
                      flexShrink: 0,
                    }}>
                      {idx + 1}
                    </span>
                    <span style={S.pill}>
                      {QUESTION_TYPES.find(t => t.value === q.type)?.label || q.type}
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

                {/* Map to lead field */}
                <div style={{ marginBottom: q.type !== 'free_text' ? 10 : 0 }} onClick={e => e.stopPropagation()}>
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

                {/* Options editor — shown for non-free_text */}
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
                      <div key={opt.id || oIdx} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                        <input
                          style={{ ...S.input, flex: 1 }}
                          maxLength={q.type === 'list_select' ? 24 : 20}
                          placeholder={`Option ${oIdx + 1} label`}
                          value={opt.label}
                          onChange={e => updateOption(idx, oIdx, e.target.value)}
                          disabled={q.type === 'yes_no'}
                        />
                        {q.type !== 'yes_no' && (
                          <button
                            style={{ ...S.iconBtn, color: '#e53e3e', borderColor: '#fc8181', flexShrink: 0 }}
                            onClick={() => removeOption(idx, oIdx)}
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Save */}
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

        {/* Right column: WhatsApp Preview */}
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
              {/* Preview selector tabs */}
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

              {/* Opening message bubble — only on Q1 */}
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
                  {/* Question bubble */}
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

                  {/* Button preview */}
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

                  {/* List preview */}
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

                  {/* Free text input preview */}
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
