/**
 * frontend/src/modules/sales/SalesReport.jsx
 * REPORT-1 — the sales report (owners and admins): a period, optional region / location / rep, the totals, money
 * received by method, by rep / region / location / product and size, part-paid invoices, and PDF / CSV downloads.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import { getSalesReport, downloadSalesReport, apiError } from '../../services/invoices.service'
import { naira, niceDate, inp, lab, card, todayYmd } from '../invoices/invoiceUi'
import { PeriodPicker, DownloadButtons, Tiles, ReportTable } from '../reports/ReportBits'

export default function SalesReport() {
  const [period, setPeriod] = useState(() => ({ start: `${todayYmd().slice(0, 8)}01`, end: todayYmd() }))
  const [region, setRegion] = useState('')
  const [locationId, setLocationId] = useState('')
  const [repId, setRepId] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const params = { start: period.start, end: period.end, region, location_id: locationId, rep_id: repId }

  useEffect(() => {
    let live = true
    getSalesReport({ start: period.start, end: period.end, region, location_id: locationId, rep_id: repId })
      .then((r) => { if (live) { setData(r); setErr('') } })
      .catch((e) => { if (live) setErr(apiError(e, 'Could not load the report. Please refresh.')) })
    return () => { live = false }
  }, [period.start, period.end, region, locationId, repId])

  const t = data?.totals
  const group = (rows) => (rows || []).map((g) => [g.name, g.count, naira(g.value), naira(g.paid), naira(g.owed)])
  const groupHead = ['', 'Sales', 'Value', 'Paid', 'Owed']
  const select = (label, value, set, options) => (
    <label style={{ minWidth: 170, flex: 1 }}><span style={lab}>{label}</span>
      <select style={inp} value={value} onChange={(e) => set(e.target.value)}>
        <option value="">All</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  )
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ ...card, display: 'grid', gap: 12 }}>
        <PeriodPicker value={period} onChange={setPeriod} />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {select('Region', region, setRegion, (data?.regions || []).map((r) => [r, r]))}
          {(data?.locations || []).length > 0 && select('Location', locationId, setLocationId, data.locations.map((l) => [l.id, l.name]))}
          {select('Rep', repId, setRepId, (data?.reps || []).map((r) => [r.id, r.name]))}
        </div>
        <DownloadButtons onDownload={(format) => downloadSalesReport(params, format)} />
      </div>
      {err && <p role="alert" style={{ color: ds.red, margin: 0 }}>{err}</p>}
      {!data && !err && <p style={{ color: ds.gray }}>Loading…</p>}
      {data && <>
        <Tiles tiles={[['Sales', t.count], ['Sales value', naira(t.value)], ['Money received', naira(t.received)], ['Still owed', naira(t.owed)]]} />
        <ReportTable title="Money received by method" head={['Method', 'Amount']} right={[1]}
          rows={data.by_method.map((m) => [m.name, naira(m.amount)])} />
        <ReportTable title="By rep" head={groupHead} right={[1, 2, 3, 4]} rows={group(data.by_rep)} />
        <ReportTable title="By region" head={groupHead} right={[1, 2, 3, 4]} rows={group(data.by_region)} />
        {data.by_location.length > 0 && <ReportTable title="By location" head={groupHead} right={[1, 2, 3, 4]} rows={group(data.by_location)} />}
        <ReportTable title="By product and size" head={['Product', 'Size', 'Units', 'Value']} right={[2, 3]}
          rows={data.by_product.map((p) => [p.name, p.size || '—', p.units, naira(p.value)])} />
        <ReportTable title="Part-paid invoices" head={['Invoice', 'Customer', 'Rep', 'Total', 'Paid', 'Owed']} right={[3, 4, 5]}
          empty="No part-paid invoices in this period."
          rows={data.part_paid.map((s) => [s.number, s.customer, s.rep, naira(s.total), naira(s.paid), naira(s.owed)])} />
        <ReportTable title="All sales" head={['Date', 'Invoice', 'Customer', 'Rep', 'Region', 'Total', 'Owed']} right={[5, 6]}
          rows={data.sales.map((s) => [niceDate(s.date), s.number, s.customer, s.rep, s.region || '—', naira(s.total), naira(s.owed)])} />
      </>}
    </div>
  )
}
