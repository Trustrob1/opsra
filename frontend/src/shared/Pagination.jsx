/**
 * shared/Pagination.jsx
 * Shared pagination controls — M01-9b.
 *
 * Used by: CustomerList, TicketList, SubscriptionList,
 *          CommissionsModule, TaskList (inline version replaced by this).
 *
 * Props:
 *   page        {number}   — current page (1-indexed)
 *   total       {number}   — total item count across all pages
 *   pageSize    {number}   — items per page
 *   onGoToPage  {function} — (pageNumber) => void
 *
 * Renders nothing when totalPages <= 1 so callers never need a guard.
 */

import { ds } from '../utils/ds'

export default function Pagination({ page, total, pageSize, onGoToPage }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  if (totalPages <= 1) return null

  const atFirst = page <= 1
  const atLast  = page >= totalPages

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: 12, padding: '16px 0', marginTop: 8,
      borderTop: '1px solid #f3f4f6',
    }}>
      <button
        onClick={() => onGoToPage(page - 1)}
        disabled={atFirst}
        style={{
          background: 'none', border: '1px solid #e5e7eb',
          borderRadius: 7, padding: '7px 14px', fontSize: 12.5,
          color: atFirst ? '#d1d5db' : '#374151',
          fontFamily: ds.fontDm,
          cursor: atFirst ? 'default' : 'pointer',
          transition: 'border-color 0.15s',
        }}
      >
        ← Previous
      </button>

      <span style={{ fontSize: 12.5, color: '#6b7280', fontFamily: ds.fontDm }}>
        Page{' '}
        <strong style={{ color: ds.dark }}>{page}</strong>
        {' '}of{' '}
        <strong style={{ color: ds.dark }}>{totalPages}</strong>
        <span style={{ color: '#9ca3af' }}> · {total} total</span>
      </span>

      <button
        onClick={() => onGoToPage(page + 1)}
        disabled={atLast}
        style={{
          background: 'none', border: '1px solid #e5e7eb',
          borderRadius: 7, padding: '7px 14px', fontSize: 12.5,
          color: atLast ? '#d1d5db' : '#374151',
          fontFamily: ds.fontDm,
          cursor: atLast ? 'default' : 'pointer',
          transition: 'border-color 0.15s',
        }}
      >
        Next →
      </button>
    </div>
  )
}
