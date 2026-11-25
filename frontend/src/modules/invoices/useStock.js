/**
 * frontend/src/modules/invoices/useStock.js
 * STOCK-2 — is stock on for this business, its open locations, and which location an invoice starts on.
 * A business without the Inventory plan (or with stock off) gets { enabled: false } and the editor shows nothing extra.
 */
import { useEffect, useState } from 'react'
import { getLocations, getAvailability } from '../../services/inventory.service'

export const LOCATION_KEY = 'opsra.invoice.location'
let cache = null

export function useStock() {
  const [state, setState] = useState(cache || { enabled: false, locations: [], ready: false })
  useEffect(() => {
    if (cache) return undefined
    let live = true
    getLocations()
      .then((r) => {
        cache = { enabled: !!r?.enabled, locations: (r?.locations || []).filter((l) => l.is_active !== false), ready: true }
        if (live) setState(cache)
      })
      .catch(() => { if (live) setState({ enabled: false, locations: [], ready: true }) })
    return () => { live = false }
  }, [])
  return state
}

/** The location a new invoice starts on: the region's own location, else the one last used, else the main one. */
export function startLocation(locations, region) {
  if (!locations.length) return ''
  const r = String(region || '').trim().toLowerCase()
  const byRegion = r && locations.find((l) => String(l.region || '').trim().toLowerCase() === r)
  if (byRegion) return byRegion.id
  let last = ''
  try { last = window.localStorage.getItem(LOCATION_KEY) || '' } catch { last = '' }
  if (last && locations.some((l) => l.id === last)) return last
  return (locations.find((l) => l.is_default) || locations[0]).id
}

export function rememberLocation(id) {
  try { if (id) window.localStorage.setItem(LOCATION_KEY, id) } catch { /* private mode: not remembered */ }
}

/** What is left per size at one location for the products on the form: { productId: { size: n } }. */
export function useAvailability(enabled, locationId, productIds) {
  const key = enabled && locationId ? `${locationId}|${[...new Set(productIds)].sort().join(',')}` : ''
  const [data, setData] = useState({ key: '', products: {} })
  useEffect(() => {
    if (!key || !productIds.length) return undefined
    let live = true
    getAvailability(locationId, [...new Set(productIds)])
      .then((r) => { if (live) setData({ key, products: r?.products || {} }) })
      .catch(() => { if (live) setData({ key, products: {} }) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return data.key === key ? data.products : null
}
