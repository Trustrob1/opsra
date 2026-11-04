/**
 * frontend/src/modules/billing/SharePanel.jsx
 * BILL-4 — make, copy and end the invoice-style Billing link. The link is shown once; making a new one ends the old one.
 */
import { useCallback, useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import { createPayLink, getPayLinkStatus, endPayLink, planError } from '../../services/accountPlan.service'
import { B, panel, panelTitle, panelSub, button } from './billingUi'

const day = (v) => (v ? new Date(v).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Africa/Lagos' }) : '')

export default function SharePanel() {
  const [link, setLink] = useState(undefined)
  const [fresh, setFresh] = useState(null)
  const [copied, setCopied] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try { setLink((await getPayLinkStatus()).link) } catch (e) { setErr(planError(e)); setLink(null) }
  }, [])
  useEffect(() => { load() }, [load])

  const make = async () => {
    setBusy(true); setErr(''); setCopied(false)
    try { setFresh(await createPayLink()); await load() } catch (e) { setErr(planError(e)) }
    setBusy(false)
  }
  const end = async () => {
    setBusy(true); setErr('')
    try { await endPayLink(); setFresh(null); await load() } catch (e) { setErr(planError(e)) }
    setBusy(false)
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(fresh.url); setCopied(true) } catch { setErr('Could not copy. Select the link and copy it.') }
  }

  return (
    <section style={panel} aria-label="Share billing link">
      <h3 style={panelTitle}>Share a billing link</h3>
      <p style={{ ...panelSub, maxWidth: 620 }}>Send the business owner a private page that shows the plan and credit left, with buttons to renew and top up. No sign-in needed, and nothing else in the account is shown.</p>
      {err && <div role="alert" style={{ color: ds.red, fontSize: 13.5, marginTop: 10 }}>{err}</div>}
      {fresh && (
        <div style={{ marginTop: 16, background: B.soft, border: `1px solid ${B.line}`, borderRadius: 14, padding: 14 }}>
          <div style={{ fontSize: 12.5, color: B.muted, marginBottom: 6 }}>Your new link. It is shown only now, so copy it before you leave this page.</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
            <input readOnly aria-label="Billing link" value={fresh.url} onFocus={(e) => e.target.select()}
              style={{ flex: '1 1 320px', minWidth: 0, minHeight: 40, boxSizing: 'border-box', padding: '0 12px', border: '1px solid #CFDCDA', borderRadius: 12, fontSize: 13, fontFamily: ds.fontDm }} />
            <button type="button" className="bl-btn" style={button(true)} onClick={copy}>{copied ? 'Copied' : 'Copy link'}</button>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 16 }}>
        {link === undefined ? <span style={{ fontSize: 13, color: B.muted }}>Loading…</span> : (
          <>
            <button type="button" className="bl-btn" style={button(!link)} disabled={busy} onClick={make}>{link ? 'Make a new link' : 'Make a link'}</button>
            {link && <button type="button" className="bl-btn" style={button(false)} disabled={busy} onClick={end}>End this link</button>}
            <span style={{ fontSize: 13, color: B.muted }}>
              {link ? `Active until ${day(link.expires_at)}. Opened ${link.use_count} time${link.use_count === 1 ? '' : 's'}. Making a new link ends this one.` : 'No active link. A link works for 7 days.'}
            </span>
          </>
        )}
      </div>
    </section>
  )
}
