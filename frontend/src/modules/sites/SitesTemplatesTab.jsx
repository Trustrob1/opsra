/**
 * frontend/src/modules/sites/SitesTemplatesTab.jsx
 * SITE-1A part 2 — Templates: the niche presets sites are built from (spec §5.1, D2:
 * boutique/restaurant/salon/services, seeded by SITE-1A_migration.sql). "Safe to edit
 * in the UI" per spec — rename, tweak sections/themes, or add a new preset any time.
 * Preview renders the preset with built-in sample data (POST /presets/{id}/preview).
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus, Eye, LayoutTemplate, Shuffle, Palette } from 'lucide-react'
import { presetLookStats, listPresets, listSites, createPreset, updatePreset, previewPreset, errorMessage } from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty, Field, Modal, Drawer, Toggle } from './sitesUi'
import SectionTiles from './SectionTiles'
import LayoutAllowance from './LayoutAllowance'
import ThemePicker from './ThemePicker'
import { T, INPUT, THEMES, PALETTES, FONT_PAIRINGS, TOKENS, SECTION_KEYS, SECTION_LABELS, insertSection } from './sitesKit'
import LookStudio from './LookStudio'
import { lookSummary } from './lookKit'
import { useIsMobile } from '../../hooks/useIsMobile'

export default function SitesTemplatesTab({ isActive, canEdit, showToast }) {
  const isMobile = useIsMobile()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(null)
  const [preview, setPreview] = useState(null) // { preset, html, recipe }
  const [stats, setStats] = useState({})
  const [usage, setUsage] = useState({ byPreset: {}, total: 0 }) // SITE-1C-3b: which sites use which template
  const [openUsed, setOpenUsed] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await listPresets())
      presetLookStats().then((s) => setStats(s || {})).catch(() => setStats({})) // informational only
      listSites({ page_size: 200 }).then((res) => { // informational only
        const byPreset = {}
        for (const s of res.items || []) (byPreset[s.preset_id] ||= []).push(s)
        setUsage({ byPreset, total: res.total || 0 })
      }).catch(() => setUsage({ byPreset: {}, total: 0 }))
    } catch (e) {
      setError(errorMessage(e, 'Could not load templates.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  // SITE-1C-1: previews use the same seeded picker new sites use, so 'Shuffle look' shows the range
  // of looks this template's allowed themes / palettes / fonts / options will produce.
  const doPreview = async (preset) => {
    const theme = preset.allowed_themes?.[0] || 'atelier'
    const palette = preset.default_palettes?.[0] || 'berry'
    const seed = Math.random().toString(36).slice(2, 10)
    try {
      const res = await previewPreset(preset.id, { theme, palette, order: preset.sections, hidden: [] }, seed)
      setPreview({ preset, html: res.html, recipe: res.recipe })
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
              <UsedBy sites={usage.byPreset[p.id] || []} partial={usage.total > 200} open={openUsed === p.id}
                onToggle={() => setOpenUsed(openUsed === p.id ? null : p.id)} />
              <LookStatsLine stat={stats[p.id]} />
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

      <CreateTemplateModal open={creating} isMobile={isMobile} onClose={() => setCreating(false)}
        onCreated={() => { setCreating(false); showToast('Template created'); load() }} showToast={showToast} />
      <EditTemplateDrawer preset={editing} isMobile={isMobile} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); load() }} showToast={showToast} />

      <Modal open={!!preview} onClose={() => setPreview(null)} title="Template preview" width={420}>
        {preview && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: T.muted, lineHeight: 1.5 }}>{describeRecipe(preview.recipe)}</span>
              <Button size="sm" variant="secondary" icon={Shuffle} onClick={() => doPreview(preview.preset)}>Shuffle look</Button>
            </div>
            <iframe title="Template preview" srcDoc={preview.html}
              style={{ width: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8 }} />
          </div>
        )}
      </Modal>
    </div>
  )
}

function describeRecipe(recipe) {
  if (!recipe) return ''
  const theme = THEMES.find((t) => t.value === recipe.theme)?.label || recipe.theme
  const palette = recipe.custom_colour || PALETTES.find((p) => p.value === recipe.palette)?.label || recipe.palette
  const fonts = FONT_PAIRINGS.find((f) => f.value === recipe.fonts)?.label
  const tokens = TOKENS.map((t) => {
    const v = recipe.tokens?.[t.key]
    return v ? `${t.label}: ${t.options.find((o) => o.value === v)?.label || v}` : null
  }).filter(Boolean)
  return [theme, palette, fonts, ...tokens].filter(Boolean).join(' · ')
}

// SITE-1C-3b: how many sites were built from this template, and which ones.
function UsedBy({ sites, partial, open, onToggle }) {
  const n = sites.length
  if (!n) return <p style={{ margin: '0 0 10px', fontSize: 12, color: T.muted }}>Not used by any site yet</p>
  return (
    <div style={{ margin: '0 0 10px' }}>
      <button type="button" onClick={onToggle} aria-expanded={open}
        style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: T.ink, textDecoration: 'underline' }}>
        Used by {n}{partial ? '+' : ''} site{n === 1 ? '' : 's'} {open ? '▴' : '▾'}
      </button>
      {open && (
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, color: T.soft, maxHeight: 160, overflowY: 'auto' }}>
          {sites.map((s) => <li key={s.id}>{s.client_business_name} <code style={{ color: T.muted }}>/s/{s.slug}</code></li>)}
        </ul>
      )}
    </div>
  )
}

// SITE-1C-2: how varied were the last 30 days of sites from this template? A thin pool = many repeats.
function LookStatsLine({ stat }) {
  if (!stat || !stat.sites) return null
  const thin = stat.sites >= 5 && stat.distinct / stat.sites < 0.7
  return (
    <p style={{ margin: '0 0 10px', fontSize: 12, color: thin ? T.warn : T.muted }}>
      {stat.sites} site{stat.sites === 1 ? '' : 's'} in 30 days &middot; {stat.distinct} different look{stat.distinct === 1 ? '' : 's'}
      {thin ? ' — repeating; allow more colours, fonts or layouts.' : ''}
    </p>
  )
}

function SectionCheckboxes({ value, onChange }) {
  const toggle = (key) => onChange(value.includes(key) ? value.filter((x) => x !== key) : insertSection(value, key))
  return <SectionTiles mode="select" keys={SECTION_KEYS} selected={value} onToggle={toggle} />
}

function ThemeCheckboxes({ value, onChange }) {
  return <ThemePicker multi value={value} onChange={onChange} recipe={{ palette: 'berry' }} />
}

function LookField({ value, nicheKey, isMobile, onChange }) {
  const [open, setOpen] = useState(false)
  // Escape closes only the Look studio, not the template form underneath it (capture phase runs first).
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open])
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', padding: '10px 12px', border: `1px solid ${T.line}`, borderRadius: 10, background: '#FAFCFD' }}>
        <span style={{ fontSize: 12.5, color: T.soft, lineHeight: 1.45, flex: 1, minWidth: 180 }}>{lookSummary(value)}</span>
        <Button size="sm" variant="secondary" icon={Palette} onClick={() => setOpen(true)}>Customise look</Button>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Look studio" width={1180}
        footer={<Button variant="primary" onClick={() => setOpen(false)}>Done</Button>}>
        <LookStudio value={value} nicheKey={nicheKey} isMobile={isMobile} onChange={onChange} />
      </Modal>
    </>
  )
}

function CreateTemplateModal({ open, isMobile, onClose, onCreated, showToast }) {
  const [form, setForm] = useState(blankForm())
  const [saving, setSaving] = useState(false)

  useEffect(() => { if (open) setForm(blankForm()) }, [open])

  function blankForm() {
    return { key: '', name: '', sections: ['hero', 'items', 'about', 'order'], allowed_themes: ['atelier'], default_palettes: ['berry'], allowed_fonts: [], token_options: {}, allowed_variants: {}, ai_tone: '', max_items: 20 }
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
        <Field label="Allowed layouts" group hint="Which section layouts new sites may use. Leave a section with none ticked to allow them all.">
          <LayoutAllowance sections={form.sections} value={form.allowed_variants || {}} onChange={(v) => setForm((f) => ({ ...f, allowed_variants: v }))} />
        </Field>
        <Field label="Colours, fonts and look" group>
          <LookField nicheKey={form.key.trim().toLowerCase()} isMobile={isMobile} onChange={(v) => setForm((f) => ({ ...f, ...v }))}
            value={{ default_palettes: form.default_palettes, allowed_fonts: form.allowed_fonts, token_options: form.token_options }} />
        </Field>
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
      default_palettes: preset.default_palettes || [], allowed_fonts: preset.allowed_fonts || [], token_options: preset.token_options || {}, allowed_variants: preset.allowed_variants || {},
      ai_tone: preset.ai_tone || '', max_items: preset.max_items ?? 20,
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
        <Field label="Allowed layouts" group hint="Which section layouts new sites may use. Leave a section with none ticked to allow them all.">
          <LayoutAllowance sections={form.sections} value={form.allowed_variants || {}} onChange={(v) => setForm((f) => ({ ...f, allowed_variants: v }))} />
        </Field>
        <Field label="Colours, fonts and look" group>
          <LookField nicheKey={preset.key} isMobile={isMobile} onChange={(v) => setForm((f) => ({ ...f, ...v }))}
            value={{ default_palettes: form.default_palettes, allowed_fonts: form.allowed_fonts, token_options: form.token_options }} />
        </Field>
        <Field label="Max items"><input style={INPUT} type="number" min="1" max="60" value={form.max_items} onChange={(e) => setForm((f) => ({ ...f, max_items: e.target.value }))} /></Field>
        <Field label="AI tone"><input style={INPUT} value={form.ai_tone} onChange={(e) => setForm((f) => ({ ...f, ai_tone: e.target.value }))} /></Field>
        <Field label="Active" group><Toggle checked={form.is_active} onChange={(v) => setForm((f) => ({ ...f, is_active: v }))} label={form.is_active ? 'Builders can use this template' : 'Hidden from builders'} /></Field>
        <div style={{ marginTop: 6 }}><Button variant="primary" loading={saving} onClick={submit}>Save</Button></div>
      </div>
    </Drawer>
  )
}
