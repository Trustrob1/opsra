/**
 * frontend/src/pages/OwnerDashboardContent.jsx
 *
 * PERF-1C — Owner external dashboard content.
 * 6 panels: Staff Performance, Tasks Health, Support & Issues,
 *           Daily Log Approvals, Sales Pulse, Business Goals.
 * Auto-refreshes every 2 minutes.
 * PDF export via window.print().
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getOwnerDashboardPanels,
  getHealthScore,
  approveOwnerLog,
  flagOwnerLog,
  getOwnerDashboardGoals,
} from '../services/performance.service'

const REFRESH_MS = 2 * 60 * 1000  // 2 minutes

const BADGE = (colour) => {
  if (colour === 'green') return { background: '#d1fae5', color: '#065f46' }
  if (colour === 'amber') return { background: '#fef3c7', color: '#92400e' }
  return { background: '#fee2e2', color: '#991b1b' }
}

const SCORE_PILL = ({ pct, colour }) => (
  <span style={{ ...BADGE(colour), borderRadius: 20, padding: '3px 10px', fontSize: 12, fontWeight: 600 }}>
    {pct}%
  </span>
)

function Panel({ title, icon, children, accentColour = '#01919E' }) {
  return (
    <div style={{ background: 'white', borderRadius: 12, border: '1px solid #e5e7eb', overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>{icon}</span>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#0f2535' }}>{title}</span>
      </div>
      <div style={{ padding: '14px 16px' }}>{children}</div>
    </div>
  )
}

function StatRow({ label, value, sub, colour }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #f9fafb' }}>
      <span style={{ fontSize: 13, color: '#374151' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: colour || '#0f2535' }}>{value} {sub && <span style={{ fontWeight: 400, color: '#9ca3af', fontSize: 11 }}>{sub}</span>}</span>
    </div>
  )
}

function GoalProgressBar({ goal }) {
  const pct = Math.min(100, goal.achievement_pct || 0)
  const colour = goal.colour === 'green' ? '#10b981' : goal.colour === 'amber' ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: '#0f2535' }}>{goal.goal_name}</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#6b7280' }}>
            {goal.current_value?.toLocaleString()} / {Number(goal.target_value)?.toLocaleString()} {goal.unit}
          </span>
          <SCORE_PILL pct={goal.achievement_pct} colour={goal.colour} />
          <span style={{ fontSize: 11, fontWeight: 500, color: goal.pace === 'Ahead' ? '#10b981' : goal.pace === 'Behind' ? '#ef4444' : '#f59e0b' }}>
            {goal.pace}
          </span>
        </div>
      </div>
      <div style={{ background: '#f3f4f6', borderRadius: 4, height: 7 }}>
        <div style={{ background: colour, borderRadius: 4, height: 7, width: `${pct}%`, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

export default function OwnerDashboardContent({ token, sessionToken, orgName, onSessionExpired }) {
  const [panels,  setPanels]  = useState(null)
  const [health,  setHealth]  = useState(null)
  const [goals,   setGoals]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [flagModal, setFlagModal] = useState(null)  // {log_id}
  const [flagNote, setFlagNote]   = useState('')
  const [actionLoading, setActionLoading] = useState(null)
  const timerRef = useRef(null)

  const periodStart = (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
  })()

  const fetchAll = useCallback(async () => {
    try {
      const [panelsData, healthData, goalsData] = await Promise.all([
        getOwnerDashboardPanels(token, sessionToken),
        getHealthScore().catch(() => null),
        getOwnerDashboardGoals(token, sessionToken, periodStart).catch(() => []),
      ])
      setPanels(panelsData.panels || panelsData)
      setHealth(healthData?.data || healthData)
      setGoals(goalsData?.data || goalsData || [])
      setLastRefresh(new Date())
      setError(null)
    } catch (e) {
      if (e?.response?.status === 401) {
        onSessionExpired()
      } else {
        setError('Failed to load dashboard data. Retrying in 2 minutes.')
      }
    } finally {
      setLoading(false)
    }
  }, [token, sessionToken, periodStart, onSessionExpired])

  useEffect(() => {
    fetchAll()
    timerRef.current = setInterval(fetchAll, REFRESH_MS)
    return () => clearInterval(timerRef.current)
  }, [fetchAll])

  const handleApprove = async (logId) => {
    setActionLoading(logId)
    try {
      await approveOwnerLog(token, logId, sessionToken)
      fetchAll()
    } catch (e) {
      if (e?.response?.status === 401) onSessionExpired()
    } finally {
      setActionLoading(null)
    }
  }

  const handleFlag = async () => {
    if (!flagNote.trim()) return
    setActionLoading(flagModal)
    try {
      await flagOwnerLog(token, flagModal, flagNote, sessionToken)
      setFlagModal(null)
      setFlagNote('')
      fetchAll()
    } catch (e) {
      if (e?.response?.status === 401) onSessionExpired()
    } finally {
      setActionLoading(null)
    }
  }

  if (loading) {
    return (
      <div style={{ position: 'fixed', inset: 0, background: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', color: '#6b7280', fontSize: 14 }}>Loading dashboard…</div>
      </div>
    )
  }

  const healthColour = health?.colour === 'green' ? '#10b981' : health?.colour === 'amber' ? '#f59e0b' : '#ef4444'

  return (
    <div style={{ background: '#f1f5f9', minHeight: '100vh', padding: '20px 16px' }}>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <div style={{ width: 34, height: 34, background: '#01919E', borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 16, color: 'white' }}>O</div>
              <span style={{ fontWeight: 700, fontSize: 18, color: '#0f2535' }}>{orgName || 'Owner Dashboard'}</span>
            </div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              {lastRefresh ? `Last updated ${lastRefresh.toLocaleTimeString()}` : 'Loading…'} · Auto-refreshes every 2 min
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={fetchAll} style={BTN_SECONDARY}>↻ Refresh</button>
            <button onClick={() => window.print()} style={BTN_SECONDARY}>🖨 Print</button>
          </div>
        </div>

        {error && (
          <div style={{ background: '#fee2e2', borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#991b1b' }}>⚠ {error}</div>
        )}

        {/* Health Score Banner */}
        {health && (
          <div style={{ background: 'white', borderRadius: 12, border: `2px solid ${healthColour}`, padding: '16px 20px', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 56, height: 56, borderRadius: '50%', background: healthColour, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 800, fontSize: 20, flexShrink: 0 }}>
              {health.health_score}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15, color: '#0f2535' }}>Organisation Health Score</div>
              <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
                {health.components && Object.entries(health.components).map(([k, v]) => (
                  <span key={k} style={{ fontSize: 11, color: '#6b7280' }}>
                    {k}: <strong style={{ color: '#374151' }}>{v.score}%</strong> <span style={{ color: '#9ca3af' }}>({v.weight}%)</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Panel 1 — Staff Performance */}
        {panels?.panel_staff && (
          <Panel title="Staff Performance" icon="👥">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 14 }}>
              {[
                { label: 'On Track', value: panels.panel_staff.on_track, colour: '#10b981' },
                { label: 'At Risk',  value: panels.panel_staff.at_risk,  colour: '#f59e0b' },
                { label: 'Off Track',value: panels.panel_staff.off_track, colour: '#ef4444' },
              ].map(s => (
                <div key={s.label} style={{ textAlign: 'center', background: '#f9fafb', borderRadius: 8, padding: '10px 0' }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: s.colour }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: '#6b7280' }}>{s.label}</div>
                </div>
              ))}
            </div>
            {panels.panel_staff.at_risk_list?.filter(s => s.score < 75).map(s => (
              <div key={s.user_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f9fafb', fontSize: 13 }}>
                <span style={{ color: '#374151' }}>{s.name}</span>
                <SCORE_PILL pct={s.score} colour={s.score >= 75 ? 'green' : s.score >= 50 ? 'amber' : 'red'} />
              </div>
            ))}
            {panels.panel_staff.overdue_log_alert?.length > 0 && (
              <div style={{ marginTop: 10, background: '#fff7ed', borderRadius: 7, padding: '8px 12px', fontSize: 12, color: '#92400e' }}>
                ⚠ {panels.panel_staff.overdue_log_alert.length} staff member{panels.panel_staff.overdue_log_alert.length > 1 ? 's have' : ' has'} not logged today
              </div>
            )}
          </Panel>
        )}

        {/* Panel 2 — Tasks Health */}
        {panels?.panel_tasks && (
          <Panel title="Tasks Health" icon="✅">
            <StatRow label="Due today — completed" value={panels.panel_tasks.due_today_completed} />
            <StatRow label="Due today — pending"   value={panels.panel_tasks.due_today_pending} colour={panels.panel_tasks.due_today_pending > 0 ? '#f59e0b' : undefined} />
            <StatRow label="Overdue tasks"          value={panels.panel_tasks.overdue?.length || 0} colour={panels.panel_tasks.overdue?.length > 0 ? '#ef4444' : undefined} />
            {panels.panel_tasks.overdue?.slice(0, 5).map(t => (
              <div key={t.id} style={{ fontSize: 12, color: '#6b7280', padding: '3px 0 3px 12px' }}>• {t.title}</div>
            ))}
          </Panel>
        )}

        {/* Panel 3 — Support & Issues */}
        {panels?.panel_support && (
          <Panel title="Support & Issues" icon="🎫">
            <StatRow label="Open tickets"        value={panels.panel_support.open_tickets}    colour={panels.panel_support.open_tickets > 0 ? '#f59e0b' : undefined} />
            <StatRow label="SLA breached"        value={panels.panel_support.overdue_tickets} colour={panels.panel_support.overdue_tickets > 0 ? '#ef4444' : undefined} />
            <StatRow label="High-priority issues" value={panels.panel_support.high_priority_issues?.length || 0} colour={panels.panel_support.high_priority_issues?.length > 0 ? '#ef4444' : undefined} />
            {panels.panel_support.high_priority_issues?.slice(0, 3).map(i => (
              <div key={i.id} style={{ fontSize: 12, color: '#6b7280', padding: '3px 0 3px 12px' }}>• {i.title}</div>
            ))}
          </Panel>
        )}

        {/* Panel 4 — Daily Log Approvals */}
        {panels?.panel_approvals && (
          <Panel title="Daily Log Approvals" icon="📋">
            {panels.panel_approvals.length === 0 && (
              <div style={{ textAlign: 'center', color: '#9ca3af', fontSize: 13, padding: '8px 0' }}>All logs approved ✓</div>
            )}
            {panels.panel_approvals.map(log => (
              <div key={log.log_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f9fafb' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#0f2535' }}>{log.kpi_label || log.entity_type}</div>
                  <div style={{ fontSize: 11, color: '#9ca3af' }}>Value: {log.value} · {log.attendance_status}</div>
                </div>
                <button
                  onClick={() => handleApprove(log.log_id)}
                  disabled={actionLoading === log.log_id}
                  style={{ ...BTN_GREEN, minWidth: 72 }}
                >
                  {actionLoading === log.log_id ? '…' : '✓ Approve'}
                </button>
                <button
                  onClick={() => { setFlagModal(log.log_id); setFlagNote('') }}
                  style={BTN_RED}
                >
                  🚩 Flag
                </button>
              </div>
            ))}
          </Panel>
        )}

        {/* Panel 5 — Business Goals */}
        {goals.length > 0 && (
          <Panel title="Business Goals" icon="🎯">
            {goals.map(g => <GoalProgressBar key={g.id} goal={g} />)}
          </Panel>
        )}

      </div>

      {/* Flag modal */}
      {flagModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <div style={{ background: 'white', borderRadius: '16px 16px 0 0', padding: 24, width: '100%', maxWidth: 480 }}>
            <h3 style={{ margin: '0 0 12px', fontWeight: 700, fontSize: 16, color: '#0f2535' }}>🚩 Flag this log</h3>
            <textarea
              value={flagNote}
              onChange={e => setFlagNote(e.target.value)}
              placeholder="Describe the issue (e.g. numbers seem inflated, attendance not matching schedule)"
              maxLength={500}
              rows={3}
              style={{ width: '100%', border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 12px', fontSize: 13, boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' }}
            />
            <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
              <button onClick={() => setFlagModal(null)} style={{ flex: 1, padding: '10px', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer', background: 'white', fontSize: 13 }}>Cancel</button>
              <button onClick={handleFlag} disabled={!flagNote.trim() || !!actionLoading} style={{ flex: 2, padding: '10px', border: 'none', borderRadius: 8, cursor: 'pointer', background: '#ef4444', color: 'white', fontSize: 13, fontWeight: 600 }}>
                {actionLoading ? 'Flagging…' : 'Submit Flag'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const BTN_SECONDARY = {
  background: 'white', border: '1px solid #e5e7eb', borderRadius: 7,
  padding: '6px 12px', fontSize: 12, cursor: 'pointer', color: '#374151',
}
const BTN_GREEN = {
  background: '#d1fae5', border: '1px solid #6ee7b7', borderRadius: 6,
  padding: '4px 10px', fontSize: 12, cursor: 'pointer', color: '#065f46', fontWeight: 600,
}
const BTN_RED = {
  background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 6,
  padding: '4px 10px', fontSize: 12, cursor: 'pointer', color: '#991b1b', fontWeight: 600,
}
