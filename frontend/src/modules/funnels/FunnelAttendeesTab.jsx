/**
 * frontend/src/modules/funnels/FunnelAttendeesTab.jsx
 * FUNNEL-1B — paid attendees: one-click copy of every Gmail (paste into the Google
 * Calendar invite), who is still missing one (one-tap re-ask), CSV export.
 */
import { useCallback, useEffect, useState } from 'react'
import { Copy, Download, Mail, UserCheck, Check } from 'lucide-react'
import { getGmailList, askGmail, exportCsv, errorMessage } from '../../services/funnels.service'
import { Card, SectionTitle, Button, Spinner, Empty, Notice, Kpi } from './funnelUi'
import { T, copyText, num } from './funnelKit'

export default function FunnelAttendeesTab({ funnel, isActive, canEdit, isMobile, showToast }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [asked, setAsked] = useState({})
  const [busy, setBusy] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try { setData(await getGmailList(funnel.id)) } catch (e) { setError(errorMessage(e, 'Could not load attendees.')) }
  }, [funnel.id])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  if (error) return <Notice tone="bad">{error}</Notice>
  if (!data) return <Spinner />

  const copyAll = async () => {
    const ok = await copyText(data.joined)
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2500); showToast(`${data.count} Gmails copied`) }
    else showToast('Copy blocked by the browser. Select the list and copy it by hand.', 'bad')
  }

  const ask = async (r) => {
    setBusy(r.id)
    try {
      await askGmail(funnel.id, r.id)
      setAsked((p) => ({ ...p, [r.id]: true }))
      showToast(`Asked ${r.name || r.phone} for their Gmail`)
    } catch (e) {
      showToast(errorMessage(e), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const seats = (data.missing || []).reduce((s, m) => s + (m.seats || 1), 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? 145 : 180}px, 1fr))`, gap: 12 }}>
        <Kpi label="Gmails collected" icon={Mail} value={num(data.count)} />
        <Kpi label="Paid, no Gmail" icon={UserCheck} value={num(data.missing.length)} tone={data.missing.length ? 'warn' : undefined}
          sub={data.missing.length ? `${seats} seat${seats === 1 ? '' : 's'} at risk of no invite` : 'Everyone is covered'} />
      </div>

      <Card>
        <SectionTitle title="Google Meet invite list"
          hint="Copy every Gmail, then paste into the guest list of the Google Calendar event. Only invited people join directly."
          right={<div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button icon={Download} onClick={() => exportCsv(funnel.id, funnel.name).catch(() => showToast('Export failed', 'bad'))}>Export CSV</Button>
            <Button variant="primary" icon={copied ? Check : Copy} disabled={!data.count} onClick={copyAll}>{copied ? 'Copied' : `Copy all ${data.count}`}</Button>
          </div>} />
        {data.count ? (
          <textarea readOnly aria-label="All Gmails, comma separated" value={data.joined} onFocus={(e) => e.target.select()}
            style={{ width: '100%', boxSizing: 'border-box', minHeight: 110, border: `1px solid ${T.line}`, borderRadius: 8, padding: 10,
              fontSize: 12.5, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: T.ink, background: '#F9FCFD', resize: 'vertical' }} />
        ) : <Empty icon={Mail} title="No Gmails yet" text="Buyers are asked for their Gmail in the payment confirmation." />}
      </Card>

      <Card>
        <SectionTitle title="Still missing a Gmail" hint="Send a reminder on WhatsApp. It only goes through if they messaged in the last 24 hours; otherwise message them from Lead Center." />
        {data.missing.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>Nobody. Every buyer has sent a Gmail.</p> : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {data.missing.map((m) => (
              <li key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: `1px solid ${T.line}`, flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: T.ink }}>{m.name || '—'}</div>
                  <div className="tnum" style={{ fontSize: 12, color: T.muted }}>+{m.phone}{m.seats > 1 ? ` · ${m.seats} seats` : ''}</div>
                </div>
                {canEdit && (asked[m.id]
                  ? <span style={{ fontSize: 12.5, color: T.good, display: 'inline-flex', alignItems: 'center', gap: 5 }}><Check size={14} aria-hidden="true" /> Asked</span>
                  : <Button size="sm" icon={Mail} loading={busy === m.id} onClick={() => ask(m)}>Ask for Gmail</Button>)}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
