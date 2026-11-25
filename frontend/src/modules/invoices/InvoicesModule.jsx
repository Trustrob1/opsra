/**
 * frontend/src/modules/invoices/InvoicesModule.jsx
 * INV-2 — the Invoices page: money owed at a glance, every quote and invoice, and (admin) the invoice settings.
 * Shown to every product mode (full, WhatsApp-only, web-chat-only).
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus, Search, FileText } from 'lucide-react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import { useIsMobile } from '../../hooks/useIsMobile'
import { listDocs, getInvoiceSummary, apiError, isPlanBlocked } from '../../services/invoices.service'
import { naira, nairaShort, niceDate, TYPE_LABEL, card, inp, btnP, btnG } from './invoiceUi'
import StatusPill from './StatusPill'
import InvoiceEditor from './InvoiceEditor'
import InvoiceSettings from './InvoiceSettings'
import ReceiptsList from './ReceiptsList'   // INV-4

const FILTERS = [
  ['', 'All'], ['draft', 'Drafts'], ['issued', 'Issued'], ['overdue', 'Overdue'], ['part_paid', 'Part paid'],
  ['paid', 'Paid'], ['accepted', 'Accepted'], ['expired', 'Expired'], ['void', 'Void'],
]
const PAGE = 50

export default function InvoicesModule() {
  const isMobile = useIsMobile()
  const isAdmin = useAuthStore((s) => s.hasPermission)('is_admin')
  const [tab, setTab] = useState('docs')
  const [type, setType] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [rows, setRows] = useState(null)
  const [more, setMore] = useState(false)
  const [summary, setSummary] = useState(null)
  const [err, setErr] = useState('')
  const [blocked, setBlocked] = useState(false)
  const [editor, setEditor] = useState(null)   // { docId } | { initial }

  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t) }, [q])

  const load = useCallback((offset = 0) => {
    const params = { limit: PAGE, offset, ...(type ? { doc_type: type } : {}), ...(status ? { status } : {}), ...(dq ? { q: dq } : {}) }
    return listDocs(params).then((r) => {
      const items = r?.items || []
      setErr('')
      setRows((prev) => (offset ? [...(prev || []), ...items] : items))
      setMore(items.length === PAGE)
    }).catch((e) => {
      if (isPlanBlocked(e)) setBlocked(true)
      setErr(apiError(e, 'Could not load your documents. Please refresh.'))
      setRows([])
    })
  }, [type, status, dq])
  const loadSummary = useCallback(() => { getInvoiceSummary().then(setSummary).catch(() => {}) }, [])
  useEffect(() => { load(0) }, [load])
  useEffect(() => { loadSummary() }, [loadSummary])
  const refresh = () => { load(0); loadSummary() }

  if (blocked) {
    return (
      <div style={{ padding: isMobile ? 16 : 28 }}>
        <div style={{ ...card, maxWidth: 560 }}>
          <h2 style={{ margin: '0 0 8px', fontSize: 19, color: ds.dark }}>Quotes and invoices</h2>
          <p style={{ color: ds.gray, margin: 0 }}>{err}</p>
        </div>
      </div>
    )
  }

  const tile = (label, value, sub, tone) => (
    <div style={{ ...card, padding: '14px 16px', flex: '1 1 160px' }}>
      <div style={{ fontSize: 12.5, color: ds.gray, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone || ds.dark, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12.5, color: ds.gray, marginTop: 2 }}>{sub}</div>}
    </div>
  )
  const chip = (active, text, onClick) => (
    <button key={text} type="button" onClick={onClick} aria-pressed={active}
      style={{ padding: '0 14px', minHeight: 36, borderRadius: 999, border: `1.5px solid ${active ? ds.teal : ds.border}`, background: active ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13.5, cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: ds.fontDm }}>{text}</button>
  )
  const filtered = !!(status || type || dq)

  return (
    <div style={{ padding: isMobile ? 16 : 28, fontFamily: ds.fontDm }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 22, color: ds.dark, flex: 1 }}>Quotes & invoices</h1>
        <button type="button" style={btnG} onClick={() => setEditor({ initial: { doc_type: 'quote' } })}><Plus size={16} />New quote</button>
        <button type="button" style={btnP} onClick={() => setEditor({ initial: { doc_type: 'invoice' } })}><Plus size={16} />New invoice</button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {chip(tab === 'docs', 'Documents', () => setTab('docs'))}
        {chip(tab === 'receipts', 'Receipts', () => setTab('receipts'))}
        {isAdmin && chip(tab === 'settings', 'Settings', () => setTab('settings'))}
      </div>

      {tab === 'settings' && isAdmin ? <InvoiceSettings /> : tab === 'receipts' ? <ReceiptsList isAdmin={isAdmin} onChanged={loadSummary} /> : (
        <>
          {summary && (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
              {tile('Owed to you', nairaShort(summary.outstanding_amount), `${summary.outstanding_count} unpaid invoice${summary.outstanding_count === 1 ? '' : 's'}`)}
              {tile('Paid this month', nairaShort(summary.paid_this_month), 'from receipts', ds.green)}
              {tile('Overdue', nairaShort(summary.overdue_amount), `${summary.overdue_count} invoice${summary.overdue_count === 1 ? '' : 's'}`, summary.overdue_count ? ds.red : undefined)}
              {tile('Open quotes', nairaShort(summary.open_quotes_amount), `${summary.open_quotes} waiting for an answer`)}
              {tile('Drafts', String(summary.drafts), 'not issued yet')}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ position: 'relative', flex: '1 1 240px' }}>
              <Search size={16} color={ds.gray} style={{ position: 'absolute', left: 12, top: 13 }} />
              <input style={{ ...inp, paddingLeft: 34 }} placeholder="Search by customer or number" aria-label="Search by customer or number" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100} />
            </div>
            <select aria-label="Type" style={{ ...inp, width: 'auto', minWidth: 140 }} value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">Quotes and invoices</option><option value="invoice">Invoices</option><option value="quote">Quotes</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 6, marginBottom: 12 }}>
            {FILTERS.map(([v, t]) => chip(status === v, t, () => setStatus(v)))}
          </div>

          {err && <p role="alert" style={{ color: ds.red }}>{err}</p>}
          {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
          {rows && rows.length === 0 && !err && (
            <div style={{ ...card, textAlign: 'center', padding: 36 }}>
              <FileText size={30} color={ds.teal} />
              <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>{filtered ? 'Nothing matches these filters' : 'No quotes or invoices yet'}</p>
              <p style={{ color: ds.gray, margin: 0 }}>{filtered ? 'Try another filter or clear the search.' : 'Make your first one with New invoice. You can also start one from a lead or a chat.'}</p>
            </div>
          )}
          {rows && rows.length > 0 && (isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {rows.map((r) => (
                <button key={r.id} type="button" onClick={() => setEditor({ docId: r.id })}
                  style={{ ...card, padding: 14, textAlign: 'left', cursor: 'pointer', display: 'grid', gap: 6, fontFamily: ds.fontDm }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <b style={{ color: ds.dark }}>{r.customer_name || 'No name yet'}</b><StatusPill status={r.display_status} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: ds.gray, fontSize: 13.5 }}>
                    <span>{TYPE_LABEL[r.doc_type]} {r.number || '(draft)'} · {niceDate(r.issue_date || r.created_at)}</span>
                    <b style={{ color: ds.dark }}>{naira(r.total)}</b>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                <thead>
                  <tr style={{ background: ds.light, textAlign: 'left', color: ds.gray, fontSize: 12.5 }}>
                    {['Number', 'Customer', 'Type', 'Date', 'Due / valid until', 'Total', 'Balance', 'Status'].map((h, i) => (
                      <th key={h} style={{ padding: '10px 14px', fontWeight: 600, textAlign: i === 5 || i === 6 ? 'right' : 'left' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} onClick={() => setEditor({ docId: r.id })} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setEditor({ docId: r.id }) }}
                      style={{ borderTop: `1px solid ${ds.border}`, cursor: 'pointer' }}>
                      <td style={{ padding: '11px 14px', fontWeight: 600, color: ds.dark }}>{r.number || <span style={{ color: ds.gray, fontWeight: 500 }}>Draft</span>}</td>
                      <td style={{ padding: '11px 14px' }}>{r.customer_name || <span style={{ color: ds.gray }}>No name yet</span>}</td>
                      <td style={{ padding: '11px 14px' }}>{TYPE_LABEL[r.doc_type]}</td>
                      <td style={{ padding: '11px 14px', whiteSpace: 'nowrap' }}>{niceDate(r.issue_date || r.created_at)}</td>
                      <td style={{ padding: '11px 14px', whiteSpace: 'nowrap' }}>{niceDate(r.due_date)}</td>
                      <td style={{ padding: '11px 14px', textAlign: 'right', whiteSpace: 'nowrap' }}>{naira(r.total)}</td>
                      <td style={{ padding: '11px 14px', textAlign: 'right', whiteSpace: 'nowrap' }}>{r.doc_type === 'invoice' && !['draft', 'void'].includes(r.status) ? naira(r.balance_due) : '—'}</td>
                      <td style={{ padding: '11px 14px' }}><StatusPill status={r.display_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {more && <div style={{ textAlign: 'center', marginTop: 14 }}><button type="button" style={btnG} onClick={() => load(rows.length)}>Show more</button></div>}
        </>
      )}

      {editor && <InvoiceEditor docId={editor.docId} initial={editor.initial} onClose={() => setEditor(null)} onChanged={refresh} />}
    </div>
  )
}
