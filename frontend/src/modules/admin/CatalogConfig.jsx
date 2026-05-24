/**
 * frontend/src/modules/admin/CatalogConfig.jsx
 * CATALOG-2B: Catalog configuration admin panel.
 * Three sections: Catalog Identity · CTA Buttons · Tag Dimensions
 * Pattern 51: full rewrite only — never sed.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

const INPUT = {
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: '1px solid #D0E8F0', fontFamily: ds.fontDm, fontSize: 13.5,
  color: '#0a1a24', background: 'white', boxSizing: 'border-box',
  outline: 'none',
}

const LABEL = {
  fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600,
  color: '#4a7a8a', marginBottom: 6, display: 'block',
}

const SECTION = {
  background: 'white', borderRadius: 12, border: '1px solid #E2EFF4',
  padding: 24, marginBottom: 20,
}

const SECTION_TITLE = {
  fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15,
  color: '#0a1a24', margin: '0 0 18px',
}

const BTN_PRIMARY = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8,
  padding: '10px 22px', fontFamily: ds.fontDm, fontSize: 13.5,
  fontWeight: 600, cursor: 'pointer',
}

const BTN_GHOST = {
  background: 'none', border: '1px solid #D0E8F0', borderRadius: 8,
  padding: '7px 14px', fontFamily: ds.fontDm, fontSize: 13,
  color: '#4a7a8a', cursor: 'pointer',
}

const BTN_DANGER = {
  background: 'none', border: 'none', color: '#e05c5c',
  cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 12.5,
  padding: '4px 8px',
}

const TOGGLE = ({ value, onChange, label }) => (
  <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
    <div
      onClick={() => onChange(!value)}
      style={{
        width: 40, height: 22, borderRadius: 11, position: 'relative',
        background: value ? ds.teal : '#D0E8F0',
        transition: 'background 0.2s', cursor: 'pointer', flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute', top: 3, left: value ? 20 : 3,
        width: 16, height: 16, borderRadius: '50%', background: 'white',
        transition: 'left 0.2s',
      }} />
    </div>
    <span style={{ fontFamily: ds.fontDm, fontSize: 13.5, color: '#0a1a24' }}>{label}</span>
  </label>
)

const FIELD_ROW = ({ children, cols = 2 }) => (
  <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 16, marginBottom: 16 }}>
    {children}
  </div>
)

function Field({ label, children }) {
  return (
    <div>
      <span style={LABEL}>{label}</span>
      {children}
    </div>
  )
}

// ── Defaults ──────────────────────────────────────────────────────────────────
const DEFAULT_CONFIG = {
  catalog_item_label:        '',
  catalog_item_label_plural: '',
  price_label_template:      '₦{price}',
  price_on_request:          false,
  availability_labels:       { available: 'In Stock', unavailable: 'Out of Stock' },
  external_sync:             'none',
  cta_buttons:               [
    { id: 'cta_1', label: 'CTA Button 1' },
    { id: 'cta_2', label: 'CTA Button 2' },
  ],
  tag_dimensions: [],
}

export default function CatalogConfig() {
  const [config, setConfig]   = useState(null)
  const [saving, setSaving]   = useState(false)
  const [toast, setToast]     = useState('')
  const [error, setError]     = useState('')

  useEffect(() => {
    adminSvc.getCatalogConfig()
      .then(async c => {
        if (!c) {
          // First time setup — seed defaults so org always has a config record
          try { await adminSvc.updateCatalogConfig(DEFAULT_CONFIG) } catch (_) {}
        }
        setConfig({
          ...DEFAULT_CONFIG, ...(c || {}),
          availability_labels: { ...DEFAULT_CONFIG.availability_labels, ...(c?.availability_labels || {}) },
          cta_buttons:    c?.cta_buttons    || DEFAULT_CONFIG.cta_buttons,
          tag_dimensions: c?.tag_dimensions || [],
          _isFirstSetup:  !c,
        })
      })
      .catch(() => setError('Failed to load catalog config.'))
  }, [])

  function flash(msg) {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  async function save() {
    setError('')
    // Validate: 2–3 CTA buttons
    if (!config.cta_buttons || config.cta_buttons.length < 2 || config.cta_buttons.length > 3) {
      setError('You need between 2 and 3 CTA buttons.')
      return
    }
    for (const btn of config.cta_buttons) {
      if (!btn.id || !btn.label) { setError('All CTA buttons need an ID and label.'); return }
      if (!/^[a-zA-Z0-9_]+$/.test(btn.id)) { setError(`Button ID "${btn.id}" must be letters, numbers, and underscores only.`); return }
      if (btn.label.length > 24) { setError(`Button label "${btn.label}" exceeds 24 characters.`); return }
    }
    for (const dim of (config.tag_dimensions || [])) {
      if (!dim.key || !dim.label) { setError('All tag dimensions need a key and label.'); return }
      if (!/^[a-zA-Z0-9_]+$/.test(dim.key)) { setError(`Tag key "${dim.key}" must be letters, numbers, and underscores only.`); return }
    }
    setSaving(true)
    try {
      const saved = await adminSvc.updateCatalogConfig(config)
      setConfig(prev => ({ ...prev, ...saved }))
      flash('Catalog config saved.')
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  // ── CTA button helpers ──────────────────────────────────────────────────────
  function updateBtn(i, field, val) {
    setConfig(prev => {
      const btns = [...prev.cta_buttons]
      btns[i] = { ...btns[i], [field]: val }
      return { ...prev, cta_buttons: btns }
    })
  }
  function addBtn() {
    if ((config.cta_buttons || []).length >= 3) return
    setConfig(prev => ({ ...prev, cta_buttons: [...prev.cta_buttons, { id: '', label: '' }] }))
  }
  function removeBtn(i) {
    setConfig(prev => ({ ...prev, cta_buttons: prev.cta_buttons.filter((_, idx) => idx !== i) }))
  }

  // ── Tag dimension helpers ───────────────────────────────────────────────────
  function updateDim(i, field, val) {
    setConfig(prev => {
      const dims = [...prev.tag_dimensions]
      dims[i] = { ...dims[i], [field]: val }
      return { ...prev, tag_dimensions: dims }
    })
  }
  function addDim() {
    if ((config.tag_dimensions || []).length >= 10) return
    setConfig(prev => ({
      ...prev,
      tag_dimensions: [...prev.tag_dimensions, { key: '', label: '', type: 'multi_select', filterable: true, options: [] }],
    }))
  }
  function removeDim(i) {
    setConfig(prev => ({ ...prev, tag_dimensions: prev.tag_dimensions.filter((_, idx) => idx !== i) }))
  }
  function moveDim(i, dir) {
    setConfig(prev => {
      const dims = [...prev.tag_dimensions]
      const j = i + dir
      if (j < 0 || j >= dims.length) return prev
      ;[dims[i], dims[j]] = [dims[j], dims[i]]
      return { ...prev, tag_dimensions: dims }
    })
  }
  function addOption(dimIdx) {
    setConfig(prev => {
      const dims = [...prev.tag_dimensions]
      dims[dimIdx] = { ...dims[dimIdx], options: [...(dims[dimIdx].options || []), ''] }
      return { ...prev, tag_dimensions: dims }
    })
  }
  function updateOption(dimIdx, optIdx, val) {
    setConfig(prev => {
      const dims = [...prev.tag_dimensions]
      const opts = [...dims[dimIdx].options]
      opts[optIdx] = val
      dims[dimIdx] = { ...dims[dimIdx], options: opts }
      return { ...prev, tag_dimensions: dims }
    })
  }
  function removeOption(dimIdx, optIdx) {
    setConfig(prev => {
      const dims = [...prev.tag_dimensions]
      dims[dimIdx] = { ...dims[dimIdx], options: dims[dimIdx].options.filter((_, i) => i !== optIdx) }
      return { ...prev, tag_dimensions: dims }
    })
  }

  if (!config) return (
    <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
      Loading catalog config…
    </div>
  )

  const isShopify = config.external_sync === 'shopify'
  const pricePreview = config.price_on_request
    ? 'Price on Request'
    : (config.price_label_template || '').replace('{price}', '150,000')

  return (
    <div style={{ maxWidth: 780 }}>

      {/* Toast */}
      {toast && (
        <div style={{ background: '#eafaf2', border: '1px solid #6fcf97', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13.5, color: '#1a6640' }}>
          ✅ {toast}
        </div>
      )}
      {error && (
        <div style={{ background: '#fff2f2', border: '1px solid #e05c5c', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13.5, color: '#c0392b' }}>
          ⚠️ {error}
        </div>
      )}
      {config._isFirstSetup && (
        <div style={{ background: '#f0f7ff', border: '1px solid #b3d4f0', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13.5, color: '#1a4a6e' }}>
          👋 First time setup — fill in your catalog settings below and click Save.
        </div>
      )}

      {/* ── Section 1: Catalog Identity ── */}
      <div style={SECTION}>
        <h3 style={SECTION_TITLE}>Catalog Identity</h3>
        <FIELD_ROW>
          <Field label="Item Label (singular)">
            <input style={INPUT} value={config.catalog_item_label || ''} maxLength={50}
              onChange={e => setConfig(p => ({ ...p, catalog_item_label: e.target.value }))} />
          </Field>
          <Field label="Item Label (plural)">
            <input style={INPUT} value={config.catalog_item_label_plural || ''} maxLength={50}
              onChange={e => setConfig(p => ({ ...p, catalog_item_label_plural: e.target.value }))} />
          </Field>
        </FIELD_ROW>

        <FIELD_ROW>
          <Field label={`Price Format  →  Preview: ${pricePreview}`}>
            <input style={{ ...INPUT, opacity: config.price_on_request ? 0.4 : 1 }}
              value={config.price_label_template || ''} maxLength={50}
              disabled={config.price_on_request}
              onChange={e => setConfig(p => ({ ...p, price_label_template: e.target.value }))}
              placeholder="e.g. ₦{price}" />
          </Field>
          <Field label=" ">
            <div style={{ paddingTop: 8 }}>
              <TOGGLE value={config.price_on_request} label="Price on Request (hides price format)"
                onChange={v => setConfig(p => ({ ...p, price_on_request: v }))} />
            </div>
          </Field>
        </FIELD_ROW>

        <FIELD_ROW>
          <Field label='Availability Label — "Available"'>
            <input style={INPUT} maxLength={50}
              value={config.availability_labels?.available || ''}
              onChange={e => setConfig(p => ({ ...p, availability_labels: { ...p.availability_labels, available: e.target.value } }))} />
          </Field>
          <Field label='Availability Label — "Unavailable"'>
            <input style={INPUT} maxLength={50}
              value={config.availability_labels?.unavailable || ''}
              onChange={e => setConfig(p => ({ ...p, availability_labels: { ...p.availability_labels, unavailable: e.target.value } }))} />
          </Field>
        </FIELD_ROW>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#f5fbfd', borderRadius: 8, border: '1px solid #D0E8F0' }}>
          <span style={{ fontSize: 16 }}>🔗</span>
          <div>
            <span style={{ fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#0a1a24' }}>Sync Source: </span>
            <span style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a' }}>
              {isShopify ? 'Shopify (products managed via Shopify)' : 'Manual (products managed in Opsra)'}
            </span>
          </div>
        </div>
      </div>

      {/* ── Section 2: CTA Buttons ── */}
      <div style={SECTION}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ ...SECTION_TITLE, margin: 0 }}>CTA Buttons</h3>
          <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>Min 2 · Max 3</span>
        </div>
        <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', margin: '0 0 18px' }}>
          These appear on the catalog product page for qualified leads. Each button sends its ID as a WhatsApp message.
        </p>

        {(config.cta_buttons || []).map((btn, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 2fr auto', gap: 12, marginBottom: 12, alignItems: 'flex-end' }}>
            <Field label={i === 0 ? 'Button ID (alphanumeric_underscore)' : ' '}>
              <input style={INPUT} value={btn.id} maxLength={50} placeholder="e.g. showroom_visit"
                onChange={e => updateBtn(i, 'id', e.target.value)} />
            </Field>
            <Field label={i === 0 ? 'Button Label (max 24 chars)' : ' '}>
              <input style={INPUT} value={btn.label} maxLength={24} placeholder="e.g. 🏪 Visit Showroom"
                onChange={e => updateBtn(i, 'label', e.target.value)} />
            </Field>
            <button style={{ ...BTN_DANGER, marginBottom: 1 }}
              onClick={() => removeBtn(i)}
              disabled={(config.cta_buttons || []).length <= 2}>
              🗑
            </button>
          </div>
        ))}

        {(config.cta_buttons || []).length < 3 && (
          <button style={BTN_GHOST} onClick={addBtn}>+ Add Button</button>
        )}

        {/* WhatsApp preview */}
        <div style={{ marginTop: 20, padding: 16, background: '#f5fbfd', borderRadius: 10, border: '1px solid #D0E8F0' }}>
          <p style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD', margin: '0 0 10px' }}>Preview — how buttons appear in WhatsApp</p>
          {(config.cta_buttons || []).filter(b => b.label).map((btn, i) => (
            <div key={i} style={{ background: 'white', border: '1px solid #D0E8F0', borderRadius: 8, padding: '9px 16px', marginBottom: 8, fontFamily: ds.fontDm, fontSize: 13.5, color: ds.teal, textAlign: 'center' }}>
              {btn.label}
            </div>
          ))}
        </div>
      </div>

      {/* ── Section 3: Tag Dimensions ── */}
      <div style={SECTION}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ ...SECTION_TITLE, margin: 0 }}>Tag Dimensions</h3>
          <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>Max 10 dimensions</span>
        </div>
        <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', margin: '0 0 18px' }}>
          Tags are used to match qualification answers to catalog items and to filter the catalog.
        </p>

        {(config.tag_dimensions || []).length === 0 && (
          <div style={{ textAlign: 'center', padding: '24px 0', color: '#7A9BAD', fontFamily: ds.fontDm, fontSize: 13.5 }}>
            No tag dimensions yet. Add one to get started.
          </div>
        )}

        {(config.tag_dimensions || []).map((dim, i) => (
          <div key={i} style={{ border: '1px solid #E2EFF4', borderRadius: 10, padding: 16, marginBottom: 12, background: '#fafeff' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <span style={{ fontFamily: ds.fontDm, fontWeight: 600, fontSize: 13.5, color: '#0a1a24' }}>
                Dimension {i + 1}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button style={BTN_GHOST} onClick={() => moveDim(i, -1)} disabled={i === 0} title="Move up">↑</button>
                <button style={BTN_GHOST} onClick={() => moveDim(i, 1)} disabled={i === (config.tag_dimensions.length - 1)} title="Move down">↓</button>
                <button style={BTN_DANGER} onClick={() => removeDim(i)}>🗑</button>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 12, marginBottom: 14, alignItems: 'flex-end' }}>
              <Field label="Key (alphanumeric_underscore)">
                <input style={INPUT} value={dim.key} maxLength={50} placeholder="e.g. health_conditions"
                  onChange={e => updateDim(i, 'key', e.target.value)} />
              </Field>
              <Field label="Label (display name)">
                <input style={INPUT} value={dim.label} maxLength={50} placeholder="e.g. Health Benefits"
                  onChange={e => updateDim(i, 'label', e.target.value)} />
              </Field>
              <Field label="Type">
                <select style={{ ...INPUT, cursor: 'pointer' }} value={dim.type}
                  onChange={e => updateDim(i, 'type', e.target.value)}>
                  <option value="single_select">Single Select</option>
                  <option value="multi_select">Multi Select</option>
                </select>
              </Field>
              <div style={{ paddingBottom: 2 }}>
                <TOGGLE value={dim.filterable} label="Filterable"
                  onChange={v => updateDim(i, 'filterable', v)} />
              </div>
            </div>

            <div>
              <span style={LABEL}>Options ({(dim.options || []).length}/20)</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
                {(dim.options || []).map((opt, oi) => (
                  <div key={oi} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'white', border: '1px solid #D0E8F0', borderRadius: 20, padding: '3px 8px 3px 12px' }}>
                    <input style={{ border: 'none', outline: 'none', fontFamily: ds.fontDm, fontSize: 13, color: '#0a1a24', width: Math.max(60, opt.length * 8), background: 'transparent' }}
                      value={opt} maxLength={100}
                      onChange={e => updateOption(i, oi, e.target.value)} />
                    <button style={{ ...BTN_DANGER, padding: '0 4px', fontSize: 11 }}
                      onClick={() => removeOption(i, oi)}>✕</button>
                  </div>
                ))}
              </div>
              {(dim.options || []).length < 20 && (
                <button style={{ ...BTN_GHOST, fontSize: 12, padding: '5px 12px' }} onClick={() => addOption(i)}>+ Add Option</button>
              )}
            </div>
          </div>
        ))}

        {(config.tag_dimensions || []).length < 10 && (
          <button style={BTN_GHOST} onClick={addDim}>+ Add Tag Dimension</button>
        )}
      </div>

      {/* ── Save ── */}
      <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
        <button style={{ ...BTN_PRIMARY, opacity: saving ? 0.6 : 1 }} onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save Catalog Config'}
        </button>
      </div>
    </div>
  )
}
