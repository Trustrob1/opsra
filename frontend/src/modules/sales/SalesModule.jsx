/**
 * frontend/src/modules/sales/SalesModule.jsx
 * SALE-1 — the Sales page: Make a sale, the sales this person made (owners, ops managers and admins see everyone's),
 * and the payments waiting for an admin's OK (admins confirm; reps see theirs and can take one back).
 * The records themselves are ordinary invoices and receipts, so they also show in Invoices.
 * REPORT-1 — Report tab (owners and admins); people the business named as payment confirmers see Payments to confirm.
 */
import { useCallback, useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import { listSales, listPaymentApprovals, getInvoiceSummary, apiError, isPlanBlocked } from '../../services/invoices.service'
import { naira, niceDate, card, inp, btnG } from '../invoices/invoiceUi'
import StatusPill from '../invoices/StatusPill'
import InvoiceEditor from '../invoices/InvoiceEditor'
import { PendingPaymentRow } from '../invoices/PendingPayments'
import SaleForm from './SaleForm'
import SalesReport from './SalesReport'

const PAGE = 50

export default function SalesModule() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = useAuthStore((s) => s.hasPermission)('is_admin')
  const manager = ['owner', 'ops_manager'].includes(user?.roles?.template) || isAdmin
  const reports = isAdmin   // owners count as admins
  const [canConfirm, setCanConfirm] = useState(manager)
  const [tab, setTab] = useState('new')
  const [openId, setOpenId] = useState(null)
  const [waiting, setWaiting] = useState(0)
  const [blocked, setBlocked] = useState(false)
  const [tick, setTick] = useState(0)
  const refresh = () => setTick((t) => t + 1)

  useEffect(() => {
    getInvoiceSummary().then((s) => { setWaiting(s?.payments_waiting || 0); setCanConfirm(!!s?.can_confirm_payments) }).catch((e) => { if (isPlanBlocked(e)) setBlocked(true) })
  }, [tick])

  if (blocked) return <div style={{ padding: 24 }}><div style={{ ...card, color: ds.gray }}>Make a sale uses Invoices, which is not included in your plan. Open Billing to see the plans.</div></div>

  const tabs = [['new', 'Make a sale'], ['mine', manager ? 'All sales' : 'My sales'],
    ['waiting', `${canConfirm ? 'Payments to confirm' : 'Waiting for an admin'}${waiting ? ` (${waiting})` : ''}`],
    ...(reports ? [['report', 'Report']] : [])]
  return (
    <div style={{ padding: 'clamp(14px, 3vw, 28px)', maxWidth: 1000, margin: '0 auto', display: 'grid', gap: 16, fontFamily: ds.fontDm }}>
      <h1 style={{ margin: 0, fontSize: 24, color: ds.dark }}>Sales</h1>
      <div role="tablist" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', borderBottom: `1px solid ${ds.border}` }}>
        {tabs.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            style={{ border: 'none', background: 'none', padding: '10px 12px', minHeight: 44, cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 14.5,
              fontWeight: 600, color: tab === id ? ds.tealDark : ds.gray, borderBottom: `2px solid ${tab === id ? ds.teal : 'transparent'}`, marginBottom: -1 }}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'new' && <SaleForm onOpenInvoice={setOpenId} onSaved={refresh} />}
      {tab === 'mine' && <SalesList key={tick} onOpen={setOpenId} />}
      {tab === 'waiting' && <Approvals key={tick} manager={canConfirm} onChanged={refresh} />}
      {tab === 'report' && reports && <SalesReport />}
      {openId && <InvoiceEditor docId={openId} onClose={() => setOpenId(null)} onChanged={refresh} />}
    </div>
  )
}

function SalesList({ onOpen }) {
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [rows, setRows] = useState(null)
  const [more, setMore] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t) }, [q])
  const load = useCallback((offset = 0) => listSales({ limit: PAGE, offset, ...(dq ? { q: dq } : {}) }).then((r) => {
    const items = r?.items || []
    setErr(''); setRows((prev) => (offset ? [...(prev || []), ...items] : items)); setMore(items.length === PAGE)
  }).catch((e) => { setErr(apiError(e, 'Could not load sales. Please refresh.')); setRows([]) }), [dq])
  useEffect(() => { load(0) }, [load])

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ position: 'relative' }}>
        <Search size={16} color={ds.gray} style={{ position: 'absolute', left: 12, top: 13 }} />
        <input style={{ ...inp, paddingLeft: 34 }} placeholder="Search by customer or number" aria-label="Search sales" maxLength={100} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {err && <p role="alert" style={{ color: ds.red, margin: 0 }}>{err}</p>}
      {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {rows && rows.length === 0 && !err && <div style={{ ...card, color: ds.gray }}>No sales yet. Make one from the Make a sale tab.</div>}
      {rows && rows.length > 0 && (
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          {rows.map((d, i) => (
            <button key={d.id} type="button" onClick={() => onOpen(d.id)}
              style={{ display: 'flex', width: '100%', gap: 12, alignItems: 'center', flexWrap: 'wrap', textAlign: 'left', border: 'none', borderTop: i ? `1px solid ${ds.border}` : 'none',
                background: '#fff', padding: '12px 16px', minHeight: 56, cursor: 'pointer', fontFamily: ds.fontDm }}>
              <div style={{ flex: '1 1 200px' }}>
                <div style={{ fontWeight: 600, color: ds.dark }}>{d.customer_name || 'No name'}</div>
                <div style={{ fontSize: 12.5, color: ds.gray }}>{[d.number || 'Draft', niceDate(d.issue_date || d.created_at)].join(' · ')}</div>
              </div>
              {Number(d.waiting_amount) > 0 && <span style={{ fontSize: 12.5, color: '#C05A00' }}>{naira(d.waiting_amount)} waiting</span>}
              <StatusPill status={d.display_status || d.status} />
              <b style={{ minWidth: 120, textAlign: 'right', color: ds.dark }}>{naira(d.total)}</b>
            </button>
          ))}
        </div>
      )}
      {more && <button type="button" style={{ ...btnG, justifySelf: 'center' }} onClick={() => load(rows.length)}>Show more</button>}
    </div>
  )
}

function Approvals({ manager, onChanged }) {
  const [status, setStatus] = useState('pending')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(() => listPaymentApprovals(status).then((r) => { setErr(''); setData(r) })
    .catch((e) => { setErr(apiError(e, 'Could not load payments. Please refresh.')); setData({ items: [] }) }), [status])
  useEffect(() => { load() }, [load])
  const changed = () => { load(); onChanged?.() }
  const items = data?.items || []
  const empty = { pending: manager ? 'Nothing to confirm. Payments reps record show here when Invoices > Settings > Payments asks for confirmation.' : 'None of your payments are waiting.',
    approved: 'No confirmed payments yet.', rejected: 'No rejected payments.' }[status]
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {[['pending', 'Waiting'], ['approved', 'Confirmed'], ['rejected', 'Rejected']].map(([id, label]) => (
          <button key={id} type="button" aria-pressed={status === id} onClick={() => setStatus(id)}
            style={{ ...btnG, minHeight: 36, background: status === id ? ds.mint : '#fff', borderColor: status === id ? ds.teal : ds.border }}>{label}</button>
        ))}
      </div>
      {err && <p role="alert" style={{ color: ds.red, margin: 0 }}>{err}</p>}
      {data === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {data && items.length === 0 && !err && <div style={{ ...card, color: ds.gray }}>{empty}</div>}
      {items.length > 0 && (
        <div style={{ ...card, display: 'grid', gap: 2, paddingTop: 8 }}>
          {items.map((p) => <PendingPaymentRow key={p.id} p={p} showInvoice canConfirm={!!data?.can_confirm} onChanged={changed} />)}
        </div>
      )}
    </div>
  )
}
