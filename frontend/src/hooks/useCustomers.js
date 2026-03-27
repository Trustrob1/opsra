/**
 * useCustomers.js — React hook for Module 02 customer list state.
 *
 * Mirrors useLeads pattern exactly:
 *  - tick counter for reliable refresh (Pattern 19)
 *  - applyFilters resets to page 1
 *  - refresh() increments tick → triggers useEffect
 */

import { useState, useEffect, useCallback } from 'react'
import { listCustomers } from '../services/whatsapp.service'

export default function useCustomers(initialFilters = {}, pageSize = 50) {
  const [customers, setCustomers]   = useState([])
  const [total, setTotal]           = useState(0)
  const [page, setPage]             = useState(1)
  const [filters, setFilters]       = useState(initialFilters)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [tick, setTick]             = useState(0)

  const refresh = useCallback(() => setTick(t => t + 1), [])

  const applyFilters = useCallback(next => {
    setFilters(next)
    setPage(1)
    setTick(t => t + 1)
  }, [])

  const goToPage = useCallback(p => {
    setPage(p)
    setTick(t => t + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const params = { page, page_size: pageSize, ...filters }
    // strip undefined / empty string values
    Object.keys(params).forEach(k => {
      if (params[k] === '' || params[k] === undefined || params[k] === null) {
        delete params[k]
      }
    })

    listCustomers(params)
      .then(res => {
        if (cancelled) return
        const d = res.data?.data
        setCustomers(d?.items ?? [])
        setTotal(d?.total ?? 0)
      })
      .catch(err => {
        if (cancelled) return
        setError(err.response?.data?.error?.message ?? 'Failed to load customers')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [filters, page, pageSize, tick])

  return {
    customers,
    total,
    page,
    pageSize,
    hasMore: page * pageSize < total,
    filters,
    applyFilters,
    goToPage,
    loading,
    error,
    refresh,
  }
}
