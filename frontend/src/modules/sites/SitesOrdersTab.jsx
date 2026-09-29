/**
 * frontend/src/modules/sites/SitesOrdersTab.jsx
 * SITE-3 part 3 — Orders (spec §13): every order with its quote breakdown, cost and profit,
 * Approve / Reject (the approval window is shown), refund status, and the way out of a
 * "needs a new domain" order.
 *
 * Approve / Reject / Record refund are owner-only (spec §17) — `canApprove`.
 * Pattern 26: this panel stays mounted; it fetches only while `isActive`.
 */
import { useCallback, useEffect, useState } from 'react'
import { Search, Inbox, Clock, ShieldCheck, Wallet, Hourglass, TriangleAlert, ArrowLeftRight } from 'lucide-react'
import {
  listOrders, approveOrder, rejectOrder, recordRefund, setOrderDomain, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty, Field, Modal, Drawer, Segmented } from './sitesUi'
import { Th, Td, Fact, AmountLine } from './sitesOpsUi'
import { T, INPUT, TEXTAREA, money, dateTime, ORDER_STATUS } from './sitesKit'
import { useIsMobile } from '../../hooks/useIsMobile'

const FILTERS = [
  { value: '', label: 'All' },
  { value: 'awaiting_approval', label: 'Needs approval' },
  { value: 'fulfilling', label: 'Being set up' },
  { value: 'live', label: 'Live' },
  { value: 'refund_pending', label: 'Refunds due' },
]

const tldOf = (domain) => {
  const d = String(domain || '')
  const i = d.indexOf('.')
  return i > 0 ? d.slice(i) : ''
}

export default function SitesOrdersTab({ isActive, canApprove, canEdit, showToast, onGoHosting, onChanged }) {
  const isMobile = useIsMobile()
  const [data, setData] = useState({ items: [], total: 0, approval: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')
  const [search, setSearch] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [detailId, setDetailId] = useState(null)
  const [modal, setModal] = useState(null) // { kind: 'reject' | 'refund' | 'domain', order }

  const load = useCallback(async () => {
    setError(null)
    try {
      const params = {}
      if (filter) params.status = filter
      if (search.trim()) params.search = search.trim()
      setData(await listOrders(params))
    } catch (e) {
      setError(errorMessage(e, 'Could not load orders.'))
    } finally {
      setLoading(false)
    }
  }, [filter, search])

  useEffect(() => {
    if (!isActive) return undefined
    setLoading(true)
    const t = setTimeout(load, search ? 250 : 0) // debounce typing only
    return () => clearTimeout(t)
  }, [isActive, load, search])

  const changed = useCallback(async () => { await load(); onChanged?.() }, [load, onChanged])

  const approve = async (order) => {
    setBusyId(order.id)
    try {
      const res = await approveOrder(order.id)
      showToast(res?.express_pending ? 'Approved — Express orders are set up by hand for now' : 'Approved — the hosting job is in the queue')
      await changed()
    } catch (e) {
      showToast(errorMessage(e, 'Could not approve this order.'), 'bad')
      await load() // the order may have moved (someone else handled it) — show the truth
    } finally {
      setBusyId(null)
    }
  }

  const approval = data.approval
  const detail = data.items.find((o) => o.id === detailId) || null
  const onAction = { approve, reject: (o) => setModal({ kind: 'reject', order: o }), refund: (o) => setModal({ kind: 'refund', order: o }),
    domain: (o) => setModal({ kind: 'domain', order: o }), open: (o) => setDetailId(o.id), hosting: () => onGoHosting?.() }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <ApprovalBanner approval={approval} />

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <Segmented ariaLabel="Filter orders" value={filter} onChange={setFilter} options={FILTERS} />
        <div style={{ position: 'relative', flex: '1 1 220px', maxWidth: 320 }}>
          <Search size={15} color={T.muted} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} aria-hidden="true" />
          <input style={{ ...INPUT, paddingLeft: 32 }} placeholder="Search domain, business or builder" aria-label="Search orders"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      {loading ? <Spinner /> : data.items.length === 0 ? (
        <Card>
          <Empty icon={Inbox} title={filter || search ? 'No orders match' : 'No orders yet'}
            text={filter || search ? 'Try a different filter or clear the search.'
              : 'Orders appear here as soon as a builder starts checkout. Paid ones wait for your approval while approvals are on.'}
            action={(filter || search) && <Button onClick={() => { setFilter(''); setSearch('') }}>Clear filters</Button>} />
        </Card>
      ) : isMobile ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {data.items.map((o) => <OrderCard key={o.id} order={o} busy={busyId === o.id} canApprove={canApprove} canEdit={canEdit}
            inWindow={approval?.in_window !== false} on={onAction} />)}
        </div>
      ) : (
        <Card pad={0}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 860 }}>
              <thead><tr>
                <Th>Order</Th><Th>Builder</Th><Th align="right">Amount</Th><Th align="right">Profit</Th><Th>Status</Th><Th>Paid</Th><Th>{' '}</Th>
              </tr></thead>
              <tbody>
                {data.items.map((o) => (
                  <tr key={o.id} className="sts-row" style={{ borderTop: `1px solid ${T.line}` }}>
                    <Td>
                      <button type="button" onClick={() => onAction.open(o)}
                        style={{ all: 'unset', cursor: 'pointer', display: 'block', minWidth: 0 }} aria-label={`Open details for ${o.domain}`}>
                        <span style={{ fontWeight: 600, color: T.ink }}>{o.domain}</span>
                        <span style={{ display: 'block', fontSize: 12, color: T.muted }}>{o.client_business_name || '—'}</span>
                      </button>
                    </Td>
                    <Td>{o.builder_name || '—'}{o.builder_business && <span style={{ display: 'block', fontSize: 12, color: T.muted }}>{o.builder_business}</span>}</Td>
                    <Td align="right" className="tnum">{money(o.amount)}</Td>
                    <Td align="right" className="tnum">{money(o.expected_profit)}</Td>
                    <Td><StatusBadge order={o} /></Td>
                    <Td className="tnum">{paidLabel(o)}</Td>
                    <Td align="right"><OrderActions order={o} busy={busyId === o.id} canApprove={canApprove} canEdit={canEdit}
                      inWindow={approval?.in_window !== false} on={onAction} /></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="tnum" style={{ margin: 0, padding: '10px 14px', fontSize: 11.5, color: T.muted, borderTop: `1px solid ${T.line}` }}>
            {data.total} order{data.total === 1 ? '' : 's'}
          </p>
        </Card>
      )}

      <OrderDrawer order={detail} onClose={() => setDetailId(null)} isMobile={isMobile} canApprove={canApprove} canEdit={canEdit}
        busy={busyId === detail?.id} inWindow={approval?.in_window !== false} on={onAction} />

      <RejectModal order={modal?.kind === 'reject' ? modal.order : null} onClose={() => setModal(null)}
        onDone={async (msg) => { setModal(null); setDetailId(null); showToast(msg); await changed() }} showToast={showToast} />
      <RefundModal order={modal?.kind === 'refund' ? modal.order : null} onClose={() => setModal(null)}
        onDone={async () => { setModal(null); showToast('Refund recorded'); await changed() }} showToast={showToast} />
      <DomainModal order={modal?.kind === 'domain' ? modal.order : null} onClose={() => setModal(null)}
        onDone={async () => { setModal(null); showToast('Domain updated — the job is back in the queue'); await changed() }} showToast={showToast} />
    </div>
  )
}

// ── Pieces ──────────────────────────────────────────────────────────────

function paidLabel(o) {
  if (!o.sla_due_at) return '—'
  return dateTime(new Date(new Date(o.sla_due_at).getTime() - 24 * 3600 * 1000).toISOString())
}

function StatusBadge({ order }) {
  const st = ORDER_STATUS[order.status] || { tone: 'neutral', label: order.status }
  return <Badge tone={st.tone}>{st.label}</Badge>
}

function ApprovalBanner({ approval }) {
  if (!approval) return null
  if (!approval.required) {
    return <Notice tone="info" icon={ShieldCheck}>Approvals are off — paid orders go straight to hosting. You can switch them back on in Settings.</Notice>
  }
  const left = approval.orders_remaining
  return (
    <Notice tone={approval.in_window ? 'info' : 'warn'} icon={approval.in_window ? ShieldCheck : Clock}>
      <strong>Approvals are on.</strong>{' '}
      You can approve orders between {approval.window_start} and {approval.window_end} ({approval.timezone}) —{' '}
      {approval.in_window
        ? 'the window is open now.'
        : `it's closed right now; paid orders wait and can be approved from ${approval.window_start}.`}
      {left !== null && left !== undefined && <> {left} approval{left === 1 ? '' : 's'} left before you planned to switch them off.</>}
    </Notice>
  )
}

function OrderActions({ order, busy, canApprove, canEdit, inWindow, on }) {
  const s = order.status
  return (
    <div style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
      {s === 'awaiting_approval' && canApprove && (<>
        <Button size="sm" variant="primary" loading={busy} disabled={!inWindow} onClick={() => on.approve(order)}
          title={!inWindow ? 'Approvals are closed until the window opens' : undefined}>Approve</Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => on.reject(order)}>Reject</Button>
      </>)}
      {s === 'refund_pending' && canApprove && <Button size="sm" variant="primary" onClick={() => on.refund(order)}>Record refund</Button>}
      {s === 'needs_builder_choice' && (<>
        {canEdit && <Button size="sm" variant="primary" onClick={() => on.domain(order)}>Set new domain</Button>}
        {canApprove && <Button size="sm" variant="danger" onClick={() => on.reject(order)}>Refund builder</Button>}
      </>)}
      {s === 'fulfilling' && <Button size="sm" onClick={on.hosting}>Open in queue</Button>}
      <Button size="sm" variant="ghost" onClick={() => on.open(order)}>Details</Button>
    </div>
  )
}

function OrderCard({ order, busy, canApprove, canEdit, inWindow, on }) {
  return (
    <Card pad={14}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <p style={{ margin: 0, fontWeight: 700, color: T.ink, overflowWrap: 'anywhere' }}>{order.domain}</p>
          <p style={{ margin: '2px 0 0', fontSize: 12.5, color: T.muted }}>{order.client_business_name || '—'} · {order.builder_name || '—'}</p>
        </div>
        <StatusBadge order={order} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, margin: '12px 0' }}>
        <Fact label="Amount"><span className="tnum">{money(order.amount)}</span></Fact>
        <Fact label="Expected profit"><span className="tnum">{money(order.expected_profit)}</span></Fact>
      </div>
      <OrderActions order={order} busy={busy} canApprove={canApprove} canEdit={canEdit} inWindow={inWindow} on={on} />
    </Card>
  )
}

function OrderDrawer({ order, onClose, isMobile, canApprove, canEdit, busy, inWindow, on }) {
  if (!order) return null
  const q = order.quote || {}
  const price = q.price || {}
  const cost = q.cost || {}
  const owner = order.legal_owner || {}
  return (
    <Drawer open onClose={onClose} isMobile={isMobile} title={order.domain}
      subtitle={`${order.client_business_name || 'Unnamed site'} · ${order.builder_name || 'No builder'}`}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <StatusBadge order={order} />
          <Badge tone="neutral">{order.route === 'express' ? 'Express' : 'Standard'}</Badge>
          {order.hosting_job && <Badge tone={({ green: 'good', amber: 'warn', red: 'bad', done: 'neutral' })[order.hosting_job.sla_state] || 'neutral'}
            icon={Hourglass}>Hosting job {order.hosting_job.status.replace('_', ' ')}</Badge>}
        </div>

        <OrderActions order={order} busy={busy} canApprove={canApprove} canEdit={canEdit} inWindow={inWindow} on={on} />

        <section aria-label="Price breakdown">
          <h3 style={{ margin: '0 0 6px', fontSize: 13.5, color: T.ink }}>What the builder paid</h3>
          <AmountLine label="Domain" value={price.domain} />
          <AmountLine label="Hosting" value={price.hosting} />
          <AmountLine label="Service fee (not refundable)" value={price.service_fee} />
          {Number(price.renewal_adjustment) > 0 && <AmountLine label="Renewal adjustment" value={price.renewal_adjustment} />}
          <AmountLine label="Total paid" value={order.amount} strong />
          <h3 style={{ margin: '16px 0 6px', fontSize: 13.5, color: T.ink }}>What it costs us</h3>
          <AmountLine label="Domain" value={cost.domain} muted />
          <AmountLine label="Hosting" value={cost.hosting} muted />
          <AmountLine label="AI and messaging (estimate)" value={cost.ai_messages} muted />
          <AmountLine label="Payment fee (estimate)" value={q.gateway_fee} muted />
          <AmountLine label="Expected profit" value={order.expected_profit} strong />
          <p style={{ margin: '8px 0 0', fontSize: 12, color: T.muted }}>
            Suggested price for the builder's client: <span className="tnum">{money(q.suggested_client_price)}</span>
          </p>
        </section>

        <section aria-label="Order details" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14 }}>
          <Fact label="Main domain">{order.domain}</Fact>
          <Fact label="Backup domain">{order.backup_domain}</Fact>
          <Fact label="Paid">{paidLabel(order)}</Fact>
          <Fact label="Hosting deadline">{order.sla_due_at ? dateTime(order.sla_due_at) : '—'}</Fact>
          <Fact label="Approved">{order.approved_at ? dateTime(order.approved_at) : '—'}</Fact>
          <Fact label="Payment reference"><code style={{ fontSize: 12 }}>{order.payment_reference}</code></Fact>
        </section>

        {(order.refund_due != null || order.refund_amount != null || order.rejected_reason) && (
          <section aria-label="Refund">
            <h3 style={{ margin: '0 0 6px', fontSize: 13.5, color: T.ink }}>Refund</h3>
            {order.rejected_reason && <p style={{ margin: '0 0 8px', fontSize: 13, color: T.soft }}>Reason: {order.rejected_reason}</p>}
            <AmountLine label={order.status === 'refunded' ? 'Refunded' : 'Refund owed (paid − service fee)'}
              value={order.status === 'refunded' ? order.refund_amount : (order.refund_amount ?? order.refund_due)} />
            {order.refunded_at && <p style={{ margin: '4px 0 0', fontSize: 12, color: T.muted }}>Sent {dateTime(order.refunded_at)}</p>}
          </section>
        )}

        <section aria-label="Client details">
          <h3 style={{ margin: '0 0 2px', fontSize: 13.5, color: T.ink }}>The client (legal owner)</h3>
          <p style={{ margin: '0 0 8px', fontSize: 12, color: T.muted }}>Used only to register the domain.</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
            <Fact label="Name">{owner.full_name}</Fact>
            <Fact label="Email">{owner.email}</Fact>
            <Fact label="Phone">{owner.phone}</Fact>
            <Fact label="Address">{owner.address}</Fact>
          </div>
        </section>
      </div>
    </Drawer>
  )
}

// ── Modals ──────────────────────────────────────────────────────────────

function RejectModal({ order, onClose, onDone, showToast }) {
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (order) setReason('') }, [order])
  if (!order) return null
  const isRefund = order.status === 'needs_builder_choice'
  const refund = order.refund_amount ?? order.refund_due
  const submit = async () => {
    if (reason.trim().length < 3) { showToast('Add a short reason first', 'bad'); return }
    setSaving(true)
    try {
      await rejectOrder(order.id, reason.trim())
      onDone(isRefund ? 'Refund started — a task was added to send it' : 'Order rejected — a task was added to send the refund')
    } catch (e) {
      showToast(errorMessage(e, 'Could not reject this order.'), 'bad')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal open onClose={onClose} title={isRefund ? `Refund ${order.domain}?` : `Reject ${order.domain}?`}
      footer={<><Button onClick={onClose}>Keep order</Button>
        <Button variant="danger" loading={saving} onClick={submit}>{isRefund ? 'Refund builder' : 'Reject and refund'}</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Notice tone="warn" icon={Wallet}>
          The builder is owed <strong className="tnum">{money(refund)}</strong> — everything except our {money(order.service_fee)} service fee.
          They'll be told, and a task is created for you to send the refund by hand in Paystack. Then click “Record refund” here.
        </Notice>
        <Field label="Reason" hint="For your records — the builder isn't shown this." count={reason.length} max={1000}>
          <textarea style={TEXTAREA} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} autoFocus />
        </Field>
      </div>
    </Modal>
  )
}

function RefundModal({ order, onClose, onDone, showToast }) {
  const [amount, setAmount] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (order) setAmount(String(order.refund_amount ?? order.refund_due ?? '')) }, [order])
  if (!order) return null
  const submit = async () => {
    const n = Number(amount)
    if (!Number.isFinite(n) || n <= 0 || n > Number(order.amount)) { showToast(`Enter an amount up to ${money(order.amount)}`, 'bad'); return }
    setSaving(true)
    try {
      await recordRefund(order.id, n)
      onDone()
    } catch (e) {
      showToast(errorMessage(e, 'Could not record this refund.'), 'bad')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal open onClose={onClose} title={`Record refund for ${order.domain}`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={saving} onClick={submit}>Record refund</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Notice tone="info" icon={TriangleAlert}>Only record this once the money has been sent in Paystack. The builder gets a message saying it's on its way.</Notice>
        <Field label="Amount refunded (₦)" hint={`Paid ${money(order.amount)}. The default leaves out the ${money(order.service_fee)} service fee.`}>
          <input style={INPUT} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus />
        </Field>
      </div>
    </Modal>
  )
}

function DomainModal({ order, onClose, onDone, showToast }) {
  const [domain, setDomain] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (order) setDomain('') }, [order])
  if (!order) return null
  const tld = tldOf(order.domain)
  const submit = async () => {
    if (!domain.trim()) { showToast('Enter the domain the builder chose', 'bad'); return }
    setSaving(true)
    try {
      await setOrderDomain(order.id, domain.trim())
      onDone()
    } catch (e) {
      showToast(errorMessage(e, 'Could not use that domain.'), 'bad')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal open onClose={onClose} title="Set a new domain"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={ArrowLeftRight} loading={saving} onClick={submit}>Use this domain</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Notice tone="warn" icon={TriangleAlert}>
          Both {order.domain} and {order.backup_domain} were taken. Enter the new domain the builder chose — we check it's free right now, then the job goes back in the queue.
        </Notice>
        <Field label="New domain" hint={tld ? `It must end in ${tld} like the original — a different ending changes the price (refund instead).` : undefined}>
          <input style={INPUT} value={domain} placeholder={`yourbrand${tld}`} onChange={(e) => setDomain(e.target.value)}
            autoCapitalize="none" autoCorrect="off" spellCheck={false} autoFocus />
        </Field>
      </div>
    </Modal>
  )
}
