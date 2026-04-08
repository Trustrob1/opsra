/**
 * hooks/useTasks.js
 * Task Management hook — Phase 7B (updated Phase 9C).
 *
 * Phase 9C additions:
 *   - assigned_to filter passed to API (was silently dropped before)
 *   - created_preset / due_preset → converted to ISO date ranges before
 *     sending to listTasks. Presets:
 *       created: today | last_7 | last_30 | custom
 *       due:     today | next_7 | next_30 | overdue | custom
 *   - custom preset uses created_from/created_to or due_from/due_to raw dates
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

export const DEFAULT_FILTERS = {
  priority:       '',
  status:         '',
  module:         '',
  assigned_to:    '',
  // Created date
  created_preset: '',   // '' | today | last_7 | last_30 | custom
  created_from:   '',   // YYYY-MM-DD — used when created_preset = custom
  created_to:     '',   // YYYY-MM-DD — used when created_preset = custom
  // Due date
  due_preset:     '',   // '' | today | next_7 | next_30 | overdue | custom
  due_from:       '',   // YYYY-MM-DD — used when due_preset = custom
  due_to:         '',   // YYYY-MM-DD — used when due_preset = custom
}

// ── Date range helpers ────────────────────────────────────────────────────────

function todayStr() {
  return new Date().toISOString().split('T')[0]
}

/**
 * Convert filter presets to concrete ISO datetime strings for the API.
 * Returns { created_from, created_to, due_from, due_to } — any can be null.
 */
function resolveDateParams(filters) {
  const now   = new Date()
  const today = todayStr()
  let created_from = null
  let created_to   = null
  let due_from     = null
  let due_to       = null

  // ── Created preset ──────────────────────────────────────────────────────
  switch (filters.created_preset) {
    case 'today':
      created_from = `${today}T00:00:00Z`
      created_to   = `${today}T23:59:59Z`
      break
    case 'last_7': {
      const d = new Date(now); d.setDate(d.getDate() - 7)
      created_from = d.toISOString()
      break
    }
    case 'last_30': {
      const d = new Date(now); d.setDate(d.getDate() - 30)
      created_from = d.toISOString()
      break
    }
    case 'custom':
      if (filters.created_from) created_from = `${filters.created_from}T00:00:00Z`
      if (filters.created_to)   created_to   = `${filters.created_to}T23:59:59Z`
      break
    default:
      break
  }

  // ── Due preset ──────────────────────────────────────────────────────────
  switch (filters.due_preset) {
    case 'today':
      due_from = `${today}T00:00:00Z`
      due_to   = `${today}T23:59:59Z`
      break
    case 'next_7': {
      const end = new Date(now); end.setDate(end.getDate() + 7)
      due_from = now.toISOString()
      due_to   = end.toISOString()
      break
    }
    case 'next_30': {
      const end = new Date(now); end.setDate(end.getDate() + 30)
      due_from = now.toISOString()
      due_to   = end.toISOString()
      break
    }
    case 'overdue':
      // due_at < now and not completed
      due_to = now.toISOString()
      break
    case 'custom':
      if (filters.due_from) due_from = `${filters.due_from}T00:00:00Z`
      if (filters.due_to)   due_to   = `${filters.due_to}T23:59:59Z`
      break
    default:
      break
  }

  return { created_from, created_to, due_from, due_to }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

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

    const { created_from, created_to, due_from, due_to } = resolveDateParams(filters)

    const params = {
      team:      teamView,
      page,
      page_size: pageSize,
      completed: false,
    }

    // Scalar filters
    if (filters.priority)    params.priority    = filters.priority
    if (filters.status)      params.status      = filters.status
    if (filters.module)      params.module      = filters.module
    if (filters.assigned_to) params.assigned_to = filters.assigned_to

    // Date range filters
    if (created_from) params.created_from = created_from
    if (created_to)   params.created_to   = created_to
    if (due_from)     params.due_from     = due_from
    if (due_to)       params.due_to       = due_to

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