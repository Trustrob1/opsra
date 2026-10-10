/**
 * frontend/src/modules/sites/SiteCaptureCard.jsx
 * SITE-ADDONS A1-2 - staff view of one site's lead capture: which capture features the plan switches on, the last 30 days
 * of enquiries and WhatsApp clicks, the copy-paste form for a site built somewhere else, and a new-key button.
 * The form and tracked links appear on the site after its next render (preview) and publish.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Copy, KeyRound, Info } from 'lucide-react'
import { getSiteCapture, rotateSiteCaptureKey, errorMessage } from '../../services/sites.service'
import { Card, SectionTitle, Button, Notice, Spinner, Badge, Modal, Kpi } from './sitesUi'
import { T, INPUT, num } from './sitesKit'
import { copyText } from './siteAddonsKit'

const FEATURES = [
  ['form_instant_reply', 'Enquiry form with instant reply'],
  ['source_tracking', 'Source tracking (WhatsApp clicks by page and product)'],
  ['speed_alerts', 'Speed-to-lead alerts to the owner'],
]

function snippetFor(action) {
  return [
    `<form method="post" action="${action}" accept-charset="utf-8">`,
    '  <input type="hidden" name="src" value="enquiry-form">',
    '  <label>Your name <input name="name" required maxlength="120"></label>',
    '  <label>Phone or WhatsApp number <input name="phone" type="tel" maxlength="20"></label>',
    '  <label>Email (optional) <input name="email" type="email" maxlength="200"></label>',
    '  <label>Your message <textarea name="message" maxlength="2000"></textarea></label>',
    '  <div style="position:absolute;left:-9999px" aria-hidden="true"><label>Leave empty <input name="website" tabindex="-1" autocomplete="off"></label></div>',
    '  <label><input type="checkbox" name="consent" value="on" required> I agree that the business may contact me about my enquiry.</label>',
    '  <button type="submit">Send enquiry</button>',
    '</form>',
  ].join('\n')
}

export default function SiteCaptureCard({ siteId, canEdit, showToast }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try { setData(await getSiteCapture(siteId)) } catch (e) { setLoadError(errorMessage(e, 'Could not load lead capture for this site.')) } finally { setLoading(false) }
  }, [siteId])
  useEffect(() => { setLoading(true); load() }, [load])

  const snippet = useMemo(() => (data ? snippetFor(data.form_action) : ''), [data])

  const copy = async (text, what) => {
    const ok = await copyText(text)
    showToast?.(ok ? `${what} copied` : 'Could not copy. Select it and copy by hand.', ok ? undefined : 'bad')
  }

  const rotate = async () => {
    setBusy(true); setError(null)
    try {
      setData(await rotateSiteCaptureKey(siteId))
      setConfirm(false)
      showToast?.('New key made')
    } catch (e) {
      setError(errorMessage(e, 'Could not make a new key.'))
    } finally { setBusy(false) }
  }

  if (loading) return <Card><Spinner /></Card>
  if (loadError) return <Card><Notice tone="bad">{loadError}</Notice></Card>

  const anyOn = Object.values(data.features).some(Boolean)
  const ev = data.events

  return (
    <Card>
      <SectionTitle title="Lead capture"
        hint="Enquiries sent from this site, and WhatsApp clicks, for the last 30 days. Leads are kept in the client's own workspace." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {FEATURES.map(([k, label]) => (
            <li key={k} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13, color: T.ink }}>
              <span style={{ flexShrink: 0 }}><Badge tone={data.features[k] ? 'good' : 'neutral'}>{data.features[k] ? 'On' : 'Off'}</Badge></span>
              <span style={{ minWidth: 0, paddingTop: 2 }}>{label}</span>
            </li>
          ))}
        </ul>

        {!anyOn && <Notice tone="info" icon={Info}>This site's plan does not include lead capture yet. Set up a Capture plan or give free access in "Plan and add-ons" above.</Notice>}
        {anyOn && (
          <Notice tone="info" icon={Info}>
            The form and tracked WhatsApp links appear on the site after its next render. Use "Render preview", then "Publish to Cloudflare" for a live site.
          </Notice>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
          <Kpi label="Enquiries" value={num(ev.form_submit)} sub={`${num(data.leads_total)} leads in total`} />
          <Kpi label="WhatsApp clicks" value={num(ev.wa_click)} />
          <Kpi label="Owner replied" value={num(ev.answer_tap)} sub="tapped Answer now" />
          <Kpi label="Spam blocked" value={num(ev.form_rejected)} />
        </div>

        <details>
          <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: T.ink }}>For a site built somewhere else</summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
            <p style={{ margin: 0, fontSize: 12.5, color: T.soft, lineHeight: 1.5 }}>
              Paste this form into the page. It works only while this site has the enquiry form on its plan. For WhatsApp buttons, use the tracked link
              below and add <code>?src=hero&amp;t=Hello</code> (where the button sits, and the first message).
            </p>
            <textarea readOnly style={{ ...INPUT, fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 12, minHeight: 190 }}
              aria-label="Enquiry form to paste" value={snippet} onFocus={(e) => e.target.select()} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button size="sm" icon={Copy} onClick={() => copy(snippet, 'Form')}>Copy form</Button>
              <Button size="sm" icon={Copy} onClick={() => copy(data.wa_link, 'Link')}>Copy tracked WhatsApp link</Button>
            </div>
          </div>
        </details>

        {canEdit && (
          <div>
            <Button size="sm" icon={KeyRound} onClick={() => { setConfirm(true); setError(null) }}>Make a new key</Button>
          </div>
        )}
      </div>

      <Modal open={confirm} onClose={() => setConfirm(false)} title="Make a new key?" width={460}
        footer={<>
          <Button onClick={() => setConfirm(false)}>Keep the current key</Button>
          <Button variant="danger" icon={KeyRound} loading={busy} onClick={rotate}>Make a new key</Button>
        </>}>
        <p style={{ margin: 0, fontSize: 13.5, color: T.ink, lineHeight: 1.55 }}>
          The old key stops working straight away. The form and WhatsApp links on the published site use it, so enquiries will not arrive
          until you render and publish the site again. Do this only if the key has been misused.
        </p>
        {error && <Notice tone="bad" style={{ marginTop: 12 }}>{error}</Notice>}
      </Modal>
    </Card>
  )
}
