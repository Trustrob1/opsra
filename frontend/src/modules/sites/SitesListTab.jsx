/**
 * frontend/src/modules/sites/SitesListTab.jsx
 * SITE-1A part 2 — Sites: list + by-hand creation + the site editor.
 * The WhatsApp brief flow is SITE-1B; this is how Trust builds and previews a site
 * directly (spec §22 "Trust can build and preview sites by hand").
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus, Search, Globe } from 'lucide-react'
import { listSites, createSite, listPresets, listBuilders, sendCareLink, errorMessage } from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty, Field, Modal } from './sitesUi'
import { T, INPUT, dateOnly, money, SITE_STATUS } from './sitesKit'
import { useIsMobile } from '../../hooks/useIsMobile'
import SiteEditorPanel from './SiteEditorPanel'

export default function SitesListTab({ isActive, canEdit, enabled, showToast }) {
  const isMobile = useIsMobile()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [presets, setPresets] = useState([])
  const [builders, setBuilders] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [careFor, setCareFor] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listSites(search ? { search } : undefined)
      setRows(res.items || [])
      setTotal(res.total || 0)
    } catch (e) {
      setError(errorMessage(e, 'Could not load sites.'))
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => { if (isActive) load() }, [isActive, load])
  // SITE-1C-3b: templates load with the tab (not just for the create modal) so each row can name its template.
  useEffect(() => {
    if (!isActive) return
    listPresets().then(setPresets).catch(() => {})
  }, [isActive])
  useEffect(() => {
    if (!isActive || !creating) return
    listBuilders().then(setBuilders).catch(() => {})
  }, [isActive, creating])
  const presetName = useMemo(() => Object.fromEntries(presets.map((p) => [p.id, p.name])), [presets])

  if (selectedId) {
    return <SiteEditorPanel siteId={selectedId} canEdit={canEdit} isMobile={isMobile} showToast={showToast}
      onBack={() => { setSelectedId(null); load() }} />
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 240px', maxWidth: 320 }}>
          <Search size={15} color={T.muted} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} aria-hidden="true" />
          <input style={{ ...INPUT, paddingLeft: 32 }} placeholder="Search by business name or slug"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {canEdit && (
          <Button variant="primary" icon={Plus} disabled={!enabled} onClick={() => setCreating(true)}
            title={!enabled ? 'Turn the site engine on in Settings first' : undefined}>
            New site
          </Button>
        )}
      </div>

      {!enabled && <Notice tone="warn">The site engine is off — turn it on in Settings before building a new site.</Notice>}
      {error && <Notice tone="bad">{error}</Notice>}

      {loading ? <Spinner /> : rows.length === 0 ? (
        <Card><Empty icon={Globe} title="No sites yet" text="Build one by hand to try the engine, or wait for SITE-1B's WhatsApp flow." /></Card>
      ) : (
        <Card pad={0}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 860 }}>
              <thead><tr>{['Business', 'Slug', 'Template', 'Status', 'Care plan', 'Updated', ''].map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
              <tbody>
                {rows.map((s) => {
                  const st = SITE_STATUS[s.status] || SITE_STATUS.brief_in_progress
                  return (
                    <tr key={s.id} className="sts-row" style={{ borderTop: `1px solid ${T.line}` }}>
                      <Td>{s.client_business_name}</Td>
                      <Td><code style={{ fontSize: 12 }}>{s.slug}</code></Td>
                      <Td>{presetName[s.preset_id] || <span style={{ color: T.muted }}>{presets.length ? 'Removed template' : '—'}</span>}</Td>
                      <Td><Badge tone={st.tone}>{st.label}</Badge></Td>
                      <Td><CareCell s={s} /></Td>
                      <Td className="tnum">{dateOnly(s.updated_at)}</Td>
                      <Td>
                        <Button size="sm" variant="ghost" onClick={() => setSelectedId(s.id)}>Open</Button>
                        {canEdit && s.care_plan_status !== undefined && ['live', 'renewal_due', 'lapsed'].includes(s.status) && (
                          <Button size="sm" variant="ghost" onClick={() => setCareFor(s)}>Care link</Button>
                        )}
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="tnum" style={{ margin: 0, padding: '10px 14px', fontSize: 11.5, color: T.muted, borderTop: `1px solid ${T.line}` }}>{total} site{total === 1 ? '' : 's'}</p>
        </Card>
      )}

      <CareLinkModal site={careFor} onClose={() => setCareFor(null)} showToast={showToast} />
      <CreateSiteModal open={creating} presets={presets} builders={builders} onClose={() => setCreating(false)}
        onCreated={(site) => { setCreating(false); showToast('Site created'); setSelectedId(site.id) }} showToast={showToast} />
    </div>
  )
}

function CareCell({ s }) {
  const st = s.care_plan_status
  const left = s.edits_left
  if (st === undefined) return <span style={{ color: T.muted }}>—</span>
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      {st === 'active' && <Badge tone="good">Active{s.care_plan_ends ? ` · to ${dateOnly(s.care_plan_ends)}` : ''}</Badge>}
      {st === 'grace' && <Badge tone="warn">Grace</Badge>}
      {(st === 'ended' || st === 'none' || !st) && <Badge tone="neutral">No plan</Badge>}
      {left != null && <span className="tnum" style={{ fontSize: 12, color: T.muted }}>{left} edit{left === 1 ? '' : 's'} left</span>}
    </span>
  )
}

function CareLinkModal({ site, onClose, showToast }) {
  const [busy, setBusy] = useState('')
  const [link, setLink] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { setLink(null); setErr(null); setBusy('') }, [site])
  if (!site) return null
  const send = async (what) => {
    setBusy(what); setErr(null)
    try {
      const res = await sendCareLink(site.id, what)
      setLink(res)
      showToast(res?.sent ? 'Care link sent to the builder' : 'Care link ready')
    } catch (e) {
      setErr(errorMessage(e, 'Could not create the care link.'))
    } finally { setBusy('') }
  }
  return (
    <Modal open onClose={onClose} title={`Care link · ${site.client_business_name}`}
      footer={<Button onClick={onClose}>Close</Button>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <p style={{ margin: 0, fontSize: 13, color: T.muted }}>Create a payment link for the builder. It is sent on WhatsApp when possible.</p>
        {err && <Notice tone="bad">{err}</Notice>}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button variant="primary" loading={busy === 'plan'} disabled={!!busy} onClick={() => send('plan')}>
            Care plan{site.plan_price != null ? ` · ${money(site.plan_price)}/month` : ''}
          </Button>
          <Button loading={busy === 'pack'} disabled={!!busy} onClick={() => send('pack')}>
            Extra edits{site.pack_price != null ? ` · ${money(site.pack_price)}` : ''}
          </Button>
        </div>
        {link?.checkout_url && <code style={{ fontSize: 12, wordBreak: 'break-all' }}>{link.checkout_url}</code>}
      </div>
    </Modal>
  )
}

function Th({ children }) {
  return <th style={{ textAlign: 'left', fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px', padding: '10px 12px', whiteSpace: 'nowrap' }}>{children}</th>
}
function Td({ children, className }) {
  return <td className={className} style={{ padding: '10px 12px', color: T.ink, verticalAlign: 'middle' }}>{children}</td>
}

function CreateSiteModal({ open, presets, builders, onClose, onCreated, showToast }) {
  const [form, setForm] = useState(blank())
  const [saving, setSaving] = useState(false)

  function blank() {
    return { preset_id: '', builder_id: '', client_business_name: '', whatsapp_e164: '', headline: '' }
  }
  useEffect(() => { if (open) setForm(blank()) }, [open])

  const activePresets = presets.filter((p) => p.is_active !== false)

  const submit = async () => {
    const preset = presets.find((p) => p.id === form.preset_id)
    if (!preset) { showToast('Choose a template', 'bad'); return }
    if (!form.client_business_name.trim()) { showToast('Business name is required', 'bad'); return }
    if (!form.whatsapp_e164.trim()) { showToast('A WhatsApp number is required', 'bad'); return }

    const content = {
      business: { name: form.client_business_name.trim(), city: '', tagline: '', whatsapp_e164: form.whatsapp_e164.trim(),
        phone_display: '', instagram: '', delivery_note: '' },
      hero: { headline: form.headline.trim() || `Welcome to ${form.client_business_name.trim()}`, subhead: '', image_asset_id: null },
      about: { title: '', body: [], owner: '', pull_quote: '', image_asset_id: null },
      items: [], categories: [], reviews: [], hours: [], location: {},
      order_section: { title: 'How to order', steps: ['Message us on WhatsApp', 'Confirm your order', 'We deliver or you collect'] },
      seo: { title: form.client_business_name.trim(), description: '' },
    }
    const recipe = {
      theme: preset.allowed_themes?.[0] || 'atelier',
      palette: preset.default_palettes?.[0] || 'berry',
      order: preset.sections,
      hidden: [],
    }

    setSaving(true)
    try {
      const site = await createSite({
        preset_id: form.preset_id, builder_id: form.builder_id || null,
        client_business_name: form.client_business_name.trim(), content, recipe, content_source: 'manual',
      })
      onCreated(site)
    } catch (e) {
      showToast(errorMessage(e, 'Could not create this site.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New site"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={saving} onClick={submit}>Create & open</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Template">
          <select style={INPUT} value={form.preset_id} onChange={(e) => setForm((f) => ({ ...f, preset_id: e.target.value }))}>
            <option value="">Choose a template…</option>
            {activePresets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Builder (optional)" hint="Leave unset for a site you're building yourself">
          <select style={INPUT} value={form.builder_id} onChange={(e) => setForm((f) => ({ ...f, builder_id: e.target.value }))}>
            <option value="">No builder</option>
            {builders.map((b) => <option key={b.id} value={b.id}>{b.full_name} — {b.business_name || b.phone_number}</option>)}
          </select>
        </Field>
        <Field label="Client business name"><input style={INPUT} value={form.client_business_name}
          onChange={(e) => setForm((f) => ({ ...f, client_business_name: e.target.value }))} /></Field>
        <Field label="Client WhatsApp number" hint="Where orders go — e.g. +2348012345678">
          <input style={INPUT} value={form.whatsapp_e164} onChange={(e) => setForm((f) => ({ ...f, whatsapp_e164: e.target.value }))} />
        </Field>
        <Field label="Hero headline (optional)"><input style={INPUT} value={form.headline}
          onChange={(e) => setForm((f) => ({ ...f, headline: e.target.value }))} /></Field>
      </div>
    </Modal>
  )
}
