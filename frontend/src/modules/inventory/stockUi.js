/**
 * frontend/src/modules/inventory/stockUi.js
 * STOCK-1 — shared look for the Inventory screens (same cards, inputs and buttons as Invoices).
 */
export { card, lab, inp, btnP, btnG, btnDanger, disabled, naira, nairaShort } from '../invoices/invoiceUi'

export const units = (n) => Number(n || 0).toLocaleString('en-NG')
export const sizeText = (variant) => (variant ? variant : 'One size')
export const signed = (n) => (n > 0 ? `+${units(n)}` : n < 0 ? `−${units(-n)}` : '0')
export const dateTime = (v) => {
  if (!v) return '—'
  const dt = new Date(v)
  return Number.isNaN(dt.getTime()) ? '—'
    : dt.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
export const ADJUST_REASONS = [
  ['recount', 'Stock count'], ['damaged', 'Damaged'], ['lost', 'Lost or stolen'], ['found', 'Found'],
  ['returned', 'Returned by customer'], ['other', 'Other'],
]
export const errBox = { background: '#FFF5F5', border: '1px solid #F5C2C2', color: '#9B2C2C', borderRadius: 10, padding: '10px 14px', marginBottom: 14, fontSize: 14 }
export const th = { padding: '10px 14px', fontWeight: 600, fontSize: 12.5, whiteSpace: 'nowrap' }
export const td = { padding: '11px 14px', fontSize: 14 }
