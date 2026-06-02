/**
 * frontend/src/pages/OwnerDashboardContent.jsx
 *
 * PERF-1C — Owner external dashboard. Option C layout.
 * Left sidebar: health score ring + goals + nav actions.
 * Right main: staff, tasks, support, approvals panels — full width.
 * Tabler icons loaded via CDN in OwnerDashboardPage.jsx head link.
 * Auto-refreshes every 2 minutes.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getOwnerDashboardPanels,
  approveOwnerLog,
  flagOwnerLog,
  getOwnerDashboardGoals,
} from '../services/performance.service'

const REFRESH_MS = 2 * 60 * 1000

const C = {
  teal:   { bg: '#E1F5EE', color: '#0F6E56' },
  amber:  { bg: '#FAEEDA', color: '#854F0B' },
  blue:   { bg: '#E6F1FB', color: '#185FA5' },
  purple: { bg: '#EEEDFE', color: '#534AB7' },
  coral:  { bg: '#FAECE7', color: '#993C1D' },
  green:  { bg: '#EAF3DE', color: '#3B6D11' },
  red:    { bg: '#FCEBEB', color: '#A32D2D' },
  gray:   { bg: '#F1EFE8', color: '#5F5E5A' },
}

const pill = (v, size = 10) => ({
  fontSize: size, fontWeight: 500,
  padding: '2px 7px', borderRadius: 20,
  background: C[v].bg, color: C[v].color,
  display: 'inline-flex', alignItems: 'center', gap: 3,
  whiteSpace: 'nowrap',
})

const CARD = {
  background: 'white',
  border: '1px solid #e5e7eb',
  borderRadius: 10, overflow: 'hidden',
}
const CH = {
  display: 'flex', alignItems: 'center', gap: 8,
  padding: '10px 12px',
  borderBottom: '1px solid #f3f4f6',
}
const CB = { padding: '10px 12px' }
const SROW = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '5px 0', borderBottom: '1px solid #f3f4f6',
  fontSize: 12,
}

function PanelIcon({ v, icon }) {
  return (
    <div style={{
      width: 26, height: 26, borderRadius: 6, flexShrink: 0,
      background: C[v].bg, color: C[v].color,
      display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13,
    }}>
      <i className={`ti ti-${icon}`} aria-hidden="true" />
    </div>
  )
}

function Avatar({ name }) {
  const i = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div style={{
      width: 26, height: 26, borderRadius: '50%', flexShrink: 0,
      background: C.teal.bg, color: C.teal.color,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 10, fontWeight: 500,
    }}>{i}</div>
  )
}

function GoalBar({ goal, compact = false }) {
  const pct  = Math.min(100, Math.round(goal.achievement_pct || 0))
  const v    = goal.colour === 'green' ? 'green' : goal.colour === 'amber' ? 'amber' : 'red'
  const fill = v === 'green' ? '#10b981' : v === 'amber' ? '#F59E0B' : '#E24B4A'
  const paceColor = goal.pace === 'Ahead' ? C.green.color : goal.pace === 'Behind' ? C.red.color : C.amber.color
  return (
    <div style={{ marginBottom: compact ? 8 : 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
        <span style={{ fontSize: compact ? 10 : 11, fontWeight: 500, color: 'var(--color-text-primary)' }}>
          {goal.goal_name}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {!compact && (
            <span style={{ fontSize: 10, color: 'var(--color-text-secondary)' }}>
              {Number(goal.current_value || 0).toLocaleString()} / {Number(goal.target_value || 0).toLocaleString()}
            </span>
          )}
          <span style={pill(v)}>{pct}%</span>
          {!compact && (
            <span style={{ fontSize: 10, fontWeight: 500, color: paceColor }}>{goal.pace}</span>
          )}
        </div>
      </div>
      <div style={{ background: 'var(--color-background-secondary)', borderRadius: 3, height: 5 }}>
        <div style={{ background: fill, borderRadius: 3, height: 5, width: `${pct}%`, transition: 'width 0.4s ease' }} />
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
  const [flagModal, setFlagModal] = useState(null)
  const [flagNote,  setFlagNote]  = useState('')
  const [actionLoading, setActionLoading] = useState(null)
  const timerRef = useRef(null)

  const periodStart = (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
  })()

  const fetchAll = useCallback(async () => {
    try {
      const [panelsData, goalsData] = await Promise.all([
        getOwnerDashboardPanels(token, sessionToken),
        getOwnerDashboardGoals(token, sessionToken, periodStart).catch(() => []),
      ])
      setPanels(panelsData.panels || panelsData)
      setHealth(panelsData.health_score || null)
      setGoals(goalsData?.data || goalsData || [])
      setLastRefresh(new Date())
      setError(null)
    } catch (e) {
      if (e?.response?.status === 401) onSessionExpired()
      else setError('Failed to load. Retrying in 2 minutes.')
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
    try { await approveOwnerLog(token, logId, sessionToken); fetchAll() }
    catch (e) { if (e?.response?.status === 401) onSessionExpired() }
    finally { setActionLoading(null) }
  }

  const handleFlag = async () => {
    if (!flagNote.trim()) return
    setActionLoading(flagModal)
    try {
      await flagOwnerLog(token, flagModal, flagNote, sessionToken)
      setFlagModal(null); setFlagNote(''); fetchAll()
    } catch (e) { if (e?.response?.status === 401) onSessionExpired() }
    finally { setActionLoading(null) }
  }

  if (loading) return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <i className="ti ti-loader" style={{ fontSize: 28, color: '#01919E' }} aria-hidden="true" />
        <span style={{ fontSize: 13, color: '#6b7280' }}>Loading dashboard…</span>
      </div>
    </div>
  )

  const hv = health?.colour === 'green' ? 'green' : health?.colour === 'amber' ? 'amber' : 'red'
  const ringBorder = hv === 'green' ? '#10b981' : hv === 'amber' ? '#F59E0B' : '#E24B4A'

  return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9', fontFamily: 'system-ui, -apple-system, sans-serif' }}>

      {/* ── Top bar (mobile fallback) ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', background: 'var(--color-background-primary)',
        borderBottom: '0.5px solid var(--color-border-tertiary)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: '#01919E', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 500, fontSize: 13, flexShrink: 0 }}>
            {(orgName || 'O')[0].toUpperCase()}
          </div>
          <div>
            <div style={{ fontWeight: 500, fontSize: 14, color: 'var(--color-text-primary)' }}>{orgName || 'Owner Dashboard'}</div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary)' }}>
              {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString()}` : 'Loading…'} · auto-refreshes every 2 min
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={fetchAll} aria-label="Refresh" style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--color-background-secondary)', border: '0.5px solid var(--color-border-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, cursor: 'pointer', color: 'var(--color-text-secondary)' }}>
            <i className="ti ti-refresh" aria-hidden="true" />
          </button>
          <button onClick={() => window.print()} aria-label="Print" style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--color-background-secondary)', border: '0.5px solid var(--color-border-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, cursor: 'pointer', color: 'var(--color-text-secondary)' }}>
            <i className="ti ti-printer" aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* ── Main layout ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px,220px) 1fr', gap: 16, padding: 16, maxWidth: 1100, margin: '0 auto' }}>

        {/* ── LEFT SIDEBAR ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

          {/* Health score card */}
          <div style={CARD}>
            <div style={{ padding: '14px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
                <i className="ti ti-heart-rate-monitor" style={{ fontSize: 16, color: C[hv].color }} aria-hidden="true" />
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Health score</span>
              </div>
              <div style={{ width: 64, height: 64, borderRadius: '50%', border: `3px solid ${ringBorder}`, background: C[hv].bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ fontSize: 22, fontWeight: 500, color: C[hv].color }}>{Math.round(health?.health_score || 0)}</span>
              </div>
              <div style={{ width: '100%', borderTop: '0.5px solid var(--color-border-tertiary)', paddingTop: 10 }}>
                {health?.components && Object.entries(health.components).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0' }}>
                    <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 5 }}>
                      <i className={`ti ti-${k === 'sales' ? 'currency-dollar' : k === 'staff' ? 'users' : k === 'tasks' ? 'checkbox' : 'ticket'}`} style={{ fontSize: 12 }} aria-hidden="true" />
                      {k}
                    </span>
                    <span style={{ fontWeight: 500, color: 'var(--color-text-primary)' }}>{Math.round(v.score)}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Business goals card */}
          {goals.length > 0 && (
            <div style={CARD}>
              <div style={CH}>
                <PanelIcon v="coral" icon="target" />
                <span style={{ fontWeight: 500, fontSize: 12, color: 'var(--color-text-primary)' }}>Business goals</span>
              </div>
              <div style={CB}>
                {goals.map(g => <GoalBar key={g.id} goal={g} compact />)}
              </div>
            </div>
          )}

          {/* Quick info */}
          <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 10, padding: '10px 12px' }}>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', lineHeight: 1.7 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
                <i className="ti ti-clock" style={{ fontSize: 12 }} aria-hidden="true" />
                {lastRefresh ? lastRefresh.toLocaleTimeString() : '—'}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <i className="ti ti-refresh" style={{ fontSize: 12 }} aria-hidden="true" />
                Every 2 minutes
              </div>
            </div>
          </div>

        </div>

        {/* ── RIGHT MAIN ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

          {error && (
            <div style={{ background: C.red.bg, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: C.red.color, display: 'flex', alignItems: 'center', gap: 8 }}>
              <i className="ti ti-alert-circle" style={{ fontSize: 16, flexShrink: 0 }} aria-hidden="true" />
              {error}
            </div>
          )}

          {/* Staff performance */}
          {panels?.panel_staff && (
            <div style={CARD}>
              <div style={CH}>
                <PanelIcon v="teal" icon="users" />
                <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text-primary)', flex: 1 }}>Staff performance</span>
                <span style={pill(panels.panel_staff.off_track > 0 ? 'red' : 'green', 11)}>
                  <i className={`ti ti-${panels.panel_staff.off_track > 0 ? 'alert-circle' : 'circle-check'}`} style={{ fontSize: 11 }} aria-hidden="true" />
                  {panels.panel_staff.off_track > 0 ? `${panels.panel_staff.off_track} off track` : 'On track'}
                </span>
              </div>
              <div style={CB}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
                  {[
                    { label: 'On track', val: panels.panel_staff.on_track,  v: 'green', icon: 'circle-check' },
                    { label: 'At risk',  val: panels.panel_staff.at_risk,   v: 'amber', icon: 'alert-triangle' },
                    { label: 'Off track',val: panels.panel_staff.off_track, v: 'red',   icon: 'circle-x' },
                  ].map(s => (
                    <div key={s.label} style={{ background: '#f9fafb', borderRadius: 8, padding: '10px 6px', textAlign: 'center' }}>
                      <i className={`ti ti-${s.icon}`} style={{ fontSize: 16, color: C[s.v].color, display: 'block', marginBottom: 4 }} aria-hidden="true" />
                      <div style={{ fontSize: 22, fontWeight: 500, color: C[s.v].color, lineHeight: 1 }}>{s.val}</div>
                      <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginTop: 3 }}>{s.label}</div>
                    </div>
                  ))}
                </div>
                {panels.panel_staff.at_risk_list?.filter(s => s.score < 75).map(s => (
                  <div key={s.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '0.5px solid var(--color-border-tertiary)' }}>
                    <Avatar name={s.name} />
                    <span style={{ fontSize: 12, color: 'var(--color-text-primary)', flex: 1 }}>{s.name}</span>
                    <span style={pill(s.score >= 75 ? 'green' : s.score >= 50 ? 'amber' : 'red', 11)}>{Math.round(s.score)}%</span>
                  </div>
                ))}
                {panels.panel_staff.overdue_log_alert?.length > 0 && (
                  <div style={{ background: C.amber.bg, borderRadius: 7, padding: '7px 10px', display: 'flex', alignItems: 'center', gap: 7, marginTop: 10, fontSize: 11, color: C.amber.color }}>
                    <i className="ti ti-clock-exclamation" style={{ fontSize: 14, flexShrink: 0 }} aria-hidden="true" />
                    {panels.panel_staff.overdue_log_alert.length} staff member{panels.panel_staff.overdue_log_alert.length > 1 ? 's have' : ' has'} not logged today
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Tasks health */}
          {panels?.panel_tasks && (
            <div style={CARD}>
              <div style={CH}>
                <PanelIcon v="amber" icon="checkbox" />
                <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text-primary)', flex: 1 }}>Tasks health</span>
                <span style={pill((panels.panel_tasks.overdue?.length || 0) > 0 ? 'red' : 'green', 11)}>
                  <i className={`ti ti-${(panels.panel_tasks.overdue?.length || 0) > 0 ? 'alert-circle' : 'circle-check'}`} style={{ fontSize: 11 }} aria-hidden="true" />
                  {(panels.panel_tasks.overdue?.length || 0) > 0 ? `${panels.panel_tasks.overdue.length} overdue` : 'Clear'}
                </span>
              </div>
              <div style={CB}>
                <div style={{ ...SROW }}>
                  <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <i className="ti ti-circle-check" style={{ fontSize: 14, color: C.green.color }} aria-hidden="true" />Due today — completed
                  </span>
                  <span style={{ fontWeight: 500, color: 'var(--color-text-primary)' }}>{panels.panel_tasks.due_today_completed}</span>
                </div>
                <div style={{ ...SROW }}>
                  <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <i className="ti ti-clock" style={{ fontSize: 14, color: C.amber.color }} aria-hidden="true" />Due today — pending
                  </span>
                  <span style={{ fontWeight: 500, color: panels.panel_tasks.due_today_pending > 0 ? C.amber.color : 'var(--color-text-primary)' }}>{panels.panel_tasks.due_today_pending}</span>
                </div>
                <div style={{ ...SROW, borderBottom: 'none' }}>
                  <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <i className="ti ti-alert-triangle" style={{ fontSize: 14, color: C.red.color }} aria-hidden="true" />Overdue tasks
                  </span>
                  <span style={{ fontWeight: 500, color: (panels.panel_tasks.overdue?.length || 0) > 0 ? C.red.color : 'var(--color-text-primary)' }}>{panels.panel_tasks.overdue?.length || 0}</span>
                </div>
                {panels.panel_tasks.overdue?.slice(0, 3).length > 0 && (
                  <div style={{ background: '#f9fafb', borderRadius: 7, padding: '8px 10px', marginTop: 10 }}>
                    <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginBottom: 5, display: 'flex', alignItems: 'center', gap: 5 }}>
                      <i className="ti ti-list" style={{ fontSize: 12 }} aria-hidden="true" />Top overdue
                    </div>
                    {panels.panel_tasks.overdue.slice(0, 3).map(t => (
                      <div key={t.id} style={{ fontSize: 11, color: 'var(--color-text-primary)', lineHeight: 1.8, display: 'flex', alignItems: 'center', gap: 5 }}>
                        <i className="ti ti-point-filled" style={{ fontSize: 10, color: C.red.color, flexShrink: 0 }} aria-hidden="true" />{t.title}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Support & issues */}
          {panels?.panel_support && (
            <div style={CARD}>
              <div style={CH}>
                <PanelIcon v="blue" icon="ticket" />
                <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text-primary)', flex: 1 }}>Support & issues</span>
                <span style={pill(panels.panel_support.open_tickets === 0 ? 'green' : 'amber', 11)}>
                  <i className={`ti ti-${panels.panel_support.open_tickets === 0 ? 'circle-check' : 'alert-circle'}`} style={{ fontSize: 11 }} aria-hidden="true" />
                  {panels.panel_support.open_tickets === 0 ? 'All clear' : `${panels.panel_support.open_tickets} open`}
                </span>
              </div>
              <div style={CB}>
                <div style={SROW}>
                  <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <i className="ti ti-inbox" style={{ fontSize: 14 }} aria-hidden="true" />Open tickets
                  </span>
                  <span style={{ fontWeight: 500, color: panels.panel_support.open_tickets > 0 ? C.amber.color : 'var(--color-text-primary)' }}>{panels.panel_support.open_tickets}</span>
                </div>
                <div style={SROW}>
                  <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <i className="ti ti-clock-bolt" style={{ fontSize: 14 }} aria-hidden="true" />SLA breached
                  </span>
                  <span style={{ fontWeight: 500, color: panels.panel_support.overdue_tickets > 0 ? C.red.color : 'var(--color-text-primary)' }}>{panels.panel_support.overdue_tickets}</span>
                </div>
                <div style={{ ...SROW, borderBottom: 'none' }}>
                  <span style={{ color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <i className="ti ti-flame" style={{ fontSize: 14 }} aria-hidden="true" />High-priority issues
                  </span>
                  <span style={{ fontWeight: 500, color: (panels.panel_support.high_priority_issues?.length || 0) > 0 ? C.red.color : 'var(--color-text-primary)' }}>
                    {panels.panel_support.high_priority_issues?.length || 0}
                  </span>
                </div>
                {panels.panel_support.high_priority_issues?.slice(0, 3).map(i => (
                  <div key={i.id} style={{ fontSize: 11, color: 'var(--color-text-primary)', lineHeight: 1.8, display: 'flex', alignItems: 'center', gap: 5, paddingLeft: 4 }}>
                    <i className="ti ti-point-filled" style={{ fontSize: 10, color: C.red.color }} aria-hidden="true" />{i.title}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Daily log approvals */}
          {panels?.panel_approvals && (
            <div style={CARD}>
              <div style={CH}>
                <PanelIcon v="purple" icon="clipboard-check" />
                <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text-primary)', flex: 1 }}>Daily log approvals</span>
                <span style={pill(panels.panel_approvals.length === 0 ? 'green' : 'amber', 11)}>
                  <i className={`ti ti-${panels.panel_approvals.length === 0 ? 'circle-check' : 'clock'}`} style={{ fontSize: 11 }} aria-hidden="true" />
                  {panels.panel_approvals.length === 0 ? 'All approved' : `${panels.panel_approvals.length} pending`}
                </span>
              </div>
              <div style={CB}>
                {panels.panel_approvals.length === 0 ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '10px 0', fontSize: 12, color: 'var(--color-text-secondary)' }}>
                    <i className="ti ti-circle-check" style={{ fontSize: 18, color: '#10b981' }} aria-hidden="true" />
                    All logs approved for today
                  </div>
                ) : panels.panel_approvals.map(log => (
                  <div key={log.log_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '0.5px solid var(--color-border-tertiary)' }}>
                    <i className="ti ti-file-text" style={{ fontSize: 18, color: C.purple.color, flexShrink: 0 }} aria-hidden="true" />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text-primary)' }}>{log.kpi_label || log.entity_type}</div>
                      <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginTop: 1 }}>
                        Value: {log.value} · {log.attendance_status}
                      </div>
                    </div>
                    <button onClick={() => handleApprove(log.log_id)} disabled={actionLoading === log.log_id}
                      style={{ fontSize: 11, padding: '5px 10px', borderRadius: 7, cursor: 'pointer', border: 'none', fontWeight: 500, background: C.green.bg, color: C.green.color, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <i className="ti ti-check" style={{ fontSize: 12 }} aria-hidden="true" />
                      {actionLoading === log.log_id ? '…' : 'Approve'}
                    </button>
                    <button onClick={() => { setFlagModal(log.log_id); setFlagNote('') }}
                      style={{ fontSize: 11, padding: '5px 10px', borderRadius: 7, cursor: 'pointer', border: 'none', fontWeight: 500, background: C.red.bg, color: C.red.color, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <i className="ti ti-flag" style={{ fontSize: 12 }} aria-hidden="true" />
                      Flag
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      </div>

      {/* Flag modal */}
      {flagModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <div style={{ background: 'var(--color-background-primary)', borderRadius: '14px 14px 0 0', padding: 22, width: '100%', maxWidth: 520 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontWeight: 500, fontSize: 15, color: 'var(--color-text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <i className="ti ti-flag" style={{ fontSize: 16, color: C.red.color }} aria-hidden="true" />
                Flag this log
              </span>
              <button onClick={() => setFlagModal(null)} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center' }}>
                <i className="ti ti-x" aria-hidden="true" />
              </button>
            </div>
            <textarea
              value={flagNote}
              onChange={e => setFlagNote(e.target.value)}
              placeholder="Describe the issue (e.g. numbers seem inflated, attendance not matching)"
              maxLength={500} rows={3}
              style={{ width: '100%', border: '0.5px solid var(--color-border-secondary)', borderRadius: 8, padding: '10px 12px', fontSize: 13, boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit', background: 'var(--color-background-primary)', color: 'var(--color-text-primary)' }}
            />
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <button onClick={() => setFlagModal(null)} style={{ flex: 1, padding: '10px', border: '0.5px solid var(--color-border-secondary)', borderRadius: 8, cursor: 'pointer', background: 'var(--color-background-primary)', fontSize: 13, color: 'var(--color-text-primary)' }}>
                Cancel
              </button>
              <button onClick={handleFlag} disabled={!flagNote.trim() || !!actionLoading}
                style={{ flex: 2, padding: '10px', border: 'none', borderRadius: 8, cursor: 'pointer', background: C.red.color, color: 'white', fontSize: 13, fontWeight: 500, opacity: !flagNote.trim() ? 0.5 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                <i className="ti ti-flag" style={{ fontSize: 14 }} aria-hidden="true" />
                {actionLoading ? 'Flagging…' : 'Submit flag'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
