/**
 * frontend/src/modules/sites/LibraryPanel.jsx
 * SITE-IMPORT 3 - the staff Design library on a site: save this site's design (an editable import or a ready Premium design) as a
 * reusable library design for its niche, preview library designs (sandboxed), use one for this site, retire / restore.
 *
 * Backend: routers/sites.py /site-library/* and /sites/{id}/library/attach (switched on per account by
 * site_builder_settings.site_library_enabled; when it is off the API answers 403 and this panel renders nothing).
 * A library design is a COPY: using one gives this site its own files and its own content; retiring never changes sites already using it.
 */
import { useCallback, useEffect, useState } from 'react'
import { Library, Eye, BookmarkPlus, CheckCircle2, Archive, RotateCcw } from 'lucide-react'
import {
  getLibraryDesigns, saveLibraryDesign, previewLibraryDesign, attachLibraryDesign, setLibraryDesignStatus, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, SectionTitle, Modal, Segmented, Field } from './sitesUi'
import { T } from './sitesKit'

const KIND = { import: 'Uploaded page', premium: 'Premium design' }

export default function LibraryPanel({ site, presetKey, canEdit, showToast, onSiteChanged }) {
  const siteId = site?.id
  const [data, setData] = useState(null)             // { designs, niches }
  const [hidden, setHidden] = useState(false)        // the library is not switched on for this account
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [all, setAll] = useState(false)              // false: only this site's niche
  const [preview, setPreview] = useState(null)       // { name, html }
  const [saving, setSaving] = useState(null)         // { name, niche, note, error, warnings, fixed }

  const load = useCallback(async () => {
    try {
      setData(await getLibraryDesigns(all ? undefined : presetKey || undefined))
      setError(null)
    } catch (e) {
      if (e?.response?.status === 403 || e?.response?.status === 404) setHidden(true)
      else setError(errorMessage(e, 'Could not load the design library.'))
    }
  }, [all, presetKey])

  useEffect(() => { load() }, [load])
  if (hidden) return null

  const designs = data?.designs || []
  const warnNiches = (data?.niches || []).filter((n) => n.warning)
  const savable = site && (site.tier === 'premium' || site.tier === 'imported') && !!site.current_design_id

  const openPreview = async (d) => {
    setBusy(d.id)
    try {
      const r = await previewLibraryDesign(d.id)
      setPreview({ name: d.name, html: r.html })
    } catch (e) {
      showToast(errorMessage(e, 'Could not open the preview.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const use = async (d) => {
    setBusy(d.id)
    try {
      await attachLibraryDesign(siteId, d.id)
      showToast(`"${d.name}" is now this site's page`)
      await load()
      onSiteChanged?.()
    } catch (e) {
      showToast(errorMessage(e, 'This design cannot be used for this site.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const useNext = async () => {
    setBusy('next')
    try {
      const r = await attachLibraryDesign(siteId, null)
      showToast(`"${r.name}" is now this site's page`)
      await load()
      onSiteChanged?.()
    } catch (e) {
      showToast(errorMessage(e, 'No library design fits this site.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const flip = async (d) => {
    setBusy(d.id)
    try {
      await setLibraryDesignStatus(d.id, d.status === 'active' ? 'retire' : 'restore')
      await load()
    } catch (e) {
      showToast(errorMessage(e, 'Could not change it.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const submitSave = async () => {
    setBusy('save')
    try {
      const r = await saveLibraryDesign({ site_id: siteId, design_id: site.current_design_id, name: saving.name, niche: saving.niche, note: saving.note })
      showToast('Saved to the library')
      setSaving((s) => ({ ...s, done: true, warnings: r.warnings || [], fixed: r.fixed_text || [] }))
      await load()
    } catch (e) {
      setSaving((s) => ({ ...s, error: errorMessage(e, 'Could not save it.') }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card>
      <SectionTitle
        title="Design library"
        hint="Reuse a finished design for other sites in the same niche, with no AI cost. Each site gets its own copy and is filled with its own text, prices and photos."
        right={<Segmented ariaLabel="Library scope" value={all ? 'all' : 'niche'} onChange={(v) => setAll(v === 'all')}
          options={[{ value: 'niche', label: presetKey ? `This niche` : 'This niche' }, { value: 'all', label: 'All niches' }]} />}
      />
      {error && <Notice tone="bad">{error}</Notice>}
      {warnNiches.length > 0 && (
        <Notice tone="warn" style={{ marginBottom: 10 }}>
          Fewer than 3 designs for: {warnNiches.map((n) => `${n.niche} (${n.active})`).join(', ')}. Aim for 3 to 5 so sites do not look alike.
        </Notice>
      )}

      {canEdit && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <Button variant="secondary" icon={BookmarkPlus} disabled={!savable || !!busy}
            title={savable ? 'Copy this site\'s current design into the library' : 'Only an editable imported page or a Premium design can be saved'}
            onClick={() => setSaving({ name: '', niche: presetKey || '', note: '' })}>Save this design to the library</Button>
          <Button variant="primary" icon={Library} loading={busy === 'next'} disabled={!!busy || !designs.some((d) => d.status === 'active')} onClick={useNext}
            title="Try the next design in the rotation: not one this builder just used, least used first">Use the next design</Button>
        </div>
      )}

      {designs.length === 0 ? (
        <p style={{ margin: 0, fontSize: 13, color: T.muted }}>No library designs yet. Make an imported page editable, then save it here.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {designs.map((d) => (
            <div key={d.id} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', opacity: d.status === 'retired' ? 0.6 : 1 }}>
              <strong style={{ fontSize: 13.5, color: T.ink }}>{d.name}</strong>
              <Badge tone="neutral">{d.niche}</Badge>
              <Badge tone="neutral">{KIND[d.source_kind] || d.source_kind}</Badge>
              {d.has_scripts && <Badge tone="warn" title="This page runs scripts (only on the client's own domain)">Scripts</Badge>}
              {d.status === 'retired' && <Badge tone="warn">Retired</Badge>}
              <span style={{ fontSize: 12, color: T.muted }}>Used {d.uses_count} time(s)</span>
              {d.note ? <span style={{ fontSize: 12, color: T.muted }}>· {d.note}</span> : null}
              <span style={{ flex: 1 }} />
              <Button size="sm" variant="secondary" icon={Eye} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => openPreview(d)}>Preview</Button>
              {canEdit && d.status === 'active' && (
                <Button size="sm" variant="primary" icon={CheckCircle2} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => use(d)}>Use for this site</Button>
              )}
              {canEdit && (
                <Button size="sm" variant="secondary" icon={d.status === 'active' ? Archive : RotateCcw} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => flip(d)}
                  title={d.status === 'active' ? 'Stop offering it. Sites already using it are not changed.' : 'Offer it again'}>
                  {d.status === 'active' ? 'Retire' : 'Restore'}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview ? `Library · ${preview.name}` : 'Preview'} width={1040}>
        {preview && (
          <iframe title="Library design preview" srcDoc={preview.html} sandbox="allow-scripts allow-popups"
            style={{ width: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8, background: '#fff' }} />
        )}
      </Modal>

      <Modal open={!!saving} onClose={() => setSaving(null)} title="Save to the design library" width={560}
        footer={saving?.done
          ? <Button variant="primary" onClick={() => setSaving(null)}>Done</Button>
          : <Button variant="primary" icon={BookmarkPlus} loading={busy === 'save'} disabled={!saving?.name?.trim() || !saving?.niche?.trim()} onClick={submitSave}>Save to library</Button>}>
        {saving && !saving.done && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Field label="Design name" hint="For example: Warm kitchen">
              <input value={saving.name} maxLength={80} onChange={(e) => setSaving({ ...saving, name: e.target.value, error: null })} style={{ width: '100%' }} />
            </Field>
            <Field label="Niche (template key)" hint="The template key this design is for, for example restaurant">
              <input value={saving.niche} maxLength={80} onChange={(e) => setSaving({ ...saving, niche: e.target.value, error: null })} style={{ width: '100%' }} />
            </Field>
            <Field label="Note (optional)">
              <input value={saving.note} maxLength={300} onChange={(e) => setSaving({ ...saving, note: e.target.value })} style={{ width: '100%' }} />
            </Field>
            <p style={{ margin: 0, fontSize: 12, color: T.muted }}>
              It is checked first: it must fill correctly with 1, 5 and 40 items, with only the required fields, and with very long text.
              The sample text stays with the library preview only; it is never copied to another site.
            </p>
            {saving.error && <Notice tone="bad">{saving.error}</Notice>}
          </div>
        )}
        {saving?.done && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Notice tone="good">Saved. Sites in this niche can now use it.</Notice>
            {(saving.warnings || []).map((w, i) => <Notice key={i} tone="warn">{w}</Notice>)}
            {(saving.fixed || []).length > 0 && (
              <div>
                <p style={{ margin: '0 0 4px', fontSize: 12.5, color: T.ink }}><strong>Text that stays the same on every site:</strong></p>
                <ul style={{ margin: '0 0 0 18px', padding: 0, fontSize: 12.5, color: T.muted, maxHeight: 180, overflow: 'auto' }}>
                  {saving.fixed.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
                <p style={{ margin: '6px 0 0', fontSize: 12, color: T.muted }}>If any of this is the sample business's own wording, retire this design and fix the source page first.</p>
              </div>
            )}
          </div>
        )}
      </Modal>
    </Card>
  )
}
