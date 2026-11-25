/**
 * frontend/src/modules/invoices/useRegions.js
 * INV-SALES-2 — the business's regions (Data Sources, same names as the Sales Record sheet tabs) and the region this
 * person picked last (kept in their browser). Used by RegionSelect, the invoice editor and the new receipt form.
 */
import { useEffect, useState } from 'react'
import { getInvoiceRegions } from '../../services/invoices.service'

export const REGION_KEY = 'opsra.invoice.region'
let cache = null

export function useRegions() {
  const [regions, setRegions] = useState(cache || [])
  useEffect(() => {
    if (cache) return undefined
    let live = true
    getInvoiceRegions().then((r) => { cache = r?.regions || []; if (live) setRegions(cache) }).catch(() => { if (live) setRegions([]) })
    return () => { live = false }
  }, [])
  return regions
}

export function lastRegion(regions) {
  let v = ''
  try { v = window.localStorage.getItem(REGION_KEY) || '' } catch { v = '' }
  return regions.includes(v) ? v : ''
}
