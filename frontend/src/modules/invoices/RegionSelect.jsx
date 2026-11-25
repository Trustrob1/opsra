/**
 * frontend/src/modules/invoices/RegionSelect.jsx
 * INV-SALES-2 — the Region box on invoices, quotes and receipts with no invoice. The list is the business's regions
 * from Data Sources (same names as the Sales Record sheet tabs). Shown only when the business has regions; then the
 * server will not issue without one. The last region this person picked is remembered in their browser.
 */
import { lab, inp } from './invoiceUi'
import { REGION_KEY } from './useRegions'

export default function RegionSelect({ regions, value, onChange, id = 'inv-region' }) {
  if (!regions?.length) return null
  const pick = (v) => {
    try { if (v) window.localStorage.setItem(REGION_KEY, v) } catch { /* private mode: just don't remember */ }
    onChange(v)
  }
  return (
    <div>
      <label style={lab} htmlFor={id}>Region</label>
      <select id={id} style={inp} value={value || ''} onChange={(e) => pick(e.target.value)} required>
        <option value="">Choose the region</option>
        {regions.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
    </div>
  )
}
