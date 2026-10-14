/**
 * frontend/src/modules/sites/OptionSetsPanel.jsx
 * SITE-OPTIONS OPT-2 - "Design options": show one client several designs behind ONE link and see which they pick.
 * One component, used in the builder portal and in the staff Sites area. It talks to the server only through the
 * `api` adapter it is given, so the builder token and the staff session never mix.
 *
 *   api        { list, eligible, create, get, attach, detach, choose, close }  (each returns the payload)
 *   errorMessage(err, fallback)
 *   canEdit    false = read only (staff roles that cannot write)
 *   builderId  staff only: the builder the new sets are for (create is off without it)
 *   builderNames { [id]: label } staff only: shown on each row when listing every builder
 *   onPayLink(siteId)  builder only: go to checkout for the picked design
 *   onNewDesign(setId) builder only: start a new site that will join this set
 *   reloadKey  change it to make the panel reload (for example after a new design was made)
 *   showToast(text, tone)
 */
import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronLeft, Copy, ExternalLink, Layers, Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Card, Empty, Field, Modal, Notice, SectionTitle, Spinner } from './sitesUi'
import { INPUT, T, dateOnly } from './sitesKit'
import { copyText } from './siteAddonsKit'

const SET_STATUS = {
  open: ['info', 'Waiting for the client'],
  chosen: ['good', 'Client picked one'],
  closed: ['neutral', 'Closed'],
  expired: ['warn', 'Expired'],
}
const ITEM_STATUS = {
  offered: ['neutral', 'Offered'],
  chosen: ['good', 'Picked'],
  released: ['neutral', 'Not picked'],
}

function SetBadge({ status }) {
  const [tone, text] = SET_STATUS[status] || ['neutral', status || '—']
  return <Badge tone={tone}>{text}</Badge>
}

export default function OptionSetsPanel({
  api, errorMessage, canEdit = true, builderId, builderNames, onPayLink, onNewDesign, reloadKey, showToast,
}) {
  const [sets, setSets] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [openId, setOpenId] = useState(null)
  const [creating, setCreating] = useState(false)

  const loadList = useCallback(async () => {
    setLoadError('')
    try { setSets(await api.list()) } catch (e) { setSets([]); setLoadError(errorMessage(e, 'Could not load your design options.')) }
  }, [api, errorMessage])
  useEffect(() => { setSets(null); loadList() }, [loadList, reloadKey])

  if (openId) {
    return (
      <SetDetail key={openId} setId={openId} api={api} errorMessage={errorMessage} canEdit={canEdit}
        onPayLink={onPayLink} onNewDesign={onNewDesign} reloadKey={reloadKey} showToast={showToast}
        onBack={() => { setOpenId(null); loadList() }} />
    )
  }

  const needBuilder = builderId === ''   // staff view with "all builders" selected
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle title="Design options"
        hint="Make several designs for one client, send one link, and see which one they choose. Nothing is final until the chosen site is paid."
        right={canEdit && (
          <Button variant="primary" icon={Plus} disabled={needBuilder} onClick={() => setCreating(true)}
            title={needBuilder ? 'Pick a builder first' : undefined}>New option set</Button>
        )} />
      {needBuilder && canEdit && <Notice tone="info">Pick a builder above to make a new set for them.</Notice>}
      {loadError && <Notice tone="bad">{loadError}</Notice>}
      {sets === null && <Spinner />}
      {sets && sets.length === 0 && !loadError && (
        <Card><Empty icon={Layers} title="No option sets yet"
          text="An option set lets your client compare up to a few designs on one page and choose the one they like." /></Card>
      )}
      {sets && sets.map((s) => (
        <Card key={s.id} pad={14} style={{ cursor: 'pointer' }} onClick={() => setOpenId(s.id)}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700, color: T.ink, fontSize: 14 }}>{s.client_name || 'Unnamed client'}</div>
              <div style={{ fontSize: 12.5, color: T.muted, marginTop: 2 }}>
                {s.options} {s.options === 1 ? 'design' : 'designs'}
                {builderNames && builderNames[s.builder_id] ? ` · ${builderNames[s.builder_id]}` : ''}
                {s.expires_at ? ` · link until ${dateOnly(s.expires_at)}` : ''}
              </div>
            </div>
            <SetBadge status={s.status} />
          </div>
        </Card>
      ))}

      <CreateSetModal open={creating} onClose={() => setCreating(false)} api={api} errorMessage={errorMessage}
        onCreated={(set) => { setCreating(false); setOpenId(set.id); showToast?.('Option set created') }} />
    </div>
  )
}

// ── one set ──────────────────────────────────────────────────────────────────────────

function SetDetail({ setId, api, errorMessage, canEdit, onPayLink, onNewDesign, reloadKey, showToast, onBack }) {
  const [set, setSet] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [copied, setCopied] = useState(false)
  const [adding, setAdding] = useState(false)
  const [confirm, setConfirm] = useState(null)   // {kind:'choose'|'remove'|'close', item?}

  const load = useCallback(async () => {
    try { setSet(await api.get(setId)); setError('') } catch (e) { setError(errorMessage(e, 'Could not load this set.')) }
  }, [api, setId, errorMessage])
  useEffect(() => { load() }, [load, reloadKey])

  async function run(key, fn, okText) {
    setBusy(key); setError('')
    try {
      const res = await fn()
      if (res && res.set) setSet(res.set); else if (res && res.items) setSet(res); else await load()
      if (okText) showToast?.(okText)
      return true
    } catch (e) {
      setError(errorMessage(e, 'That did not work. Please try again.'))
      return false
    } finally { setBusy(''); setConfirm(null) }
  }

  async function copy() {
    const ok = await copyText(set.link)
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000) } else setError('Could not copy. Select the link and copy it by hand.')
  }

  const header = (
    <button type="button" onClick={onBack} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'none', border: 'none',
      color: T.teal, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: '6px 0', minHeight: 44, fontFamily: 'inherit', alignSelf: 'flex-start' }}>
      <ChevronLeft size={16} aria-hidden="true" /> All option sets
    </button>
  )
  if (!set) {
    return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>{header}{error ? <Notice tone="bad">{error}</Notice> : <Spinner />}</div>
  }

  const live = set.status === 'open' || set.status === 'chosen'
  const picked = (set.items || []).find((i) => i.status === 'chosen')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {header}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <h2 style={{ margin: 0, fontSize: 18, color: T.ink }}>{set.client_name || 'Unnamed client'}</h2>
        <SetBadge status={set.status} />
      </div>
      {error && <Notice tone="bad">{error}</Notice>}

      {live && (
        <Card pad={14}>
          <Field label="Send this link to your client" hint={set.expires_at ? `Works until ${dateOnly(set.expires_at)}.` : undefined}>
            <input readOnly value={set.link} onFocus={(e) => e.target.select()} style={INPUT} aria-label="Option link" />
          </Field>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
            <Button variant="primary" icon={copied ? Check : Copy} onClick={copy}>{copied ? 'Copied' : 'Copy link'}</Button>
            <Button icon={ExternalLink} onClick={() => window.open(set.link, '_blank', 'noopener')}>See what the client sees</Button>
          </div>
        </Card>
      )}

      {set.status === 'chosen' && picked && (
        <Notice tone="good">
          <div>
            <strong>{picked.label}</strong> ({picked.business_name || 'site'}) was picked
            {set.chosen_at ? ` on ${dateOnly(set.chosen_at)}` : ''}. The client can still change it until the site is paid.
            {set.release_after ? ` The other designs are kept until ${dateOnly(set.release_after)}.` : ''}
            {canEdit && onPayLink && (
              <div style={{ marginTop: 8 }}><Button variant="primary" onClick={() => onPayLink(picked.site_id)}>Create payment link</Button></div>
            )}
          </div>
        </Notice>
      )}

      <SectionTitle title="Designs in this set"
        right={canEdit && live && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button size="sm" icon={Plus} onClick={() => setAdding(true)}>Add an existing site</Button>
            {onNewDesign && <Button size="sm" icon={Plus} onClick={() => onNewDesign(set.id)}>Make a new design</Button>}
          </div>
        )} />
      {(set.items || []).length === 0 && (
        <Card><Empty icon={Layers} title="No designs yet" text="Add a site you have already made, or make a new design for this set." /></Card>
      )}
      {(set.items || []).map((it) => {
        const [tone, text] = ITEM_STATUS[it.status] || ['neutral', it.status]
        return (
          <Card key={it.id} pad={14}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: T.teal }}>{it.label}</div>
                <div style={{ fontWeight: 700, color: T.ink, margin: '2px 0', wordBreak: 'break-word' }}>{it.business_name || 'Untitled site'}</div>
                {it.headline && <div style={{ fontSize: 12.5, color: T.soft, wordBreak: 'break-word' }}>{it.headline}</div>}
              </div>
              <Badge tone={tone}>{text}</Badge>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
              {it.preview_url && <Button size="sm" icon={ExternalLink} onClick={() => window.open(it.preview_url, '_blank', 'noopener')}>Open design</Button>}
              {canEdit && live && it.status !== 'chosen' && (
                <Button size="sm" onClick={() => setConfirm({ kind: 'choose', item: it })}>Client picked this</Button>
              )}
              {canEdit && live && it.status !== 'chosen' && (
                <Button size="sm" variant="danger" icon={Trash2} onClick={() => setConfirm({ kind: 'remove', item: it })}>Remove</Button>
              )}
            </div>
          </Card>
        )
      })}

      {canEdit && live && (
        <div><Button variant="danger" onClick={() => setConfirm({ kind: 'close' })}>Close this set</Button></div>
      )}

      <AddSiteModal open={adding} onClose={() => setAdding(false)} api={api} errorMessage={errorMessage}
        onAdd={async (siteId) => { if (await run('add', () => api.attach(set.id, siteId), 'Design added')) setAdding(false) }} />

      <Modal open={!!confirm} onClose={() => setConfirm(null)} width={460}
        title={confirm?.kind === 'choose' ? 'Record the client’s choice' : confirm?.kind === 'remove' ? 'Remove this design?' : 'Close this set?'}
        footer={(
          <>
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            {confirm?.kind === 'choose' && <Button variant="primary" loading={busy === 'choose'} onClick={() => run('choose', () => api.choose(set.id, confirm.item.id), 'Choice saved')}>Yes, they picked it</Button>}
            {confirm?.kind === 'remove' && <Button variant="danger" loading={busy === 'remove'} onClick={() => run('remove', () => api.detach(set.id, confirm.item.site_id), 'Design removed')}>Remove</Button>}
            {confirm?.kind === 'close' && <Button variant="danger" loading={busy === 'close'} onClick={() => run('close', () => api.close(set.id), 'Set closed')}>Close set</Button>}
          </>
        )}>
        <p style={{ margin: 0, fontSize: 13.5, color: T.soft, lineHeight: 1.5 }}>
          {confirm?.kind === 'choose' && `Use this when the client told you their choice another way. “${confirm.item.label}” will be marked as picked and the others set aside for now. It can still be changed until the site is paid.`}
          {confirm?.kind === 'remove' && `“${confirm?.item?.label}” leaves this set and goes back to being a normal site in My sites. The client link will no longer show it.`}
          {confirm?.kind === 'close' && 'The client link stops working and the designs go back to being normal sites. Use this if the client will not be choosing.'}
        </p>
      </Modal>
    </div>
  )
}

// ── pickers ──────────────────────────────────────────────────────────────────────────

function useEligible(open, api, errorMessage) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!open) return
    setRows(null); setErr('')
    api.eligible().then(setRows).catch((e) => { setRows([]); setErr(errorMessage(e, 'Could not load your sites.')) })
  }, [open, api, errorMessage])
  return [rows, err]
}

function SiteLine({ s, children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44, padding: '6px 0', borderBottom: `1px solid ${T.line}` }}>
      {children}
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, color: T.ink, fontSize: 13.5, wordBreak: 'break-word' }}>{s.business_name || 'Untitled site'}</div>
        <div style={{ fontSize: 12, color: T.muted }}>{String(s.status || '').replace(/_/g, ' ')}</div>
      </div>
    </div>
  )
}

function CreateSetModal({ open, onClose, api, errorMessage, onCreated }) {
  const [name, setName] = useState('')
  const [picked, setPicked] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [rows, loadErr] = useEligible(open, api, errorMessage)
  useEffect(() => { if (open) { setName(''); setPicked([]); setError('') } }, [open])

  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  async function create() {
    setBusy(true); setError('')
    try { onCreated(await api.create({ client_name: name.trim() || undefined, site_ids: picked })) }
    catch (e) { setError(errorMessage(e, 'Could not create the set.')) }
    finally { setBusy(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title="New option set" width={520}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={create}>Create set</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Client name (only you see this)" hint="For example “Mrs Obi, boutique”.">
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} style={INPUT} />
        </Field>
        <Field label="Sites to include (optional)" hint="You can also add them later, or make new designs for the set." group>
          {rows === null && <Spinner />}
          {rows && rows.length === 0 && !loadErr && <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No sites are free to add right now.</p>}
          <div style={{ maxHeight: 240, overflowY: 'auto' }}>
            {rows && rows.map((s) => (
              <SiteLine key={s.site_id} s={s}>
                <input type="checkbox" checked={picked.includes(s.site_id)} onChange={() => toggle(s.site_id)}
                  aria-label={`Include ${s.business_name || 'site'}`} style={{ width: 20, height: 20 }} />
              </SiteLine>
            ))}
          </div>
        </Field>
        {(error || loadErr) && <Notice tone="bad">{error || loadErr}</Notice>}
      </div>
    </Modal>
  )
}

function AddSiteModal({ open, onClose, api, errorMessage, onAdd }) {
  const [rows, loadErr] = useEligible(open, api, errorMessage)
  const [busyId, setBusyId] = useState('')
  useEffect(() => { if (open) setBusyId('') }, [open])
  return (
    <Modal open={open} onClose={onClose} title="Add an existing site" width={520} footer={<Button onClick={onClose}>Close</Button>}>
      {rows === null && <Spinner />}
      {loadErr && <Notice tone="bad">{loadErr}</Notice>}
      {rows && rows.length === 0 && !loadErr && (
        <p style={{ margin: 0, fontSize: 13, color: T.muted }}>No sites are free to add. Live sites, paid sites and sites already in a set cannot be added.</p>
      )}
      {rows && rows.map((s) => (
        <SiteLine key={s.site_id} s={s}>
          <Button size="sm" loading={busyId === s.site_id} onClick={async () => { setBusyId(s.site_id); await onAdd(s.site_id); setBusyId('') }}>Add</Button>
        </SiteLine>
      ))}
    </Modal>
  )
}
