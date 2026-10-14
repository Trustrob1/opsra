/**
 * frontend/src/modules/sites/VersionSharesPanel.jsx
 * SITE-OPTIONS OPT-3 - "Versions of one site": share several saved versions of ONE client's Premium site behind one
 * link. The client opens each version and picks one; the pick becomes the site's live preview. Used in the builder
 * portal and in the staff Sites area through an `api` adapter, so the builder token and staff session never mix.
 *
 *   api        { list, sites, versions(siteId), create({site_id, client_name, design_ids}), get, add(id, designId),
 *                remove(id, itemId), choose(id, itemId), close(id) }   (each returns the payload; memoise it)
 *   errorMessage(err, fallback)
 *   canEdit    false = read only
 *   canCreate  false = creating is off (staff with "All builders" selected)
 *   builderNames { [id]: label }  staff only
 *   onPayLink(siteId)  builder only: go to checkout for the site
 *   showToast(text, tone)
 */
import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronLeft, Copy, ExternalLink, Layers, Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Card, Empty, Field, Modal, Notice, SectionTitle, Spinner } from './sitesUi'
import { INPUT, T, dateOnly } from './sitesKit'
import { copyText } from './siteAddonsKit'

const STATUS = {
  open: ['info', 'Waiting for the client'],
  chosen: ['good', 'Client picked one'],
  closed: ['neutral', 'Closed'],
  expired: ['warn', 'Expired'],
}

function StatusBadge({ status }) {
  const [tone, text] = STATUS[status] || ['neutral', status || '—']
  return <Badge tone={tone}>{text}</Badge>
}

const versionLine = (v) => `Version ${v.version}${v.created_at ? ` · ${dateOnly(v.created_at)}` : ''}${v.label && v.label !== `Version ${v.version}` ? ` · ${v.label}` : ''}`

export default function VersionSharesPanel({ api, errorMessage, canEdit = true, canCreate = true, builderNames, onPayLink, showToast }) {
  const [rows, setRows] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [openId, setOpenId] = useState(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoadError('')
    try { setRows(await api.list()) } catch (e) { setRows([]); setLoadError(errorMessage(e, 'Could not load your version links.')) }
  }, [api, errorMessage])
  useEffect(() => { setRows(null); load() }, [load])

  if (openId) {
    return (
      <ShareDetail key={openId} shareId={openId} api={api} errorMessage={errorMessage} canEdit={canEdit} onPayLink={onPayLink}
        showToast={showToast} onBack={() => { setOpenId(null); load() }} />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle title="Versions of one site"
        hint="Show your client the different versions made for their Premium site. They open each one on one link and choose. Their choice becomes the site’s preview."
        right={canEdit && (
          <Button variant="primary" icon={Plus} disabled={!canCreate} onClick={() => setCreating(true)}
            title={!canCreate ? 'Pick a builder first' : undefined}>Share versions</Button>
        )} />
      {!canCreate && canEdit && <Notice tone="info">Pick a builder above to share versions for one of their sites.</Notice>}
      {loadError && <Notice tone="bad">{loadError}</Notice>}
      {rows === null && <Spinner />}
      {rows && rows.length === 0 && !loadError && (
        <Card><Empty icon={Layers} title="No version links yet"
          text="Share a Premium site’s saved versions with its client. The site needs at least two saved versions." /></Card>
      )}
      {rows && rows.map((s) => (
        <Card key={s.id} pad={14} style={{ cursor: 'pointer' }} onClick={() => setOpenId(s.id)}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700, color: T.ink, fontSize: 14, wordBreak: 'break-word' }}>{s.client_name || s.business_name || 'Unnamed client'}</div>
              <div style={{ fontSize: 12.5, color: T.muted, marginTop: 2 }}>
                {s.business_name && s.client_name ? `${s.business_name} · ` : ''}{s.versions} {s.versions === 1 ? 'version' : 'versions'}
                {builderNames && builderNames[s.builder_id] ? ` · ${builderNames[s.builder_id]}` : ''}
                {s.expires_at ? ` · link until ${dateOnly(s.expires_at)}` : ''}
              </div>
            </div>
            <StatusBadge status={s.status} />
          </div>
        </Card>
      ))}
      <CreateModal open={creating} onClose={() => setCreating(false)} api={api} errorMessage={errorMessage}
        onCreated={(share) => { setCreating(false); setOpenId(share.id); showToast?.('Version link created') }} />
    </div>
  )
}

// ── one link ─────────────────────────────────────────────────────────────────────────

function ShareDetail({ shareId, api, errorMessage, canEdit, onPayLink, showToast, onBack }) {
  const [share, setShare] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [copied, setCopied] = useState(false)
  const [adding, setAdding] = useState(false)
  const [confirm, setConfirm] = useState(null)   // {kind:'choose'|'remove'|'close', item?}

  const load = useCallback(async () => {
    try { setShare(await api.get(shareId)); setError('') } catch (e) { setError(errorMessage(e, 'Could not load this link.')) }
  }, [api, shareId, errorMessage])
  useEffect(() => { load() }, [load])

  async function run(key, fn, okText) {
    setBusy(key); setError('')
    try {
      const res = await fn()
      if (res && res.set) setShare(res.set); else if (res && res.items) setShare(res); else await load()
      if (okText) showToast?.(okText)
      return true
    } catch (e) {
      setError(errorMessage(e, 'That did not work. Please try again.'))
      return false
    } finally { setBusy(''); setConfirm(null) }
  }

  async function copy() {
    const ok = await copyText(share.link)
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000) } else setError('Could not copy. Select the link and copy it by hand.')
  }

  const back = (
    <button type="button" onClick={onBack} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'none', border: 'none',
      color: T.teal, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: '6px 0', minHeight: 44, fontFamily: 'inherit', alignSelf: 'flex-start' }}>
      <ChevronLeft size={16} aria-hidden="true" /> All version links
    </button>
  )
  if (!share) return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>{back}{error ? <Notice tone="bad">{error}</Notice> : <Spinner />}</div>

  const live = share.status === 'open' || share.status === 'chosen'
  const picked = share.items.find((i) => i.chosen)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {back}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 18, color: T.ink, wordBreak: 'break-word' }}>{share.client_name || share.business_name || 'Unnamed client'}</h2>
          {share.client_name && share.business_name && <div style={{ fontSize: 12.5, color: T.muted }}>{share.business_name}</div>}
        </div>
        <StatusBadge status={share.status} />
      </div>
      {error && <Notice tone="bad">{error}</Notice>}

      {live && (
        <Card pad={14}>
          <Field label="Send this link to your client" hint={share.expires_at ? `Works until ${dateOnly(share.expires_at)}.` : undefined}>
            <input readOnly value={share.link} onFocus={(e) => e.target.select()} style={INPUT} aria-label="Version link" />
          </Field>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
            <Button variant="primary" icon={copied ? Check : Copy} onClick={copy}>{copied ? 'Copied' : 'Copy link'}</Button>
            <Button icon={ExternalLink} onClick={() => window.open(share.link, '_blank', 'noopener')}>See what the client sees</Button>
          </div>
        </Card>
      )}

      {share.status === 'chosen' && picked && (
        <Notice tone="good">
          <div>
            <strong>{picked.label}</strong> was picked{share.chosen_at ? ` on ${dateOnly(share.chosen_at)}` : ''} and is now the site’s preview.
            The client can still change it until the site is paid.
            {share.paid && ' The site has been paid, so the choice is final.'}
            {canEdit && onPayLink && !share.paid && (
              <div style={{ marginTop: 8 }}><Button variant="primary" onClick={() => onPayLink(share.site_id)}>Create payment link</Button></div>
            )}
          </div>
        </Notice>
      )}

      <SectionTitle title="Versions in this link"
        right={canEdit && live && <Button size="sm" icon={Plus} onClick={() => setAdding(true)}>Add a version</Button>} />
      {share.items.map((it) => (
        <Card key={it.id} pad={14}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: T.teal }}>{it.label}</div>
              <div style={{ fontSize: 12.5, color: T.soft, marginTop: 2 }}>{it.created_at ? `Saved ${dateOnly(it.created_at)}` : ''}</div>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {it.chosen && <Badge tone="good">Picked</Badge>}
              {it.is_current && <Badge tone="info">Showing now</Badge>}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
            {live && <Button size="sm" icon={ExternalLink} onClick={() => window.open(it.preview_url, '_blank', 'noopener')}>Open version</Button>}
            {canEdit && live && !it.chosen && <Button size="sm" onClick={() => setConfirm({ kind: 'choose', item: it })}>Client picked this</Button>}
            {canEdit && live && !it.chosen && share.items.length > 1 && (
              <Button size="sm" variant="danger" icon={Trash2} onClick={() => setConfirm({ kind: 'remove', item: it })}>Remove</Button>
            )}
          </div>
        </Card>
      ))}

      {canEdit && live && <div><Button variant="danger" onClick={() => setConfirm({ kind: 'close' })}>Close this link</Button></div>}

      <AddVersionModal open={adding} onClose={() => setAdding(false)} api={api} errorMessage={errorMessage} share={share}
        onAdd={async (designId) => { if (await run('add', () => api.add(share.id, designId), 'Version added')) setAdding(false) }} />

      <Modal open={!!confirm} onClose={() => setConfirm(null)} width={460}
        title={confirm?.kind === 'choose' ? 'Record the client’s choice' : confirm?.kind === 'remove' ? 'Remove this version?' : 'Close this link?'}
        footer={(
          <>
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            {confirm?.kind === 'choose' && <Button variant="primary" loading={busy === 'choose'} onClick={() => run('choose', () => api.choose(share.id, confirm.item.id), 'Choice saved')}>Yes, they picked it</Button>}
            {confirm?.kind === 'remove' && <Button variant="danger" loading={busy === 'remove'} onClick={() => run('remove', () => api.remove(share.id, confirm.item.id), 'Version removed')}>Remove</Button>}
            {confirm?.kind === 'close' && <Button variant="danger" loading={busy === 'close'} onClick={() => run('close', () => api.close(share.id), 'Link closed')}>Close link</Button>}
          </>
        )}>
        <p style={{ margin: 0, fontSize: 13.5, color: T.soft, lineHeight: 1.5 }}>
          {confirm?.kind === 'choose' && `Use this when the client told you their choice another way. “${confirm.item.label}” becomes the site’s preview straight away. It can still be changed until the site is paid.`}
          {confirm?.kind === 'remove' && `“${confirm?.item?.label}” is taken off this link. The version itself is kept on the site.`}
          {confirm?.kind === 'close' && 'The client link stops working. The site keeps whichever version is showing now. Your versions are not deleted.'}
        </p>
      </Modal>
    </div>
  )
}

// ── pickers ──────────────────────────────────────────────────────────────────────────

function VersionRow({ v, children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44, padding: '6px 0', borderBottom: `1px solid ${T.line}` }}>
      {children}
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, color: T.ink, fontSize: 13.5 }}>{versionLine({ ...v, label: '' })}</div>
        <div style={{ fontSize: 12, color: T.muted }}>{[v.label, v.is_current ? 'showing now' : null].filter(Boolean).join(' · ')}</div>
      </div>
    </div>
  )
}

function CreateModal({ open, onClose, api, errorMessage, onCreated }) {
  const [sites, setSites] = useState(null)
  const [siteId, setSiteId] = useState('')
  const [versions, setVersions] = useState(null)
  const [picked, setPicked] = useState([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setSites(null); setSiteId(''); setVersions(null); setPicked([]); setName(''); setError('')
    api.sites().then((rows) => { setSites(rows); if (rows.length === 1) setSiteId(rows[0].site_id) })
      .catch((e) => { setSites([]); setError(errorMessage(e, 'Could not load your Premium sites.')) })
  }, [open, api, errorMessage])

  useEffect(() => {
    if (!siteId) { setVersions(null); return }
    setVersions(null); setPicked([])
    api.versions(siteId)
      .then((rows) => { setVersions(rows); setPicked(rows.slice(0, 3).map((r) => r.id)) })
      .catch((e) => { setVersions([]); setError(errorMessage(e, 'Could not load the versions.')) })
  }, [siteId, api, errorMessage])

  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  async function create() {
    setBusy(true); setError('')
    try { onCreated(await api.create({ site_id: siteId, client_name: name.trim() || undefined, design_ids: picked })) }
    catch (e) { setError(errorMessage(e, 'Could not create the link.')) }
    finally { setBusy(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title="Share versions of a site" width={520}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!siteId || picked.length === 0} onClick={create}>Create link</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {sites === null && <Spinner />}
        {sites && sites.length === 0 && !error && (
          <Notice tone="info">No Premium sites with two or more saved versions yet. Make another design of a Premium site, then come back.</Notice>
        )}
        {sites && sites.length > 0 && (
          <Field label="Which site?">
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)} style={INPUT}>
              <option value="">Choose a site…</option>
              {sites.map((s) => <option key={s.site_id} value={s.site_id}>{s.business_name || 'Untitled site'} ({s.versions} versions)</option>)}
            </select>
          </Field>
        )}
        {siteId && (
          <Field label="Versions to show your client" hint="Tick the ones to include." group>
            {versions === null && <Spinner />}
            <div style={{ maxHeight: 240, overflowY: 'auto' }}>
              {versions && versions.map((v) => (
                <VersionRow key={v.id} v={v}>
                  <input type="checkbox" checked={picked.includes(v.id)} onChange={() => toggle(v.id)}
                    aria-label={`Include version ${v.version}`} style={{ width: 20, height: 20 }} />
                </VersionRow>
              ))}
            </div>
          </Field>
        )}
        {siteId && (
          <Field label="Client name (only you see this)" hint="Optional. For example “Mrs Obi”.">
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} style={INPUT} />
          </Field>
        )}
        {error && <Notice tone="bad">{error}</Notice>}
      </div>
    </Modal>
  )
}

function AddVersionModal({ open, onClose, api, errorMessage, share, onAdd }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState('')
  useEffect(() => {
    if (!open) return
    setRows(null); setErr(''); setBusyId('')
    api.versions(share.site_id).then(setRows).catch((e) => { setRows([]); setErr(errorMessage(e, 'Could not load the versions.')) })
  }, [open, api, errorMessage, share.site_id])
  const inShare = new Set((share.items || []).map((i) => i.design_id))
  const free = (rows || []).filter((v) => !inShare.has(v.id))
  return (
    <Modal open={open} onClose={onClose} title="Add a version" width={520} footer={<Button onClick={onClose}>Close</Button>}>
      {rows === null && <Spinner />}
      {err && <Notice tone="bad">{err}</Notice>}
      {rows && free.length === 0 && !err && <p style={{ margin: 0, fontSize: 13, color: T.muted }}>Every saved version is already in this link.</p>}
      {free.map((v) => (
        <VersionRow key={v.id} v={v}>
          <Button size="sm" loading={busyId === v.id} onClick={async () => { setBusyId(v.id); await onAdd(v.id); setBusyId('') }}>Add</Button>
        </VersionRow>
      ))}
    </Modal>
  )
}
