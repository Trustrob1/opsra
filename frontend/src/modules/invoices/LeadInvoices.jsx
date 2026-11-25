/**
 * frontend/src/modules/invoices/LeadInvoices.jsx
 * INV-2 — the Invoices tab on a lead: this lead's quotes and invoices, and buttons to start new ones for them.
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { ds } from '../../utils/ds'
import { listDocs, apiError } from '../../services/invoices.service'
import { naira, niceDate, TYPE_LABEL, btnP, btnG } from './invoiceUi'
import StatusPill from './StatusPill'
import InvoiceEditor from './InvoiceEditor'

export default function LeadInvoices({ leadId }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [editor, setEditor] = useState(null)
  const load = useCallback(() => {
    listDocs({ lead_id: leadId, limit: 100 }).then((r) => setRows(r?.items || [])).catch((e) => { setErr(apiError(e)); setRows([]) })
  }, [leadId])
  useEffect(() => { load() }, [load])

  return (
    <div style={{ padding: 16, fontFamily: ds.fontDm }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
        <button type="button" style={btnG} onClick={() => setEditor({ initial: { doc_type: 'quote', lead_id: leadId } })}><Plus size={16} />New quote</button>
        <button type="button" style={btnP} onClick={() => setEditor({ initial: { doc_type: 'invoice', lead_id: leadId } })}><Plus size={16} />New invoice</button>
      </div>
      {err && <p role="alert" style={{ color: ds.red }}>{err}</p>}
      {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {rows && rows.length === 0 && !err && <p style={{ color: ds.gray }}>No quotes or invoices for this lead yet.</p>}
      {rows && rows.map((r) => (
        <button key={r.id} type="button" onClick={() => setEditor({ docId: r.id })}
          style={{ display: 'flex', width: '100%', alignItems: 'center', gap: 12, padding: '12px 14px', marginBottom: 8, border: `1px solid ${ds.border}`, borderRadius: 10, background: '#fff', cursor: 'pointer', fontFamily: ds.fontDm, textAlign: 'left', minHeight: 44 }}>
          <span style={{ flex: 1, minWidth: 0 }}>
            <b style={{ color: ds.dark }}>{TYPE_LABEL[r.doc_type]} {r.number || '(draft)'}</b>
            <span style={{ display: 'block', color: ds.gray, fontSize: 13 }}>{niceDate(r.issue_date || r.created_at)}</span>
          </span>
          <b style={{ color: ds.dark, whiteSpace: 'nowrap' }}>{naira(r.total)}</b>
          <StatusPill status={r.display_status} />
        </button>
      ))}
      {editor && <InvoiceEditor docId={editor.docId} initial={editor.initial} onClose={() => setEditor(null)} onChanged={load} />}
    </div>
  )
}
