/**
 * frontend/src/catalog/catalog.service.js
 * CATALOG-3B: Public catalog API calls — NO auth header, ever.
 * These routes are unauthenticated by design (public catalog).
 * Uses plain fetch — NOT the api.js axios instance (which injects auth headers).
 */

import { fetchWithTimeout, withRetry } from './fetchRetry'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// LOAD-RETRY-1: each try gives up after 12 s and a dropped connection is retried twice, so a visitor never waits on a stalled request.
async function _get(path) {
  return withRetry(async () => {
    const res = await fetchWithTimeout(`${BASE}${path}`)
    if (!res.ok) {
      const err = new Error(`Catalog API error: ${res.status}`)
      err.status = res.status
      throw err
    }
    return res.json()
  })
}

export const getCatalogList = (orgSlug, tagFilters = {}) => {
  const params = new URLSearchParams(tagFilters)
  const qs = params.toString()
  return _get(`/api/v1/public/catalog/${orgSlug}${qs ? '?' + qs : ''}`)
}

export const getCatalogItem = (orgSlug, itemSlug) =>
  _get(`/api/v1/public/catalog/${orgSlug}/${itemSlug}`)

export const searchCatalog = (orgSlug, q) =>
  _get(`/api/v1/public/catalog/${orgSlug}/search?q=${encodeURIComponent(q)}`)

// STORE-7: counts one open of a tagged link. Fire and forget; the page never waits for it.
export const postCatalogVisit = (orgSlug, src) =>
  fetch(`${BASE}/api/v1/public/catalog/${orgSlug}/visit`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ src }), keepalive: true,
  })

export const getCatalogCompare = (orgSlug, sizeValue) =>
  _get(`/api/v1/public/catalog/${orgSlug}?sizes=${encodeURIComponent(sizeValue)}`)
