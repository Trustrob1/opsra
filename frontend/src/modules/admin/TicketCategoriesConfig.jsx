/**
 * frontend/src/modules/admin/TicketCategoriesConfig.jsx
 * CONFIG-1 — Org-configurable ticket and KB article categories.
 *
 * - Lists existing categories with editable labels and enabled toggles
 * - Add new custom categories (key auto-generated from label)
 * - Remove custom categories (default categories can be disabled but not deleted)
 * - Applies to both ticket category dropdown and KB article category dropdown
 *
 * Pattern 50: axios + _h() via admin.service.js only.
 * Pattern 51: full rewrite only, never sed.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getTicketCategories, updateTicketCategories } from '../../services/admin.service'

const DEFAULT_KEYS = new Set([
  'technical_bug', 'billing', 'feature_question',
  'onboarding_help', 'account_access', 'hardware',
])

const DEFAULT_CATEGORIES = [
  { key: 'technical_bug',    label: 'Technical Bug',    enabled: true },
  { key: 'billing',          label: 'Billing',          enabled: true },
  { key: 'feature_question', label: 'Feature Question', enabled: true },
  { key: 'onboarding_help',  label: 'Onboarding Help',  enabled: true },
  { key: 'account_access',   label: 'Account Access',   enabled: true },
  { key: 'hardware',         label: 'Hardware',         enabled: true },
]

function labelToKey(label) {
  return label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
}

export default function TicketCategoriesConfig() {
  const [categories, setCategories] = useState(null)
  const [saving,     setSaving]     = useState(false)
  const [error,      setError]      = useState(null)
  const [success,    setSuccess]    = useState(false)
  const [newLabel,   setNewLabel]   = useState('')
  const [addError,   setAddError]   = useState(null)

  useEffect(() => {
    getTicketCategories()
      .then(data => setCategories(data.categories ?? DEFAULT_CATEGORIES))
      .catch(() => setCategories([...DEFAULT_CATEGORIES]))
  }, [])

  // ── Helpers ───────────────────────────────────────────────────────────────

  function updateLabel(idx, value) {
    setCategories(prev => prev.map((c, i) => i === idx ? { ...c, label: value } : c))
    setSuccess(false)
  }

  function toggleEnabled(idx) {
    setCategories(prev => prev.map((c, i) => i === idx ? { ...c, enabled: !c.enabled } : c))
    setSuccess(false)
  }

  function removeCategory(idx) {
    setCategories(prev => prev.filter((_, i) => i !== idx))
    setSuccess(false)
  }

  function addCategory() {
    const label = newLabel.trim()
    if (!label) { setAddError('Enter a category name.'); return }
    const key = labelToKey(label)
    if (!key) { setAddError('Invalid name — use letters and numbers only.'); return }
    if (categories.some(c => c.key === key)) {
      setAddError(`A category with key "${key}" already exists.`)
      return
    }
    setCategories(prev => [...prev, { key, label, enabled: true }])
    setNewLabel('')
    setAddError(null)
    setSuccess(false)
  }

  async function handleSave() {
    if (!categories) return
    const invalid = categories.find(c => !c.label || !c.label.trim())
    if (invalid) { setError('All category labels are required.'); return }
    const tooLong = categories.find(c => c.label.trim().length > 80)
    if (tooLong) { setError(`Label "${tooLong.label}" exceeds 80 characters.`); return }
    const enabledCount = categories.filter(c => c.enabled).length
    if (enabledCount < 1) { setError('At least one category must be enabled.'); return }

    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      await updateTicketCategories({ categories })
      setSuccess(true)
    } catch (e) {
      const msg = e?.response?.data?.detail?.message
        || e?.response?.data?.detail
        || 'Failed to save. Please try again.'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setSaving(false)
    }
  }

  // ── Loading ───────────────────────────────────────────────────────────────

  if (!categories) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
        <div style={{ fontSize: 22, marginBottom: 8 }}>🏷️</div>
        Loading categories…
      </div>
    )
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ maxWidth: 720 }}>

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18,
          color: '#0a1a24', margin: '0 0 6px',
        }}>
          🏷️ Ticket &amp; KB Categories
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0 }}>
          These categories appear in both the ticket creation form and the knowledge base.
          Disable defaults that don't apply to your business, or add custom ones.
        </p>
      </div>

      {/* Category list */}
      <div style={{
        background: 'white',
        border: '1px solid #d4e5ee',
        borderRadius: 10,
        overflow: 'hidden',
        marginBottom: 20,
      }}>

        {/* Column headers */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 160px 80px 44px',
          padding: '8px 16px',
          background: '#f0f6f9',
          borderBottom: '1px solid #d4e5ee',
          alignItems: 'center',
          gap: 0,
        }}>
          <span style={hdr}>Label</span>
          <span style={hdr}>Key</span>
          <span style={{ ...hdr, textAlign: 'center' }}>Enabled</span>
          <span />
        </div>

        {categories.map((cat, idx) => {
          const isDefault = DEFAULT_KEYS.has(cat.key)
          return (
            <div
              key={cat.key}
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 160px 80px 44px',
                padding: '11px 16px',
                borderBottom: idx < categories.length - 1 ? '1px solid #edf3f7' : 'none',
                alignItems: 'center',
                background: cat.enabled ? 'white' : '#f9fbfc',
                gap: 0,
              }}
            >
              {/* Label */}
              <div style={{ paddingRight: 16 }}>
                <input
                  value={cat.label}
                  onChange={e => updateLabel(idx, e.target.value)}
                  maxLength={80}
                  style={{
                    width: '100%', border: '1px solid #d4e5ee', borderRadius: 6,
                    padding: '6px 10px', fontSize: 13, fontFamily: ds.fontDm,
                    color: cat.enabled ? '#0a1a24' : '#9ab0bc',
                    background: cat.enabled ? 'white' : '#f0f6f9',
                    outline: 'none', boxSizing: 'border-box',
                  }}
                />
              </div>

              {/* Key */}
              <div style={{ paddingRight: 16 }}>
                <span style={{
                  fontFamily: 'monospace', fontSize: 11,
                  background: '#edf3f7', color: '#4a7a8a',
                  padding: '3px 8px', borderRadius: 4, whiteSpace: 'nowrap',
                }}>
                  {cat.key}
                </span>
              </div>

              {/* Enabled toggle */}
              <div style={{ textAlign: 'center' }}>
                <button
                  onClick={() => toggleEnabled(idx)}
                  style={{
                    width: 36, height: 20, borderRadius: 10, border: 'none',
                    cursor: 'pointer',
                    background: cat.enabled ? ds.teal : '#c8d8e4',
                    position: 'relative', transition: 'background 0.2s',
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 2,
                    left: cat.enabled ? 18 : 2,
                    width: 16, height: 16, borderRadius: '50%',
                    background: 'white', transition: 'left 0.2s',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }} />
                </button>
              </div>

              {/* Remove (custom only) */}
              <div style={{ textAlign: 'center' }}>
                {!isDefault && (
                  <button
                    onClick={() => removeCategory(idx)}
                    title="Remove category"
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      color: '#c8d8e4', fontSize: 16, lineHeight: 1,
                      padding: 2,
                    }}
                    onMouseEnter={e => e.target.style.color = '#ef4444'}
                    onMouseLeave={e => e.target.style.color = '#c8d8e4'}
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Add custom category */}
      <div style={{
        background: '#f0f6f9', border: '1px dashed #c8d8e4',
        borderRadius: 10, padding: '14px 16px', marginBottom: 24,
      }}>
        <p style={{ fontSize: 12, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 10px' }}>
          Add Custom Category
        </p>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <div style={{ flex: 1 }}>
            <input
              value={newLabel}
              onChange={e => { setNewLabel(e.target.value); setAddError(null) }}
              onKeyDown={e => e.key === 'Enter' && addCategory()}
              placeholder="e.g. Integration Support"
              maxLength={80}
              style={{
                width: '100%', border: '1px solid #d4e5ee', borderRadius: 6,
                padding: '7px 11px', fontSize: 13, fontFamily: ds.fontDm,
                color: '#0a1a24', background: 'white', outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            {newLabel && (
              <p style={{ fontSize: 11, color: '#7A9BAD', margin: '4px 0 0' }}>
                Key: <code style={{ fontFamily: 'monospace' }}>{labelToKey(newLabel) || '—'}</code>
              </p>
            )}
            {addError && <p style={{ fontSize: 12, color: '#b91c1c', margin: '4px 0 0' }}>{addError}</p>}
          </div>
          <button
            onClick={addCategory}
            style={{
              background: ds.teal, color: 'white', border: 'none',
              borderRadius: 7, padding: '8px 16px', fontSize: 13,
              fontFamily: ds.fontDm, fontWeight: 600, cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            + Add
          </button>
        </div>
      </div>

      {/* Feedback */}
      {error && (
        <div style={{
          marginBottom: 16, padding: '10px 14px',
          background: '#fef2f2', border: '1px solid #fca5a5',
          borderRadius: 8, fontSize: 13, color: '#b91c1c',
        }}>
          {error}
        </div>
      )}
      {success && (
        <div style={{
          marginBottom: 16, padding: '10px 14px',
          background: '#f0fdf4', border: '1px solid #86efac',
          borderRadius: 8, fontSize: 13, color: '#15803d',
        }}>
          ✅ Categories saved successfully.
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: saving ? '#7A9BAD' : ds.teal, color: 'white',
            border: 'none', borderRadius: 8, padding: '9px 22px',
            fontSize: 13, fontFamily: ds.fontDm, fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        <button
          onClick={() => { setCategories([...DEFAULT_CATEGORIES]); setSuccess(false); setError(null) }}
          disabled={saving}
          style={{
            background: 'none', color: '#4a7a8a',
            border: '1px solid #d4e5ee', borderRadius: 8,
            padding: '8px 18px', fontSize: 13, fontFamily: ds.fontDm,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          Reset to Defaults
        </button>
      </div>
    </div>
  )
}

const hdr = {
  fontSize: 11, fontWeight: 700, color: '#7A9BAD',
  textTransform: 'uppercase', letterSpacing: '0.06em',
}
