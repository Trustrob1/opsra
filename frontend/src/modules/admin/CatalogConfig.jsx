/**
 * frontend/src/modules/admin/CatalogConfig.jsx
 * CATALOG-2B: Catalog configuration admin panel.
 * STORE-13: shown as "Settings", in plain words with a live preview. What you sell, prices, stock wording,
 * product-page headings and the product-page buttons. Button IDs, the price format code and tag dimensions
 * sit under Advanced. The saved fields are exactly the same as before.
 * Pattern 51: full rewrite only — never sed.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { PRICE_STYLES, priceStyleOf, nextButtonId } from './catalogConfigLogic'

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

function Field({ label, htmlFor, children }) {
  return (
    <div>
      {htmlFor ? <label htmlFor={htmlFor} style={LABEL}>{label}</label> : <span style={LABEL}>{label}</span>}
      {children}
    </div>
  )
}

const HINT = { marginTop: 6, fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }
const SECTION_HELP = { fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#7A9BAD', margin: '0 0 16px' }

// STORE-13: a real switch button (keyboard and screen-reader friendly)
const Switch = ({ value, onChange, label }) => (
  <button type="button" role="switch" aria-checked={!!value} aria-label={label} onClick={() => onChange(!value)}
    style={{ width: 46, height: 28, borderRadius: 14, border: 'none', padding: 0, position: 'relative', flexShrink: 0, cursor: 'pointer', background: value ? ds.teal : '#8AA6B3' }}>
    <span style={{ position: 'absolute', top: 3, left: value ? 21 : 3, width: 22, height: 22, borderRadius: '50%', background: 'white' }} />
  </button>
)

// ── Defaults ──────────────────────────────────────────────────────────────────
const DEFAULT_CONFIG = {
  catalog_item_label:        '',
  catalog_item_label_plural: '',
  price_label_template:      '₦{price}',
  price_on_request:          false,
  availability_labels:       { available: 'In Stock', unavailable: 'Out of Stock' },
  external_sync:                'none',
  gallery_section_label:        'Gallery',
  specifications_section_label: 'Specifications',
  cta_buttons:                  [
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
  const [advOpen, setAdvOpen] = useState(false)

  useEffect(() => {
    adminSvc.getCatalogConfig()
      .then(async c => {
        if (!c) {
          // First time setup — seed defaults so org always has a config record
          try { await adminSvc.updateCatalogConfig(DEFAULT_CONFIG) } catch { /* seeding is best effort */ }
        }
        setConfig({
          ...DEFAULT_CONFIG, ...(c || {}),
          availability_labels: { ...DEFAULT_CONFIG.availability_labels, ...(c?.availability_labels || {}) },
          cta_buttons:    c?.cta_buttons    || DEFAULT_CONFIG.cta_buttons,
          // STORE-6: categories are managed on the Categories tab; the server keeps that group safe
          tag_dimensions: (c?.tag_dimensions || []).filter(d => d.key !== 'category'),
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
      setError('You need two or three buttons.')
      return
    }
    for (const btn of config.cta_buttons) {
      if (!btn.label) { setError('Every button needs some text.'); return }
      if (!btn.id) { setAdvOpen(true); setError('A button is missing its ID. Open Advanced and fill it in.'); return }
      if (!/^[a-zA-Z0-9_]+$/.test(btn.id)) { setAdvOpen(true); setError(`Button ID "${btn.id}" must be letters, numbers, and underscores only.`); return }
      if (btn.label.length > 24) { setError(`Button text "${btn.label}" is longer than 24 characters.`); return }
    }
    for (const dim of (config.tag_dimensions || [])) {
      if (!dim.key || !dim.label) { setAdvOpen(true); setError('All tag dimensions need a key and label.'); return }
      if (!/^[a-zA-Z0-9_]+$/.test(dim.key)) { setAdvOpen(true); setError(`Tag key "${dim.key}" must be letters, numbers, and underscores only.`); return }
    }
    setSaving(true)
    try {
      // STORE-6: never send the Look settings from here; the Look tab owns them
      const STORE_KEYS = ['template', 'announcement', 'trust_points', 'accent', 'logo_url', 'show_categories']
      const payload = Object.fromEntries(Object.entries(config).filter(([k]) => !STORE_KEYS.includes(k)))
      const saved = await adminSvc.updateCatalogConfig(payload)
      const { tag_dimensions: _td, ...savedRest } = saved || {}
      setConfig(prev => ({ ...prev, ...savedRest }))
      flash('Settings saved.')
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
    setConfig(prev => ({ ...prev, cta_buttons: [...prev.cta_buttons, { id: nextButtonId(prev.cta_buttons), label: '' }] }))
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
  const word1 = (config.catalog_item_label || '').trim() || 'Product'
  const word2 = (config.catalog_item_label_plural || '').trim() || 'Products'
  const style = priceStyleOf(config.price_label_template)
  const pricePreview = config.price_on_request
    ? 'Contact us for the price'
    : (config.price_label_template || '').replace('{price}', '150,000')
  const buttons = (config.cta_buttons || [])
  const availText = config.availability_labels?.available || 'In Stock'

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap', paddingBottom: 40 }}>
      <div style={{ flex: '1 1 480px', minWidth: 0, maxWidth: 700 }}>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
          <div>
            <h2 style={{ margin: 0, fontFamily: ds.fontSyne, fontSize: 20, fontWeight: 700, color: '#0a1a24' }}>Wording and buttons</h2>
            <p style={{ margin: '6px 0 0', fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.5, color: '#4a7a8a', maxWidth: 520 }}>
              Optional. Your catalog already works with the defaults. Change these only if you want the words to match your business.
            </p>
          </div>
          <button style={{ ...BTN_PRIMARY, minHeight: 46, opacity: saving ? 0.6 : 1 }} onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save settings'}
          </button>
        </div>

        {toast && (
          <div role="status" style={{ background: '#eafaf2', border: '1px solid #6fcf97', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13.5, color: '#1a6640' }}>
            ✅ {toast}
          </div>
        )}
        {error && (
          <div role="alert" style={{ background: '#fff2f2', border: '1px solid #e05c5c', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13.5, color: '#c0392b' }}>
            ⚠️ {error}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', background: 'white', borderRadius: 10, border: '1px solid #E2EFF4', marginBottom: 16 }}>
          <span aria-hidden="true" style={{ fontSize: 16 }}>🔗</span>
          <span style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a' }}>
            <b style={{ color: '#0a1a24' }}>Where products come from:</b>{' '}
            {isShopify ? 'your Shopify store, synced automatically.' : 'you add them yourself in Opsra.'}
          </span>
        </div>

        {/* What you sell */}
        <div style={SECTION}>
          <h3 style={{ ...SECTION_TITLE, margin: '0 0 4px' }}>What you sell</h3>
          <p style={SECTION_HELP}>These words appear in headings, buttons and share messages.</p>
          <FIELD_ROW>
            <Field label="One item is called" htmlFor="cat-single">
              <input id="cat-single" style={INPUT} value={config.catalog_item_label || ''} maxLength={50} placeholder="Product"
                onChange={e => setConfig(p => ({ ...p, catalog_item_label: e.target.value }))} />
              <div style={HINT}>For example: Mattress, Dress, Room</div>
            </Field>
            <Field label="Several items are called" htmlFor="cat-plural">
              <input id="cat-plural" style={INPUT} value={config.catalog_item_label_plural || ''} maxLength={50} placeholder="Products"
                onChange={e => setConfig(p => ({ ...p, catalog_item_label_plural: e.target.value }))} />
              <div style={HINT}>For example: Mattresses, Dresses, Rooms</div>
            </Field>
          </FIELD_ROW>
        </div>

        {/* Prices */}
        <div style={SECTION}>
          <h3 style={SECTION_TITLE}>Prices</h3>
          <Field label="How prices look" htmlFor="cat-pstyle">
            <select id="cat-pstyle" style={{ ...INPUT, cursor: 'pointer', opacity: config.price_on_request ? 0.5 : 1 }}
              value={style} disabled={config.price_on_request}
              onChange={e => {
                const hit = PRICE_STYLES.find(p => p.id === e.target.value)
                if (hit) setConfig(p => ({ ...p, price_label_template: hit.template }))
              }}>
              {PRICE_STYLES.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
              {style === 'custom' && <option value="custom">Custom ({config.price_label_template}) – change under Advanced</option>}
            </select>
          </Field>
          <div style={{ marginTop: 16, padding: '14px 16px', borderRadius: 10, background: '#f5fbfd', display: 'flex', justifyContent: 'space-between', gap: 14, alignItems: 'center' }}>
            <div style={{ fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.4, color: '#4a7a8a' }}>
              <b style={{ display: 'block', color: '#0a1a24', fontSize: 13.5 }}>Ask customers to contact me for prices</b>
              Hides prices. Good if you quote each customer.
            </div>
            <Switch value={config.price_on_request} label="Ask customers to contact me for prices"
              onChange={v => setConfig(p => ({ ...p, price_on_request: v }))} />
          </div>
        </div>

        {/* Stock wording */}
        <div style={SECTION}>
          <h3 style={SECTION_TITLE}>Stock wording</h3>
          <FIELD_ROW>
            <Field label="When it is available" htmlFor="cat-avail">
              <input id="cat-avail" style={INPUT} maxLength={50} placeholder="In Stock"
                value={config.availability_labels?.available || ''}
                onChange={e => setConfig(p => ({ ...p, availability_labels: { ...p.availability_labels, available: e.target.value } }))} />
            </Field>
            <Field label="When it is sold out" htmlFor="cat-unavail">
              <input id="cat-unavail" style={INPUT} maxLength={50} placeholder="Out of Stock"
                value={config.availability_labels?.unavailable || ''}
                onChange={e => setConfig(p => ({ ...p, availability_labels: { ...p.availability_labels, unavailable: e.target.value } }))} />
            </Field>
          </FIELD_ROW>
        </div>

        {/* Headings */}
        <div style={SECTION}>
          <h3 style={SECTION_TITLE}>Product page headings</h3>
          <FIELD_ROW>
            <Field label="Heading above the photos" htmlFor="cat-gallery">
              <input id="cat-gallery" style={INPUT} value={config.gallery_section_label || ''} maxLength={50} placeholder="Gallery"
                onChange={e => setConfig(p => ({ ...p, gallery_section_label: e.target.value }))} />
            </Field>
            <Field label="Heading above the details" htmlFor="cat-specs">
              <input id="cat-specs" style={INPUT} value={config.specifications_section_label || ''} maxLength={50} placeholder="Specifications"
                onChange={e => setConfig(p => ({ ...p, specifications_section_label: e.target.value }))} />
            </Field>
          </FIELD_ROW>
        </div>

        {/* Buttons */}
        <div style={SECTION}>
          <h3 style={{ ...SECTION_TITLE, margin: '0 0 4px' }}>Buttons on the product page</h3>
          <p style={SECTION_HELP}>Each button opens WhatsApp with a message from the customer, so you can tell which one they pressed. Keep two or three.</p>
          {buttons.map((btn, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-end', marginBottom: 12 }}>
              <div style={{ flexGrow: 1 }}>
                <Field label={`Button ${i + 1}`} htmlFor={`cat-btn-${i}`}>
                  <input id={`cat-btn-${i}`} style={INPUT} value={btn.label} maxLength={24} placeholder="e.g. Chat on WhatsApp"
                    onChange={e => updateBtn(i, 'label', e.target.value)} />
                </Field>
              </div>
              <div style={{ width: 52, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>
                {(btn.label || '').length}/24
              </div>
              <button aria-label={`Remove button ${i + 1}`} style={{ ...BTN_DANGER, minHeight: 44, minWidth: 44, opacity: buttons.length <= 2 ? 0.35 : 1 }}
                onClick={() => removeBtn(i)} disabled={buttons.length <= 2}>
                🗑
              </button>
            </div>
          ))}
          {buttons.length < 3 && (
            <button style={{ ...BTN_GHOST, minHeight: 44 }} onClick={addBtn}>Add a third button</button>
          )}
        </div>

        {/* Advanced */}
        <div style={{ ...SECTION, padding: '6px 24px' }}>
          <button aria-expanded={advOpen} onClick={() => setAdvOpen(o => !o)}
            style={{ width: '100%', minHeight: 56, border: 'none', background: 'none', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, cursor: 'pointer', textAlign: 'left', padding: 0 }}>
            <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24' }}>
              Advanced <span style={{ fontFamily: ds.fontDm, fontWeight: 400, fontSize: 13, color: '#7A9BAD' }}>&nbsp;For developers and power users</span>
            </span>
            <span aria-hidden="true" style={{ fontSize: 14, color: '#0a1a24', transform: advOpen ? 'rotate(180deg)' : 'none' }}>▾</span>
          </button>

          {advOpen && (
            <div style={{ paddingBottom: 18 }}>
              <Field label="Price format code" htmlFor="cat-pfmt">
                <input id="cat-pfmt" style={{ ...INPUT, opacity: config.price_on_request ? 0.4 : 1 }}
                  value={config.price_label_template || ''} maxLength={50} disabled={config.price_on_request}
                  onChange={e => setConfig(p => ({ ...p, price_label_template: e.target.value }))}
                  placeholder="e.g. ₦{price}" />
                <div style={HINT}>Overrides the choice under Prices. Use {'{price}'} where the number goes.</div>
              </Field>

              <h4 style={{ ...SECTION_TITLE, fontSize: 14, margin: '22px 0 8px' }}>Button IDs</h4>
              <p style={SECTION_HELP}>The code each button sends to WhatsApp. They are made for you; change one only if a WhatsApp flow depends on it.</p>
              {buttons.map((btn, i) => (
                <div key={i} style={{ marginBottom: 10 }}>
                  <Field label={`Button ${i + 1} ID (letters, numbers, underscores)`} htmlFor={`cat-btnid-${i}`}>
                    <input id={`cat-btnid-${i}`} style={INPUT} value={btn.id} maxLength={50} placeholder="e.g. showroom_visit"
                      onChange={e => updateBtn(i, 'id', e.target.value)} />
                  </Field>
                </div>
              ))}

              <h4 style={{ ...SECTION_TITLE, fontSize: 14, margin: '22px 0 8px' }}>Tag dimensions</h4>
              <p style={SECTION_HELP}>Tags match qualification answers to products and filter the catalog. Up to 10.</p>
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
          )}
        </div>

      </div>

      {/* What customers will see */}
      <aside aria-label="Preview" style={{ flex: '0 1 320px', minWidth: 260, position: 'sticky', top: 16, ...SECTION, marginBottom: 0 }}>
        <div style={{ fontFamily: ds.fontDm, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#4a7a8a' }}>What customers will see</div>
        <div style={{ marginTop: 14, fontFamily: ds.fontDm, fontSize: 13, fontWeight: 700, color: '#3a5a6a' }}>Showing all {word2.toLowerCase()}</div>
        <div style={{ marginTop: 10, border: '1px solid #E2EFF4', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ height: 130, background: 'repeating-linear-gradient(135deg, #E4EEF0 0 10px, #F5F9FA 10px 20px)' }} />
          <div style={{ padding: 14 }}>
            <div style={{ fontFamily: ds.fontDm, fontSize: 15, fontWeight: 700, color: '#0a1a24' }}>Sample {word1.toLowerCase()}</div>
            <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 15, fontWeight: 600, color: '#0a1a24' }}>{pricePreview}</div>
            <div style={{ marginTop: 8 }}>
              <span style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 12, background: '#eafaf2', fontFamily: ds.fontDm, fontSize: 12, fontWeight: 700, color: '#1a6640' }}>{availText}</span>
            </div>
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {buttons.filter(b => b.label).map((b, i) => (
                <div key={i} style={i === 0
                  ? { minHeight: 42, borderRadius: 10, background: ds.teal, color: 'white', fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center' }
                  : { minHeight: 42, borderRadius: 10, border: '1.5px solid #0a1a24', color: '#0a1a24', fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {b.label}
                </div>
              ))}
            </div>
          </div>
        </div>
        <p style={{ margin: '14px 0 0', fontFamily: ds.fontDm, fontSize: 12, lineHeight: 1.5, color: '#7A9BAD' }}>The preview changes as you type. Nothing goes live until you save.</p>
      </aside>
    </div>
  )
}
