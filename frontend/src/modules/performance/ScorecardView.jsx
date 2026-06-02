/**
 * frontend/src/modules/performance/ScorecardView.jsx
 *
 * Cross-entity scorecard for owner / ops_manager.
 * Shows all staff + contractors with score %, pace, attendance, last log, 3-month sparkline.
 * Filters: role type, entity type (staff/contractor), month selector.
 * Click any row → onOpenProfile(userId, month)
 */
import { useState, useEffect, useCallback } from 'react'
import { getScorecard } from '../../services/performance.service'
import { ds } from '../../utils/ds'

const _SCORE_COLOUR = (pct, colour) => {
  if (colour === 'green')  return { background: '#d1fae5', color: '#065f46' }
  if (colour === 'amber')  return { background: '#fef3c7', color: '#92400e' }
  return                          { background: '#fee2e2', color: '#991b1b' }
}

const _LAST_LOG_COLOUR = (c) => {
  if (c === 'green') return '#10b981'
  if (c === 'amber') return '#f59e0b'
  return '#ef4444'
}

function MiniSparkline({ data }) {
  if (!data || data.length === 0) return <span style={{ fontSize: 11, color: '#9ca3af' }}>—</span>
  const max = Math.max(...data.map(d => d.score_pct), 1)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 24 }}>
      {data.map((d, i) => (
        <div
          key={i}
          title={`${d.month}: ${d.score_pct}%`}
          style={{
            width: 10,
            height: Math.max(3, (d.score_pct / max) * 24),
            borderRadius: 2,
            background: d.score_pct >= 75 ? '#10b981' : d.score_pct >= 50 ? '#f59e0b' : '#ef4444',
          }}
        />
      ))}
    </div>
  )
}

export default function ScorecardView({ onOpenProfile }) {
  const [rows, setRows]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  const [month, setMonth] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  const [filterRole,   setFilterRole]   = useState('all')
  const [filterEntity, setFilterEntity] = useState('all')

  const fetchScorecard = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getScorecard(month)
      setRows(data || [])
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load scorecard')
    } finally {
      setLoading(false)
    }
  }, [month])

  useEffect(() => { fetchScorecard() }, [fetchScorecard])

  // Python-side filtering (Pattern 33 equivalent in JS — no server-side ILIKE)
  const filtered = rows.filter(r => {
    if (filterEntity !== 'all' && r.entity_type !== filterEntity) return false
    if (filterRole !== 'all' && r.role !== filterRole) return false
    return true
  })

  const allRoles = [...new Set(rows.map(r => r.role).filter(Boolean))]

  const INPUT = {
    background: 'white', border: '1px solid #e5e7eb', borderRadius: 7,
    padding: '6px 10px', fontSize: 12, color: ds.dark, cursor: 'pointer',
    fontFamily: ds.fontDm,
  }

  const CELL = { padding: '12px 14px', fontSize: 13, borderBottom: '1px solid #f3f4f6', verticalAlign: 'middle' }
  const HEADER = { ...CELL, fontWeight: 600, fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.5px', background: '#f9fafb', padding: '10px 14px' }

  return (
    <div>
      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="month"
          value={month}
          onChange={e => setMonth(e.target.value)}
          style={INPUT}
        />
        <select value={filterEntity} onChange={e => setFilterEntity(e.target.value)} style={INPUT}>
          <option value="all">All types</option>
          <option value="staff">Staff</option>
          <option value="contractor">Contractors</option>
        </select>
        <select value={filterRole} onChange={e => setFilterRole(e.target.value)} style={INPUT}>
          <option value="all">All roles</option>
          {allRoles.map(r => <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>)}
        </select>
        <button
          onClick={fetchScorecard}
          style={{ ...INPUT, background: ds.teal, color: 'white', border: 'none', cursor: 'pointer', padding: '6px 14px' }}
        >
          ↻ Refresh
        </button>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 40, color: '#7A9BAD', fontSize: 13 }}>Loading scorecard…</div>
      )}
      {error && (
        <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', color: '#991b1b', fontSize: 13, marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}

      {!loading && !error && (
        <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={HEADER}>Name</th>
                <th style={HEADER}>Score %</th>
                <th style={HEADER}>Pace</th>
                <th style={HEADER}>Attendance today</th>
                <th style={HEADER}>Last log</th>
                <th style={HEADER}>3-month trend</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ ...CELL, textAlign: 'center', color: '#9ca3af', padding: 32 }}>
                    No records found
                  </td>
                </tr>
              )}
              {filtered.map(row => (
                <tr
                  key={`${row.entity_type}-${row.entity_id}`}
                  onClick={() => row.entity_type === 'staff' && onOpenProfile(row.entity_id, month)}
                  style={{
                    cursor: row.entity_type === 'staff' ? 'pointer' : 'default',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = '#f9fafb'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={CELL}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ width: 32, height: 32, borderRadius: '50%', background: ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'white', flexShrink: 0 }}>
                        {(row.name || '?')[0].toUpperCase()}
                      </div>
                      <div>
                        <div style={{ fontWeight: 500, color: ds.dark }}>{row.name}</div>
                        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 1 }}>
                          {row.role?.replace(/_/g, ' ')}
                          {row.entity_type === 'contractor' && <span style={{ marginLeft: 4, background: '#ede9fe', color: '#5b21b6', borderRadius: 4, padding: '1px 5px', fontSize: 10 }}>contractor</span>}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td style={CELL}>
                    {row.score_pct != null ? (
                      <span style={{ ..._SCORE_COLOUR(row.score_pct, row.score_colour), borderRadius: 20, padding: '3px 10px', fontSize: 12, fontWeight: 600 }}>
                        {row.score_pct}%
                      </span>
                    ) : <span style={{ color: '#9ca3af', fontSize: 12 }}>—</span>}
                  </td>
                  <td style={CELL}>
                    <span style={{
                      fontSize: 12, fontWeight: 500,
                      color: row.pace === 'Ahead' ? '#065f46' : row.pace === 'Behind' ? '#991b1b' : '#92400e',
                    }}>
                      {row.pace || '—'}
                    </span>
                  </td>
                  <td style={CELL}>
                    <span style={{ fontSize: 12, color: '#374151' }}>
                      {row.attendance_today === '—' ? <span style={{ color: '#9ca3af' }}>Not logged</span> : row.attendance_today}
                    </span>
                  </td>
                  <td style={CELL}>
                    <span style={{ fontSize: 12, color: _LAST_LOG_COLOUR(row.last_log_colour) }}>
                      {row.last_log_date ?? 'Never'}
                    </span>
                  </td>
                  <td style={CELL}>
                    <MiniSparkline data={row.sparkline} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
