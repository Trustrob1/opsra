/**
 * frontend/src/modules/inventory/StockHistory.jsx
 * STOCK-1 — every stock change, newest first: what happened, where, how many, what was left, who did it.
 */
import { useCallback, useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getStockHistory, stockError } from '../../services/inventory.service'
import { card, inp, btnG, units, signed, dateTime, th, td } from './stockUi'

const PAGE = 50

export default function StockHistory({ locations }) {
  const isMobile = useIsMobile()
  const [locationId, setLocationId] = useState('')
  const [rows, setRows] = useState(null)
  const [more, setMore] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback((offset = 0) => {
    getStockHistory({ limit: PAGE, offset, ...(locationId ? { location_id: locationId } : {}) }).then((r) => {
      setErr('')
      setRows((prev) => (offset ? [...(prev || []), ...(r?.items || [])] : (r?.items || [])))
      setMore(!!r?.more)
    }).catch((e) => { setErr(stockError(e, 'Could not load the history. Please refresh.')); setRows([]) })
  }, [locationId])
  useEffect(() => { load(0) }, [load])

  const tone = (n) => (n < 0 ? ds.red : n > 0 ? ds.green : ds.gray)
  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        <select aria-label="Location" style={{ ...inp, width: 'auto', minWidth: 200 }} value={locationId} onChange={(e) => setLocationId(e.target.value)}>
          <option value="">All locations</option>
          {(locations || []).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
      </div>
      {err && <p role="alert" style={{ color: ds.red }}>{err}</p>}
      {rows === null && <p style={{ color: ds.gray }}>Loading…</p>}
      {rows && rows.length === 0 && !err && (
        <div style={{ ...card, textAlign: 'center', padding: 36 }}>
          <History size={30} color={ds.teal} />
          <p style={{ color: ds.dark, fontWeight: 600, margin: '10px 0 4px' }}>No stock changes yet</p>
          <p style={{ color: ds.gray, margin: 0 }}>Every receive, adjustment and sale will be listed here.</p>
        </div>
      )}
      {rows && rows.length > 0 && (isMobile ? (
        <div style={{ display: 'grid', gap: 10 }}>
          {rows.map((m) => (
            <div key={m.id} style={{ ...card, padding: 14, display: 'grid', gap: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <b style={{ color: ds.dark }}>{m.title}{m.variant ? ` · ${m.variant}` : ''}</b>
                <b style={{ color: tone(m.change) }}>{m.change ? signed(m.change) : '—'}</b>
              </div>
              <div style={{ color: ds.gray, fontSize: 13.5 }}>{m.kind_label} · {m.location} · {dateTime(m.created_at)}</div>
              {(m.reason || m.ref) && <div style={{ color: ds.gray, fontSize: 13.5 }}>{[m.reason, m.ref].filter(Boolean).join(' · ')}</div>}
              <div style={{ color: ds.gray, fontSize: 13.5 }}>{units(m.on_hand_after)} on hand after{m.by ? ` · ${m.by}` : ''}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ background: ds.light, color: ds.gray, textAlign: 'left' }}>
              <th style={th}>When</th><th style={th}>Product</th><th style={th}>Location</th><th style={th}>What happened</th>
              <th style={{ ...th, textAlign: 'right' }}>Change</th><th style={{ ...th, textAlign: 'right' }}>On hand after</th><th style={th}>By</th>
            </tr></thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id} style={{ borderTop: `1px solid ${ds.border}` }}>
                  <td style={{ ...td, whiteSpace: 'nowrap', color: ds.gray }}>{dateTime(m.created_at)}</td>
                  <td style={td}>{m.title}{m.variant ? <span style={{ color: ds.gray }}> · {m.variant}</span> : ''}</td>
                  <td style={td}>{m.location}</td>
                  <td style={td}>{m.kind_label}{m.reason ? <span style={{ color: ds.gray }}> · {m.reason}</span> : ''}{m.ref ? <span style={{ color: ds.gray }}> · {m.ref}</span> : ''}</td>
                  <td style={{ ...td, textAlign: 'right', fontWeight: 700, color: tone(m.change) }}>{m.change ? signed(m.change) : '—'}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{units(m.on_hand_after)}</td>
                  <td style={{ ...td, color: ds.gray }}>{m.by || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {more && <div style={{ textAlign: 'center', marginTop: 14 }}><button type="button" style={btnG} onClick={() => load(rows.length)}>Show more</button></div>}
    </div>
  )
}
