/**
 * frontend/src/catalog/catalog.service.js
 * CATALOG-3B: Public catalog API calls — NO auth header, ever.
 * These routes are unauthenticated by design (public catalog).
 * Uses plain fetch — NOT the api.js axios instance (which injects auth headers).
 */

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function _get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const err = new Error(`Catalog API error: ${res.status}`)
    err.status = res.status
    throw err
  }
  return res.json()
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
