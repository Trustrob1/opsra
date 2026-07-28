/**
 * frontend/src/modules/ops/DateRangePresets.jsx
 * REPORTS-DEPT-1 Phase 4c — shared date-range control for Sales Record
 * and Commissions. Defaults to "Today". "Custom" reveals raw from/to
 * date inputs; every other preset computes the range internally.
 *
 * Usage: <DateRangePresets onChange={({ dateFrom, dateTo }) => ...} />
 * Fires once on mount (Today) and again on every preset/custom change.
 */
import { useState, useEffect } from 'react'

const INP = {
  padding:      '8px 10px',
  border:       '1px solid #D1D5DB',
  borderRadius: 8,
  fontSize:     13,
  outline:      'none',
  background:   'white',
  fontFamily:   'inherit',
}

const PRESETS = ['Today', 'Yesterday', 'Last 30 days', 'Last Month', 'Last Year', 'Custom']

function fmt(d) {
  return d.toISOString().slice(0, 10)
}

function computeRange(preset, customFrom, customTo) {
  const today = new Date()
  switch (preset) {
    case 'Today':
      return { dateFrom: fmt(today), dateTo: fmt(today) }
    case 'Yesterday': {
      const y = new Date(today)
      y.setDate(y.getDate() - 1)
      return { dateFrom: fmt(y), dateTo: fmt(y) }
    }
    case 'Last 30 days': {
      const from = new Date(today)
      from.setDate(from.getDate() - 29)
      return { dateFrom: fmt(from), dateTo: fmt(today) }
    }
    case 'Last Month': {
      const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1)
      const lastMonthEnd = new Date(firstOfThisMonth)
      lastMonthEnd.setDate(0) // rolls back to the last day of the previous month
      const lastMonthStart = new Date(lastMonthEnd.getFullYear(), lastMonthEnd.getMonth(), 1)
      return { dateFrom: fmt(lastMonthStart), dateTo: fmt(lastMonthEnd) }
    }
    case 'Last Year': {
      const start = new Date(today.getFullYear() - 1, 0, 1)
      const end = new Date(today.getFullYear() - 1, 11, 31)
      return { dateFrom: fmt(start), dateTo: fmt(end) }
    }
    case 'Custom':
      return { dateFrom: customFrom, dateTo: customTo }
    default:
      return { dateFrom: fmt(today), dateTo: fmt(today) }
  }
}

export default function DateRangePresets({ onChange }) {
  const [preset, setPreset]         = useState('Today')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo]     = useState('')

  useEffect(() => {
    onChange(computeRange(preset, customFrom, customTo))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, customFrom, customTo])

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <select value={preset} onChange={e => setPreset(e.target.value)} style={{ ...INP, width: 'auto' }}>
        {PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
      </select>
      {preset === 'Custom' && (
        <>
          <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} style={{ ...INP, width: 'auto' }} />
          <span style={{ color: '#9CA3AF', fontSize: 13 }}>to</span>
          <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)} style={{ ...INP, width: 'auto' }} />
        </>
      )}
    </div>
  )
}
