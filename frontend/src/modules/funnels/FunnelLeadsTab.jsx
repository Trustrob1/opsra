/**
 * frontend/src/modules/funnels/FunnelLeadsTab.jsx
 * FUNNEL-1B — every lead in the funnel. "Needs you" filter = the needs-you inbox.
 * Row → drawer with details, timeline and actions (open lead, resend link,
 * re-open early price, mark paid, Gmail, mark handled, reset test lead).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Search, CircleAlert, ExternalLink, Send, Clock, Wallet, Mail, Check, RotateCcw, Users, ChevronLeft, ChevronRight,
} from 'lucide-react'
import {
  listRegistrations, getRegistrationEvents, patchRegistration, grantEarly, resendLink, markPaid, askGmail,
  resetTestLead, errorMessage,
} from '../../services/funnels.service'
import { Card, Button, Badge, Spinner, Empty, Notice, Drawer, Modal, Field } from './funnelUi'
import { T, INPUT, REG_STATUS, money, dateTime, ago } from './funnelKit'

const PAGE_SIZE = 50

const EVENT_LABEL = {
  lead_created: 'Messaged the number',
  greeting_sent: 'Greeting + pay button sent',
  step_sent: 'Follow-up sent',
  template_sent: 'Template reminder sent',
  step_skipped: 'Follow-up skipped',
  step_failed: 'Follow-up failed to send',
  pay_link_opened: 'Opened the pay link',
  payment_confirmed: 'Payment confirmed',
  payment_amount_mismatch: 'Payment amount did not match',
  manual_paid: 'Marked paid by hand',
  email_captured: 'Sent their Gmail',
  handoff: 'Asked something only you can answer',
  override_granted: 'Early price re-opened',
  opted_out: 'Unsubscribed',
  closed_sent: 'Told registration is closed',
  broadcast_sent: 'Broadcast sent',
  broadcast_failed: 'Broadcast failed',
}
const SKIP_REASON = {
  stale: 'too late to send', no_longer_early: 'early price already over', before_join: 'before they joined',
  registration_closed: 'registration closed', window_closed_no_template: 'outside 24 h, no template set',
  anchor_not_applicable: 'not used in this pricing mode', budget_cap: 'template budget reached',
}

export default function FunnelLeadsTab({ funnel, isActive, canEdit, isMobile, showToast, onOpenLead, onChanged, needsYou }) {
  const [filters, setFilters] = useState({ status: '', ad_code: '', needs_human: false, search: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)
  const searchTimer = useRef(null)
  const [searchInput, setSearchInput] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (filters.status) params.status = filters.status
      if (filters.ad_code) params.ad_code = filters.ad_code
      if (filters.needs_human) params.needs_human = true
      if (filters.search) params.search = filters.search
      setData(await listRegistrations(funnel.id, params))
    } catch (e) {
      setError(errorMessage(e, 'Could not load leads.'))
    } finally {
      setLoading(false)
    }
  }, [funnel.id, filters, page])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  const setFilter = (k, v) => { setPage(1); setFilters((p) => ({ ...p, [k]: v })) }
  const onSearch = (v) => {
    setSearchInput(v)
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => setFilter('search', v.trim()), 350)
  }

  const refresh = () => { load(); onChanged?.() }
  const pages = Math.max(1, Math.ceil((data.total || 0) / PAGE_SIZE))
  const codes = (funnel.ad_codes || []).map((c) => c.code)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: '1 1 220px', maxWidth: isMobile ? '100%' : 320 }}>
          <Search size={15} color={T.muted} style={{ position: 'absolute', left: 11, top: 12 }} aria-hidden="true" />
          <input aria-label="Search leads" placeholder="Search name, phone, Gmail, code" style={{ ...INPUT, paddingLeft: 33 }}
            value={searchInput} onChange={(e) => onSearch(e.target.value)} />
        </div>
        <select aria-label="Status" style={{ ...INPUT, width: 'auto' }} value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
          <option value="">All statuses</option>
          <option value="new">Not paid</option>
          <option value="paid">Paid</option>
          <option value="opted_out">Opted out</option>
        </select>
        <select aria-label="Ad code" style={{ ...INPUT, width: 'auto' }} value={filters.ad_code} onChange={(e) => setFilter('ad_code', e.target.value)}>
          <option value="">All ad codes</option>
          {codes.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button type="button" aria-pressed={filters.needs_human} onClick={() => setFilter('needs_human', !filters.needs_human)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 40, padding: '0 13px', borderRadius: 20, fontFamily: 'inherit',
            fontSize: 13, fontWeight: 600, cursor: 'pointer', border: `1px solid ${filters.needs_human ? T.bad : T.lineStrong}`,
            background: filters.needs_human ? T.badBg : '#fff', color: filters.needs_human ? T.bad : T.ink }}>
          <CircleAlert size={15} aria-hidden="true" /> Needs you{needsYou ? ` (${needsYou})` : ''}
        </button>
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      <Card pad={0} style={{ overflow: 'hidden' }}>
        {loading ? <Spinner /> : data.items.length === 0 ? (
          <Empty icon={Users} title={filters.needs_human ? 'Nobody is waiting on you' : 'No leads match'}
            text={filters.needs_human ? 'When a lead asks something the buttons can’t answer, they show up here.' : 'Leads appear the moment someone messages the funnel number.'} />
        ) : isMobile ? (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {data.items.map((r) => (
              <li key={r.id} style={{ borderTop: `1px solid ${T.line}` }}>
                <button type="button" className="fnl-row" onClick={() => setOpen(r)}
                  style={{ width: '100%', textAlign: 'left', border: 'none', background: 'none', padding: '12px 14px', fontFamily: 'inherit', cursor: 'pointer', minHeight: 56 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <strong style={{ fontSize: 14, color: T.ink, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name || r.phone}</strong>
                    {r.needs_human && <Badge tone="bad" icon={CircleAlert}>Needs you</Badge>}
                    <StatusBadge r={r} />
                  </div>
                  <div className="tnum" style={{ fontSize: 12, color: T.muted, marginTop: 3 }}>
                    {r.ad_code || 'no code'} · {ago(r.first_message_at)}{r.status === 'paid' ? ` · ${money(r.amount_paid)}` : ''}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead style={{ background: '#F7FBFC' }}>
                <tr>{['Lead', 'Code', 'Status', 'First message', 'Last reply', 'Paid', 'Gmail'].map((h, i) => (
                  <th key={h} style={{ textAlign: i === 5 ? 'right' : 'left', fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px', padding: '10px 12px', whiteSpace: 'nowrap' }}>{h}</th>
                ))}</tr>
              </thead>
              <tbody className="tnum">
                {data.items.map((r) => (
                  <tr key={r.id} className="fnl-row" onClick={() => setOpen(r)} style={{ borderTop: `1px solid ${T.line}`, cursor: 'pointer' }}>
                    <td style={{ padding: '10px 12px' }}>
                      <button type="button" onClick={(e) => { e.stopPropagation(); setOpen(r) }}
                        style={{ border: 'none', background: 'none', padding: 0, textAlign: 'left', fontFamily: 'inherit', cursor: 'pointer' }}>
                        <span style={{ display: 'block', fontWeight: 600, color: T.ink }}>{r.name || '—'}</span>
                        <span style={{ fontSize: 12, color: T.muted }}>+{r.phone}</span>
                      </button>
                    </td>
                    <td style={{ padding: '10px 12px' }}>{r.ad_code || <span style={{ color: T.muted }}>—</span>}</td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                        <StatusBadge r={r} />
                        {r.needs_human && <Badge tone="bad" icon={CircleAlert}>Needs you</Badge>}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }} title={dateTime(r.first_message_at)}>{ago(r.first_message_at)}</td>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>{ago(r.last_inbound_at)}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>{r.status === 'paid' ? money(r.amount_paid) : '—'}</td>
                    <td style={{ padding: '10px 12px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.email || (r.status === 'paid' ? <Badge tone="warn">Missing</Badge> : '—')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data.total > PAGE_SIZE && (
        <div className="tnum" style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'flex-end', fontSize: 12.5, color: T.soft }}>
          <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}</span>
          <Button size="sm" icon={ChevronLeft} disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page" />
          <Button size="sm" icon={ChevronRight} disabled={page >= pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page" />
        </div>
      )}

      <LeadDrawer reg={open} funnel={funnel} canEdit={canEdit} isMobile={isMobile} showToast={showToast}
        onOpenLead={onOpenLead} onClose={() => setOpen(null)}
        onChanged={(updated) => { if (updated) setOpen(updated); refresh() }}
        onRemoved={() => { setOpen(null); refresh() }} />
    </div>
  )
}

function StatusBadge({ r }) {
  const s = REG_STATUS[r.status] || REG_STATUS.new
  const early = r.early_override_until && new Date(r.early_override_until) > new Date()
  return (
    <>
      <Badge tone={s.tone}>{s.label}{r.status === 'paid' && r.seats > 1 ? ` ×${r.seats}` : ''}</Badge>
      {early && r.status !== 'paid' && <Badge tone="info" icon={Clock}>Early price re-opened</Badge>}
    </>
  )
}

function LeadDrawer({ reg, funnel, canEdit, isMobile, showToast, onOpenLead, onClose, onChanged, onRemoved }) {
  const [events, setEvents] = useState(null)
  const [busy, setBusy] = useState(null)
  const [email, setEmail] = useState('')
  const [payOpen, setPayOpen] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  useEffect(() => {
    if (!reg) return
    setEmail(reg.email || '')
    setEvents(null)
    getRegistrationEvents(funnel.id, reg.id).then(setEvents).catch(() => setEvents([]))
  }, [reg, funnel.id])

  if (!reg) return null
  const run = async (key, fn, okMsg) => {
    setBusy(key)
    try {
      const res = await fn()
      showToast(okMsg)
      return res
    } catch (e) {
      showToast(errorMessage(e), 'bad')
      return null
    } finally {
      setBusy(null)
    }
  }
  const isPaid = reg.status === 'paid'
  const Row = ({ k, v }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '7px 0', borderTop: `1px solid ${T.line}`, fontSize: 13 }}>
      <span style={{ color: T.muted }}>{k}</span><span className="tnum" style={{ color: T.ink, textAlign: 'right', minWidth: 0, overflowWrap: 'anywhere' }}>{v}</span>
    </div>
  )

  return (
    <Drawer open={!!reg} onClose={onClose} isMobile={isMobile} title={reg.name || `+${reg.phone}`} subtitle={`+${reg.phone}`}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        <StatusBadge r={reg} />
        {reg.needs_human && <Badge tone="bad" icon={CircleAlert}>Needs you</Badge>}
      </div>

      {reg.lead_id && onOpenLead && (
        <Button variant="primary" icon={ExternalLink} style={{ width: '100%', marginBottom: 10 }} onClick={() => onOpenLead(reg.lead_id)}>
          Open chat in Lead Center
        </Button>
      )}
      {reg.needs_human && canEdit && (
        <Button icon={Check} style={{ width: '100%', marginBottom: 14 }} loading={busy === 'handled'}
          onClick={async () => { const r = await run('handled', () => patchRegistration(funnel.id, reg.id, { needs_human: false }), 'Marked handled'); if (r) onChanged(r) }}>
          Mark handled
        </Button>
      )}

      <div style={{ marginBottom: 16 }}>
        <Row k="Ad code" v={reg.ad_code || '—'} />
        <Row k="Referral code" v={reg.ref_code} />
        <Row k="First message" v={dateTime(reg.first_message_at)} />
        <Row k="Last reply" v={dateTime(reg.last_inbound_at)} />
        {isPaid && <Row k="Paid" v={`${money(reg.amount_paid)} · ${dateTime(reg.paid_at)}${reg.seats > 1 ? ` · ${reg.seats} seats` : ''}`} />}
        {reg.referred_by_id && <Row k="Referred" v="Yes (by another attendee)" />}
      </div>

      {canEdit && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 18 }}>
          {!isPaid && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button icon={Send} loading={busy === 'resend'} onClick={() => run('resend', () => resendLink(funnel.id, reg.id), 'Pay link sent')}>Resend pay link</Button>
              <Button icon={Clock} loading={busy === 'early'} onClick={async () => {
                const r = await run('early', () => grantEarly(funnel.id, reg.id, 24), 'Early price re-opened for 24 h. Resend the link to tell them.')
                if (r) onChanged({ ...reg, early_override_until: r.early_override_until })
              }}>Re-open early price</Button>
              <Button icon={Wallet} onClick={() => setPayOpen(true)}>Mark paid (transfer)</Button>
            </div>
          )}
          <Field label="Gmail for the Meet invite">
            <div style={{ display: 'flex', gap: 8 }}>
              <input type="email" style={INPUT} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@gmail.com" />
              <Button loading={busy === 'email'} disabled={email === (reg.email || '')}
                onClick={async () => { const r = await run('email', () => patchRegistration(funnel.id, reg.id, { email }), 'Gmail saved'); if (r) onChanged(r) }}>Save</Button>
            </div>
          </Field>
          {isPaid && !reg.email && (
            <Button icon={Mail} loading={busy === 'ask'} onClick={() => run('ask', () => askGmail(funnel.id, reg.id), 'Gmail request sent')}>Ask them for their Gmail</Button>
          )}
        </div>
      )}

      <h3 style={{ fontSize: 13, fontWeight: 700, color: T.ink, margin: '0 0 8px' }}>Timeline</h3>
      {events === null ? <Spinner /> : events.length === 0 ? <p style={{ fontSize: 12.5, color: T.muted, margin: 0 }}>Nothing yet.</p> : (
        <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {events.map((e, i) => (
            <li key={i} style={{ display: 'flex', gap: 10, padding: '8px 0', borderTop: i ? `1px solid ${T.line}` : 'none' }}>
              <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 4, marginTop: 6, flexShrink: 0,
                background: /paid|confirmed/.test(e.type) ? T.good : /fail|mismatch|opted/.test(e.type) ? T.bad : e.type === 'handoff' ? T.warn : '#B9CDD5' }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, color: T.ink }}>
                  {EVENT_LABEL[e.type] || e.type}
                  {e.step_key && !e.step_key.startsWith('bc_') && <code style={{ fontSize: 11.5, color: T.soft, marginLeft: 6 }}>{e.step_key}</code>}
                  {e.type === 'step_skipped' && e.detail?.reason && <span style={{ color: T.muted }}> · {SKIP_REASON[e.detail.reason] || e.detail.reason}</span>}
                  {e.type === 'pay_link_opened' && e.detail?.tier && <span style={{ color: T.muted }}> · {e.detail.tier} price</span>}
                </div>
                <div className="tnum" style={{ fontSize: 11.5, color: T.muted }}>{dateTime(e.created_at)}</div>
              </div>
            </li>
          ))}
        </ol>
      )}

      {canEdit && !isPaid && (
        <div style={{ marginTop: 22, paddingTop: 14, borderTop: `1px dashed ${T.line}` }}>
          <Button variant="danger" icon={RotateCcw} onClick={() => setConfirmReset(true)}>Reset test lead</Button>
          <p style={{ fontSize: 11.5, color: T.muted, margin: '6px 0 0' }}>For testing: deletes this lead’s funnel record so their next message starts from the greeting. Their Lead Center record stays.</p>
        </div>
      )}

      <MarkPaidModal key={payOpen ? `pay-${reg.id}` : 'closed'} open={payOpen} onClose={() => setPayOpen(false)} funnel={funnel}
        onConfirm={async (payload) => {
          const r = await run('paid', () => markPaid(funnel.id, reg.id, payload), 'Marked paid. Confirmation sent on WhatsApp.')
          if (r) { setPayOpen(false); onChanged(r) }
        }} busy={busy === 'paid'} />

      <Modal open={confirmReset} onClose={() => setConfirmReset(false)} title="Reset this test lead?" width={440}
        footer={<>
          <Button onClick={() => setConfirmReset(false)}>Cancel</Button>
          <Button variant="danger" loading={busy === 'reset'} onClick={async () => {
            const r = await run('reset', () => resetTestLead(funnel.id, reg.id), 'Lead reset')
            setConfirmReset(false)
            if (r !== null) onRemoved()
          }}>Reset</Button>
        </>}>
        <p style={{ margin: 0, fontSize: 13.5, color: T.ink }}>Their funnel history is deleted. The next message from <strong>+{reg.phone}</strong> gets the greeting again. Only unpaid leads can be reset.</p>
      </Modal>
    </Drawer>
  )
}

function MarkPaidModal({ open, onClose, funnel, onConfirm, busy }) {
  const [amount, setAmount] = useState(funnel.early_price)
  const [seats, setSeats] = useState(1)
  const [note, setNote] = useState('')
  return (
    <Modal open={open} onClose={onClose} title="Mark as paid" width={460}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={() => onConfirm({ amount: Number(amount), seats: Number(seats), note: note || undefined })}>Confirm payment</Button>
      </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <p style={{ margin: 0, fontSize: 13, color: T.soft }}>For bank transfers or cash. They get the seat confirmation, group link and Gmail request on WhatsApp.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {[funnel.early_price, funnel.regular_price, funnel.group_price].filter(Boolean).map((p) => (
            <Button key={p} size="sm" variant={Number(amount) === Number(p) ? 'primary' : 'secondary'}
              onClick={() => { setAmount(p); setSeats(p === funnel.group_price ? funnel.group_size : 1) }}>{money(p)}</Button>
          ))}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Amount (₦)"><input type="number" min={1} style={INPUT} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          <Field label="Seats"><input type="number" min={1} max={20} style={INPUT} value={seats} onChange={(e) => setSeats(e.target.value)} /></Field>
        </div>
        <Field label="Note (optional)"><input style={INPUT} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="e.g. GTB transfer, ref 1234" /></Field>
      </div>
    </Modal>
  )
}
