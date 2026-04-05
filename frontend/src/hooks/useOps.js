/**
 * hooks/useOps.js
 * React hook for the Operations Intelligence module — Phase 6B.
 *
 * Returns:
 *   metrics   — DashboardMetrics object (null while loading)
 *   loading   — true during initial fetch
 *   error     — error string or null
 *   refresh() — manually re-fetch metrics
 *   ask(q)    — call ask-your-data; returns answer string; throws on error
 */

import { useState, useEffect, useCallback } from 'react'
import { getDashboardMetrics, askData } from '../services/ops.service'

export default function useOps() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const fetchMetrics = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getDashboardMetrics()
      setMetrics(data)
    } catch (err) {
      setError('Could not load dashboard metrics. Please refresh.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchMetrics() }, [fetchMetrics])

  const ask = useCallback(async (question) => {
    // Throws on error — caller handles 429 and other codes
    return askData(question)
  }, [])

  return { metrics, loading, error, refresh: fetchMetrics, ask }
}
