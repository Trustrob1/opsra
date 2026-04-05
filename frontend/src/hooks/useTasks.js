/**
 * hooks/useTasks.js
 * Task Management hook — Phase 7B.
 *
 * Returns:
 *   tasks       — array of task objects for the current page
 *   total       — total matching tasks
 *   loading     — true during fetch
 *   error       — error string or null
 *   filters     — current filter state
 *   applyFilters(newFilters) — update filters and reset to page 1
 *   page        — current page number
 *   goToPage(n) — navigate to page n
 *   refresh()   — re-fetch with current filters
 *   teamView    — bool: whether team tab is active
 *   setTeamView — toggle team/personal view
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { listTasks } from '../services/tasks.service'

const DEFAULT_FILTERS = {
  priority: '',
  status:   '',
  module:   '',
}

export default function useTasks(pageSize = 20) {
  const [tasks,    setTasks]    = useState([])
  const [total,    setTotal]    = useState(0)
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [filters,  setFilters]  = useState(DEFAULT_FILTERS)
  const [page,     setPage]     = useState(1)
  const [teamView, setTeamView] = useState(false)
  const [tick,     setTick]     = useState(0)   // Pattern 19 — force re-fetch

  const cancelRef = useRef(false)

  const fetchTasks = useCallback(async () => {
    setLoading(true)
    setError(null)
    cancelRef.current = false

    const params = {
      team:      teamView,
      page,
      page_size: pageSize,
      completed: false,
    }
    if (filters.priority) params.priority = filters.priority
    if (filters.status)   params.status   = filters.status
    if (filters.module)   params.module   = filters.module

    try {
      const data = await listTasks(params)
      if (cancelRef.current) return
      setTasks(data.items || [])
      setTotal(data.total || 0)
    } catch (err) {
      if (cancelRef.current) return
      setError('Could not load tasks. Please refresh.')
    } finally {
      if (!cancelRef.current) setLoading(false)
    }
  }, [filters, page, pageSize, teamView, tick])  // eslint-disable-line

  useEffect(() => {
    fetchTasks()
    return () => { cancelRef.current = true }
  }, [fetchTasks])

  const applyFilters = useCallback((newFilters) => {
    setFilters(prev => ({ ...prev, ...newFilters }))
    setPage(1)
  }, [])

  const goToPage = useCallback((n) => setPage(n), [])

  const refresh = useCallback(() => setTick(t => t + 1), [])

  return {
    tasks,
    total,
    loading,
    error,
    filters,
    applyFilters,
    page,
    goToPage,
    refresh,
    teamView,
    setTeamView,
  }
}
