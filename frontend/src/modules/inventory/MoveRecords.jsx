/**
 * frontend/src/modules/inventory/MoveRecords.jsx
 * STOCK-4 — approved stock movements: moves out of a warehouse and deliveries from a warehouse, for this week,
 * this month or any dates (by the day they were approved), with a CSV download.
 */
import { useCallback, useEffect, useState } from 'react'
import { Download, FileText } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getMoveRecords, stockError } from '../../services/inventory.service'
import { card, lab, inp, btnG, disabled, errBox, units, dateTime, th, td } from './stockUi'
import { kindText, toText, goodsText, stateText, recordsCsv } from './moveRequestUi'

export default function MoveRecords({ locations }) {
  const isMobile = useIsMobile()
  const [period, setPeriod] = useState('week')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [locationId, setLocationId] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const custom = period === 'custom'
  const ready = !custom || (start && end)

  const load = useCallback(() => {
    if (!ready) return Promise.resolve()
    return getMoveRecords({ period, ...(custom ? { start, end } : {}), ...(locationId ? { location_id: locationId } : {}) })
      .then((r) => { setData(r); setErr('') })
      .catch((e) => { setErr(stockError(e, 'Could not load the records. Please refresh.')); setData(null) })
  }, [period, start, end, locationId, custom, ready])
  useEffect(() => { load() }, [load])

  const rows = data?.records || []
  const s = data?.summary || {}
  const download = () => {
    const blob = new Blob(['﻿' + recordsCsv(rows)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `stock-movements-${data?.start || 'from'}-to-${data?.end || 'to'}.csv`
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10000)
  }
  const chip = (v, text) => (
    <button key={v} type="button" aria-pressed={period === v} onClick={() => setPeriod(v)}
      style={{ padding: '0 12px', minHeight: 34, borderRadius: 999, border: `1.5px solid ${period === v ? ds.teal : ds.border}`, background: period === v ? ds.mint : '#fff', color: ds.dark, fontWeight: 600, fontSize: 13, cursor: 'pointer', fontFamily: ds.fontDm }}>{text}</button>
  )
  const warehouses = (locations || []).filter((l) => l.kind === 'warehouse')

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <p style={{ margin: 0, color: ds.gray, fontSize: 14 }}>Stock the owner approved to leave a warehouse, by the day it was approved.</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'end' }}>
        {chip('week', 'This week')}{chip('month', 'This month')}{chip('custom', 'Choose dates')}
        {custom && <>
          <div><label style={lab} htmlFor="rec-start">From</label><input id="rec-start" type="date" style={{ ...inp, width: 'auto' }} value={start} max={end || undefined} onChange={(e) => setStart(e.target.value)} /></div>
          <div><label style={lab} htmlFor="rec-end">To</label><input id="rec-end" type="date" style={{ ...inp, width: 'auto' }} value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} /></div>
        </>}
        {warehouses.length > 1 && (
          <select aria-label="Warehouse" style={{ ...inp, width: 'auto', minWidth: 170 }} value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            <option value="">All warehouses</option>
            {warehouses.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        )}
        <button type="button" style={{ ...disabled(btnG, !rows.length), marginLeft: 'auto' }} disabled={!rows.length} onClick={download}><Download size={16} />Download CSV</button>
      </div>
      {custom && !ready && <p style={{ color: ds.gray, margin: 0, fontSize: 13.5 }}>Choose both dates to see the records.</p>}
      {err && <div role="alert" style={errBox}>{err}</div>}
      {data && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {[['Moves', s.moves], ['Deliveries', s.deliveries], ['Units', s.units]].map(([k, v]) => (
            <div key={k} style={{ ...card, padding: '12px 16px', flex: '1 1 140px' }}>
              <div style={{ fontSize: 12.5, color: ds.gray, fontWeight: 600 }}>{k}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: ds.dark, marginTop: 2 }}>{units(v)}</div>
            </div>
          ))}
        </div>
      )}
      {!data && ready && !err && <p style={{ color: ds.gray }}>Loading…</p>}
      {data && rows.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 32 }}>
          <FileText size={28} color={ds.teal} />
          <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>No approved movements in these dates</p>
          <p style={{ color: ds.gray, margin: 0 }}>Try another period.</p>
        </div>
      )}
      {rows.length > 0 && (isMobile ? (
        <div style={{ display: 'grid', gap: 10 }}>
          {rows.map((r) => (
            <div key={r.id} style={{ ...card, padding: 14, display: 'grid', gap: 4 }}>
              <div style={{ display: 'flex', gap: 8 }}><b style={{ flex: 1, color: ds.dark }}>{kindText(r)}: {r.from_name} → {toText(r)}</b><span>{units(r.units)}</span></div>
              <div style={{ fontSize: 13.5, color: ds.dark }}>{goodsText(r)}</div>
              <div style={{ fontSize: 13, color: ds.gray }}>Approved {dateTime(r.decided_at)}{r.decided_by_name ? ` by ${r.decided_by_name}` : ''} · {stateText(r)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ background: ds.light, color: ds.gray, textAlign: 'left' }}>
              {['Approved on', 'Type', 'From', 'To / for', 'Goods', 'Units', 'Asked by', 'Approved by', 'Status'].map((h) => <th key={h} style={{ ...th, ...(h === 'Units' ? { textAlign: 'right' } : {}) }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={{ borderTop: `1px solid ${ds.border}` }}>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>{dateTime(r.decided_at)}</td>
                  <td style={td}>{kindText(r)}</td>
                  <td style={td}>{r.from_name}</td>
                  <td style={td}>{toText(r)}</td>
                  <td style={td}>{goodsText(r)}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{units(r.units)}</td>
                  <td style={td}>{r.requested_by_name || '—'}</td>
                  <td style={td}>{r.decided_by_name || '—'}</td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>{stateText(r)}{r.status === 'done' && r.done_at ? <div style={{ color: ds.gray, fontSize: 12 }}>{dateTime(r.done_at)}</div> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
