/**
 * frontend/src/hooks/useTickets.js
 * Custom hook for the tickets list — follows tick-counter pattern (Pattern 19).
 * Returns tickets, loading, error, pagination helpers, and refresh().
 */

import { useState, useEffect, useCallback } from 'react'
import { listTickets } from '../services/support.service'

export default function useTickets(initialFilters = {}, pageSize = 20) {
  const [tickets, setTickets]     = useState([])
  const [total, setTotal]         = useState(0)
  const [page, setPage]           = useState(1)
  const [filters, setFilters]     = useState(initialFilters)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
  const [tick, setTick]           = useState(0)

  // tick-counter pattern (Pattern 19)
  const refresh = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    listTickets({ ...filters, page, page_size: pageSize })
      .then(data => {
        if (cancelled) return
        setTickets(data?.items || [])
        setTotal(data?.total || 0)
      })
      .catch(err => {
        if (cancelled) return
        setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [filters, page, pageSize, tick])

  const applyFilters = useCallback(newFilters => {
    setFilters(newFilters)
    setPage(1)
  }, [])

  const goToPage = useCallback(n => setPage(n), [])

  const hasMore = page * pageSize < total

  return {
    tickets, total, page, pageSize, hasMore,
    filters, applyFilters, goToPage,
    loading, error, refresh,
  }
}
