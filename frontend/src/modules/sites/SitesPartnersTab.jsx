/**
 * frontend/src/modules/sites/SitesPartnersTab.jsx
 * PARTNER-1B — Launch Partners: applications waiting for a decision, and the partner roster.
 */
import { useCallback, useEffect, useState } from 'react'
import { Handshake, Check, X } from 'lucide-react'
import {
  listPartners, listPartnerApplications, approvePartnerApplication, declinePartnerApplication,
  suspendPartner, reactivatePartner, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty } from './sitesUi'
import { T, dateOnly } from './sitesKit'
import SitesGiveawaysCard from './SitesGiveawaysCard'            // GIVEAWAY-1

const Th = ({ children }) => <th style={{ textAlign: 'left', padding: '10px 14px', fontSize: 11.5, color: T.muted, fontWeight: 600 }}>{children}</th>
const Td = ({ children, ...r }) => <td style={{ padding: '10px 14px', verticalAlign: 'middle' }} {...r}>{children}</td>

export default function SitesPartnersTab({ isActive, canEdit, showToast }) {
  const [apps, setApps] = useState([])
  const [partners, setPartners] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [a, p] = await Promise.all([listPartnerApplications('applied'), listPartners()])
      setApps(a || []); setPartners(p || [])
    } catch (e) { setError(errorMessage(e, 'Could not load partners.')) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  async function act(id, fn, done) {
    setBusy(id)
    try { await fn(id); showToast(done); await load() }
    catch (e) { showToast(errorMessage(e, 'That did not work.'), 'bad') }
    finally { setBusy(null) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ margin: 0, fontSize: 13, color: T.muted, maxWidth: 560 }}>
        Launch Partners are CAC agents who send clients to Opsra. Applicants confirm their email first; approve them here and they get a sign-in link by email and WhatsApp.
      </p>
      {error && <Notice tone="bad">{error}</Notice>}
      {loading ? <Spinner /> : (
        <>
          <h3 style={{ margin: 0, fontSize: 14, color: T.ink }}>Waiting for approval ({apps.length})</h3>
          {apps.length === 0 ? (
            <Card><Empty icon={Handshake} title="No applications waiting" text="New applications appear here once the applicant has confirmed their email." /></Card>
          ) : (
            <Card pad={0}><div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 640 }}>
                <thead><tr>{['Name', 'Agency', 'Email', 'WhatsApp', 'Applied', ''].map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
                <tbody>{apps.map((a) => (
                  <tr key={a.id} style={{ borderTop: `1px solid ${T.line}` }}>
                    <Td>{a.full_name}</Td><Td>{a.agency_name || '—'}</Td><Td>{a.email}</Td><Td>{a.phone_number}</Td><Td>{dateOnly(a.created_at)}</Td>
                    <Td>{canEdit && (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <Button size="sm" variant="primary" icon={Check} loading={busy === a.id} onClick={() => act(a.id, approvePartnerApplication, 'Partner approved')}>Approve</Button>
                        <Button size="sm" variant="ghost" icon={X} disabled={busy === a.id} onClick={() => act(a.id, declinePartnerApplication, 'Application declined')}>Decline</Button>
                      </div>
                    )}</Td>
                  </tr>))}</tbody>
              </table></div></Card>
          )}

          <h3 style={{ margin: '8px 0 0', fontSize: 14, color: T.ink }}>Partners ({partners.length})</h3>
          {partners.length === 0 ? (
            <Card><Empty icon={Handshake} title="No partners yet" text="Approved applicants appear here with their permanent client link." /></Card>
          ) : (
            <Card pad={0}><div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 700 }}>
                <thead><tr>{['Name', 'Agency', 'WhatsApp', 'Code', 'Status', ''].map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
                <tbody>{partners.map((p) => (
                  <tr key={p.id} style={{ borderTop: `1px solid ${T.line}` }}>
                    <Td>{p.full_name}</Td><Td>{p.agency_name || '—'}</Td><Td>{p.phone_number}</Td><Td>{p.partner_code}</Td>
                    <Td><Badge tone={p.status === 'active' ? 'good' : 'warn'}>{p.status === 'active' ? 'Active' : 'Suspended'}</Badge></Td>
                    <Td>{canEdit && (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <Button size="sm" variant="ghost" onClick={async () => { try { await navigator.clipboard.writeText(p.link_url); showToast('Link copied') } catch (_) { showToast('Could not copy', 'bad') } }}>Copy link</Button>
                        {p.status === 'active'
                          ? <Button size="sm" variant="ghost" loading={busy === p.id} onClick={() => act(p.id, suspendPartner, 'Partner suspended')}>Suspend</Button>
                          : <Button size="sm" variant="ghost" loading={busy === p.id} onClick={() => act(p.id, reactivatePartner, 'Partner reactivated')}>Reactivate</Button>}
                      </div>
                    )}</Td>
                  </tr>))}</tbody>
              </table></div></Card>
          )}
        </>
      )}
      <SitesGiveawaysCard isActive={isActive} canEdit={canEdit} partners={partners} showToast={showToast} />
    </div>
  )
}
