/**
 * frontend/src/modules/sites/ExtraSectionCards.jsx
 * SITE-1C-3 — content forms for the optional sections (announcement bar, FAQ, price list,
 * how we work, team, gallery). Shared by the staff editor and the builder editor.
 *
 * A form only appears when the site's template offers that section (or the site already has
 * content for it), so a plain site's editor is unchanged. "Hours & location" already has its own
 * card in both editors and feeds the new hours section.
 * Limits mirror models/sites.py.
 */
import { useState } from 'react'
import { Plus, Trash2, ImagePlus, ChevronDown } from 'lucide-react'
import { Card, Button, Field, SectionTitle } from './sitesUi'
import { T, INPUT, TEXTAREA, photoHint } from './sitesKit'

const EXTRA_LIMITS = { faqs: 12, menuGroups: 8, menuLines: 15, steps: 6, team: 6, gallery: 9 }

function Toggle({ open, onToggle }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open} aria-label={open ? 'Collapse' : 'Expand'}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30, borderRadius: 8,
        border: `1px solid ${T.lineStrong}`, background: '#fff', cursor: 'pointer', flexShrink: 0 }}>
      <ChevronDown size={15} color={T.ink} aria-hidden="true" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
    </button>
  )
}

/** Card with a title, an optional "Add" button and (in the builder editor) a collapse toggle. */
function Frame({ title, hint, addLabel, onAdd, canAdd = true, canEdit, collapsible, children }) {
  const [open, setOpen] = useState(!collapsible)
  const right = (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {canEdit && onAdd && canAdd && <Button size="sm" variant="secondary" icon={Plus} onClick={onAdd}>{addLabel}</Button>}
      {collapsible && <Toggle open={open} onToggle={() => setOpen((o) => !o)} />}
    </div>
  )
  return (
    <Card>
      <SectionTitle title={title} hint={hint} right={right} />
      {open && children}
    </Card>
  )
}

const Empty = ({ children }) => <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>{children}</p>
const Rows = ({ children }) => <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>{children}</div>
const Box = ({ children }) => <div style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>{children}</div>
const Grid2 = ({ children }) => <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>{children}</div>

function Photo({ label, slot, assetId, assetUrls, canEdit, onPick, onRemove }) {
  const url = assetId ? assetUrls?.[assetId] : null
  return (
    <Field label={label} hint={photoHint(slot)}>
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
        {canEdit && assetId && (
          <button type="button" onClick={onRemove}
            style={{ fontSize: 12.5, fontWeight: 600, color: T.bad || '#B42318', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'inherit' }}>
            Remove photo
          </button>
        )}
      </div>
    </Field>
  )
}

/** Read/update/add/remove helpers for a top-level list in the content JSON. */
function useList(content, setContent, key, max, blank) {
  const rows = content[key] || []
  return {
    rows,
    add: () => { if (rows.length < max) setContent((c) => ({ ...c, [key]: [...(c[key] || []), blank()] })) },
    update: (i, patch) => setContent((c) => ({ ...c, [key]: (c[key] || []).map((r, idx) => (idx === i ? { ...r, ...patch } : r)) })),
    remove: (i) => setContent((c) => ({ ...c, [key]: (c[key] || []).filter((_, idx) => idx !== i) })),
    canAdd: rows.length < max,
  }
}

function AnnouncementCard({ content, setContent, canEdit, collapsible }) {
  const text = content.announcement?.text || ''
  return (
    <Frame title="Announcement bar" hint="One short line above the menu: a promo or a delivery cut-off. Leave empty to show nothing." canEdit={canEdit} collapsible={collapsible}>
      <Field label="Announcement" count={text.length} max={140}>
        <input style={INPUT} value={text} maxLength={140} disabled={!canEdit}
          onChange={(e) => setContent((c) => ({ ...c, announcement: { text: e.target.value } }))} />
      </Field>
    </Frame>
  )
}

function FaqCard({ content, setContent, canEdit, collapsible }) {
  const { rows, add, update, remove, canAdd } = useList(content, setContent, 'faqs', EXTRA_LIMITS.faqs, () => ({ q: '', a: '' }))
  return (
    <Frame title="FAQ" hint={`Questions customers keep asking, with your answers. Up to ${EXTRA_LIMITS.faqs}. Rows missing a question or answer are not shown.`}
      addLabel="Add question" onAdd={add} canAdd={canAdd} canEdit={canEdit} collapsible={collapsible}>
      {rows.length === 0 ? <Empty>No questions yet.</Empty> : (
        <Rows>
          {rows.map((r, i) => (
            <Box key={i}>
              <Field label="Question" count={r.q.length} max={140}><input style={INPUT} value={r.q} maxLength={140} disabled={!canEdit} onChange={(e) => update(i, { q: e.target.value })} /></Field>
              <Field label="Answer" count={r.a.length} max={600}><textarea style={TEXTAREA} value={r.a} maxLength={600} disabled={!canEdit} onChange={(e) => update(i, { a: e.target.value })} /></Field>
              {canEdit && <div><Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button></div>}
            </Box>
          ))}
        </Rows>
      )}
    </Frame>
  )
}

function MenuCard({ content, setContent, canEdit, collapsible }) {
  const { rows, add, remove, canAdd } = useList(content, setContent, 'menu', EXTRA_LIMITS.menuGroups, () => ({ name: '', lines: [] }))
  const setGroup = (gi, fn) => setContent((c) => ({ ...c, menu: (c.menu || []).map((g, idx) => (idx === gi ? fn(g) : g)) }))
  const updateLine = (gi, li, patch) => setGroup(gi, (g) => ({ ...g, lines: g.lines.map((l, idx) => (idx === li ? { ...l, ...patch } : l)) }))
  const addLine = (gi) => setGroup(gi, (g) => (g.lines.length < EXTRA_LIMITS.menuLines
    ? { ...g, lines: [...g.lines, { name: '', desc: '', price_ngn: 0, price_style: 'exact' }] } : g))
  const removeLine = (gi, li) => setGroup(gi, (g) => ({ ...g, lines: g.lines.filter((_, idx) => idx !== li) }))
  return (
    <Frame title="Price list" hint={`Groups of priced lines (a menu, a rate card). Up to ${EXTRA_LIMITS.menuGroups} groups of ${EXTRA_LIMITS.menuLines} lines. Groups with no lines are not shown.`}
      addLabel="Add group" onAdd={add} canAdd={canAdd} canEdit={canEdit} collapsible={collapsible}>
      {rows.length === 0 ? <Empty>No price list yet.</Empty> : (
        <Rows>
          {rows.map((g, gi) => (
            <Box key={gi}>
              <Field label="Group name" count={g.name.length} max={60}>
                <input style={INPUT} value={g.name} maxLength={60} disabled={!canEdit} onChange={(e) => setGroup(gi, (x) => ({ ...x, name: e.target.value }))} />
              </Field>
              {g.lines.map((l, li) => (
                <div key={li} style={{ borderTop: `1px dashed ${T.line}`, paddingTop: 10 }}>
                  <Grid2>
                    <Field label="Name"><input style={INPUT} value={l.name} maxLength={100} disabled={!canEdit} onChange={(e) => updateLine(gi, li, { name: e.target.value })} /></Field>
                    <Field label="Price (₦)"><input style={INPUT} type="number" min="0" step="0.01" value={l.price_ngn} disabled={!canEdit}
                      onChange={(e) => updateLine(gi, li, { price_ngn: Number(e.target.value) || 0 })} /></Field>
                    <Field label="Price style">
                      <select style={INPUT} value={l.price_style} disabled={!canEdit} onChange={(e) => updateLine(gi, li, { price_style: e.target.value })}>
                        <option value="exact">Exact</option><option value="from">From</option><option value="on_request">On request</option>
                      </select>
                    </Field>
                    <Field label="Note (optional)"><input style={INPUT} value={l.desc} maxLength={200} disabled={!canEdit} onChange={(e) => updateLine(gi, li, { desc: e.target.value })} /></Field>
                  </Grid2>
                  {canEdit && <div style={{ marginTop: 8 }}><Button size="sm" variant="danger" icon={Trash2} onClick={() => removeLine(gi, li)}>Remove line</Button></div>}
                </div>
              ))}
              {canEdit && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {g.lines.length < EXTRA_LIMITS.menuLines && <Button size="sm" variant="secondary" icon={Plus} onClick={() => addLine(gi)}>Add line</Button>}
                  <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(gi)}>Remove group</Button>
                </div>
              )}
            </Box>
          ))}
        </Rows>
      )}
    </Frame>
  )
}

function ProcessCard({ content, setContent, canEdit, collapsible }) {
  const p = content.process || { title: '', steps: [] }
  const steps = p.steps || []
  const setP = (patch) => setContent((c) => ({ ...c, process: { title: '', steps: [], ...(c.process || {}), ...patch } }))
  const updateStep = (i, patch) => setP({ steps: steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) })
  return (
    <Frame title="How we work" hint={`How a job goes from first message to done, in up to ${EXTRA_LIMITS.steps} steps. Different from "How to order", which is only the ordering steps.`}
      addLabel="Add step" onAdd={() => setP({ steps: [...steps, { title: '', text: '' }] })} canAdd={steps.length < EXTRA_LIMITS.steps} canEdit={canEdit} collapsible={collapsible}>
      <Field label="Section title" count={(p.title || '').length} max={100}>
        <input style={INPUT} value={p.title || ''} maxLength={100} disabled={!canEdit} placeholder="How we work" onChange={(e) => setP({ title: e.target.value })} />
      </Field>
      <div style={{ height: 12 }} />
      {steps.length === 0 ? <Empty>No steps yet.</Empty> : (
        <Rows>
          {steps.map((s, i) => (
            <Box key={i}>
              <Field label={`Step ${i + 1} title`} count={s.title.length} max={80}><input style={INPUT} value={s.title} maxLength={80} disabled={!canEdit} onChange={(e) => updateStep(i, { title: e.target.value })} /></Field>
              <Field label="What happens" count={(s.text || '').length} max={300}><textarea style={TEXTAREA} value={s.text || ''} maxLength={300} disabled={!canEdit} onChange={(e) => updateStep(i, { text: e.target.value })} /></Field>
              {canEdit && <div><Button size="sm" variant="danger" icon={Trash2} onClick={() => setP({ steps: steps.filter((_, idx) => idx !== i) })}>Remove</Button></div>}
            </Box>
          ))}
        </Rows>
      )}
    </Frame>
  )
}

function TeamCard({ content, setContent, canEdit, collapsible, assetUrls, onUpload }) {
  const { rows, add, update, remove, canAdd } = useList(content, setContent, 'team', EXTRA_LIMITS.team, () => ({ name: '', role: '', bio: '', image_asset_id: null }))
  return (
    <Frame title="Team" hint={`The people behind the business. Up to ${EXTRA_LIMITS.team}.`} addLabel="Add person" onAdd={add} canAdd={canAdd} canEdit={canEdit} collapsible={collapsible}>
      {rows.length === 0 ? <Empty>No team members yet.</Empty> : (
        <Rows>
          {rows.map((m, i) => (
            <Box key={i}>
              <Grid2>
                <Field label="Name"><input style={INPUT} value={m.name} maxLength={80} disabled={!canEdit} onChange={(e) => update(i, { name: e.target.value })} /></Field>
                <Field label="Role"><input style={INPUT} value={m.role || ''} maxLength={80} disabled={!canEdit} onChange={(e) => update(i, { role: e.target.value })} /></Field>
              </Grid2>
              <Field label="Short bio" count={(m.bio || '').length} max={300}><textarea style={TEXTAREA} value={m.bio || ''} maxLength={300} disabled={!canEdit} onChange={(e) => update(i, { bio: e.target.value })} /></Field>
              <Photo label="Photo" slot="team" assetId={m.image_asset_id} assetUrls={assetUrls} canEdit={canEdit}
                onPick={(f) => onUpload(`team_${i}`, f, (id) => update(i, { image_asset_id: id }))} onRemove={() => update(i, { image_asset_id: null })} />
              {canEdit && <div><Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button></div>}
            </Box>
          ))}
        </Rows>
      )}
    </Frame>
  )
}

function GalleryCard({ content, setContent, canEdit, collapsible, assetUrls, onUpload }) {
  const { rows, add, update, remove, canAdd } = useList(content, setContent, 'gallery', EXTRA_LIMITS.gallery, () => ({ caption: '', image_asset_id: null }))
  return (
    <Frame title="Gallery" hint={`Photos of your work. Up to ${EXTRA_LIMITS.gallery}. Each site can hold 20 photos in total, including the hero, about and item photos.`}
      addLabel="Add photo" onAdd={add} canAdd={canAdd} canEdit={canEdit} collapsible={collapsible}>
      {rows.length === 0 ? <Empty>No gallery photos yet.</Empty> : (
        <Rows>
          {rows.map((g, i) => (
            <Box key={i}>
              <Photo label="Photo" slot="gallery" assetId={g.image_asset_id} assetUrls={assetUrls} canEdit={canEdit}
                onPick={(f) => onUpload(`gallery_${i}`, f, (id) => update(i, { image_asset_id: id }))} onRemove={() => update(i, { image_asset_id: null })} />
              <Field label="Caption (optional)" count={(g.caption || '').length} max={100}>
                <input style={INPUT} value={g.caption || ''} maxLength={100} disabled={!canEdit} onChange={(e) => update(i, { caption: e.target.value })} />
              </Field>
              {canEdit && <div><Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button></div>}
            </Box>
          ))}
        </Rows>
      )}
    </Frame>
  )
}

function BannerCard({ content, setContent, canEdit, collapsible, assetUrls, onUpload }) {
  const b = content.banner || {}
  const set = (patch) => setContent((c) => ({ ...c, banner: { eyebrow: '', headline: '', text: '', button_text: '', image_asset_id: null, ...(c.banner || {}), ...patch } }))
  return (
    <Frame title="Closing banner" hint="A full-width photo near the bottom of the page. It only appears once it has a headline." canEdit={canEdit} collapsible={collapsible}>
      <Rows>
        <Box>
          <Field label="Small line above (optional)" count={(b.eyebrow || '').length} max={60}><input style={INPUT} value={b.eyebrow || ''} maxLength={60} disabled={!canEdit} onChange={(e) => set({ eyebrow: e.target.value })} /></Field>
          <Field label="Headline" count={(b.headline || '').length} max={100}><input style={INPUT} value={b.headline || ''} maxLength={100} disabled={!canEdit} placeholder="Ready when you are." onChange={(e) => set({ headline: e.target.value })} /></Field>
          <Field label="Short text (optional)" count={(b.text || '').length} max={300}><textarea style={TEXTAREA} value={b.text || ''} maxLength={300} disabled={!canEdit} onChange={(e) => set({ text: e.target.value })} /></Field>
          <Field label="Button text (optional)" count={(b.button_text || '').length} max={40}><input style={INPUT} value={b.button_text || ''} maxLength={40} disabled={!canEdit} placeholder="Chat with us" onChange={(e) => set({ button_text: e.target.value })} /></Field>
          <Photo label="Background photo" slot="banner" assetId={b.image_asset_id} assetUrls={assetUrls} canEdit={canEdit}
            onPick={(f) => onUpload('banner_0', f, (id) => set({ image_asset_id: id }))} onRemove={() => set({ image_asset_id: null })} />
        </Box>
      </Rows>
    </Frame>
  )
}

const HAS = {
  announcement: (c) => !!c.announcement?.text,
  faq: (c) => (c.faqs || []).length > 0,
  menu: (c) => (c.menu || []).length > 0,
  process: (c) => (c.process?.steps || []).length > 0,
  team: (c) => (c.team || []).length > 0,
  gallery: (c) => (c.gallery || []).length > 0,
  banner: (c) => !!c.banner?.headline,
}

/** `offered` = section keys the template (or the site's recipe) includes. */
export default function ExtraSectionCards({ content, setContent, offered = [], canEdit = true, collapsible = false, assetUrls, onUpload }) {
  const show = (key) => offered.includes(key) || HAS[key](content)
  const shared = { content, setContent, canEdit, collapsible }
  return (
    <>
      {show('announcement') && <AnnouncementCard {...shared} />}
      {show('faq') && <FaqCard {...shared} />}
      {show('menu') && <MenuCard {...shared} />}
      {show('process') && <ProcessCard {...shared} />}
      {show('team') && <TeamCard {...shared} assetUrls={assetUrls} onUpload={onUpload} />}
      {show('gallery') && <GalleryCard {...shared} assetUrls={assetUrls} onUpload={onUpload} />}
      {show('banner') && <BannerCard {...shared} assetUrls={assetUrls} onUpload={onUpload} />}
    </>
  )
}
