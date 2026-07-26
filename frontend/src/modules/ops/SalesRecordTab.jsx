/**
 * frontend/src/modules/ops/SalesRecordTab.jsx
 * REPORTS-DEPT-1 Phase 4b — Sales Record tab inside Business Activities.
 *
 * Individual-sale listing (not the daily-aggregate revenue rows) —
 * filterable by date range, sales rep, and model. Reads GET
 * /api/v1/growth/direct-sales, extended with optional filters in this
 * same phase. Owner/ops_manager only, matching the backend gate exactly.
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getDirectSales } from '../../services/growth.service'
import { listUsers } from '../../services/admin.service'

const INP = {
  padding:      '8px 10px',
  border:       '1px solid #D1D5DB',
  borderRadius: 8,
  fontSize:     13,
  outline:      'none',
  background:   'white',
  fontFamily:   'inherit',
}

function Badge({ text, tone }) {
  const colours = {
    rec:  { bg: '#ECFDF5', text: '#059669' },
    pen:  { bg: '#FDF4E3', text: '#92601A' },
    none: { bg: '#F3F4F6', text: '#6B7280' },
  }[tone]
  return (
    <span style={{ background: colours.bg, color: colours.text, fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 20, whiteSpace: 'nowrap' }}>
      {text}
    </span>
  )
}

export default function SalesRecordTab() {
  const [sales, setSales]       = useState([])
  const [users, setUsers]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [page, setPage]         = useState(1)
  const [total, setTotal]       = useState(0)
  const [hasMore, setHasMore]   = useState(false)
  const pageSize = 25

  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [repId, setRepId]       = useState('')
  const [model, setModel]       = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const filters = {}
      if (dateFrom) filters.date_from = dateFrom
      if (dateTo)   filters.date_to   = dateTo
      if (repId)    filters.rep_id    = repId
      if (model)    filters.model     = model
      const data = await getDirectSales(page, pageSize, filters)
      setSales(data?.items ?? [])
      setTotal(data?.total ?? 0)
      setHasMore(!!data?.has_more)
    } catch {
      setError('Failed to load sales records.')
    } finally {
      setLoading(false)
    }
  }, [page, dateFrom, dateTo, repId, model])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    listUsers().then(us => setUsers(us ?? [])).catch(() => {})
  }, [])

  const resetPage = () => setPage(1)

  return (
    <div style={{ padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Sales Record</h2>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>{total} sale{total !== 1 ? 's' : ''}</p>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); resetPage() }} style={{ ...INP, width: 'auto' }} />
        <span style={{ color: '#9CA3AF', fontSize: 13 }}>to</span>
        <input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); resetPage() }} style={{ ...INP, width: 'auto' }} />
        <select value={repId} onChange={e => { setRepId(e.target.value); resetPage() }} style={{ ...INP, width: 'auto' }}>
          <option value="">All reps</option>
          {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </select>
        <input
          value={model}
          onChange={e => { setModel(e.target.value); resetPage() }}
          placeholder="Search model…"
          style={{ ...INP, width: 160 }}
        />
      </div>

      {error && <p style={{ color: '#DC2626', fontSize: 13, marginBottom: 14 }}>{error}</p>}

      {loading ? (
        <p style={{ color: '#7A9BAD', fontSize: 14 }}>Loading…</p>
      ) : sales.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 32px', color: '#7A9BAD' }}>
          <p style={{ fontSize: 14 }}>No sales match these filters.</p>
        </div>
      ) : (
        <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#F8FBFC' }}>
                {['Date', 'Rep', 'Region', 'Model', 'Units', 'Amount', 'Status'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '10px 14px', fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.6px' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sales.map((s, i) => {
                const rep = users.find(u => u.id === s.recorded_by)
                return (
                  <tr key={s.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none' }}>
                    <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.sale_date}</td>
                    <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{rep?.full_name ?? '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 13, color: '#7A9BAD' }}>{s.region ?? '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.model ?? '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24' }}>{s.units ?? '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 13, color: '#0a1a24', fontWeight: 500 }}>
                      {s.amount != null ? `₦${Number(s.amount).toLocaleString()}` : '—'}
                    </td>
                    <td style={{ padding: '10px 14px' }}>
                      {s.reconciliation_status
                        ? <Badge text={s.reconciliation_status} tone={s.reconciliation_status === 'Reconciled' ? 'rec' : 'pen'} />
                        : <Badge text="—" tone="none" />}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 16 }}>
        <button
          onClick={() => setPage(p => Math.max(1, p - 1))}
          disabled={page === 1}
          style={{ ...INP, cursor: page === 1 ? 'not-allowed' : 'pointer', opacity: page === 1 ? 0.5 : 1 }}
        >
          Previous
        </button>
        <span style={{ fontSize: 13, color: '#7A9BAD' }}>Page {page}</span>
        <button
          onClick={() => setPage(p => p + 1)}
          disabled={!hasMore}
          style={{ ...INP, cursor: !hasMore ? 'not-allowed' : 'pointer', opacity: !hasMore ? 0.5 : 1 }}
        >
          Next
        </button>
      </div>
    </div>
  )
}
