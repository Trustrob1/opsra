/**
 * frontend/src/modules/inventory/InventoryReport.jsx
 * REPORT-1 — the inventory report (owners and admins): stock now per product + size, value at cost, running low,
 * paid orders waiting delivery and stock moves in the period, for one location or all, with PDF / CSV downloads.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import { getInventoryReport, downloadInventoryReport, stockError } from '../../services/inventory.service'
import { todayYmd } from '../invoices/invoiceUi'
import { card, inp, lab, naira, units, signed, sizeText } from './stockUi'
import { PeriodPicker, DownloadButtons, Tiles, ReportTable } from '../reports/ReportBits'

export default function InventoryReport({ locations }) {
  const [period, setPeriod] = useState(() => ({ start: `${todayYmd().slice(0, 8)}01`, end: todayYmd() }))
  const [locationId, setLocationId] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const params = { start: period.start, end: period.end, ...(locationId ? { location_id: locationId } : {}) }

  useEffect(() => {
    let live = true
    getInventoryReport({ start: period.start, end: period.end, ...(locationId ? { location_id: locationId } : {}) })
      .then((r) => { if (live) { setData(r); setErr('') } })
      .catch((e) => { if (live) setErr(stockError(e, 'Could not load the report. Please refresh.')) })
    return () => { live = false }
  }, [period.start, period.end, locationId])

  const s = data?.summary || {}
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ ...card, display: 'grid', gap: 12 }}>
        <PeriodPicker value={period} onChange={setPeriod} />
        {locations.length > 1 && (
          <label style={{ maxWidth: 280 }}><span style={lab}>Location</span>
            <select style={inp} value={locationId} onChange={(e) => setLocationId(e.target.value)}>
              <option value="">All locations</option>
              {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </label>
        )}
        <p style={{ margin: 0, color: ds.gray, fontSize: 13.5 }}>Stock figures are as of now. The period sets which stock moves are counted.</p>
        <DownloadButtons onDownload={(format) => downloadInventoryReport(params, format)} />
      </div>
      {err && <p role="alert" style={{ color: ds.red, margin: 0 }}>{err}</p>}
      {!data && !err && <p style={{ color: ds.gray }}>Loading…</p>}
      {data && <>
        <Tiles tiles={[['Products and sizes', units(s.lines)], ['Units on hand', units(s.units_on_hand)],
          ['Value at cost', naira(s.stock_value)], ['Running low', units(s.low)]]} />
        {s.missing_cost > 0 && <p style={{ margin: 0, color: ds.gray, fontSize: 13.5 }}>{s.missing_cost} item{s.missing_cost === 1 ? '' : 's'} in stock {s.missing_cost === 1 ? 'has' : 'have'} no cost price, so the value is lower than it should be.</p>}
        <ReportTable title="Running low" head={['Product', 'Size', 'Available', 'Reorder at']} right={[2, 3]} empty="Nothing is running low."
          rows={data.low.map((i) => [i.title, sizeText(i.size), units(i.available), units(i.reorder_level)])} />
        <ReportTable title="Paid, waiting delivery" head={['Invoice', 'Customer', 'Location', 'Items']} empty="Nothing waiting delivery."
          rows={data.waiting.map((w) => [w.number, w.customer, w.location || '—', w.lines])} />
        <ReportTable title="Stock moves in the period" head={['Kind', 'Moves', 'Units in / out']} right={[1, 2]}
          rows={data.moves.map((k) => [k.name, units(k.moves), signed(k.units)])} />
        <ReportTable title="Stock now" head={['Product', 'Size', 'On hand', 'Held', 'To deliver', 'Available', 'In transit', 'Value']}
          right={[2, 3, 4, 5, 6, 7]} empty="No products yet."
          rows={data.items.map((i) => [i.title, sizeText(i.size), units(i.on_hand), units(i.held), units(i.to_deliver),
            units(i.available), units(i.in_transit), naira(i.value)])} />
      </>}
    </div>
  )
}
