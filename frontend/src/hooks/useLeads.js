import { useState, useCallback, useEffect } from 'react'
import { listLeads } from '../services/leads.service'

export function useLeads(initialFilters = {}, pageSize = 200) {
  const [leads, setLeads]     = useState([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [filters, setFilters] = useState(initialFilters)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [tick, setTick]       = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    listLeads({ ...filters, page, page_size: pageSize })
      .then((res) => {
        if (cancelled) return
        if (res.success) {
          setLeads(res.data.items ?? [])
          setTotal(res.data.total ?? 0)
          setHasMore(res.data.has_more ?? false)
        } else {
          setError(res.error ?? 'Failed to load leads')
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(
          err?.response?.data?.error ??
          err?.response?.data?.message ??
          'Failed to load leads',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [filters, page, pageSize, tick])

  const applyFilters = useCallback((newFilters) => {
    setFilters(newFilters)
    setPage(1)
  }, [])

  /** Increment tick to force a fresh fetch with current filters/page */
  const refresh = useCallback(() => setTick(t => t + 1), [])

  const goToPage = useCallback((n) => setPage(n), [])

  return {
    leads, total, page, pageSize,
    hasMore, filters, applyFilters,
    goToPage, loading, error, refresh,
  }
}