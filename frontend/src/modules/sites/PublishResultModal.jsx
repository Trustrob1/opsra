/**
 * frontend/src/modules/sites/PublishResultModal.jsx
 * SITE-HOSTNAMES — shown after "Publish to Cloudflare": what was uploaded, the DNS records the client
 * must add, and whether Cloudflare has connected each address yet ("Check again" re-reads the status).
 */
import { useState } from 'react'
import { RefreshCw, Copy } from 'lucide-react'
import { getSiteHostnames, publishSite, errorMessage } from '../../services/sites.service'
import { Button, Badge, Notice, Modal } from './sitesUi'
import { T } from './sitesKit'

function hostBadge(h, isZone) {
  if (h.active) return { tone: 'good', text: 'Live' }
  if (h.status === 'not_registered') return { tone: 'neutral', text: 'Not connected' }
  if (h.status === 'waiting_nameservers') return { tone: 'warn', text: 'Waiting for nameservers' }
  if (isZone && h.status === 'pending') return { tone: 'warn', text: 'Setting up SSL' }
  return { tone: 'warn', text: 'Waiting for DNS' }
}

const copy = (text) => { try { navigator.clipboard?.writeText(text) } catch { /* clipboard blocked: the text is still selectable */ } }

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
  // Domains we bought: move the domain's DNS to Cloudflare so nobody has to add a CNAME by hand.
  const useCloudflareDns = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await publishSite(siteId, { dns_mode: 'cloudflare_zone' })
      if (res.hostnames_error) setError(res.hostnames_error)
      else setFresh(res.hostnames)
    } catch (e) { setError(errorMessage(e, 'Could not switch to Cloudflare DNS.')) } finally { setBusy(false) }
  }
  const isZone = info?.mode === 'cloudflare_zone'

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

        {info && info.route_ok === false && (
          <Notice tone="warn">The Worker rule for this domain is missing, so visitors won't reach the site. Press Publish again to add it.</Notice>
        )}

        {info && (
          <>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: T.ink, marginBottom: 6 }}>Cloudflare status</div>
              {info.hostnames.map((h) => {
                const b = hostBadge(h, isZone)
                return (
                  <div key={h.hostname} style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderTop: `1px solid ${T.line}` }}>
                    <code style={{ fontSize: 13 }}>{h.hostname}</code>
                    <Badge tone={b.tone}>{b.text}</Badge>
                  </div>
                )
              })}
              {info.all_active && <p style={{ margin: '8px 0 0', fontSize: 13, color: T.good }}>Both addresses are live.</p>}
            </div>

            {isZone && !info.all_active && info.zone_status !== 'active' && (
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.ink, marginBottom: 6 }}>Set these two nameservers where the domain was bought</div>
                {(info.nameservers || []).map((ns) => (
                  <div key={ns} style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderTop: `1px solid ${T.line}` }}>
                    <code style={{ fontSize: 13 }}>{ns}</code>
                    <Button icon={Copy} onClick={() => copy(ns)}>Copy</Button>
                  </div>
                ))}
                <p style={{ margin: '8px 0 0', fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
                  At QServers: open the domain, choose Nameservers, pick custom nameservers and enter these two. Cloudflare then connects the domain and issues the SSL certificate by itself; press Check again after a few minutes (nameserver changes can take up to a few hours).
                </p>
                <p style={{ margin: '6px 0 0', fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
                  Only for domains with no email or other services on them yet: changing nameservers replaces the domain's existing DNS records.
                </p>
              </div>
            )}

            {!isZone && !info.all_active && (
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
                <p style={{ margin: '10px 0 0', fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
                  Did we buy this domain? <Button loading={busy} onClick={useCloudflareDns}>Use Cloudflare DNS instead</Button> — no record to add, only two nameservers to set at the registrar.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
