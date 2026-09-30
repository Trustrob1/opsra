/**
 * frontend/src/modules/sites/SiteEditorPanel.jsx
 * SITE-1A part 2 — the by-hand site editor: content form, design (recipe) picker,
 * photo upload, and a rendered-HTML preview. Content/recipe edits are saved
 * separately (PATCH .../content, PATCH .../recipe) and only take effect on the
 * live preview after "Render preview" (POST .../render) — matches the backend's
 * own separation (routers/sites.py) so a half-finished edit never auto-publishes.
 */
import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Plus, Trash2, Save, RefreshCw, Eye, ImagePlus, ExternalLink } from 'lucide-react'
import {
  getSite, patchSiteContent, patchSiteRecipe, renderSite, uploadSiteAsset, getPreset, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Field, Modal, SectionTitle } from './sitesUi'
import SectionTiles from './SectionTiles'
import ThemePicker from './ThemePicker'
import { T, INPUT, TEXTAREA, dateTime, THEMES, SECTION_LABELS, SITE_STATUS } from './sitesKit'
import LookPickerField from './LookPicker'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export default function SiteEditorPanel({ siteId, canEdit, isMobile, showToast, onBack }) {
  const [site, setSite] = useState(null)
  const [preset, setPreset] = useState(null)
  const [content, setContent] = useState(null)
  const [recipe, setRecipe] = useState(null)
  const [assetUrls, setAssetUrls] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [savingContent, setSavingContent] = useState(false)
  const [savingRecipe, setSavingRecipe] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await getSite(siteId)
      setSite(s)
      setContent(s.content)
      setRecipe(s.recipe)
      try { setPreset(await getPreset(s.preset_id)) } catch { /* preset may have been deleted — editor still works */ }
    } catch (e) {
      setError(errorMessage(e, 'Could not load this site.'))
    } finally {
      setLoading(false)
    }
  }, [siteId])

  useEffect(() => { load() }, [load])

  const saveContent = async () => {
    setSavingContent(true)
    try {
      const s = await patchSiteContent(siteId, content)
      setSite(s)
      showToast('Content saved — render to refresh the preview')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save content.'), 'bad')
    } finally {
      setSavingContent(false)
    }
  }

  const saveRecipe = async () => {
    setSavingRecipe(true)
    try {
      const s = await patchSiteRecipe(siteId, recipe)
      setSite(s)
      showToast('Design saved — render to refresh the preview')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save design.'), 'bad')
    } finally {
      setSavingRecipe(false)
    }
  }

  const doRender = async () => {
    setRendering(true)
    try {
      const s = await renderSite(siteId)
      setSite(s)
      showToast('Preview rendered')
    } catch (e) {
      showToast(errorMessage(e, 'Could not render — check content and design for errors.'), 'bad')
    } finally {
      setRendering(false)
    }
  }

  const uploadFor = async (slot, file, onSet) => {
    try {
      const asset = await uploadSiteAsset(siteId, slot, file)
      setAssetUrls((m) => ({ ...m, [asset.id]: asset.public_url }))
      onSet(asset.id)
      showToast('Photo uploaded')
    } catch (e) {
      showToast(errorMessage(e, 'Could not upload this photo.'), 'bad')
    }
  }

  if (loading) return <Spinner />
  if (error) return (<><BackLink onBack={onBack} /><Notice tone="bad">{error}</Notice></>)
  if (!site) return null
  if (!content || !recipe) {
    return (
      <>
        <BackLink onBack={onBack} />
        <Notice tone="info">
          This site came in through a brief form and doesn't have page content yet — that's built by the
          AI copy step, which isn't switched on here yet. The submitted brief is saved; check back once
          that's live.
        </Notice>
      </>
    )
  }

  const st = SITE_STATUS[site.status] || SITE_STATUS.brief_in_progress
  const previewUrl = `${BASE}/s/${site.slug}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, opacity: canEdit ? 1 : 0.85 }}>
      <BackLink onBack={onBack} />
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: isMobile ? 18 : 21, fontWeight: 700, color: T.ink }}>{site.client_business_name}</h2>
        <Badge tone={st.tone}>{st.label}</Badge>
        <code style={{ fontSize: 12, color: T.muted }}>/s/{site.slug}</code>
      </header>

      {!canEdit && <Notice tone="info">Read-only — only an owner or ops manager can edit sites.</Notice>}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button variant="secondary" icon={Eye} onClick={() => setPreviewOpen(true)} disabled={!site.rendered_html}>
          {site.rendered_html ? 'View preview' : 'Render to preview'}
        </Button>
        <Button variant="secondary" icon={ExternalLink} onClick={() => window.open(previewUrl, '_blank', 'noopener')}
          disabled={!site.rendered_html}>Open live preview URL</Button>
        <Button variant="primary" icon={RefreshCw} loading={rendering} onClick={doRender}>Render preview</Button>
      </div>
      <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>
        {site.updated_at ? `Last saved ${dateTime(site.updated_at)}` : null}
        {site.preview_expires_at ? ` · Preview link expires ${dateTime(site.preview_expires_at)}` : null}
      </p>

      <BusinessCard content={content} setContent={setContent} canEdit={canEdit} />
      <HeroCard content={content} setContent={setContent} canEdit={canEdit} assetUrls={assetUrls} onUpload={uploadFor} />
      <AboutCard content={content} setContent={setContent} canEdit={canEdit} assetUrls={assetUrls} onUpload={uploadFor} />
      <ItemsCard content={content} setContent={setContent} canEdit={canEdit} preset={preset} assetUrls={assetUrls} onUpload={uploadFor} />
      <CategoriesCard content={content} setContent={setContent} canEdit={canEdit} />
      <ReviewsCard content={content} setContent={setContent} canEdit={canEdit} />
      <HoursLocationCard content={content} setContent={setContent} canEdit={canEdit} />
      <OrderSeoCard content={content} setContent={setContent} canEdit={canEdit} />

      {canEdit && (
        <div><Button variant="primary" icon={Save} loading={savingContent} onClick={saveContent}>Save content</Button></div>
      )}

      <DesignCard recipe={recipe} setRecipe={setRecipe} canEdit={canEdit} preset={preset} isMobile={isMobile} />
      {canEdit && (
        <div><Button variant="primary" icon={Save} loading={savingRecipe} onClick={saveRecipe}>Save design</Button></div>
      )}

      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title="Preview" width={420}>
        {site.rendered_html
          ? <iframe title="Site preview" srcDoc={site.rendered_html} style={{ width: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8 }} />
          : <p style={{ fontSize: 13, color: T.muted }}>Render the preview first.</p>}
      </Modal>
    </div>
  )
}

function BackLink({ onBack }) {
  return (
    <button type="button" onClick={onBack}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 36, padding: '0 4px', border: 'none', background: 'none',
        color: T.teal, fontSize: 13, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer' }}>
      <ArrowLeft size={15} aria-hidden="true" /> All sites
    </button>
  )
}

function PhotoField({ label, assetId, assetUrls, canEdit, onPick }) {
  const url = assetId ? assetUrls[assetId] : null
  return (
    <Field label={label}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {url
          ? <img src={url} alt="" style={{ width: 56, height: 56, borderRadius: 8, objectFit: 'cover', border: `1px solid ${T.line}` }} />
          : <div style={{ width: 56, height: 56, borderRadius: 8, background: '#F1F6F8', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <ImagePlus size={18} color={T.muted} aria-hidden="true" />
            </div>}
        {canEdit && (
          <label style={{ fontSize: 12.5, fontWeight: 600, color: T.teal, cursor: 'pointer' }}>
            {assetId ? 'Replace photo' : 'Upload photo'}
            <input type="file" accept="image/jpeg,image/png,image/webp" style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onPick(f) }} />
          </label>
        )}
      </div>
    </Field>
  )
}

function BusinessCard({ content, setContent, canEdit }) {
  const b = content.business
  const set = (k) => (e) => setContent((c) => ({ ...c, business: { ...c.business, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="Business" />
      <Grid2>
        <Field label="Name"><input style={INPUT} value={b.name} disabled={!canEdit} onChange={set('name')} /></Field>
        <Field label="City"><input style={INPUT} value={b.city} disabled={!canEdit} onChange={set('city')} /></Field>
        <Field label="Tagline" style={{ gridColumn: '1 / -1' }}><input style={INPUT} value={b.tagline} disabled={!canEdit} onChange={set('tagline')} /></Field>
        <Field label="WhatsApp number"><input style={INPUT} value={b.whatsapp_e164} disabled={!canEdit} onChange={set('whatsapp_e164')} /></Field>
        <Field label="Phone (display)"><input style={INPUT} value={b.phone_display} disabled={!canEdit} onChange={set('phone_display')} /></Field>
        <Field label="Instagram handle"><input style={INPUT} value={b.instagram} disabled={!canEdit} onChange={set('instagram')} /></Field>
        <Field label="Delivery note"><input style={INPUT} value={b.delivery_note} disabled={!canEdit} onChange={set('delivery_note')} /></Field>
      </Grid2>
    </Card>
  )
}

function HeroCard({ content, setContent, canEdit, assetUrls, onUpload }) {
  const h = content.hero
  const set = (k) => (e) => setContent((c) => ({ ...c, hero: { ...c.hero, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="Hero" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Headline"><input style={INPUT} value={h.headline} disabled={!canEdit} onChange={set('headline')} /></Field>
        <Field label="Subhead"><input style={INPUT} value={h.subhead} disabled={!canEdit} onChange={set('subhead')} /></Field>
        <PhotoField label="Hero photo" assetId={h.image_asset_id} assetUrls={assetUrls} canEdit={canEdit}
          onPick={(f) => onUpload('hero', f, (id) => setContent((c) => ({ ...c, hero: { ...c.hero, image_asset_id: id } })))} />
      </div>
    </Card>
  )
}

function AboutCard({ content, setContent, canEdit, assetUrls, onUpload }) {
  const a = content.about
  const set = (k) => (e) => setContent((c) => ({ ...c, about: { ...c.about, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="About" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Title"><input style={INPUT} value={a.title} disabled={!canEdit} onChange={set('title')} /></Field>
        <Field label="Story" hint="One paragraph per line, up to 6">
          <textarea style={TEXTAREA} disabled={!canEdit} value={a.body.join('\n')}
            onChange={(e) => setContent((c) => ({ ...c, about: { ...c.about, body: e.target.value.split('\n').slice(0, 6) } }))} />
        </Field>
        <Field label="Owner name"><input style={INPUT} value={a.owner} disabled={!canEdit} onChange={set('owner')} /></Field>
        <Field label="Pull quote"><input style={INPUT} value={a.pull_quote} disabled={!canEdit} onChange={set('pull_quote')} /></Field>
        <PhotoField label="About photo" assetId={a.image_asset_id} assetUrls={assetUrls} canEdit={canEdit}
          onPick={(f) => onUpload('about', f, (id) => setContent((c) => ({ ...c, about: { ...c.about, image_asset_id: id } })))} />
      </div>
    </Card>
  )
}

function ItemsCard({ content, setContent, canEdit, preset, assetUrls, onUpload }) {
  const items = content.items
  const max = preset?.max_items ?? 60
  const itemLabel = preset?.labels?.item || 'Item'
  const itemsLabel = preset?.labels?.items || 'Items'

  const update = (i, patch) => setContent((c) => ({ ...c, items: c.items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)) }))
  const add = () => { if (items.length < max) setContent((c) => ({ ...c, items: [...c.items, blankItem()] })) }
  const remove = (i) => setContent((c) => ({ ...c, items: c.items.filter((_, idx) => idx !== i) }))
  function blankItem() { return { name: '', desc: '', price_ngn: 0, price_style: 'exact', tag: null, image_asset_id: null } }

  return (
    <Card>
      <SectionTitle title={itemsLabel} hint={`Up to ${max} ${itemLabel.toLowerCase()}s`}
        right={canEdit && items.length < max && <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add {itemLabel.toLowerCase()}</Button>} />
      {items.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No {itemsLabel.toLowerCase()} yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {items.map((it, i) => (
            <div key={i} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Grid2>
                <Field label="Name"><input style={INPUT} value={it.name} disabled={!canEdit} onChange={(e) => update(i, { name: e.target.value })} /></Field>
                <Field label="Price (₦)"><input style={INPUT} type="number" min="0" step="0.01" value={it.price_ngn} disabled={!canEdit}
                  onChange={(e) => update(i, { price_ngn: Number(e.target.value) || 0 })} /></Field>
                <Field label="Description" style={{ gridColumn: '1 / -1' }}><input style={INPUT} value={it.desc} disabled={!canEdit}
                  onChange={(e) => update(i, { desc: e.target.value })} /></Field>
                <Field label="Price style">
                  <select style={INPUT} value={it.price_style} disabled={!canEdit} onChange={(e) => update(i, { price_style: e.target.value })}>
                    <option value="exact">Exact</option><option value="from">From</option><option value="on_request">On request</option>
                  </select>
                </Field>
                <Field label="Tag (optional)"><input style={INPUT} value={it.tag || ''} disabled={!canEdit}
                  onChange={(e) => update(i, { tag: e.target.value || null })} /></Field>
              </Grid2>
              <PhotoField label={`${itemLabel} photo`} assetId={it.image_asset_id} assetUrls={assetUrls} canEdit={canEdit}
                onPick={(f) => onUpload(`item_${i}`, f, (id) => update(i, { image_asset_id: id }))} />
              {canEdit && <div><Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button></div>}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function CategoriesCard({ content, setContent, canEdit }) {
  const rows = content.categories
  const update = (i, patch) => setContent((c) => ({ ...c, categories: c.categories.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const add = () => { if (rows.length < 20) setContent((c) => ({ ...c, categories: [...c.categories, { name: '', teaser: '' }] })) }
  const remove = (i) => setContent((c) => ({ ...c, categories: c.categories.filter((_, idx) => idx !== i) }))
  return (
    <Card>
      <SectionTitle title="Categories" right={canEdit && <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add category</Button>} />
      {rows.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No categories yet.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Name" style={{ flex: 1, minWidth: 140 }}><input style={INPUT} value={r.name} disabled={!canEdit} onChange={(e) => update(i, { name: e.target.value })} /></Field>
              <Field label="Teaser" style={{ flex: 2, minWidth: 160 }}><input style={INPUT} value={r.teaser} disabled={!canEdit} onChange={(e) => update(i, { teaser: e.target.value })} /></Field>
              {canEdit && <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button>}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function ReviewsCard({ content, setContent, canEdit }) {
  const rows = content.reviews
  const update = (i, patch) => setContent((c) => ({ ...c, reviews: c.reviews.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const add = () => { if (rows.length < 20) setContent((c) => ({ ...c, reviews: [...c.reviews, { text: '', who: '' }] })) }
  const remove = (i) => setContent((c) => ({ ...c, reviews: c.reviews.filter((_, idx) => idx !== i) }))
  return (
    <Card>
      <SectionTitle title="Reviews" hint="Only ever the builder's own words — never invented."
        right={canEdit && <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add review</Button>} />
      {rows.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No reviews yet.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Review text" style={{ flex: 2, minWidth: 200 }}><input style={INPUT} value={r.text} disabled={!canEdit} onChange={(e) => update(i, { text: e.target.value })} /></Field>
              <Field label="Who" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.who} disabled={!canEdit} onChange={(e) => update(i, { who: e.target.value })} /></Field>
              {canEdit && <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button>}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function HoursLocationCard({ content, setContent, canEdit }) {
  const hours = content.hours
  const loc = content.location
  const updateHour = (i, patch) => setContent((c) => ({ ...c, hours: c.hours.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const addHour = () => { if (hours.length < 7) setContent((c) => ({ ...c, hours: [...c.hours, { days: '', time: '' }] })) }
  const removeHour = (i) => setContent((c) => ({ ...c, hours: c.hours.filter((_, idx) => idx !== i) }))
  const setLoc = (k) => (e) => setContent((c) => ({ ...c, location: { ...c.location, [k]: e.target.value } }))

  return (
    <Card>
      <SectionTitle title="Hours & location" right={canEdit && hours.length < 7 && <Button size="sm" variant="secondary" icon={Plus} onClick={addHour}>Add hours row</Button>} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 14 }}>
        {hours.map((r, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <Field label="Days" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.days} disabled={!canEdit} onChange={(e) => updateHour(i, { days: e.target.value })} /></Field>
            <Field label="Time" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.time} disabled={!canEdit} onChange={(e) => updateHour(i, { time: e.target.value })} /></Field>
            {canEdit && <Button size="sm" variant="danger" icon={Trash2} onClick={() => removeHour(i)}>Remove</Button>}
          </div>
        ))}
      </div>
      <Grid2>
        <Field label="Address"><input style={INPUT} value={loc.address || ''} disabled={!canEdit} onChange={setLoc('address')} /></Field>
        <Field label="Landmark"><input style={INPUT} value={loc.landmark || ''} disabled={!canEdit} onChange={setLoc('landmark')} /></Field>
      </Grid2>
    </Card>
  )
}

function OrderSeoCard({ content, setContent, canEdit }) {
  const o = content.order_section
  const seo = content.seo
  return (
    <Card>
      <SectionTitle title="How to order & SEO" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Order section title"><input style={INPUT} value={o.title} disabled={!canEdit}
          onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, title: e.target.value } }))} /></Field>
        <Field label="Steps" hint="One per line, up to 6">
          <textarea style={TEXTAREA} disabled={!canEdit} value={o.steps.join('\n')}
            onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, steps: e.target.value.split('\n').slice(0, 6) } }))} />
        </Field>
        <Field label="SEO title"><input style={INPUT} value={seo.title} disabled={!canEdit}
          onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, title: e.target.value } }))} /></Field>
        <Field label="SEO description"><input style={INPUT} value={seo.description} disabled={!canEdit}
          onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, description: e.target.value } }))} /></Field>
      </div>
    </Card>
  )
}

function DesignCard({ recipe, setRecipe, canEdit, preset, isMobile }) {
  const allowedThemes = preset?.allowed_themes?.length ? THEMES.filter((t) => preset.allowed_themes.includes(t.value)) : THEMES
  const sections = preset?.sections || Object.keys(SECTION_LABELS)
  const toggleHidden = (key) => setRecipe((r) => ({
    ...r, hidden: r.hidden.includes(key) ? r.hidden.filter((x) => x !== key) : [...r.hidden, key],
  }))

  const setVariant = (key, value) => setRecipe((r) => ({ ...r, variants: { ...(r.variants || {}), [key]: value } }))

  return (
    <Card>
      <SectionTitle title="Design" hint="Theme, colours, fonts and style. Pick a layout for each section, or hide one without losing its content." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Theme" group>
          <ThemePicker themes={allowedThemes} value={recipe.theme} onChange={(v) => setRecipe((r) => ({ ...r, theme: v }))} recipe={recipe} disabled={!canEdit} />
        </Field>
        <Field label="Colour, fonts and style" group>
          <LookPickerField recipe={recipe} setRecipe={setRecipe} preset={preset} canEdit={canEdit} isMobile={isMobile} />
        </Field>
        <Field label="Sections and layouts" group>
          <SectionTiles mode="show" keys={sections} selected={sections.filter((k) => !recipe.hidden.includes(k))} onToggle={toggleHidden}
            variants={recipe.variants} onVariant={setVariant} disabled={!canEdit} />
        </Field>
      </div>
    </Card>
  )
}

function Grid2({ children }) {
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>{children}</div>
}
