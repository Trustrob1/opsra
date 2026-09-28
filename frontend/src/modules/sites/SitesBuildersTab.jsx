/**
 * frontend/src/modules/sites/SitesBuildersTab.jsx
 * SITE-1A part 2 — Builders: web developers registered to use the site-builder bot
 * (spec §1, L6/L7). By-hand add, CSV import, and edit (status/limits/plan dates).
 * The WhatsApp bot itself (SITE-1B) isn't built yet — this is roster management only.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, Upload, UserPlus, Users, Link2 } from 'lucide-react'
import { listBuilders, createBuilder, updateBuilder, importBuilders, createBriefForm, createEditorLink, errorMessage } from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty, Field, Modal, Drawer } from './sitesUi'
import { T, INPUT, dateOnly, BUILDER_STATUS } from './sitesKit'
import { useIsMobile } from '../../hooks/useIsMobile'

export default function SitesBuildersTab({ isActive, canEdit, showToast }) {
  const isMobile = useIsMobile()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(null)
  const [formLinkFor, setFormLinkFor] = useState(null)
  const [editLinkFor, setEditLinkFor] = useState(null)
  const fileRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await listBuilders())
    } catch (e) {
      setError(errorMessage(e, 'Could not load builders.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  const onImportFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const res = await importBuilders(file)
      showToast(`Imported ${res.created} builder${res.created === 1 ? '' : 's'}${res.skipped ? `, skipped ${res.skipped}` : ''}`)
      load()
    } catch (err) {
      showToast(errorMessage(err, 'Import failed.'), 'bad')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <p style={{ margin: 0, fontSize: 13, color: T.muted, maxWidth: 480 }}>
          Web developers who build sites for their own clients through the bot. Not included in the webinar ticket — they pay for this separately.
        </p>
        {canEdit && (
          <div style={{ display: 'flex', gap: 8 }}>
            <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={onImportFile} />
            <Button variant="secondary" icon={Upload} onClick={() => fileRef.current?.click()}>Import CSV</Button>
            <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Add builder</Button>
          </div>
        )}
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      {loading ? <Spinner /> : rows.length === 0 ? (
        <Card>
          <Empty icon={Users} title="No builders yet" text="Add one by hand or import a CSV (columns: phone_number, full_name, email, business_name)."
            action={canEdit && <Button variant="primary" icon={UserPlus} onClick={() => setCreating(true)}>Add builder</Button>} />
        </Card>
      ) : (
        <Card pad={0}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 640 }}>
              <thead><tr>{['Name', 'Phone', 'Business', 'Status', 'Joined', ''].map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
              <tbody>
                {rows.map((b) => {
                  const st = BUILDER_STATUS[b.status] || BUILDER_STATUS.active
                  return (
                    <tr key={b.id} className="sts-row" style={{ borderTop: `1px solid ${T.line}` }}>
                      <Td>{b.full_name}</Td>
                      <Td className="tnum">{b.phone_number}</Td>
                      <Td>{b.business_name || '—'}</Td>
                      <Td><Badge tone={st.tone}>{st.label}</Badge></Td>
                      <Td className="tnum">{dateOnly(b.joined_at)}</Td>
                      <Td>
                        {canEdit && (
                          <div style={{ display: 'flex', gap: 4 }}>
                            <Button size="sm" variant="ghost" icon={Link2} onClick={() => setFormLinkFor(b)}>Get form link</Button>
                            <Button size="sm" variant="ghost" icon={Link2} onClick={() => setEditLinkFor(b)}>Get edit link</Button>
                            <Button size="sm" variant="ghost" onClick={() => setEditing(b)}>Edit</Button>
                          </div>
                        )}
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <CreateBuilderModal open={creating} onClose={() => setCreating(false)}
        onCreated={() => { setCreating(false); showToast('Builder added'); load() }} showToast={showToast} />
      <EditBuilderDrawer builder={editing} isMobile={isMobile} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); load() }} showToast={showToast} />
      <GetFormLinkModal builder={formLinkFor} onClose={() => setFormLinkFor(null)} showToast={showToast} />
      <GetEditLinkModal builder={editLinkFor} onClose={() => setEditLinkFor(null)} showToast={showToast} />
    </div>
  )
}

function GetEditLinkModal({ builder, onClose, showToast }) {
  const [saving, setSaving] = useState(false)
  const [url, setUrl] = useState(null)

  useEffect(() => { if (builder) setUrl(null) }, [builder])

  if (!builder) return null

  const generate = async () => {
    setSaving(true)
    try {
      const res = await createEditorLink(builder.id)
      setUrl(res.url)
    } catch (e) {
      showToast(errorMessage(e, 'Could not create an edit link.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const copy = async () => {
    try { await navigator.clipboard.writeText(url); showToast('Link copied') }
    catch (_) { showToast('Could not copy — select and copy the link by hand', 'bad') }
  }

  return (
    <Modal open={!!builder} onClose={onClose} title={`Edit link for ${builder.full_name}`}
      footer={url
        ? <Button onClick={onClose}>Done</Button>
        : <><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={saving} onClick={generate}>Create link</Button></>}>
      {!url ? (
        <p style={{ fontSize: 13, color: T.ink, margin: 0 }}>
          Opens the site editor and signs {builder.full_name} in automatically. Works for 7 days, single use —
          this is the stand-in for the WhatsApp EDIT command until the site-builder number is live.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <p style={{ fontSize: 13, color: T.ink, margin: 0 }}>Here's the link — this is the only time it's shown in full, so copy it now:</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input readOnly style={{ ...INPUT, fontFamily: 'monospace', fontSize: 12.5 }} value={url} onFocus={(e) => e.target.select()} />
            <Button variant="secondary" onClick={copy}>Copy</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function GetFormLinkModal({ builder, onClose, showToast }) {
  const [audience, setAudience] = useState('builder')
  const [clientLabel, setClientLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const [url, setUrl] = useState(null)

  useEffect(() => { if (builder) { setAudience('builder'); setClientLabel(''); setUrl(null) } }, [builder])

  if (!builder) return null

  const generate = async () => {
    setSaving(true)
    try {
      const res = await createBriefForm({
        builder_id: builder.id, audience,
        client_label: audience === 'client' ? (clientLabel.trim() || null) : null,
      })
      setUrl(res.url)
    } catch (e) {
      showToast(errorMessage(e, 'Could not create a form link.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const copy = async () => {
    try { await navigator.clipboard.writeText(url); showToast('Link copied') }
    catch (_) { showToast('Could not copy — select and copy the link by hand', 'bad') }
  }

  return (
    <Modal open={!!builder} onClose={onClose} title={`Form link for ${builder.full_name}`}
      footer={url
        ? <Button onClick={onClose}>Done</Button>
        : <><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={saving} onClick={generate}>Create link</Button></>}>
      {!url ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="Who's filling it in?">
            <select style={INPUT} value={audience} onChange={(e) => setAudience(e.target.value)}>
              <option value="builder">The builder themselves</option>
              <option value="client">Their client (no Opsra branding, no pricing shown)</option>
            </select>
          </Field>
          {audience === 'client' && (
            <Field label="Client label (optional)" hint="Just for your own reference in the list">
              <input style={INPUT} value={clientLabel} onChange={(e) => setClientLabel(e.target.value)} placeholder="e.g. Adaeze's Boutique" />
            </Field>
          )}
          <p style={{ fontSize: 12, color: T.muted, margin: 0 }}>
            The link works for 14 days. It doesn't ask them to choose a business type yet —
            they'll pick one as the first step on the form.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <p style={{ fontSize: 13, color: T.ink, margin: 0 }}>Here's the link — this is the only time it's shown in full, so copy it now:</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input readOnly style={{ ...INPUT, fontFamily: 'monospace', fontSize: 12.5 }} value={url} onFocus={(e) => e.target.select()} />
            <Button variant="secondary" onClick={copy}>Copy</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Th({ children }) {
  return <th style={{ textAlign: 'left', fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px', padding: '10px 12px', whiteSpace: 'nowrap' }}>{children}</th>
}
function Td({ children, className }) {
  return <td className={className} style={{ padding: '10px 12px', color: T.ink, verticalAlign: 'middle' }}>{children}</td>
}

function CreateBuilderModal({ open, onClose, onCreated, showToast }) {
  const [form, setForm] = useState({ full_name: '', phone_number: '', email: '', business_name: '' })
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  useEffect(() => { if (open) setForm({ full_name: '', phone_number: '', email: '', business_name: '' }) }, [open])

  const submit = async () => {
    if (!form.full_name.trim() || !form.phone_number.trim()) {
      showToast('Name and phone number are required', 'bad'); return
    }
    setSaving(true)
    try {
      await createBuilder(form)
      onCreated()
    } catch (e) {
      showToast(errorMessage(e, 'Could not add this builder.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Add builder"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={saving} onClick={submit}>Add builder</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Full name"><input style={INPUT} value={form.full_name} onChange={set('full_name')} /></Field>
        <Field label="WhatsApp phone number" hint="Include the country code, e.g. +2348012345678">
          <input style={INPUT} value={form.phone_number} onChange={set('phone_number')} />
        </Field>
        <Field label="Email (optional)"><input style={INPUT} type="email" value={form.email} onChange={set('email')} /></Field>
        <Field label="Business name (optional)"><input style={INPUT} value={form.business_name} onChange={set('business_name')} /></Field>
      </div>
    </Modal>
  )
}

function EditBuilderDrawer({ builder, isMobile, onClose, onSaved, showToast }) {
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (builder) setForm({
      full_name: builder.full_name || '', email: builder.email || '', business_name: builder.business_name || '',
      status: builder.status || 'active', max_active_sites: builder.max_active_sites ?? '',
      access_paid_until: builder.access_paid_until ? builder.access_paid_until.slice(0, 10) : '',
    })
  }, [builder])

  if (!builder || !form) return null
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async () => {
    setSaving(true)
    try {
      const payload = { ...form }
      payload.max_active_sites = payload.max_active_sites === '' ? null : Number(payload.max_active_sites)
      payload.access_paid_until = payload.access_paid_until || null
      await updateBuilder(builder.id, payload)
      showToast('Builder updated')
      onSaved()
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={!!builder} onClose={onClose} title={builder.full_name} subtitle={builder.phone_number} isMobile={isMobile}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Full name"><input style={INPUT} value={form.full_name} onChange={set('full_name')} /></Field>
        <Field label="Email"><input style={INPUT} type="email" value={form.email} onChange={set('email')} /></Field>
        <Field label="Business name"><input style={INPUT} value={form.business_name} onChange={set('business_name')} /></Field>
        <Field label="Status">
          <select style={INPUT} value={form.status} onChange={set('status')}>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="suspended">Suspended</option>
          </select>
        </Field>
        <Field label="Max active sites" hint="Leave blank for no limit">
          <input style={INPUT} type="number" min="0" value={form.max_active_sites} onChange={set('max_active_sites')} />
        </Field>
        <Field label="Access paid until" hint="Leave blank if not on a paid plan">
          <input style={INPUT} type="date" value={form.access_paid_until} onChange={set('access_paid_until')} />
        </Field>
        <div style={{ marginTop: 6 }}>
          <Button variant="primary" loading={saving} onClick={submit}>Save</Button>
        </div>
      </div>
    </Drawer>
  )
}
