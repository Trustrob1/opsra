/**
 * frontend/src/modules/sites/PublishResultModal.jsx
 * SITE-HOSTNAMES — shown after "Publish to Cloudflare": what was uploaded, the DNS records the client
 * must add, and whether Cloudflare has connected each address yet ("Check again" re-reads the status).
 */
import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { getSiteHostnames, errorMessage } from '../../services/sites.service'
import { Button, Badge, Notice, Modal } from './sitesUi'
import { T } from './sitesKit'

function hostBadge(h) {
  if (h.active) return { tone: 'good', text: 'Live' }
  if (h.status === 'not_registered') return { tone: 'neutral', text: 'Not connected' }
  return { tone: 'warn', text: 'Waiting for DNS' }
}

export default function PublishResultModal({ open, onClose, siteId, result }) {
  const [fresh, setFresh] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (!result) return null
  const info = fresh || result.hostnames
  const check = async () => {
    setBusy(true)
    setError(null)
    try { setFresh(await getSiteHostnames(siteId)) } catch (e) { setError(errorMessage(e, 'Could not check the status.')) } finally { setBusy(false) }
  }
  const close = () => { setFresh(null); setError(null); onClose() }

  return (
    <Modal open={open} onClose={close} title="Published to Cloudflare" width={600}
      footer={<><Button onClick={close}>Done</Button>{info && <Button icon={RefreshCw} loading={busy} onClick={check}>Check again</Button>}</>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Notice tone="good">
          {result.files} files uploaded for <strong>{result.domain}</strong>
          {result.removed ? ` (${result.removed} old file${result.removed === 1 ? '' : 's'} removed)` : ''}.
        </Notice>

        {result.hostnames_error && <Notice tone="warn">The site is uploaded, but connecting the domain failed: {result.hostnames_error}</Notice>}
        {error && <Notice tone="bad">{error}</Notice>}
        {!info && !result.hostnames_error && (
          <Notice tone="info">Automatic domain connection isn't set up yet, so the domain must be added to the Worker by hand in Cloudflare.</Notice>
        )}

        {info && (
          <>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: T.ink, marginBottom: 6 }}>Cloudflare status</div>
              {info.hostnames.map((h) => {
                const b = hostBadge(h)
                return (
                  <div key={h.hostname} style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderTop: `1px solid ${T.line}` }}>
                    <code style={{ fontSize: 13 }}>{h.hostname}</code>
                    <Badge tone={b.tone}>{b.text}</Badge>
                  </div>
                )
              })}
              {info.all_active && <p style={{ margin: '8px 0 0', fontSize: 13, color: T.good }}>Both addresses are live.</p>}
            </div>

            {!info.all_active && (
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.ink, marginBottom: 6 }}>Records the client must add where their domain's DNS is managed</div>
                {info.dns.map((r) => (
                  <div key={r.host} style={{ padding: '8px 0', borderTop: `1px solid ${T.line}`, fontSize: 13 }}>
                    <code>{r.type}</code> &nbsp;<code>{r.host}</code> &nbsp;→&nbsp; <code>{r.value}</code>
                    <p style={{ margin: '4px 0 0', fontSize: 12, color: T.muted, lineHeight: 1.5 }}>{r.note}</p>
                  </div>
                ))}
                <p style={{ margin: '8px 0 0', fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
                  Once the record is added, Cloudflare connects the domain and issues the SSL certificate by itself. This usually takes a few minutes; press Check again.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
