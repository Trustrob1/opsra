/**
 * frontend/src/modules/inventory/moveRequestUi.js
 * STOCK-4 — shared words for stock requests, deliveries from a warehouse and the movement records.
 */
import { units, sizeText, dateTime } from './stockUi'

export const REQ_STATUS = { pending: 'Waiting for approval', approved: 'Approved', done: 'Done', rejected: 'Rejected', cancelled: 'Cancelled' }
export const requestTitle = (r) => (r.kind === 'transfer'
  ? `Move from ${r.from_name || '—'} to ${r.to_name || '—'}`
  : `Delivery from ${r.from_name || '—'} · ${r.invoice_number || 'invoice'}${r.customer_name ? ` (${r.customer_name})` : ''}`)

export const lineText = (r, l) => (r.kind === 'transfer'
  ? `${units(l.quantity)} × ${l.title || sizeText(l.variant)}`
  : `${units(l.quantity)} × ${l.title || 'item'}`)

const STATE = { approved: 'Approved, not gone yet', done: 'Gone' }
export const kindText = (r) => (r.kind === 'transfer' ? 'Move' : 'Delivery')
export const toText = (r) => (r.kind === 'transfer' ? r.to_name || '—' : `${r.customer_name || 'Customer'} (${r.invoice_number || 'invoice'})`)
export const goodsText = (r) => (r.lines || []).map((l) => lineText(r, l)).join('; ')
export const stateText = (r) => (r.status === 'done' ? (r.kind === 'transfer' ? 'Sent' : 'Delivered') : STATE[r.status] || r.status)

export function recordsCsv(rows) {
  const q = (v) => {
    const s = String(v ?? '')
    return /^[=+\-@]/.test(s) ? `"'${s.replace(/"/g, '""')}"` : `"${s.replace(/"/g, '""')}"`
  }
  const head = ['Approved on', 'Type', 'From', 'To / for', 'Goods', 'Units', 'Asked by', 'Approved by', 'Status', 'Sent / delivered on', 'By']
  const body = rows.map((r) => [dateTime(r.decided_at), kindText(r), r.from_name, toText(r), goodsText(r), r.units,
    r.requested_by_name, r.decided_by_name, stateText(r), r.status === 'done' ? dateTime(r.done_at) : '', r.status === 'done' ? r.done_by_name : ''])
  return [head, ...body].map((row) => row.map(q).join(',')).join('\r\n')
}

// STOCK-4: what can happen to a row's goods now
export function deliverState(r, isOwner) {
  const a = r.approval || { pending: 0, approved: 0 }
  const ware = Number(r.warehouse_units || 0)
  if (!ware || isOwner) return { action: 'deliver', text: '' }
  if (a.approved > 0) return { action: 'deliver', text: `Approved: ${units(a.approved)} unit${a.approved === 1 ? '' : 's'} can go` }
  if (a.pending >= ware) return { action: 'wait', text: 'Waiting for the owner\'s approval' }
  return { action: 'ask', text: a.pending ? 'Partly waiting for approval' : 'Needs the owner\'s approval' }
}

