/**
 * frontend/src/modules/admin/CatalogItemDrawer.jsx
 * CATALOG-2B: Slide-in panel for editing a catalog item.
 * Sections: Basic Info · Images · Tags · Custom Fields · Settings
 * Pattern 51: full rewrite only — never sed.
 */
import { useState, useEffect, useRef } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

const INPUT = {
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: '1px solid #D0E8F0', fontFamily: ds.fontDm, fontSize: 13.5,
  color: '#0a1a24', background: 'white', boxSizing: 'border-box', outline: 'none',
}

const LABEL = {
  fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600,
  color: '#4a7a8a', marginBottom: 6, display: 'block',
}

const SECTION_TITLE = {
  fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14,
  color: '#0a1a24', margin: '0 0 16px', paddingBottom: 10,
  borderBottom: '1px solid #E2EFF4',
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

const TOGGLE = ({ value, onChange, label }) => (
  <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
    <div onClick={() => onChange(!value)} style={{
      width: 40, height: 22, borderRadius: 11, position: 'relative',
      background: value ? ds.teal : '#D0E8F0', transition: 'background 0.2s', cursor: 'pointer', flexShrink: 0,
    }}>
      <div style={{
        position: 'absolute', top: 3, left: value ? 20 : 3,
        width: 16, height: 16, borderRadius: '50%', background: 'white', transition: 'left 0.2s',
      }} />
    </div>
    <span style={{ fontFamily: ds.fontDm, fontSize: 13.5, color: '#0a1a24' }}>{label}</span>
  </label>
)

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <span style={LABEL}>{label}</span>
      {children}
    </div>
  )
}

export default function CatalogItemDrawer({ item, config, isOpen, onClose, onSaved }) {
  const [form, setForm]       = useState({})
  const [saving, setSaving]   = useState(false)
  const [uploading, setUpload] = useState(false)
  const [toast, setToast]     = useState('')
  const [error, setError]     = useState('')
  const fileRef               = useRef()
  const extraFileRef          = useRef()

  const isShopify = (config?.external_sync || 'none') === 'shopify'
  const orgSlug   = config?.org_slug || ''

  useEffect(() => {
    if (!item) return
    setForm({
      title:                item.title || '',
      price:                item.price ?? '',
      description:          item.description || '',
      catalog_description:  item.catalog_description || '',
      slug:                 item.slug || '',
      catalog_visible:      item.catalog_visible !== false,
      available:            item.available !== false,
      inventory_count:      item.inventory_count ?? '',
      tags:                 item.tags || {},
      custom_fields:        item.custom_fields || {},
      catalog_images:       item.catalog_images || [],
      extra_catalog_images: item.extra_catalog_images || [],
    })
    setError('')
    setToast('')
  }, [item])

  function flash(msg) { setToast(msg); setTimeout(() => setToast(''), 3000) }

  function setField(key, val) { setForm(p => ({ ...p, [key]: val })) }
  function setTag(key, val)   { setForm(p => ({ ...p, tags: { ...p.tags, [key]: val } })) }

  async function save() {
    setError('')
    const payload = {
      tags:                 form.tags,
      custom_fields:        form.custom_fields,
      catalog_visible:      form.catalog_visible,
      slug:                 form.slug,
      catalog_images:       form.catalog_images,
      extra_catalog_images: form.extra_catalog_images,
      catalog_description:  form.catalog_description || null,
    }
    if (!isShopify) {
      payload.available       = form.available
      payload.inventory_count = form.inventory_count === '' ? null : Number(form.inventory_count)
    }
    setSaving(true)
    try {
      const updated = await adminSvc.updateCatalogItem(item.id, payload)
      flash('Item saved.')
      if (onSaved) onSaved(updated)
    } catch (e) {
      const msg = e?.response?.data?.detail
      if (typeof msg === 'string' && msg.includes('already in use')) setError('That slug is already used by another item.')
      else setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  async function handleImageUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 5 * 1024 * 1024) { setError('Image must be under 5 MB.'); return }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { setError('Only JPEG, PNG, or WebP images allowed.'); return }
    const fd = new FormData()
    fd.append('file', file)
    setUpload(true)
    setError('')
    try {
      const result = await adminSvc.uploadCatalogImage(item.id, fd)
      setField('catalog_images', [...form.catalog_images, result.url])
      flash('Image uploaded.')
    } catch { setError('Image upload failed.') }
    finally { setUpload(false); if (fileRef.current) fileRef.current.value = '' }
  }

  async function handleExtraImageUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 5 * 1024 * 1024) { setError('Image must be under 5 MB.'); return }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { setError('Only JPEG, PNG, or WebP images allowed.'); return }
    const fd = new FormData()
    fd.append('file', file)
    setUpload(true)
    setError('')
    try {
      const result = await adminSvc.uploadExtraCatalogImage(item.id, fd)
      setField('extra_catalog_images', [...form.extra_catalog_images, result.url])
      flash('Extra image uploaded.')
    } catch { setError('Extra image upload failed.') }
    finally { setUpload(false); if (extraFileRef.current) extraFileRef.current.value = '' }
  }

  async function removeExtraImage(idx) {
    try {
      await adminSvc.deleteExtraCatalogImage(item.id, idx)
      setField('extra_catalog_images', form.extra_catalog_images.filter((_, i) => i !== idx))
    } catch { setError('Failed to remove extra image.') }
  }

  async function removeImage(idx) {
    try {
      await adminSvc.deleteCatalogImage(item.id, idx)
      setField('catalog_images', form.catalog_images.filter((_, i) => i !== idx))
    } catch { setError('Failed to remove image.') }
  }

  // Custom fields helpers
  const cfEntries = Object.entries(form.custom_fields || {})
  function setCFKey(oldKey, newKey) {
    setForm(p => {
      const cf = { ...p.custom_fields }
      const val = cf[oldKey]
      delete cf[oldKey]
      cf[newKey] = val
      return { ...p, custom_fields: cf }
    })
  }
  function setCFVal(key, val) { setForm(p => ({ ...p, custom_fields: { ...p.custom_fields, [key]: val } })) }
  function addCF()             { setForm(p => ({ ...p, custom_fields: { ...p.custom_fields, '': '' } })) }
  function removeCF(key)       { setForm(p => { const cf = { ...p.custom_fields }; delete cf[key]; return { ...p, custom_fields: cf } }) }

  if (!isOpen || !item) return null

  return (
    <>
      {/* Backdrop */}
      <div onClick={onClose} style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 900,
      }} />

      {/* Drawer */}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 540,
        background: 'white', zIndex: 901, overflowY: 'auto',
        boxShadow: '-4px 0 32px rgba(0,0,0,0.15)', display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px', borderBottom: '1px solid #E2EFF4', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>
              Edit Item
            </h2>
            <p style={{ fontFamily: ds.fontDm, fontSize: 12.5, color: '#7A9BAD', margin: '3px 0 0' }}>
              {item.title}
            </p>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#7A9BAD', lineHeight: 1 }}>✕</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, padding: '20px 24px', overflowY: 'auto' }}>

          {toast && <div style={{ background: '#eafaf2', border: '1px solid #6fcf97', borderRadius: 8, padding: '9px 14px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13, color: '#1a6640' }}>✅ {toast}</div>}
          {error && <div style={{ background: '#fff2f2', border: '1px solid #e05c5c', borderRadius: 8, padding: '9px 14px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13, color: '#c0392b' }}>⚠️ {error}</div>}

          {/* ── Section 1: Basic Info ── */}
          <h3 style={SECTION_TITLE}>Basic Info</h3>

          <Field label="Title">
            <input style={{ ...INPUT, background: isShopify ? '#f5fbfd' : 'white' }}
              value={form.title || ''} readOnly={isShopify} maxLength={500}
              onChange={e => setField('title', e.target.value)} />
            {isShopify && <p style={{ fontFamily: ds.fontDm, fontSize: 11.5, color: '#7A9BAD', margin: '4px 0 0' }}>Managed via Shopify — edit in your Shopify store.</p>}
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Field label="Price">
              <input style={{ ...INPUT, background: isShopify ? '#f5fbfd' : 'white' }}
                value={form.price ?? ''} type="number" readOnly={isShopify}
                onChange={e => setField('price', e.target.value)} />
            </Field>
            {!isShopify && (
              <Field label="Inventory Count">
                <input style={INPUT} value={form.inventory_count ?? ''} type="number"
                  onChange={e => setField('inventory_count', e.target.value)} />
              </Field>
            )}
          </div>

          <Field label="Description">
            <textarea style={{ ...INPUT, minHeight: 80, resize: 'vertical' }}
              value={form.description || ''} maxLength={5000}
              readOnly={isShopify}
              onChange={e => setField('description', e.target.value)} />
            {isShopify && <p style={{ fontFamily: ds.fontDm, fontSize: 11.5, color: '#7A9BAD', margin: '4px 0 0' }}>Managed via Shopify — read only.</p>}
          </Field>

          <Field label="Catalog Description (Opsra only — never overwritten by Shopify)">
            <textarea style={{ ...INPUT, minHeight: 120, resize: 'vertical' }}
              value={form.catalog_description || ''} maxLength={20000}
              placeholder="Add richer product details here — specifications, sizing, care instructions, warranty, etc. This appears on the public catalog page instead of the Shopify description if filled in."
              onChange={e => setField('catalog_description', e.target.value)} />
          </Field>

          {/* ── Section 2: Images ── */}
          <h3 style={{ ...SECTION_TITLE, marginTop: 8 }}>Images</h3>
          <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', margin: '-10px 0 14px' }}>
            First image is the cover. Max 5 MB each. JPEG · PNG · WebP.
          </p>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
            {(form.catalog_images || []).map((url, idx) => (
              <div key={idx} style={{ position: 'relative', width: 90, height: 90 }}>
                <img src={url} alt={`img-${idx}`}
                  style={{ width: 90, height: 90, objectFit: 'cover', borderRadius: 8, border: `2px solid ${idx === 0 ? ds.teal : '#E2EFF4'}` }} />
                {idx === 0 && (
                  <span style={{ position: 'absolute', top: 4, left: 4, background: ds.teal, color: 'white', fontSize: 10, fontFamily: ds.fontDm, fontWeight: 700, borderRadius: 4, padding: '2px 6px' }}>
                    Cover
                  </span>
                )}
                <button onClick={() => removeImage(idx)} style={{
                  position: 'absolute', top: 4, right: 4, background: 'rgba(0,0,0,0.55)',
                  border: 'none', borderRadius: '50%', width: 20, height: 20,
                  color: 'white', cursor: 'pointer', fontSize: 11, lineHeight: '20px', textAlign: 'center', padding: 0,
                }}>✕</button>
              </div>
            ))}
            <button onClick={() => fileRef.current?.click()}
              style={{ width: 90, height: 90, border: '2px dashed #D0E8F0', borderRadius: 8, background: '#f5fbfd', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
              <span style={{ fontSize: 20 }}>{uploading ? '⏳' : '+'}</span>
              <span style={{ fontFamily: ds.fontDm, fontSize: 11, color: '#7A9BAD' }}>{uploading ? 'Uploading' : 'Add image'}</span>
            </button>
          </div>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp"
            style={{ display: 'none' }} onChange={handleImageUpload} />

          {/* ── Extra Catalog Images (Opsra only — never overwritten by Shopify) ── */}
          <h3 style={{ ...SECTION_TITLE, marginTop: 20 }}>Extra Catalog Images</h3>
          <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', margin: '-10px 0 14px' }}>
            These are managed in Opsra only and will never be overwritten by Shopify sync.
            They appear after the Shopify images on the public catalog page.
          </p>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
            {(form.extra_catalog_images || []).map((url, idx) => (
              <div key={idx} style={{ position: 'relative', width: 90, height: 90 }}>
                <img src={url} alt={`extra-${idx}`}
                  style={{ width: 90, height: 90, objectFit: 'cover', borderRadius: 8, border: '2px solid #E2EFF4' }} />
                <button onClick={() => removeExtraImage(idx)} style={{
                  position: 'absolute', top: 4, right: 4, background: 'rgba(0,0,0,0.55)',
                  border: 'none', borderRadius: '50%', width: 20, height: 20,
                  color: 'white', cursor: 'pointer', fontSize: 11, lineHeight: '20px', textAlign: 'center', padding: 0,
                }}>✕</button>
              </div>
            ))}
            <button onClick={() => extraFileRef.current?.click()}
              style={{ width: 90, height: 90, border: '2px dashed #D0E8F0', borderRadius: 8, background: '#f5fbfd', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
              <span style={{ fontSize: 20 }}>{uploading ? '⏳' : '+'}</span>
              <span style={{ fontFamily: ds.fontDm, fontSize: 11, color: '#7A9BAD' }}>{uploading ? 'Uploading' : 'Add image'}</span>
            </button>
          </div>
          <input ref={extraFileRef} type="file" accept="image/jpeg,image/png,image/webp"
            style={{ display: 'none' }} onChange={handleExtraImageUpload} />

          {/* ── Section 3: Tags ── */}
          {(config?.tag_dimensions || []).length > 0 && (
            <>
              <h3 style={{ ...SECTION_TITLE, marginTop: 8 }}>Tags</h3>
              {(config.tag_dimensions || []).map(dim => (
                <Field key={dim.key} label={dim.label || dim.key}>
                  {dim.type === 'single_select' ? (
                    <select style={{ ...INPUT, cursor: 'pointer' }}
                      value={(form.tags || {})[dim.key] || ''}
                      onChange={e => setTag(dim.key, e.target.value)}>
                      <option value="">— None —</option>
                      {(dim.options || []).map(opt => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  ) : (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {(dim.options || []).map(opt => {
                        const current = (form.tags || {})[dim.key] || []
                        const selected = Array.isArray(current) ? current.includes(opt) : false
                        return (
                          <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 13, color: '#0a1a24' }}>
                            <input type="checkbox" checked={selected}
                              onChange={e => {
                                const prev = Array.isArray(current) ? current : []
                                setTag(dim.key, e.target.checked ? [...prev, opt] : prev.filter(v => v !== opt))
                              }} />
                            {opt}
                          </label>
                        )
                      })}
                    </div>
                  )}
                </Field>
              ))}
            </>
          )}

          {/* ── Section 4: Custom Fields ── */}
          <h3 style={{ ...SECTION_TITLE, marginTop: 8 }}>Custom Fields</h3>
          {cfEntries.length === 0 && (
            <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', marginBottom: 12 }}>No custom fields yet.</p>
          )}
          {cfEntries.map(([key, val], i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 2fr auto', gap: 10, marginBottom: 10, alignItems: 'center' }}>
              <input style={INPUT} value={key} placeholder="Field name" maxLength={100}
                onChange={e => setCFKey(key, e.target.value)} />
              <input style={INPUT} value={val} placeholder="Value" maxLength={5000}
                onChange={e => setCFVal(key, e.target.value)} />
              <button style={{ background: 'none', border: 'none', color: '#e05c5c', cursor: 'pointer', fontSize: 16 }}
                onClick={() => removeCF(key)}>🗑</button>
            </div>
          ))}
          <button style={{ ...BTN_GHOST, fontSize: 12, padding: '6px 12px' }} onClick={addCF}>+ Add Field</button>

          {/* ── Section 5: Settings ── */}
          <h3 style={{ ...SECTION_TITLE, marginTop: 20 }}>Settings</h3>

          <Field label="Slug">
            <input style={INPUT} value={form.slug || ''} maxLength={200} placeholder="e.g. premium-mattress"
              onChange={e => setField('slug', e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))} />
            {form.slug && (
              <p style={{ fontFamily: ds.fontDm, fontSize: 11.5, color: '#7A9BAD', margin: '4px 0 0' }}>
                Public URL: /catalog/{orgSlug || '<org-slug>'}/{form.slug}
              </p>
            )}
          </Field>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <TOGGLE value={form.catalog_visible} label="Visible in catalog"
              onChange={v => setField('catalog_visible', v)} />
            {!isShopify && (
              <TOGGLE value={form.available} label="Available (in stock)"
                onChange={v => setField('available', v)} />
            )}
          </div>

          <div style={{ height: 32 }} />
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: '1px solid #E2EFF4', display: 'flex', justifyContent: 'flex-end', gap: 12, flexShrink: 0 }}>
          <button style={BTN_GHOST} onClick={onClose}>Cancel</button>
          <button style={{ ...BTN_PRIMARY, opacity: saving ? 0.6 : 1 }} onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </>
  )
}
