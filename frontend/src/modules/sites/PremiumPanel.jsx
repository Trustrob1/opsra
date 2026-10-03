/**
 * frontend/src/modules/sites/PremiumPanel.jsx
 * SITE-PREMIUM P2b — the staff Premium panel on a site: "Design with Claude", the design history (status, cost,
 * time, why a design failed), a preview of any finished version, switch to an older version, back to Standard.
 *
 * Backend: routers/sites.py /sites/{id}/premium/* (switched on per org by site_builder_settings.premium_enabled;
 * when it is off the API answers 403 and this panel renders nothing). A finished design becomes the site's preview
 * straight away (the job re-renders it); publishing to Cloudflare stays a separate, deliberate step.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Sparkles, Eye, Undo2, RefreshCw } from 'lucide-react'
import {
  getPremiumDesigns, generatePremiumDesign, previewPremiumDesign, switchPremiumDesign, premiumBackToStandard, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, SectionTitle, Modal, Segmented } from './sitesUi'
import { T, dateTime } from './sitesKit'

const POLL_MS = 5000
const ACTIVE = ['generating', 'checking']
const STATUS = {
  generating: { tone: 'info', label: 'Designing…' },
  checking: { tone: 'info', label: 'Checking…' },
  ready: { tone: 'good', label: 'Ready' },
  failed: { tone: 'bad', label: 'Failed' },
}

const money = (v) => `$${Number(v || 0).toFixed(2)}`
const seconds = (ms) => (ms ? `${Math.round(ms / 1000)}s` : '—')
const who = (by) => (String(by || '').startsWith('user:') ? 'Staff' : String(by || '').startsWith('script') ? 'Script' : String(by || '') === 'system' ? 'System' : 'Import')

export default function PremiumPanel({ siteId, canEdit, showToast, onSiteChanged }) {
  const [data, setData] = useState(null)        // { tier, current_design_id, designs }
  const [hidden, setHidden] = useState(false)   // Premium is not switched on for this account
  const [error, setError] = useState(null)
  const [starting, setStarting] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [preview, setPreview] = useState(null)  // { version, html }
  const [width, setWidth] = useState('desktop')
  const hadActive = useRef(false)

  const load = useCallback(async () => {
    try {
      const d = await getPremiumDesigns(siteId)
      setData(d)
      setError(null)
      return d
    } catch (e) {
      if (e?.response?.status === 403 || e?.response?.status === 404) setHidden(true)
      else setError(errorMessage(e, 'Could not load the Premium designs.'))
      return null
    }
  }, [siteId])

  useEffect(() => { load() }, [load])

  const designs = data?.designs || []
  const inFlight = designs.some((d) => ACTIVE.includes(d.status))

  // Poll while a design is being made; when it finishes, tell the editor so the preview refreshes.
  useEffect(() => {
    if (!inFlight) {
      if (hadActive.current) {
        hadActive.current = false
        const latest = designs[0]
        showToast(latest?.status === 'ready' ? 'Premium design is ready' : 'The Premium design could not be finished — see the reason below', latest?.status === 'ready' ? undefined : 'bad')
        onSiteChanged?.()
      }
      return undefined
    }
    hadActive.current = true
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [inFlight, load]) // eslint-disable-line react-hooks/exhaustive-deps

  if (hidden) return null

  const generate = async () => {
    setStarting(true)
    try {
      await generatePremiumDesign(siteId)
      showToast('Designing started — this takes 1 to 4 minutes')
      await load()
    } catch (e) {
      showToast(errorMessage(e, 'Could not start the design.'), 'bad')
    } finally {
      setStarting(false)
    }
  }

  const openPreview = async (d) => {
    setBusyId(d.id)
    try {
      const r = await previewPremiumDesign(siteId, d.id)
      setWidth('desktop')
      setPreview({ version: d.version, html: r.html })
    } catch (e) {
      showToast(errorMessage(e, 'Could not open the preview.'), 'bad')
    } finally {
      setBusyId(null)
    }
  }

  const switchVersion = async (d) => {
    setBusyId(d.id)
    try {
      await switchPremiumDesign(siteId, d.id)
      showToast(`Version ${d.version} is now the preview`)
      await load()
      onSiteChanged?.()
    } catch (e) {
      showToast(errorMessage(e, 'Could not switch the design.'), 'bad')
    } finally {
      setBusyId(null)
    }
  }

  const backToStandard = async () => {
    setBusyId('standard')
    try {
      await premiumBackToStandard(siteId)
      showToast('Back on the Standard design — Premium versions are kept')
      await load()
      onSiteChanged?.()
    } catch (e) {
      showToast(errorMessage(e, 'Could not switch back.'), 'bad')
    } finally {
      setBusyId(null)
    }
  }

  const isPremium = data?.tier === 'premium'
  const current = designs.find((d) => d.id === data?.current_design_id)

  return (
    <Card>
      <SectionTitle
        title="Premium design"
        hint="Claude designs a one-of-a-kind page for this site from its content and photos. Takes 1 to 4 minutes and typically costs $0.20 to $0.60."
        right={(
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <Badge tone={isPremium ? 'good' : 'neutral'}>{isPremium ? `Premium${current ? ` · version ${current.version}` : ''}` : 'Standard'}</Badge>
            {canEdit && (
              <Button variant="primary" icon={Sparkles} loading={starting} disabled={inFlight} onClick={generate}>
                {inFlight ? 'Designing…' : designs.length ? 'Design again with Claude' : 'Design with Claude'}
              </Button>
            )}
            {canEdit && isPremium && (
              <Button variant="secondary" icon={Undo2} loading={busyId === 'standard'} disabled={inFlight} onClick={backToStandard}
                title="Show the Standard design again. Premium versions are kept.">Back to Standard</Button>
            )}
          </div>
        )}
      />

      {error && <Notice tone="bad">{error}</Notice>}
      <Notice tone="info">
        Use clean photos: no text, logos or screenshots on them. A portrait or product photo works best. A finished design
        replaces this site's preview straight away; publish to Cloudflare only when you are happy with it. Older versions are kept.
      </Notice>

      {designs.length > 0 && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {designs.map((d) => {
            const st = STATUS[d.status] || { tone: 'neutral', label: d.status }
            const isCurrent = d.id === data?.current_design_id && isPremium
            const reason = d.status === 'failed' ? ((d.checks?.errors || [])[0] || 'The design could not be finished.') : null
            const attempts = d.checks?.attempts
            return (
              <div key={d.id} style={{ border: `1px solid ${isCurrent ? T.teal : T.line}`, borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: 13.5, color: T.ink }}>Version {d.version}</strong>
                  <Badge tone={st.tone}>{st.label}</Badge>
                  {isCurrent && <Badge tone="good">In use</Badge>}
                  <span style={{ fontSize: 12, color: T.muted }}>
                    {dateTime(d.created_at)} · {who(d.created_by)}
                    {d.status === 'ready' || d.status === 'failed' ? ` · ${money(d.cost_usd)} · ${seconds(d.duration_ms)}` : ''}
                    {attempts?.build > 1 ? ' · needed a second try' : ''}
                  </span>
                  <span style={{ flex: 1 }} />
                  {d.status === 'ready' && (
                    <>
                      <Button size="sm" variant="secondary" icon={Eye} loading={busyId === d.id} onClick={() => openPreview(d)}>Preview</Button>
                      {canEdit && !isCurrent && (
                        <Button size="sm" variant="secondary" icon={RefreshCw} loading={busyId === d.id} disabled={inFlight} onClick={() => switchVersion(d)}>Use this version</Button>
                      )}
                    </>
                  )}
                </div>
                {reason && <p style={{ margin: 0, fontSize: 12.5, color: T.bad }}>{reason}</p>}
                {d.status === 'ready' && (d.checks?.static?.warnings || []).length > 0 && (
                  <p style={{ margin: 0, fontSize: 12, color: T.warn }}>{d.checks.static.warnings[0]}</p>
                )}
              </div>
            )
          })}
        </div>
      )}

      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview ? `Premium design · version ${preview.version}` : 'Preview'} width={1040}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Segmented ariaLabel="Preview width" value={width} onChange={setWidth}
            options={[{ value: 'desktop', label: 'Desktop' }, { value: 'phone', label: 'Phone' }]} />
          <div style={{ display: 'flex', justifyContent: 'center', background: '#F1F6F8', borderRadius: 10, padding: width === 'phone' ? 12 : 0 }}>
            {preview && (
              <iframe title="Premium design preview" srcDoc={preview.html} sandbox=""
                style={{ width: width === 'phone' ? 390 : '100%', maxWidth: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8, background: '#fff' }} />
            )}
          </div>
        </div>
      </Modal>
    </Card>
  )
}
