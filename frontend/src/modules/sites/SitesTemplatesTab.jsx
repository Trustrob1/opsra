/**
 * frontend/src/modules/sites/SitesTemplatesTab.jsx
 * SITE-1A part 2 — Templates: the niche presets sites are built from (spec §5.1, D2:
 * boutique/restaurant/salon/services, seeded by SITE-1A_migration.sql). "Safe to edit
 * in the UI" per spec — rename, tweak sections/themes, or add a new preset any time.
 * Preview renders the preset with built-in sample data (POST /presets/{id}/preview).
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus, Eye, LayoutTemplate } from 'lucide-react'
import { listPresets, createPreset, updatePreset, previewPreset, errorMessage } from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty, Field, Modal, Drawer, Toggle } from './sitesUi'
import { T, INPUT, THEMES, PALETTES, SECTION_KEYS, SECTION_LABELS } from './sitesKit'
import { useIsMobile } from '../../hooks/useIsMobile'

export default function SitesTemplatesTab({ isActive, canEdit, showToast }) {
  const isMobile = useIsMobile()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(null)
  const [previewHtml, setPreviewHtml] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await listPresets())
    } catch (e) {
      setError(errorMessage(e, 'Could not load templates.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  const doPreview = async (preset) => {
    const theme = preset.allowed_themes?.[0] || 'atelier'
    const palette = preset.default_palettes?.[0] || 'berry'
    try {
      const res = await previewPreset(preset.id, { theme, palette, order: preset.sections, hidden: [] })
      setPreviewHtml(res.html)
    } catch (e) {
      showToast(errorMessage(e, 'Could not render a preview.'), 'bad')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <p style={{ margin: 0, fontSize: 13, color: T.muted, maxWidth: 520 }}>
          Niche templates sites are built from — each with its own item labels, WhatsApp messages, and brief questions.
        </p>
        {canEdit && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>New template</Button>}
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      {loading ? <Spinner /> : rows.length === 0 ? (
        <Card><Empty icon={LayoutTemplate} title="No templates yet" text="Run SITE-1A_migration.sql to seed the launch presets, or create one here." /></Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
          {rows.map((p) => (
            <Card key={p.id}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <div>
                  <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>{p.name}</p>
                  <p style={{ margin: '2px 0 0', fontSize: 12, color: T.muted }}><code>{p.key}</code></p>
                </div>
                {!p.is_active && <Badge tone="neutral">Inactive</Badge>}
              </div>
              <p style={{ margin: '10px 0', fontSize: 12.5, color: T.soft }}>
                {(p.sections || []).map((s) => SECTION_LABELS[s] || s).join(' · ')}
              </p>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {(p.allowed_themes || []).map((t) => <Badge key={t} tone="info">{THEMES.find((x) => x.value === t)?.label || t}</Badge>)}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button size="sm" variant="secondary" icon={Eye} onClick={() => doPreview(p)}>Preview</Button>
                {canEdit && <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>Edit</Button>}
              </div>
            </Card>
          ))}
        </div>
      )}

      <CreateTemplateModal open={creating} onClose={() => setCreating(false)}
        onCreated={() => { setCreating(false); showToast('Template created'); load() }} showToast={showToast} />
      <EditTemplateDrawer preset={editing} isMobile={isMobile} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); load() }} showToast={showToast} />

      <Modal open={!!previewHtml} onClose={() => setPreviewHtml(null)} title="Template preview" width={420}>
        {previewHtml && (
          <iframe title="Template preview" srcDoc={previewHtml}
            style={{ width: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8 }} />
        )}
      </Modal>
    </div>
  )
}

function SectionCheckboxes({ value, onChange }) {
  const toggle = (key) => {
    onChange(value.includes(key) ? value.filter((x) => x !== key) : [...value, key])
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
      {SECTION_KEYS.map((key) => (
        <label key={key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: T.ink }}>
          <input type="checkbox" checked={value.includes(key)} onChange={() => toggle(key)} />
          {SECTION_LABELS[key]}
        </label>
      ))}
    </div>
  )
}

function ThemeCheckboxes({ value, onChange }) {
  const toggle = (key) => {
    onChange(value.includes(key) ? value.filter((x) => x !== key) : [...value, key])
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
      {THEMES.map((t) => (
        <label key={t.value} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: T.ink }} title={t.hint}>
          <input type="checkbox" checked={value.includes(t.value)} onChange={() => toggle(t.value)} />
          {t.label}
        </label>
      ))}
    </div>
  )
}

function PaletteCheckboxes({ value, onChange }) {
  const toggle = (key) => {
    onChange(value.includes(key) ? value.filter((x) => x !== key) : [...value, key])
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
      {PALETTES.map((p) => (
        <label key={p.value} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: T.ink }}>
          <input type="checkbox" checked={value.includes(p.value)} onChange={() => toggle(p.value)} />
          <span style={{ width: 12, height: 12, borderRadius: '50%', background: p.accent, display: 'inline-block', border: `1px solid ${T.line}` }} />
          {p.label}
        </label>
      ))}
    </div>
  )
}

function CreateTemplateModal({ open, onClose, onCreated, showToast }) {
  const [form, setForm] = useState(blankForm())
  const [saving, setSaving] = useState(false)

  useEffect(() => { if (open) setForm(blankForm()) }, [open])

  function blankForm() {
    return { key: '', name: '', sections: ['hero', 'items', 'about', 'order'], allowed_themes: ['atelier'], default_palettes: ['berry'], ai_tone: '', max_items: 20 }
  }

  const submit = async () => {
    if (!form.key.trim() || !form.name.trim() || !form.sections.length || !form.allowed_themes.length) {
      showToast('Key, name, at least one section, and at least one theme are required', 'bad'); return
    }
    setSaving(true)
    try {
      await createPreset({ ...form, key: form.key.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'), max_items: Number(form.max_items) || 20 })
      onCreated()
    } catch (e) {
      showToast(errorMessage(e, 'Could not create this template.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New template"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={saving} onClick={submit}>Create</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Key" hint="Lowercase letters, digits, underscore — e.g. bakery">
          <input style={INPUT} value={form.key} onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))} />
        </Field>
        <Field label="Name"><input style={INPUT} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
        <Field label="Sections" group><SectionCheckboxes value={form.sections} onChange={(v) => setForm((f) => ({ ...f, sections: v }))} /></Field>
        <Field label="Allowed themes" group><ThemeCheckboxes value={form.allowed_themes} onChange={(v) => setForm((f) => ({ ...f, allowed_themes: v }))} /></Field>
        <Field label="Default palettes" group><PaletteCheckboxes value={form.default_palettes} onChange={(v) => setForm((f) => ({ ...f, default_palettes: v }))} /></Field>
        <Field label="Max items"><input style={INPUT} type="number" min="1" max="60" value={form.max_items} onChange={(e) => setForm((f) => ({ ...f, max_items: e.target.value }))} /></Field>
        <Field label="AI tone (optional)" hint="Guides SITE-2's AI copy generation for this niche">
          <input style={INPUT} value={form.ai_tone} onChange={(e) => setForm((f) => ({ ...f, ai_tone: e.target.value }))} />
        </Field>
      </div>
    </Modal>
  )
}

function EditTemplateDrawer({ preset, isMobile, onClose, onSaved, showToast }) {
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (preset) setForm({
      name: preset.name, sections: preset.sections || [], allowed_themes: preset.allowed_themes || [],
      default_palettes: preset.default_palettes || [], ai_tone: preset.ai_tone || '', max_items: preset.max_items ?? 20,
      is_active: preset.is_active !== false,
    })
  }, [preset])

  if (!preset || !form) return null

  const submit = async () => {
    setSaving(true)
    try {
      await updatePreset(preset.id, { ...form, max_items: Number(form.max_items) || 20 })
      showToast('Template updated')
      onSaved()
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={!!preset} onClose={onClose} title={preset.name} subtitle={preset.key} isMobile={isMobile}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Name"><input style={INPUT} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
        <Field label="Sections" group><SectionCheckboxes value={form.sections} onChange={(v) => setForm((f) => ({ ...f, sections: v }))} /></Field>
        <Field label="Allowed themes" group><ThemeCheckboxes value={form.allowed_themes} onChange={(v) => setForm((f) => ({ ...f, allowed_themes: v }))} /></Field>
        <Field label="Default palettes" group><PaletteCheckboxes value={form.default_palettes} onChange={(v) => setForm((f) => ({ ...f, default_palettes: v }))} /></Field>
        <Field label="Max items"><input style={INPUT} type="number" min="1" max="60" value={form.max_items} onChange={(e) => setForm((f) => ({ ...f, max_items: e.target.value }))} /></Field>
        <Field label="AI tone"><input style={INPUT} value={form.ai_tone} onChange={(e) => setForm((f) => ({ ...f, ai_tone: e.target.value }))} /></Field>
        <Field label="Active" group><Toggle checked={form.is_active} onChange={(v) => setForm((f) => ({ ...f, is_active: v }))} label={form.is_active ? 'Builders can use this template' : 'Hidden from builders'} /></Field>
        <div style={{ marginTop: 6 }}><Button variant="primary" loading={saving} onClick={submit}>Save</Button></div>
      </div>
    </Drawer>
  )
}
