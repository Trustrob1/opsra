/**
 * frontend/src/modules/sites/ImportPanel.jsx
 * SITE-IMPORT 1b - the staff Import panel on a site: upload a finished single-page site made outside Opsra (.zip or one
 * .html), read the safety report, accept named overridable findings, copy pictures/stylesheets/fonts the page loads
 * from unlisted websites, preview it in a sandbox, and make it the site's page.
 *
 * Backend: routers/sites.py /sites/{id}/import/* (switched on per account by site_builder_settings.site_import_enabled;
 * when it is off the API answers 403 and this panel renders nothing). Making a design the page changes the preview only;
 * publishing to the client's domain stays the separate "Publish to Cloudflare" step.
 *
 * SITE-IMPORT 2: "Make editable" asks Claude to map the page onto the editor's fields (a plan, never page code). It runs in a
 * worker (a few minutes), so the panel polls while a design is running. An editable design can take the page's own text as the
 * site's content when it is used; on failure the design simply stays a plain import.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { UploadCloud, Eye, Copy, CheckCircle2, Undo2, ShieldCheck, Wand2 } from 'lucide-react'
import {
  getImportDesigns, importSiteFile, previewImportDesign, resolveImportDesign, activateImportDesign, makeImportEditable, premiumBackToStandard, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, SectionTitle, Modal, Segmented } from './sitesUi'
import { T, dateTime } from './sitesKit'

const who = (by) => (String(by || '').startsWith('user:') ? 'Staff' : 'System')

export default function ImportPanel({ siteId, canEdit, showToast, onSiteChanged }) {
  const [data, setData] = useState(null)           // { tier, current_design_id, designs }
  const [hidden, setHidden] = useState(false)      // import is not switched on for this account
  const [error, setError] = useState(null)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(null)           // 'check' | 'import' | design id | 'standard'
  const [result, setResult] = useState(null)       // { saved, report, errors, message }
  const [accepted, setAccepted] = useState({})     // { file: [rule, ...] }
  const [preview, setPreview] = useState(null)     // { version, html }
  const [width, setWidth] = useState('desktop')
  const [adopt, setAdopt] = useState({})           // design id -> use the page's own text as the site's content (default yes)
  const input = useRef(null)

  const load = useCallback(async () => {
    try {
      const d = await getImportDesigns(siteId)
      setData(d)
      setError(null)
    } catch (e) {
      if (e?.response?.status === 403 || e?.response?.status === 404) setHidden(true)
      else setError(errorMessage(e, 'Could not load the imported designs.'))
    }
  }, [siteId])

  useEffect(() => { load() }, [load])

  const working = (data?.designs || []).some((d) => ['running', 'working'].includes(d.level2?.status))
  useEffect(() => {
    if (!working) return undefined
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [working, load])
  if (hidden) return null

  const designs = data?.designs || []
  const isImported = data?.tier === 'imported'

  const toggleAccept = (f) => {
    setAccepted((prev) => {
      const list = new Set(prev[f.file.split(' (')[0]] || [])
      if (list.has(f.rule)) list.delete(f.rule); else list.add(f.rule)
      return { ...prev, [f.file.split(' (')[0]]: [...list] }
    })
  }
  const isAccepted = (f) => (accepted[f.file.split(' (')[0]] || []).includes(f.rule)

  const send = async (dry) => {
    if (!file) return
    setBusy(dry ? 'check' : 'import')
    try {
      const clean = Object.fromEntries(Object.entries(accepted).filter(([, v]) => v.length))
      const r = await importSiteFile(siteId, file, { dryRun: dry, accepted: clean })
      setResult({ saved: !!r.saved, report: r.report, errors: [], message: dry ? 'Checked only: nothing was saved.' : 'Import saved. Review it below, then use it.' })
      if (!dry) { setFile(null); setAccepted({}); if (input.current) input.current.value = ''; await load() }
    } catch (e) {
      const d = e?.response?.data?.detail
      if (e?.response?.status === 422 && d?.report) setResult({ saved: false, report: d.report, errors: d.errors || [], message: d.message })
      else if (e?.response?.status === 422 && d?.errors) setResult({ saved: false, report: null, errors: d.errors, message: d.message })
      else showToast(errorMessage(e, 'The upload failed.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const openPreview = async (d) => {
    setBusy(d.id)
    try {
      const r = await previewImportDesign(siteId, d.id)
      setWidth('desktop')
      setPreview({ version: d.version, html: r.html })
    } catch (e) {
      showToast(errorMessage(e, 'Could not open the preview.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const copyExternal = async (d) => {
    setBusy(d.id)
    try {
      const r = await resolveImportDesign(siteId, d.id)
      const failed = (r.failed || []).length
      showToast(`${(r.resolved || []).length} file(s) copied${failed ? `, ${failed} could not be: ${r.failed[0].url} (${r.failed[0].reason})` : ''}`, failed ? 'bad' : undefined)
      await load()
    } catch (e) {
      showToast(errorMessage(e, 'Could not copy the files.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const makeEditable = async (d) => {
    setBusy(d.id)
    try {
      await makeImportEditable(siteId, d.id)
      showToast('Making the page editable. This takes a few minutes; you can leave this screen.')
      await load()
    } catch (e) {
      showToast(errorMessage(e, 'Could not start.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const use = async (d) => {
    setBusy(d.id)
    try {
      await activateImportDesign(siteId, d.id, d.editable && adopt[d.id] !== false)
      showToast(`Version ${d.version} is now this site's page`)
      await load()
      onSiteChanged?.()
    } catch (e) {
      showToast(errorMessage(e, 'Could not switch the design.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const backToStandard = async () => {
    setBusy('standard')
    try {
      await premiumBackToStandard(siteId)
      showToast('Back on the Standard design — imported versions are kept')
      await load()
      onSiteChanged?.()
    } catch (e) {
      showToast(errorMessage(e, 'Could not switch back.'), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const findings = result?.report ? [...(result.report.errors || []), ...(result.report.warnings || [])] : []
  const blockers = (result?.report?.errors || [])

  return (
    <Card>
      <SectionTitle
        title="Import a finished site"
        hint="Upload a single-page site made outside Opsra (a .zip with index.html at the top, or one .html file). It is checked and cleaned first. Scripts run only on the client's own domain."
        right={<Badge tone={isImported ? 'good' : 'neutral'}>{isImported ? 'Imported page in use' : 'Not in use'}</Badge>}
      />
      {error && <Notice tone="bad">{error}</Notice>}

      {canEdit && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
          <input ref={input} type="file" accept=".zip,.html,.htm" onChange={(e) => { setFile(e.target.files?.[0] || null); setResult(null) }} />
          <Button variant="secondary" icon={ShieldCheck} loading={busy === 'check'} disabled={!file || !!busy} onClick={() => send(true)}>Check only</Button>
          <Button variant="primary" icon={UploadCloud} loading={busy === 'import'} disabled={!file || !!busy} onClick={() => send(false)}>Import</Button>
          {isImported && (
            <Button variant="secondary" icon={Undo2} loading={busy === 'standard'} disabled={!!busy} onClick={backToStandard}
              title="Show the Standard design again. Imported versions are kept.">Back to Standard</Button>
          )}
        </div>
      )}

      {result && (
        <div style={{ border: `1px solid ${result.errors?.length || blockers.length ? T.bad : T.line}`, borderRadius: 10, padding: '10px 12px', marginBottom: 12 }}>
          <p style={{ margin: '0 0 6px', fontSize: 13, color: T.ink }}><strong>{result.message}</strong></p>
          {(result.errors || []).length > 0 && (
            <ul style={{ margin: '0 0 6px 18px', padding: 0, fontSize: 12.5, color: T.bad }}>
              {result.errors.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
          )}
          {result.report && (
            <p style={{ margin: '0 0 6px', fontSize: 12, color: T.muted }}>
              {result.report.counts?.files} files · {(result.report.scripts || []).length + (result.report.page?.inline_scripts || 0)} script(s)
              {(result.report.external?.unknown || []).length ? ` · ${(result.report.external.unknown).length} file(s) loaded from other websites (can be copied after import)` : ''}
              {(result.report.missing_files || []).length ? ` · missing: ${result.report.missing_files.slice(0, 3).join(', ')}` : ''}
            </p>
          )}
          {findings.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {findings.map((f, i) => (
                <div key={i} style={{ fontSize: 12.5, display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <Badge tone={f.severity === 'error' && !f.accepted ? 'bad' : 'warn'}>{f.accepted ? 'accepted' : f.severity}</Badge>
                  <span style={{ color: T.ink }}>{f.file}{f.line ? `:${f.line}` : ''} — {f.message}</span>
                  {f.severity === 'error' && f.overridable && canEdit && (
                    <label style={{ fontSize: 12, color: T.muted }}>
                      <input type="checkbox" checked={isAccepted(f)} onChange={() => toggleAccept(f)} /> Accept this for {f.file.split(' (')[0]}
                    </label>
                  )}
                  {f.severity === 'error' && !f.overridable && <span style={{ fontSize: 12, color: T.muted }}>cannot be accepted</span>}
                </div>
              ))}
              {blockers.some((f) => f.overridable) && <p style={{ margin: '4px 0 0', fontSize: 12, color: T.muted }}>Tick what you accept, then press Import again.</p>}
            </div>
          )}
        </div>
      )}

      {designs.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {designs.map((d) => (
            <div key={d.id} style={{ border: `1px solid ${d.active ? T.teal : T.line}`, borderRadius: 10, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 13.5, color: T.ink }}>Import {d.version}</strong>
              {d.active && <Badge tone="good">In use</Badge>}
              {d.staged && !d.active && <Badge tone="neutral">Not used yet</Badge>}
              {d.editable && <Badge tone="good">Editable</Badge>}
              {['running', 'working'].includes(d.level2?.status) && <Badge tone="warn">Making editable…</Badge>}
              {d.level2?.status === 'failed' && !d.editable && <Badge tone="warn">Stays a plain import</Badge>}
              <span style={{ fontSize: 12, color: T.muted }}>
                {dateTime(d.created_at)} · {who(d.created_by)} · {d.filename || 'upload'} · {d.counts?.files ?? '?'} files · {d.scripts} script(s)
                {d.warnings ? ` · ${d.warnings} warning(s)` : ''}
                {d.missing_files ? ` · ${d.missing_files} missing file(s)` : ''}
              </span>
              <span style={{ flex: 1 }} />
              <Button size="sm" variant="secondary" icon={Eye} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => openPreview(d)}>Preview</Button>
              {canEdit && d.external_unknown > 0 && (
                <Button size="sm" variant="secondary" icon={Copy} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => copyExternal(d)}
                  title="Download the pictures, styles and fonts this page loads from other websites and keep them with the site.">
                  Copy {d.external_unknown} outside file(s)
                </Button>
              )}
              {canEdit && !d.editable && !['running', 'working'].includes(d.level2?.status) && (
                <Button size="sm" variant="secondary" icon={Wand2} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => makeEditable(d)}
                  title="Claude maps this page onto the editor's fields so the text, prices, photos and contact links can be edited here and by WhatsApp EDIT. The page's code is never changed. Takes a few minutes.">
                  {d.level2?.status === 'failed' ? 'Try again' : 'Make editable'}
                </Button>
              )}
              {canEdit && d.editable && !d.active && (
                <label style={{ fontSize: 12, color: T.muted }} title="Replaces this site's text with what the page says. The old text stays available through Undo.">
                  <input type="checkbox" checked={adopt[d.id] !== false} onChange={(e) => setAdopt((p) => ({ ...p, [d.id]: e.target.checked }))} /> Use the page's own text
                </label>
              )}
              {canEdit && !d.active && (
                <Button size="sm" variant="primary" icon={CheckCircle2} loading={busy === d.id} disabled={!!busy && busy !== d.id} onClick={() => use(d)}>Use this design</Button>
              )}
              {d.level2?.status === 'failed' && !d.editable && (d.level2.errors || []).length > 0 && (
                <div style={{ flexBasis: '100%', fontSize: 12, color: T.muted }}>
                  Could not make it editable: {(d.level2.errors || []).slice(0, 3).join(' · ')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {isImported && (
        <Notice tone="info" style={{ marginTop: 12 }}>
          {designs.some((d) => d.active && d.editable)
            ? 'This site shows an editable imported page. The text, prices, photos and contact links you edit appear on it; everything else on the page stays as it was uploaded.'
            : 'This site now shows the imported page. The content fields below do not change it. Press Make editable on a version, or import a new version, to change the page.'}
        </Notice>
      )}

      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview ? `Imported page · version ${preview.version}` : 'Preview'} width={1040}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Segmented ariaLabel="Preview width" value={width} onChange={setWidth}
            options={[{ value: 'desktop', label: 'Desktop' }, { value: 'phone', label: 'Phone' }]} />
          <div style={{ display: 'flex', justifyContent: 'center', background: '#F1F6F8', borderRadius: 10, padding: width === 'phone' ? 12 : 0 }}>
            {preview && (
              <iframe title="Imported page preview" srcDoc={preview.html} sandbox="allow-scripts allow-popups"
                style={{ width: width === 'phone' ? 390 : '100%', maxWidth: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8, background: '#fff' }} />
            )}
          </div>
        </div>
      </Modal>
    </Card>
  )
}
