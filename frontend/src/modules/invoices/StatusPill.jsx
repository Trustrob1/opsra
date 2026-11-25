/**
 * frontend/src/modules/invoices/StatusPill.jsx
 * INV-2 — coloured status word for a quote or invoice.
 */
import { STATUS } from './invoiceUi'

export default function StatusPill({ status }) {
  const [text, bg, fg] = STATUS[status] || [status, '#F3F4F6', '#4B5563']
  return <span style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 999, background: bg, color: fg, fontSize: 12.5, fontWeight: 600, whiteSpace: 'nowrap' }}>{text}</span>
}
