/**
 * frontend/src/pages/SiteBriefFormPage.jsx
 * SITE-1B — the public brief form. Spec §7.3.
 *
 * Standalone page — no AppShell, no sidebar, no auth required. Registered in
 * App.jsx via URL pattern match: /f/:token (same pattern as PublicLogPage's /log/:token).
 *
 * Simplification vs spec (documented in SITE-1B-2_Edits.md): the spec groups
 * brief_questions into named steps (About/Contact/Look/…) for a niche like
 * boutique. This pass renders every question on one scrollable page instead
 * of a multi-step wizard — simpler to get right, and arguably friendlier on
 * mobile than a forced wizard. A stepped version is a fast follow if long
 * forms turn out to feel overwhelming in practice.
 *
 * States: loading | error (invalid/expired link) | choose_preset (no business
 * type pinned to this form yet) | form | submitted
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  autosaveBriefForm, errorMessage, getBriefForm, submitBriefForm, uploadBriefFormAsset,
} from '../services/site_forms.service'

const S = {
  page: {
    minHeight: '100vh', background: '#f0f4f7', display: 'flex', flexDirection: 'column',
    alignItems: 'center', fontFamily: "'DM Sans', system-ui, sans-serif",
  },
  header: {
    width: '100%', background: '#0a1f2e', padding: '18px 20px',
    display: 'flex', alignItems: 'center', gap: 12, boxSizing: 'border-box',
  },
  logo: { fontFamily: "'Syne', system-ui, sans-serif", fontWeight: 800, fontSize: 18, color: '#1dc8a4', letterSpacing: '-0.5px' },
  logoSub: { fontSize: 11, color: '#6B8FA0', marginTop: 1 },
  card: {
    background: 'white', borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    padding: '24px 20px', width: '100%', maxWidth: 560, margin: '20px 14px 48px', boxSizing: 'border-box',
  },
  h1: { fontSize: 19, fontWeight: 700, color: '#0a1f2e', margin: '0 0 4px' },
  sub: { fontSize: 13, color: '#6B8FA0', margin: '0 0 20px' },
  section: { marginBottom: 22 },
  label: { fontSize: 12.5, fontWeight: 600, color: '#4a6375', marginBottom: 6, display: 'block' },
  skipBtn: { fontSize: 11.5, color: '#6B8FA0', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', marginLeft: 8 },
  input: {
    width: '100%', padding: '11px 12px', border: '1.5px solid #dde4e8', borderRadius: 8,
    fontSize: 14.5, color: '#0a1f2e', outline: 'none', boxSizing: 'border-box', background: 'white', fontFamily: 'inherit',
  },
  textarea: {
    width: '100%', padding: '11px 12px', border: '1.5px solid #dde4e8', borderRadius: 8,
    fontSize: 14.5, color: '#0a1f2e', outline: 'none', boxSizing: 'border-box', minHeight: 80, fontFamily: 'inherit', resize: 'vertical',
  },
  choiceRow: { display: 'flex', flexWrap: 'wrap', gap: 8 },
  choiceBtn: (on) => ({
    padding: '9px 14px', borderRadius: 20, border: `1.5px solid ${on ? '#1dc8a4' : '#dde4e8'}`,
    background: on ? '#e7faf5' : 'white', color: on ? '#0a1f2e' : '#4a6375', fontSize: 13.5,
    fontWeight: on ? 600 : 500, cursor: 'pointer',
  }),
  photoGrid: { display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8 },
  photoThumb: { width: 74, height: 74, borderRadius: 8, objectFit: 'cover', border: '1.5px solid #dde4e8' },
  photoAdd: {
    width: 74, height: 74, borderRadius: 8, border: '1.5px dashed #b7c3cb', display: 'flex',
    alignItems: 'center', justifyContent: 'center', fontSize: 22, color: '#6B8FA0', cursor: 'pointer', background: '#fafcfd',
  },
  itemCard: { border: '1.5px solid #edf1f4', borderRadius: 10, padding: 12, marginBottom: 10 },
  itemRow: { display: 'flex', gap: 8, marginBottom: 8 },
  addBtn: {
    width: '100%', padding: '10px 14px', borderRadius: 8, border: '1.5px dashed #1dc8a4', background: 'white',
    color: '#0e8f74', fontSize: 13.5, fontWeight: 600, cursor: 'pointer', marginTop: 4,
  },
  removeBtn: { border: 'none', background: 'none', color: '#c0392b', fontSize: 12, cursor: 'pointer', padding: '4px 6px' },
  btn: {
    width: '100%', padding: '13px 16px', background: '#1dc8a4', color: 'white', border: 'none',
    borderRadius: 8, fontSize: 15, fontWeight: 700, cursor: 'pointer', marginTop: 6,
  },
  btnDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  presetCard: (on) => ({
    display: 'block', width: '100%', textAlign: 'left', padding: '14px 16px', borderRadius: 10,
    border: `1.5px solid ${on ? '#1dc8a4' : '#dde4e8'}`, background: on ? '#e7faf5' : 'white',
    marginBottom: 10, cursor: 'pointer', fontSize: 15, fontWeight: 600, color: '#0a1f2e',
  }),
  error: { background: '#fff0f0', border: '1px solid #ffc0c0', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#c0392b', marginBottom: 16 },
  saveHint: { fontSize: 11.5, color: '#8aa0ab', textAlign: 'center', margin: '10px 0 0' },
  centered: { textAlign: 'center', padding: '40px 0' },
  successIcon: { fontSize: 44, marginBottom: 10 },
  successTitle: { fontSize: 19, fontWeight: 700, color: '#0a1f2e', margin: '0 0 8px' },
  successSub: { fontSize: 14, color: '#6B8FA0' },
  spinner: {
    width: 28, height: 28, borderRadius: '50%', border: '3px solid #1dc8a4',
    borderTopColor: 'transparent', animation: 'sbfspin 0.7s linear infinite', margin: '60px auto',
  },
  honeypot: { position: 'absolute', left: '-9999px', width: 1, height: 1, overflow: 'hidden' },
}

// Photo records belong to the server (the upload route stores them); the page must never send them back.
function withoutPhotos(answers) {
  return Object.fromEntries(Object.entries(answers || {}).filter(([k]) => k !== '_photos'))
}

function debounce(fn, ms) {
  let t
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
}

export default function SiteBriefFormPage({ token }) {
  const [state, setState] = useState('loading')
  const [error, setError] = useState('')
  const [form, setForm] = useState(null)
  const [presets, setPresets] = useState([])
  const [preset, setPreset] = useState(null)
  const [answers, setAnswers] = useState({})
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [website, setWebsite] = useState('')  // honeypot
  const answersRef = useRef(answers)
  answersRef.current = answers

  const load = useCallback(async () => {
    try {
      const data = await getBriefForm(token)
      if (data.status === 'submitted') { setState('submitted'); setForm(data); return }
      setForm(data)
      setAnswers(data.answers || {})
      if (data.preset) { setPreset(data.preset); setState('form') }
      else { setPresets(data.presets || []); setState('choose_preset') }
    } catch (e) {
      setError(errorMessage(e))
      setState('error')
    }
  }, [token])

  useEffect(() => { load() }, [load])

  const doAutosave = useRef(debounce(async (t, ans) => {
    try { setSaving(true); await autosaveBriefForm(t, { answers: withoutPhotos(ans) }); }
    catch (_) { /* best-effort — next change or the submit will retry */ }
    finally { setSaving(false) }
  }, 1200)).current

  function updateAnswer(key, value) {
    setAnswers(prev => {
      const next = { ...prev, [key]: value }
      doAutosave(token, next)
      return next
    })
  }

  async function choosePreset(p) {
    try {
      await autosaveBriefForm(token, { answers: {}, preset_id: p.id })
      const data = await getBriefForm(token)
      setForm(data)
      setAnswers(data.answers || {})
      setPreset(data.preset)
      setState('form')
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handlePhoto(key, file, max) {
    const existing = (answers._photos && answers._photos[key]) || []
    if (existing.length >= max) return
    try {
      const res = await uploadBriefFormAsset(token, key, file)
      const next = { ...answers, _photos: { ...(answers._photos || {}), [key]: [...existing, res.public_url] } }
      setAnswers(next)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  function updateItem(idx, field, value) {
    const items = [...(answers.items || [])]
    items[idx] = { ...items[idx], [field]: value }
    updateAnswer('items', items)
  }
  function addItem(max) {
    const items = [...(answers.items || [])]
    if (items.length >= max) return
    items.push({ name: '', price_ngn: '', desc: '' })
    updateAnswer('items', items)
  }
  function removeItem(idx) {
    const items = [...(answers.items || [])]
    items.splice(idx, 1)
    updateAnswer('items', items)
  }

  async function handleSubmit() {
    setError('')
    const businessName = (answers.business_name || '').trim()
    if (!businessName) { setError("Please fill in the business name before submitting."); return }
    setSubmitting(true)
    try {
      const res = await submitBriefForm(token, {
        answers: withoutPhotos(answersRef.current), client_business_name: businessName, website,
      })
      setForm(f => ({ ...f, message: res.message }))
      setState('submitted')
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={S.page}>
      <style>{'@keyframes sbfspin { to { transform: rotate(360deg); } }'}</style>
      <div style={S.header}>
        <div>
          <div style={S.logo}>{form?.header_name || 'Opsra'}</div>
          <div style={S.logoSub}>Tell us about your business</div>
        </div>
      </div>

      {state === 'loading' && <div style={S.spinner} />}

      {state === 'error' && (
        <div style={S.card}>
          <p style={S.error}>{error}</p>
        </div>
      )}

      {state === 'choose_preset' && (
        <div style={S.card}>
          <h1 style={S.h1}>What kind of business is this?</h1>
          <p style={S.sub}>Pick the closest match — you can add all the details next.</p>
          {presets.map(p => (
            <button key={p.id} type="button" style={S.presetCard(false)} onClick={() => choosePreset(p)}>
              {p.name}
            </button>
          ))}
          {presets.length === 0 && <p style={S.sub}>No business types are set up yet — please check back later.</p>}
        </div>
      )}

      {state === 'form' && preset && (
        <div style={S.card}>
          <h1 style={S.h1}>{preset.name}</h1>
          <p style={S.sub}>Fill in what you can — it saves automatically as you go.</p>
          {error && <p style={S.error}>{error}</p>}

          <input
            type="text" name="website" autoComplete="off" tabIndex={-1} style={S.honeypot}
            value={website} onChange={e => setWebsite(e.target.value)}
          />

          <Field label="Business name" required>
            <input type="text" style={S.input} maxLength={120} value={answers.business_name || ''}
                   onChange={e => updateAnswer('business_name', e.target.value)} placeholder="e.g. Adaeze Styles" />
          </Field>

          {(preset.brief_questions || []).map(q => (
            <Question key={q.key} q={q} value={answers[q.key]} answers={answers}
                      onChange={v => updateAnswer(q.key, v)}
                      onPhoto={(file) => handlePhoto(q.key, file, preset.max_items || 10)}
                      onAddItem={() => addItem(preset.max_items || 20)}
                      onUpdateItem={updateItem} onRemoveItem={removeItem}
                      maxItems={preset.max_items || 20} />
          ))}

          <button type="button" style={{ ...S.btn, ...(submitting ? S.btnDisabled : {}) }} disabled={submitting} onClick={handleSubmit}>
            {submitting ? 'Submitting…' : 'Submit'}
          </button>
          <p style={S.saveHint}>{saving ? 'Saving…' : 'Saved'}</p>
        </div>
      )}

      {state === 'submitted' && (
        <div style={S.card}>
          <div style={S.centered}>
            <div style={S.successIcon}>✅</div>
            <p style={S.successTitle}>All done!</p>
            <p style={S.successSub}>{form?.message || 'Thank you — this has been submitted.'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, required, skippable, onSkip, skipped, children }) {
  return (
    <div style={S.section}>
      <label style={S.label}>
        {label}{required && !skippable ? ' *' : ''}
        {skippable && !skipped && <button type="button" style={S.skipBtn} onClick={onSkip}>Skip</button>}
      </label>
      {!skipped && children}
      {skipped && <p style={{ fontSize: 13, color: '#8aa0ab', fontStyle: 'italic' }}>Skipped</p>}
    </div>
  )
}

function Question({ q, value, answers, onChange, onPhoto, onAddItem, onUpdateItem, onRemoveItem, maxItems }) {
  const [skipped, setSkipped] = useState(value === null)
  const skippable = !!q.skip_ok

  if (skipped) {
    return <Field label={q.prompt} skippable skipped />
  }

  if (q.type === 'choice' && Array.isArray(q.choices)) {
    return (
      <Field label={q.prompt} required={q.required} skippable={skippable} onSkip={() => { setSkipped(true); onChange(null) }}>
        <div style={S.choiceRow}>
          {q.choices.map(c => (
            <button key={c} type="button" style={S.choiceBtn(value === c)} onClick={() => onChange(c)}>{c}</button>
          ))}
        </div>
      </Field>
    )
  }

  if (q.type === 'photos') {
    const urls = (answers._photos && answers._photos[q.key]) || []
    return (
      <Field label={q.prompt} required={q.required} skippable={skippable} onSkip={() => setSkipped(true)}>
        <div style={S.photoGrid}>
          {urls.map((u, i) => <img key={i} src={(u && u.public_url) || u} alt="" style={S.photoThumb} />)}
          {urls.length < maxItems && (
            <label style={S.photoAdd}>
              +
              <input type="file" accept="image/jpeg,image/png,image/webp" style={{ display: 'none' }}
                     onChange={e => { const f = e.target.files?.[0]; if (f) onPhoto(f); e.target.value = '' }} />
            </label>
          )}
        </div>
      </Field>
    )
  }

  if (q.type === 'items') {
    const items = Array.isArray(value) ? value : []
    return (
      <Field label={q.prompt} required={q.required}>
        {items.map((it, idx) => (
          <div key={idx} style={S.itemCard}>
            <div style={S.itemRow}>
              <input style={S.input} placeholder="Name" value={it.name || ''} onChange={e => onUpdateItem(idx, 'name', e.target.value)} />
              <input style={{ ...S.input, maxWidth: 120 }} placeholder="Price (₦)" inputMode="numeric"
                     value={it.price_ngn ?? ''} onChange={e => onUpdateItem(idx, 'price_ngn', e.target.value.replace(/[^\d.]/g, ''))} />
            </div>
            <textarea style={{ ...S.textarea, minHeight: 50 }} placeholder="Description (optional)"
                      value={it.desc || ''} onChange={e => onUpdateItem(idx, 'desc', e.target.value)} />
            <button type="button" style={S.removeBtn} onClick={() => onRemoveItem(idx)}>Remove</button>
          </div>
        ))}
        {items.length < maxItems && (
          <button type="button" style={S.addBtn} onClick={onAddItem}>+ Add an item</button>
        )}
      </Field>
    )
  }

  if (q.type === 'colour') {
    return (
      <Field label={q.prompt} required={q.required} skippable={skippable} onSkip={() => { setSkipped(true); onChange(null) }}>
        <div style={S.choiceRow}>
          {['One of your palettes', 'Pick a colour', 'Match my logo'].map(mode => (
            <button key={mode} type="button" style={S.choiceBtn(value?.mode === mode)}
                    onClick={() => onChange({ mode, hex: value?.hex || '' })}>{mode}</button>
          ))}
        </div>
        {value?.mode === 'Pick a colour' && (
          <input type="color" style={{ marginTop: 8 }} value={value?.hex || '#1dc8a4'}
                 onChange={e => onChange({ ...value, hex: e.target.value })} />
        )}
      </Field>
    )
  }

  // text / number / phone — plain input
  const inputType = q.type === 'phone' ? 'tel' : q.type === 'number' ? 'number' : 'text'
  const long = (q.max_len || 0) > 160
  return (
    <Field label={q.prompt} required={q.required} skippable={skippable} onSkip={() => { setSkipped(true); onChange(null) }}>
      {long ? (
        <textarea style={S.textarea} maxLength={q.max_len || 600} value={value || ''} onChange={e => onChange(e.target.value)} />
      ) : (
        <input type={inputType} style={S.input} maxLength={q.max_len || 200} value={value || ''} onChange={e => onChange(e.target.value)} />
      )}
    </Field>
  )
}
