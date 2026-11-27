/**
 * frontend/src/modules/invoices/invoiceUi.js
 * INV-2 — shared look, money format and status labels for the invoice screens.
 */
import { ds } from '../../utils/ds'

export const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
export const nairaShort = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
export const niceDate = (v) => {
  if (!v) return '—'
  const dt = new Date(`${String(v).slice(0, 10)}T00:00:00`)
  return Number.isNaN(dt.getTime()) ? '—' : dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}
export const todayYmd = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** [label, background, text colour] — status words a business owner reads at a glance. */
export const STATUS = {
  draft:     ['Draft', '#F3F4F6', '#4B5563'],
  issued:    ['Issued', '#E4EDFD', '#1F54B8'],
  accepted:  ['Accepted', '#E8F8EE', '#1A7A40'],
  declined:  ['Declined', '#FFE8E8', '#C0392B'],
  part_paid: ['Part paid', '#FFF3E0', '#C05A00'],
  paid:      ['Paid', '#E8F8EE', '#1A7A40'],
  void:      ['Void', '#F3F4F6', '#6B7280'],
  overdue:   ['Overdue', '#FFE8E8', '#C0392B'],
  expired:   ['Expired', '#FFF9E0', '#A07C00'],
}
export const TYPE_LABEL = { quote: 'Quote', invoice: 'Invoice' }
export const METHOD_LABEL = { bank_transfer: 'Bank transfer', cash: 'Cash', pos: 'POS', ussd: 'USSD', paystack: 'Paystack (online)', other: 'Other' }

export const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.xl, padding: '18px 20px', boxShadow: ds.cardShadow }
export const lab = { display: 'block', fontSize: 11, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 5 }
export const inp = { width: '100%', boxSizing: 'border-box', padding: '9px 12px', minHeight: 42, border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md, fontSize: 14, color: ds.dark, background: '#fff', fontFamily: ds.fontDm }
export const btnP = { background: ds.teal, color: '#fff', border: 'none', borderRadius: ds.radius.md, padding: '0 18px', minHeight: 42, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontDm, display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center' }
export const btnG = { background: '#fff', color: ds.tealDark, border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md, padding: '0 14px', minHeight: 42, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontDm, display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center' }
export const btnDanger = { ...btnG, color: ds.red, borderColor: '#F5C2C2' }
export const disabled = (style, off) => (off ? { ...style, opacity: 0.55, cursor: 'not-allowed' } : style)

// REVISE-1: the accounts a sales rep may pick for a region: the region's own; if none, the ones linked to no region
// (else all). Same rule as the server (invoice_service.accounts_for_region).
export function accountsForRegion(accounts, region) {
  const list = accounts || []
  const want = (region || '').trim().toLowerCase()
  if (!want) return list
  const mine = list.filter((a) => (a.region || '').toLowerCase() === want)
  if (mine.length) return mine
  const free = list.filter((a) => !a.region)
  return free.length ? free : list
}
