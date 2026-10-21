/**
 * frontend/src/modules/sites/HostSitesView.jsx
 * HOST-1 - "Host a site" screen of the builder portal: drop a finished website (.zip with index.html, or one .html file),
 * see the safety check in plain words, preview it, and go live through the normal Checkout.
 *
 * Backend: routers/host_portal.py (/api/v1/builder/host/*). The page is shown in a sandboxed iframe (scripts on, no access to
 * the portal). Replacing the files of a paid or live site is saved for the Opsra team to publish (the server says so).
 * The session token stays in React state, as everywhere in the builder portal.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { UploadCloud, Eye, Link2, Rocket, FileArchive, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import { hostConfig, hostListSites, hostUploadSite, hostSitePreview, errorMessage } from '../../services/builder_portal.service'
import { Card, Button, Badge, Notice, Spinner, Modal, Segmented, Field } from './sitesUi'
import { T, INPUT, SITE_STATUS, dateTime } from './sitesKit'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const OK_EXT = ['.zip', '.html', '.htm']
const LIVE_LIKE = ['paid', 'publishing', 'live', 'renewal_due', 'lapsed']

const extOf = (n) => { const i = (n || '').lastIndexOf('.'); return i < 0 ? '' : n.slice(i).toLowerCase() }
const size = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`)
const nameFromFile = (n) => (n || '').replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim().slice(0, 120)

export default function HostSitesView({ token, showToast, onGoLive }) {
  const [cfg, setCfg] = useState(null)
  const [sites, setSites] = useState(null)
  const [error, setError] = useState(null)
  const [file, setFile] = useState(null)
  const [name, setName] = useState('')
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pct, setPct] = useState(null)
  const [fail, setFail] = useState(null)          // { message, errors[] }
  const [done, setDone] = useState(null)          // the successful upload result
  const [preview, setPreview] = useState(null)    // { name, html }
  const [width, setWidth] = useState('desktop')
  const [replaceFor, setReplaceFor] = useState(null)   // site being given new files
  const pick = useRef(null)
  const pickReplace = useRef(null)

  const load = useCallback(async () => {
    try {
      const c = await hostConfig(token)
      setCfg(c)
      if (c.enabled) setSites(await hostListSites(token)); else setSites([])
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load this page.'))
    }
  }, [token])
  useEffect(() => { load() }, [load])

  function choose(f) {
    setFail(null); setDone(null)
    if (!f) return
    if (!OK_EXT.includes(extOf(f.name))) { setFile(null); setFail({ message: 'Please choose a .zip (with index.html inside) or a single .html file.', errors: [] }); return }
    if (cfg && f.size > cfg.max_upload_mb * 1048576) { setFile(null); setFail({ message: `That file is ${size(f.size)}. The limit is ${cfg.max_upload_mb} MB.`, errors: [] }); return }
    setFile(f)
    setName((n) => n || nameFromFile(f.name))
  }

  async function send(f, { siteId } = {}) {
    setBusy(true); setPct(0); setFail(null); setDone(null)
    try {
      const r = await hostUploadSite(token, f, { name: siteId ? undefined : name.trim(), siteId, onProgress: setPct })
      setDone(r)
      setFile(null); setName(''); setReplaceFor(null)
      if (pick.current) pick.current.value = ''
      await load()
    } catch (e) {
      const d = e?.response?.data?.detail
      setFail({ message: d?.message || errorMessage(e, 'The upload did not work. Please try again.'), errors: Array.isArray(d?.errors) ? d.errors : [] })
    } finally {
      setBusy(false); setPct(null)
    }
  }

  async function openPreview(site) {
    try {
      const r = await hostSitePreview(token, site.id, site.design?.id)
      setWidth('desktop')
      setPreview({ name: site.client_business_name, html: r.html })
    } catch (e) {
      showToast(errorMessage(e, 'Could not open the preview.'), 'bad')
    }
  }

  async function copyLink(site) {
    const url = `${API}/s/${site.slug}`
    try { await navigator.clipboard.writeText(url); showToast('Preview link copied. Anyone with it can look at the site for 30 days.') }
    catch { window.prompt('Copy this preview link:', url) }
  }

  if (error) return <Notice tone="bad">{error}</Notice>
  if (!cfg || sites === null) return <Spinner />
  if (!cfg.enabled) {
    return (
      <Card>
        <h2 style={{ margin: '0 0 6px', fontSize: 18, color: T.ink }}>Host a site you built elsewhere</h2>
        <Notice tone="info">This isn’t open on your account yet. We’ll let you know as soon as it is.</Notice>
      </Card>
    )
  }

  const full = cfg.used >= cfg.max_sites
  let remembered = ''
  try { remembered = window.localStorage.getItem('opsra_host_domain') || '' } catch { /* storage blocked */ }
  const doneSite = done?.site
  const warnings = done?.report?.warnings || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card>
        <h2 style={{ margin: '0 0 4px', fontSize: 19, color: T.ink }}>Host a site you built elsewhere</h2>
        <p style={{ margin: '0 0 14px', fontSize: 14, color: T.soft }}>
          Drop in your finished website. We check it, show you a preview, and when you’re happy you pick a domain and pay to put it live.
          One page per site: a .zip with <b>index.html</b> at the top, or a single .html file.
        </p>

        <Notice tone="warn" style={{ marginBottom: 12 }}>
          <strong>Before you go live, make sure your domain name is free.</strong> You can upload and preview first, but you will need the
          exact domain at checkout. {remembered
            ? <>You checked <b>{remembered}</b> earlier. </>
            : null}
          <a href="/host#domain" target="_blank" rel="noopener noreferrer" style={{ color: T.teal, fontWeight: 700 }}>Check a domain</a>
        </Notice>

        {full && <Notice tone="warn">You have {cfg.used} hosted sites, which is the limit ({cfg.max_sites}). Please contact us to host more.</Notice>}

        {!full && (
          <>
            <div
              role="button" tabIndex={0} aria-label="Choose a website file to upload"
              onClick={() => !busy && pick.current?.click()}
              onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !busy) { e.preventDefault(); pick.current?.click() } }}
              onDragOver={(e) => { e.preventDefault(); setOver(true) }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); if (!busy) choose(e.dataTransfer.files?.[0]) }}
              style={{
                border: `2px dashed ${over ? T.teal : T.lineStrong}`, background: over ? T.infoBg : '#fff', borderRadius: 14,
                padding: '28px 16px', textAlign: 'center', cursor: busy ? 'default' : 'pointer', transition: 'all .15s',
              }}
            >
              {file ? (
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, color: T.ink }}>
                  <FileArchive size={22} color={T.teal} />
                  <strong style={{ fontSize: 15 }}>{file.name}</strong>
                  <span style={{ fontSize: 13, color: T.muted }}>{size(file.size)}</span>
                </div>
              ) : (
                <>
                  <UploadCloud size={34} color={T.teal} />
                  <p style={{ margin: '8px 0 2px', fontSize: 15, fontWeight: 700, color: T.ink }}>Drag your website here, or tap to choose it</p>
                  <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>.zip or .html · up to {cfg.max_upload_mb} MB · up to {cfg.limits.files} files</p>
                </>
              )}
              <input ref={pick} type="file" accept=".zip,.html,.htm" hidden onChange={(e) => choose(e.target.files?.[0])} />
            </div>

            {file && (
              <div style={{ marginTop: 12, display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div style={{ flex: '1 1 240px' }}>
                  <Field label="Site name" hint="Usually your client’s business name. You can use it to tell sites apart.">
                    <input style={INPUT} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="e.g. Adaeze Styles" />
                  </Field>
                </div>
                <Button variant="primary" icon={UploadCloud} loading={busy} onClick={() => send(file)}>
                  {busy ? (pct != null ? `Uploading ${pct}%` : 'Checking…') : 'Upload and check'}
                </Button>
                {!busy && <Button variant="secondary" onClick={() => { setFile(null); setName(''); setFail(null); if (pick.current) pick.current.value = '' }}>Clear</Button>}
              </div>
            )}
          </>
        )}

        {fail && (
          <div style={{ marginTop: 12 }}>
            <Notice tone="bad" icon={AlertTriangle}>
              <strong>{fail.message}</strong>
              {fail.errors.length > 0 && (
                <ul style={{ margin: '6px 0 0 18px', padding: 0 }}>
                  {fail.errors.map((m, i) => <li key={i} style={{ fontSize: 13 }}>{m}</li>)}
                </ul>
              )}
              {fail.errors.length > 0 && <p style={{ margin: '8px 0 0', fontSize: 12.5 }}>Fix these in your files and upload again. Nothing was saved.</p>}
            </Notice>
          </div>
        )}

        {doneSite && (
          <div style={{ marginTop: 12 }}>
            <Notice tone="good" icon={CheckCircle2}>
              <strong>{done.message}</strong>
              <div style={{ fontSize: 13, marginTop: 4 }}>
                {doneSite.client_business_name} · {done.files} files{warnings.length ? ` · ${warnings.length} note${warnings.length === 1 ? '' : 's'} below` : ' · nothing to fix'}
              </div>
              {warnings.length > 0 && (
                <ul style={{ margin: '6px 0 0 18px', padding: 0 }}>
                  {warnings.slice(0, 8).map((w, i) => <li key={i} style={{ fontSize: 12.5 }}>{w.file}{w.line ? `:${w.line}` : ''} — {w.message}</li>)}
                  {warnings.length > 8 && <li style={{ fontSize: 12.5 }}>and {warnings.length - 8} more</li>}
                </ul>
              )}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <Button size="sm" variant="secondary" icon={Eye} onClick={() => openPreview(doneSite)}>Preview</Button>
                {done.switched_on && !LIVE_LIKE.includes(doneSite.status) && <Button size="sm" variant="primary" icon={Rocket} onClick={() => onGoLive(doneSite.id)}>Go live</Button>}
              </div>
            </Notice>
          </div>
        )}
      </Card>

      {sites.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <p style={{ margin: '4px 0 0', fontSize: 13, fontWeight: 700, color: T.ink }}>Your hosted sites ({cfg.used} of {cfg.max_sites})</p>
          {sites.map((s) => {
            const st = SITE_STATUS[s.status] || { tone: 'neutral', label: s.status }
            const live = LIVE_LIKE.includes(s.status)
            const d = s.design
            return (
              <Card key={s.id} pad={14}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: 15, color: T.ink }}>{s.client_business_name}</strong>
                  <Badge tone={st.tone}>{st.label}</Badge>
                  <span style={{ flex: 1 }} />
                  {s.live_url && <a href={s.live_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13, color: T.teal, fontWeight: 600 }}>{s.live_url.replace(/^https?:\/\//, '')}</a>}
                </div>
                <p style={{ margin: '4px 0 10px', fontSize: 12.5, color: T.muted }}>
                  {d ? `Version ${d.version} · ${d.filename || 'upload'} · ${d.files ?? '?'} files · ${dateTime(d.created_at)}${d.staged && !d.active ? ' · waiting for our team to publish' : ''}` : 'No files uploaded yet'}
                </p>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {d && <Button size="sm" variant="secondary" icon={Eye} onClick={() => openPreview(s)}>Preview</Button>}
                  {s.has_preview_link && !live && <Button size="sm" variant="secondary" icon={Link2} onClick={() => copyLink(s)}>Copy preview link</Button>}
                  <Button size="sm" variant="secondary" icon={RefreshCw} disabled={busy} onClick={() => { setReplaceFor(s); pickReplace.current?.click() }}>Replace files</Button>
                  {d && !live && <Button size="sm" variant="primary" icon={Rocket} onClick={() => onGoLive(s.id)}>Go live</Button>}
                </div>
              </Card>
            )
          })}
        </div>
      )}
      <input ref={pickReplace} type="file" accept=".zip,.html,.htm" hidden
        onChange={(e) => {
          const f = e.target.files?.[0]; e.target.value = ''
          if (!f || !replaceFor) return
          if (!OK_EXT.includes(extOf(f.name))) { setFail({ message: 'Please choose a .zip (with index.html inside) or a single .html file.', errors: [] }); return }
          send(f, { siteId: replaceFor.id })
        }} />

      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview ? `Preview · ${preview.name}` : 'Preview'} width={1040}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Segmented ariaLabel="Preview width" value={width} onChange={setWidth}
            options={[{ value: 'desktop', label: 'Desktop' }, { value: 'phone', label: 'Phone' }]} />
          <div style={{ display: 'flex', justifyContent: 'center', background: '#F1F6F8', borderRadius: 10, padding: width === 'phone' ? 12 : 0 }}>
            {preview && (
              <iframe title="Site preview" srcDoc={preview.html} sandbox="allow-scripts allow-popups"
                style={{ width: width === 'phone' ? 390 : '100%', maxWidth: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8, background: '#fff' }} />
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}
