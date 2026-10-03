/**
 * frontend/src/modules/sites/PremiumDesignsCard.jsx
 * SITE-PREMIUM P4-4 - a Premium customer's design history and "Try another design" (builder portal).
 * Buttons only. History: the last saved versions with a plain label, small live previews, Preview (in the big pane)
 * and Restore (never uses an edit; the version being replaced stays in the list). Try another design: Claude makes a
 * completely new look into a held-back slot; the live site only changes when the customer presses Keep.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCcw, Sparkles, Check, X, Eye, Images } from 'lucide-react'
import { T } from './sitesKit'
import { Card, Button, Notice, SectionTitle, Badge } from './sitesUi'
import {
  getPremiumHistory, getPremiumHistoryPreview, restorePremiumVersion,
  premiumCheckout, getPremiumRedesign, startPremiumRedesign, getPremiumRedesignPreview, keepPremiumRedesign, discardPremiumRedesign,
  errorMessage,
} from '../../services/builder_portal.service'

const POLL_MS = 6000
const THUMBS_MAX = 6

function when(iso) {
  try {
    return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch (e) { return '' }
}

// A small live preview: the whole page drawn at desktop width and scaled down. No scripts run in it.
function Thumb({ html }) {
  const W = 190
  const scale = W / 1280
  return (
    <div aria-hidden="true" style={{ width: W, height: 120, overflow: 'hidden', borderRadius: 8, border: `1px solid ${T.lineStrong}`, background: '#fff', flex: '0 0 auto' }}>
      <iframe title="" sandbox="" srcDoc={html} tabIndex={-1}
        style={{ width: 1280, height: 120 / scale, border: 0, transform: `scale(${scale})`, transformOrigin: 'top left', pointerEvents: 'none' }} />
    </div>
  )
}

export default function PremiumDesignsCard({ token, siteId, onResult, onPreviewHtml, previewingHtml }) {
  const [history, setHistory] = useState([])
  const [redesign, setRedesign] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [thumbs, setThumbs] = useState({})          // {design id: html}
  const [showThumbs, setShowThumbs] = useState(false)
  const [previewLabel, setPreviewLabel] = useState(null)
  const [dismissedFailure, setDismissedFailure] = useState(null)
  const wasRunning = useRef(false)

  const take = useCallback((r) => {
    if (r?.history) setHistory(r.history)
    if (r?.redesign) setRedesign(r.redesign)
  }, [])

  const load = useCallback(async () => {
    try { take(await getPremiumHistory(token, siteId)) } catch (e) { /* the card just stays empty */ }
  }, [token, siteId, take])

  useEffect(() => { load() }, [load])

  // While a new design is being made, ask every few seconds. When it is ready, show it in the big pane.
  const running = !!redesign?.in_progress
  useEffect(() => {
    if (!running) return undefined
    const id = setInterval(async () => {
      try { setRedesign(await getPremiumRedesign(token, siteId)) } catch (e) { /* try again next time */ }
    }, POLL_MS)
    return () => clearInterval(id)
  }, [running, token, siteId])

  useEffect(() => {
    if (wasRunning.current && !running && redesign?.staged) showStaged()
    wasRunning.current = running
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, redesign?.staged?.id])

  // Small previews load one after another, newest first, and only when asked for.
  useEffect(() => {
    if (!showThumbs) return undefined
    let stop = false
    ;(async () => {
      for (const h of history.slice(0, THUMBS_MAX)) {
        if (stop || thumbs[h.id]) continue
        try {
          const r = await getPremiumHistoryPreview(token, siteId, h.id)
          if (!stop) setThumbs((t) => ({ ...t, [h.id]: r.html }))
        } catch (e) { /* skip this one */ }
      }
    })()
    return () => { stop = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showThumbs, history])

  const guard = async (fn, fallback) => {
    setBusy(true); setError(null)
    try { return await fn() } catch (e) { setError(errorMessage(e, fallback)); return null } finally { setBusy(false) }
  }

  const previewVersion = async (h) => {
    const r = await guard(() => getPremiumHistoryPreview(token, siteId, h.id), 'Could not show that version.')
    if (r) { onPreviewHtml(r.html); setPreviewLabel(h.label) }
  }
  const closePreview = () => { onPreviewHtml(null); setPreviewLabel(null) }

  const restore = async (h) => {
    const r = await guard(() => restorePremiumVersion(token, siteId, h.id), 'Could not restore that version.')
    if (r) { closePreview(); take(r); onResult(r) }
  }

  const start = async () => {
    setConfirming(false)
    const r = await guard(() => startPremiumRedesign(token, siteId), 'Could not start a new design.')
    if (r) { setDismissedFailure(null); setRedesign(r.redesign) }
  }

  async function showStaged() {
    const r = await guard(() => getPremiumRedesignPreview(token, siteId), 'Could not show the new design.')
    if (r) { onPreviewHtml(r.html); setPreviewLabel('Your new design') }
  }

  const buy = async () => {
    const r = await guard(() => premiumCheckout(token, siteId, 'redesign'), 'Could not start the payment.')
    if (r?.checkout_url) window.location.assign(r.checkout_url)
  }

  const keep = async () => {
    const r = await guard(() => keepPremiumRedesign(token, siteId), 'Could not keep the new design.')
    if (r) { closePreview(); take(r); onResult(r) }
  }
  const discard = async () => {
    const r = await guard(() => discardPremiumRedesign(token, siteId), 'Could not discard the new design.')
    if (r) { closePreview(); take(r); load() }
  }

  if (!redesign && history.length === 0) return null
  const staged = redesign?.staged
  const failure = redesign?.last_failure && redesign.last_failure !== dismissedFailure ? redesign.last_failure : null

  return (
    <Card>
      <SectionTitle title="Designs" />

      {/* ---- Try another design ---- */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.ink, marginBottom: 4 }}>Try another design</div>
        <p style={{ margin: '0 0 10px', fontSize: 13, color: T.muted }}>
          Claude designs a completely new look from your own text and photos. Your current design stays as it is until you press Keep, and you can always come back to it.
          {redesign ? ` You have ${redesign.remaining} of ${redesign.included} new designs left.` : ''}
        </p>

        {running && <Notice tone="info">Designing your new look. This takes a few minutes, and you can leave this page open.</Notice>}

        {staged && !running && (
          <>
            <Notice tone="info">
              Your new design is ready. {previewingHtml ? 'It is showing in the preview.' : 'Press Preview to see it.'} Nothing has changed on your site yet.
            </Notice>
            {staged.carried_note && <p style={{ margin: '8px 0 0', fontSize: 12.5 }}>{staged.carried_note}</p>}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
              {!previewingHtml && <Button icon={Eye} disabled={busy} onClick={showStaged}>Preview</Button>}
              <Button variant="primary" icon={Check} loading={busy} onClick={keep}>Keep this design</Button>
              <Button icon={X} disabled={busy} onClick={discard}>Discard it</Button>
            </div>
          </>
        )}

        {failure && !running && !staged && (
          <Notice tone="bad">
            {failure} This did not use one of your new designs.{' '}
            <button type="button" onClick={() => setDismissedFailure(redesign.last_failure)} style={{ border: 0, background: 'none', color: T.teal, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit', fontSize: 'inherit' }}>Dismiss</button>
          </Notice>
        )}

        {!running && !staged && redesign && !redesign.allowed && <Notice tone="info">{redesign.blocked_reason}</Notice>}
        {!running && !staged && redesign?.can_buy && (
          <Button variant="primary" icon={Sparkles} loading={busy} onClick={buy}>Buy a new design · ₦{Number(redesign.price).toLocaleString('en-NG')}</Button>
        )}

        {!running && !staged && redesign?.allowed && !confirming && (
          <Button icon={Sparkles} disabled={busy} onClick={() => setConfirming(true)}>Try another design</Button>
        )}
        {confirming && (
          <div style={{ border: `1px solid ${T.lineStrong}`, borderRadius: 10, padding: 12 }}>
            <p style={{ margin: '0 0 10px', fontSize: 13, color: T.ink }}>
              Make a completely new design? {redesign.uses_free === false
                ? 'It uses the new design you bought, even if you decide not to keep it.'
                : `It uses 1 of your ${redesign.remaining} new designs left, even if you decide not to keep it.`} If it cannot be finished, nothing is used.
            </p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button variant="primary" icon={Sparkles} loading={busy} onClick={start}>Yes, make a new design</Button>
              <Button disabled={busy} onClick={() => setConfirming(false)}>Not now</Button>
            </div>
          </div>
        )}
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      {/* ---- History ---- */}
      {history.length > 0 && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.ink }}>Earlier versions</div>
            {!showThumbs && history.length > 1 && <Button size="sm" icon={Images} onClick={() => setShowThumbs(true)}>Show small previews</Button>}
          </div>
          <p style={{ margin: '0 0 10px', fontSize: 13, color: T.muted }}>
            Restoring an earlier version never uses one of your edits, and the version you leave stays here.
          </p>
          {previewLabel && previewingHtml && (
            <Notice tone="info">
              Previewing: {previewLabel}.{' '}
              <button type="button" onClick={closePreview} style={{ border: 0, background: 'none', color: T.teal, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit', fontSize: 'inherit' }}>Close preview</button>
            </Notice>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
            {history.map((h) => (
              <div key={h.id} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', padding: 10, border: `1px solid ${h.is_current ? T.teal : T.lineStrong}`, borderRadius: 10 }}>
                {showThumbs && (thumbs[h.id] ? <Thumb html={thumbs[h.id]} /> : (h.id === history[0]?.id || history.indexOf(h) < THUMBS_MAX) ? <div style={{ width: 190, height: 120, borderRadius: 8, background: '#f1f1f1', flex: '0 0 auto' }} aria-hidden="true" /> : null)}
                <div style={{ flex: '1 1 160px', minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: T.ink }}>{h.label}</div>
                  <div style={{ fontSize: 12, color: T.muted }}>{when(h.created_at)}</div>
                  {h.is_current && <div style={{ marginTop: 4 }}><Badge tone="good">Current</Badge></div>}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Button size="sm" icon={Eye} disabled={busy} onClick={() => previewVersion(h)}>Preview</Button>
                  {h.can_restore && <Button size="sm" icon={RotateCcw} disabled={busy} onClick={() => restore(h)}>Restore this version</Button>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}
