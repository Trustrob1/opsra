/**
 * frontend/src/modules/sites/SitesDomainsTab.jsx
 * SITE-3 part 3 — Domains & renewals (spec §13): every client domain with its registrar,
 * renewal dates, cost at renewal and status, filterable by "expiring in 30 / 14 / 7 days".
 * SITE-4: the daily renewal cycle reminds builders; "Send renewal link" sends one on demand.
 *
 * Pattern 26: stays mounted; fetches only while `isActive`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Search, Globe, CalendarClock, TriangleAlert, Wallet, ExternalLink, Send } from 'lucide-react'
import { listSiteDomains, sendRenewalLink, errorMessage } from '../../services/sites.service'
import { Card, Button, Badge, Kpi, Notice, Spinner, Empty, Segmented } from './sitesUi'
import { Th, Td, Fact } from './sitesOpsUi'
import { T, INPUT, money, num, dateOnly, DOMAIN_STATUS } from './sitesKit'
import { useIsMobile } from '../../hooks/useIsMobile'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: '30', label: 'Expiring in 30 days' },
  { value: '14', label: '14 days' },
  { value: '7', label: '7 days' },
  { value: 'lapsed', label: 'Lapsed' },
]

const REGISTRAR = { qservers: 'QServers', hostinger: 'Hostinger' }

const cost = (row) => (row.cost_at_renewal == null ? '—' : money(row.cost_at_renewal, 'NGN'))

function daysText(d) {
  if (d === null || d === undefined) return '—'
  if (d < 0) return `${Math.abs(d)} day${Math.abs(d) === 1 ? '' : 's'} ago`
  if (d === 0) return 'today'
  return `in ${d} day${d === 1 ? '' : 's'}`
}

export default function SitesDomainsTab({ isActive, canEdit, showToast }) {
  const isMobile = useIsMobile()
  const [sending, setSending] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      setRows(await listSiteDomains())
    } catch (e) {
      const msg = errorMessage(e, 'Could not load domains.')
      setError(msg)
      showToast?.(msg, 'bad')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { if (isActive) { setLoading(true); load() } }, [isActive, load])

  const sendLink = useCallback(async (row) => {
    setSending(row.id)
    try {
      const res = await sendRenewalLink(row.id)
      showToast?.(res.sent ? 'Renewal link sent to the builder' : 'Link created, but WhatsApp could not deliver it — managers were alerted', res.sent ? undefined : 'bad')
      if (!res.sent && res.checkout_url && navigator.clipboard) navigator.clipboard.writeText(res.checkout_url).catch(() => {})
    } catch (e) {
      showToast?.(errorMessage(e, 'Could not create the renewal link.'), 'bad')
    } finally {
      setSending(null)
    }
  }, [showToast])

  const canSend = (r) => canEdit && r.effective_status !== 'transferred'

  const stats = useMemo(() => {
    const soon = rows.filter((r) => r.effective_status === 'expiring')
    return {
      total: rows.length,
      expiring: soon.length,
      lapsed: rows.filter((r) => r.effective_status === 'lapsed').length,
      value: soon.reduce((sum, r) => sum + (r.cost_at_renewal || 0), 0),
    }
  }, [rows])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (filter === 'lapsed') { if (r.effective_status !== 'lapsed') return false }
      else if (filter !== 'all') {
        if (r.effective_status === 'transferred' || r.days_to_renewal == null || r.days_to_renewal > Number(filter)) return false
      }
      if (!q) return true
      return [r.domain, r.client_business_name, r.builder_name, r.builder_business].some((v) => String(v || '').toLowerCase().includes(q))
    })
  }, [rows, filter, search])

  const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(165px, 1fr))', gap: 12 }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={grid}>
        <Kpi label="Domains" icon={Globe} value={num(stats.total)} />
        <Kpi label="Expiring in 30 days" icon={CalendarClock} value={num(stats.expiring)} tone={stats.expiring ? 'warn' : undefined} />
        <Kpi label="Lapsed" icon={TriangleAlert} value={num(stats.lapsed)} tone={stats.lapsed ? 'bad' : undefined} />
        <Kpi label="Renewals due (30 days)" icon={Wallet} value={money(stats.value)} sub="what it costs us" />
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <Segmented ariaLabel="Filter domains" value={filter} onChange={setFilter} options={FILTERS} />
        <div style={{ position: 'relative', flex: '1 1 220px', maxWidth: 320 }}>
          <Search size={15} color={T.muted} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} aria-hidden="true" />
          <input style={{ ...INPUT, paddingLeft: 32 }} placeholder="Search domain, business or builder" aria-label="Search domains"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      {loading ? <Spinner /> : visible.length === 0 ? (
        <Card>
          <Empty icon={Globe} title={rows.length === 0 ? 'No domains yet' : 'No domains match'}
            text={rows.length === 0 ? 'A domain is added here, with its renewal dates, the moment a site is marked live.'
              : 'Try a wider window or clear the search.'}
            action={rows.length > 0 && <Button onClick={() => { setFilter('all'); setSearch('') }}>Clear filters</Button>} />
        </Card>
      ) : isMobile ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {visible.map((r) => <DomainCard key={r.id} row={r} canSend={canSend(r)} sending={sending === r.id} onSend={() => sendLink(r)} />)}
        </div>
      ) : (
        <Card pad={0}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 1020 }}>
              <thead><tr>
                <Th>Domain</Th><Th>Client · Builder</Th><Th>Registrar</Th><Th>Registered</Th><Th>Domain renews</Th><Th>Hosting renews</Th><Th align="right">Cost at renewal</Th><Th>Status</Th><Th><span className="sr-only">Actions</span></Th>
              </tr></thead>
              <tbody>
                {visible.map((r) => {
                  const st = DOMAIN_STATUS[r.effective_status] || DOMAIN_STATUS.active
                  return (
                    <tr key={r.id} className="sts-row" style={{ borderTop: `1px solid ${T.line}` }}>
                      <Td><DomainName row={r} /></Td>
                      <Td>{r.client_business_name || '—'}<span style={{ display: 'block', fontSize: 12, color: T.muted }}>{r.builder_name || '—'}</span></Td>
                      <Td>{REGISTRAR[r.registrar] || r.registrar}</Td>
                      <Td className="tnum">{dateOnly(r.registered_at)}</Td>
                      <Td className="tnum">{dateOnly(r.renews_on)}</Td>
                      <Td className="tnum">{dateOnly(r.hosting_renews_on)}</Td>
                      <Td align="right" className="tnum">{cost(r)}</Td>
                      <Td>
                        <Badge tone={st.tone}>{st.label}</Badge>
                        <span className="tnum" style={{ display: 'block', fontSize: 11.5, color: T.muted, marginTop: 3 }}>{daysText(r.days_to_renewal)}</span>
                      </Td>
                      <Td>{canSend(r) && <Button icon={Send} loading={sending === r.id} onClick={() => sendLink(r)}>Send renewal link</Button>}</Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="tnum" style={{ margin: 0, padding: '10px 14px', fontSize: 11.5, color: T.muted, borderTop: `1px solid ${T.line}` }}>
            {visible.length} of {rows.length} domain{rows.length === 1 ? '' : 's'}
          </p>
        </Card>
      )}
    </div>
  )
}

function DomainName({ row }) {
  if (!row.live_url) return <span style={{ fontWeight: 600 }}>{row.domain}</span>
  return (
    <a href={row.live_url} target="_blank" rel="noreferrer noopener" style={{ fontWeight: 600, color: T.ink, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      {row.domain}<ExternalLink size={12} color={T.muted} aria-hidden="true" /><span className="sr-only"> (opens the live site)</span>
    </a>
  )
}

function DomainCard({ row, canSend, sending, onSend }) {
  const st = DOMAIN_STATUS[row.effective_status] || DOMAIN_STATUS.active
  return (
    <Card pad={14}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
          <DomainName row={row} />
          <p style={{ margin: '2px 0 0', fontSize: 12.5, color: T.muted }}>{row.client_business_name || '—'} · {row.builder_name || '—'}</p>
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12 }}>
        <Fact label="Domain renews"><span className="tnum">{dateOnly(row.renews_on)}</span></Fact>
        <Fact label="Hosting renews"><span className="tnum">{dateOnly(row.hosting_renews_on)}</span></Fact>
        <Fact label="Cost at renewal"><span className="tnum">{cost(row)}</span></Fact>
        <Fact label="Registrar">{REGISTRAR[row.registrar] || row.registrar}</Fact>
      </div>
      <p className="tnum" style={{ margin: '10px 0 0', fontSize: 12, color: T.muted }}>Renewal {daysText(row.days_to_renewal)}</p>
      {canSend && <div style={{ marginTop: 10 }}><Button icon={Send} loading={sending} onClick={onSend}>Send renewal link</Button></div>}
    </Card>
  )
}
