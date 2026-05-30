/**
 * frontend/src/modules/admin/InternalIssueCategoriesConfig.jsx
 * OPS-1A — Internal Issue Categories configuration panel in Admin Dashboard.
 *
 * Allows owner/ops_manager to define categories for internal ops issues.
 * Completely separate from ticket_categories (customer support).
 *
 * Follows same pattern as TicketCategoriesConfig.
 * Pattern 51: full rewrite if editing — never partial sed.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getInternalIssueCategories, updateInternalIssueCategories } from '../../services/admin.service'

const LABEL = {
  display:       'block',
  fontSize:      11,
  fontWeight:    600,
  color:         '#4a7a8a',
  textTransform: 'uppercase',
  letterSpacing: '0.7px',
  marginBottom:  8,
}

const INPUT = {
  padding:      '9px 12px',
  border:       '1px solid #D4E6EC',
  borderRadius: 8,
  fontSize:     13.5,
  fontFamily:   'inherit',
  color:        '#0a1a24',
  background:   'white',
  outline:      'none',
}

function slugify(str) {
  return str.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')
}

export default function InternalIssueCategoriesConfig() {
  const [categories, setCategories] = useState([])
  const [newLabel, setNewLabel]     = useState('')
  const [loading, setLoading]       = useState(true)
  const [saving, setSaving]         = useState(false)
  const [error, setError]           = useState(null)
  const [saved, setSaved]           = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getInternalIssueCategories()
      setCategories(data?.categories ?? [])
    } catch {
      setError('Failed to load categories.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleAdd = () => {
    const trimmed = newLabel.trim()
    if (!trimmed) return
    const key = slugify(trimmed)
    if (!key) { setError('Invalid category name.'); return }
    if (categories.some(c => c.key === key)) {
      setError('A category with this name already exists.')
      return
    }
    setCategories(prev => [...prev, { key, label: trimmed, enabled: true }])
    setNewLabel('')
    setError(null)
  }

  const handleToggle = (index) => {
    setCategories(prev => prev.map((c, i) =>
      i === index ? { ...c, enabled: !c.enabled } : c
    ))
  }

  const handleRemove = (index) => {
    setCategories(prev => prev.filter((_, i) => i !== index))
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); handleAdd() }
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await updateInternalIssueCategories({ categories })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to save categories.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading categories…</div>
  }

  return (
    <div style={{ maxWidth: 600 }}>
      <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 6px' }}>
        Internal Issue Categories
      </h2>
      <p style={{ fontSize: 13, color: '#7A9BAD', margin: '0 0 28px', lineHeight: 1.6 }}>
        Define the categories used when logging internal team issues. These are separate
        from customer support ticket categories. Toggle any off to hide it without deleting it.
      </p>

      {/* Category list */}
      <label style={LABEL}>Current categories</label>
      {categories.length === 0 ? (
        <div style={{
          padding: '16px 18px', background: '#F8FAFC',
          border: '1px dashed #CBD5E1', borderRadius: 8,
          fontSize: 13, color: '#7A9BAD', marginBottom: 20,
        }}>
          No categories configured yet. Add your first one below.
        </div>
      ) : (
        <div style={{ marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {categories.map((cat, i) => (
            <div
              key={cat.key}
              style={{
                display:       'flex',
                alignItems:    'center',
                justifyContent:'space-between',
                background:    cat.enabled ? '#EEF8FA' : '#F8FAFC',
                border:        `1px solid ${cat.enabled ? '#B2DDE8' : '#E2E8F0'}`,
                borderRadius:  8,
                padding:       '9px 12px 9px 16px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {/* Toggle */}
                <div
                  onClick={() => handleToggle(i)}
                  style={{
                    width: 32, height: 18, borderRadius: 9,
                    background: cat.enabled ? ds.teal : '#CBD5E1',
                    position: 'relative', cursor: 'pointer', flexShrink: 0,
                    transition: 'background 0.2s',
                  }}
                >
                  <div style={{
                    position: 'absolute', top: 2,
                    left: cat.enabled ? 16 : 2,
                    width: 14, height: 14, borderRadius: '50%',
                    background: 'white', transition: 'left 0.2s',
                  }} />
                </div>
                <span style={{
                  fontSize: 13.5, fontWeight: 500,
                  color: cat.enabled ? '#0a1a24' : '#94A3B8',
                }}>
                  {cat.label}
                </span>
                <span style={{ fontSize: 11, color: '#94A3B8' }}>({cat.key})</span>
              </div>
              <button
                onClick={() => handleRemove(i)}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: '#94A3B8', fontSize: 18, lineHeight: 1,
                  padding: '0 4px', fontFamily: 'inherit',
                }}
                title={`Remove ${cat.label}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add new */}
      <label style={LABEL}>Add a category</label>
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        <input
          value={newLabel}
          onChange={e => { setNewLabel(e.target.value); setError(null) }}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Process Issue, Resource Blocker"
          style={{ ...INPUT, flex: 1 }}
          maxLength={100}
        />
        <button
          onClick={handleAdd}
          disabled={!newLabel.trim()}
          style={{
            background:   newLabel.trim() ? ds.teal : '#CBD5E1',
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '9px 18px',
            fontSize:     13.5,
            fontWeight:   600,
            cursor:       newLabel.trim() ? 'pointer' : 'not-allowed',
            fontFamily:   'inherit',
            whiteSpace:   'nowrap',
          }}
        >
          + Add
        </button>
      </div>

      {error && (
        <p style={{ color: '#DC2626', fontSize: 13, margin: '-14px 0 16px' }}>⚠ {error}</p>
      )}

      {/* Save */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background:   saving ? '#aaa' : ds.teal,
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '10px 24px',
            fontSize:     14,
            fontWeight:   600,
            cursor:       saving ? 'not-allowed' : 'pointer',
            fontFamily:   ds.fontSyne,
          }}
        >
          {saving ? 'Saving…' : 'Save Categories'}
        </button>
        {saved && (
          <span style={{ fontSize: 13, color: '#059669', fontWeight: 500 }}>
            ✓ Categories saved
          </span>
        )}
      </div>
    </div>
  )
}
