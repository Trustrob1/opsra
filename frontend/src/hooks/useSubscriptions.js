/**
 * useSubscriptions.js — paginated subscription list hook
 *
 * Pattern 19: internal tick counter enables explicit refresh without
 *             changing filters or page (e.g., after a payment confirmation).
 * Cancelable useEffect: ref flag prevents stale state updates when the
 *             component unmounts or deps change before the fetch resolves.
 *
 * @param {object} initialFilters   Optional initial filter object
 * @param {number} pageSize         Rows per page (default 20)
 * @returns {object}                Hook API — see return statement
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { listSubscriptions } from '../services/renewal.service'

export default function useSubscriptions(initialFilters = {}, pageSize = 20) {
  const [subscriptions, setSubscriptions] = useState([])
  const [total, setTotal]                 = useState(0)
  const [page, setPage]                   = useState(1)
  const [filters, setFilters]             = useState(initialFilters)
  const [loading, setLoading]             = useState(false)
  const [error, setError]                 = useState(null)
  const [tick, setTick]                   = useState(0)    // Pattern 19
  const cancelRef                         = useRef(false)

  useEffect(() => {
    cancelRef.current = false
    setLoading(true)
    setError(null)

    listSubscriptions({ ...filters, page, page_size: pageSize })
      .then(res => {
        if (cancelRef.current) return
        if (res.success) {
          setSubscriptions(res.data.items ?? [])
          setTotal(res.data.total ?? 0)
        } else {
          setError(res.error ?? 'Failed to load subscriptions')
        }
      })
      .catch(err => {
        if (cancelRef.current) return
        setError(err?.response?.data?.detail ?? 'Failed to load subscriptions')
      })
      .finally(() => {
        if (!cancelRef.current) setLoading(false)
      })

    return () => { cancelRef.current = true }
  }, [filters, page, pageSize, tick])

  /** Replace active filters and reset to page 1. */
  const applyFilters = useCallback((newFilters) => {
    setFilters(newFilters)
    setPage(1)
  }, [])

  /** Navigate to a specific page. */
  const goToPage = useCallback((p) => setPage(p), [])

  /**
   * Trigger an explicit re-fetch without changing filters or page.
   * Call after any mutation (confirm payment, cancel, bulk upload).
   */
  const refresh = useCallback(() => setTick(t => t + 1), [])

  return {
    subscriptions,
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
