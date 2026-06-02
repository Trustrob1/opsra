/**
 * frontend/src/pages/OwnerDashboardContent.jsx
 *
 * PERF-1C — Owner external dashboard content. Redesigned UI.
 * 6 panels: Staff Performance, Tasks Health, Support & Issues,
 *           Daily Log Approvals, Business Goals, Health Score banner.
 * Auto-refreshes every 2 minutes.
 * PDF export via window.print().
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getOwnerDashboardPanels,
  approveOwnerLog,
  flagOwnerLog,
  getOwnerDashboardGoals,
} from '../services/performance.service'

const REFRESH_MS = 2 * 60 * 1000

// ── Design tokens ────────────────────────────────────────────────────────────
const T = {
  teal:   { bg: '#E1F5EE', color: '#0F6E56' },
  amber:  { bg: '#FAEEDA', color: '#854F0B' },
  blue:   { bg: '#E6F1FB', color: '#185FA5' },
  purple: { bg: '#EEEDFE', color: '#534AB7' },
  coral:  { bg: '#FAECE7', color: '#993C1D' },
  green:  { bg: '#EAF3DE', color: '#3B6D11' },
  red:    { bg: '#FCEBEB', color: '#A32D2D' },
}

const pill = (variant) => ({
  fontSize: 11, fontWeight: 500,
  padding: '2px 8px', borderRadius: 20,
  background: T[variant].bg, color: T[variant].color,
  display: 'inline-block',
})

const PANEL = {
  background: 'var(--color-background-primary, white)',
  border: '0.5px solid var(--color-border-tertiary, #e5e7eb)',
  borderRadius: 12, marginBottom: 10, overflow: 'hidden',
}
const PANEL_HEADER = {
  display: 'flex', alignItems: 'center', gap: 8,
  padding: '11px 14px',
  borderBottom: '0.5px solid var(--color-border-tertiary, #f3f4f6)',
}
const PANEL_BODY = { padding: '12px 14px' }

const STAT_ROW = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '7px 0', borderBottom: '0.5px solid var(--color-border-tertiary, #f9fafb)',
  fontSize: 13,
}

// ── Sub-components ───────────────────────────────────────────────────────────

function PanelIcon({ variant, icon }) {
  return (
    <div style={{
      width: 28, height: 28, borderRadius: 7, flexShrink: 0,
      background: T[variant].bg, color: T[variant].color,
      display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
    }}>
      <i className={`ti ti-${icon}`} aria-hidden="true" />
    </div>
  )
}

function Panel({ title, icon, iconVariant, badge, badgeVariant, children }) {
  return (
    <div style={PANEL}>
      <div style={PANEL_HEADER}>
        <PanelIcon variant={iconVariant} icon={icon} />
        <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text-primary)', flex: 1 }}>{title}</span>
        {badge && <span style={pill(badgeVariant || 'green')}>{badge}</span>}
      </div>
      <div style={PANEL_BODY}>{children}</div>
    </div>
  )
}

function StatRow({ label, value, variant }) {
  return (
    <div style={{ ...STAT_ROW }}>
      <span style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>{label}</span>
      <span style={{ fontWeight: 500, fontSize: 13, color: variant ? T[variant].color : 'var(--color-text-primary)' }}>
        {value}
      </span>
    </div>
  )
}

function Avatar({ name }) {
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div style={{
      width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
      background: T.teal.bg, color: T.teal.color,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 11, fontWeight: 500,
    }}>{initials}</div>
  )
}

function GoalBar({ goal }) {
  const pct = Math.min(100, Math.round(goal.achievement_pct || 0))
  const variant = goal.colour === 'green' ? 'green' : goal.colour === 'amber' ? 'amber' : 'red'
  const fillColor = variant === 'green' ? '#10b981' : variant === 'amber' ? '#F59E0B' : '#E24B4A'
  const paceColor = goal.pace === 'Ahead' ? T.green.color : goal.pace === 'Behind' ? T.red.color : T.amber.color
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text-primary)' }}>{goal.goal_name}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            {Number(goal.current_value || 0).toLocaleString()} / {Number(goal.target_value || 0).toLocaleString()} {goal.unit}
          </span>
          <span style={pill(variant)}>{pct}%</span>
          <span style={{ fontSize: 10, fontWeight: 500, color: paceColor }}>{goal.pace}</span>
        </div>
      </div>
      <div style={{ background: 'var(--color-background-secondary, #f3f4f6)', borderRadius: 4, height: 6 }}>
        <div style={{ background: fillColor, borderRadius: 4, height: 6, width: `${pct}%`, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

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
      else setError('Failed to load dashboard data. Retrying in 2 minutes.')
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

  if (loading) return (
    <div style={{ position: 'fixed', inset: 0, background: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center', color: '#6b7280', fontSize: 14 }}>Loading dashboard…</div>
    </div>
  )

  const healthVariant = health?.colour === 'green' ? 'green' : health?.colour === 'amber' ? 'amber' : 'red'
  const ringColor     = health?.colour === 'green' ? '#10b981' : health?.colour === 'amber' ? '#F59E0B' : '#E24B4A'
  const ringBg        = T[healthVariant]?.bg || '#f3f4f6'
  const ringText      = T[healthVariant]?.color || '#374151'

  return (
    <div style={{ background: '#f1f5f9', minHeight: '100vh', padding: '14px 14px 32px' }}>
      <div style={{ maxWidth: 480, margin: '0 auto' }}>

        {/* Top bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
            <button onClick={fetchAll} style={{ background: 'var(--color-background-primary, white)', border: '0.5px solid var(--color-border-secondary, #d1d5db)', borderRadius: 8, padding: '6px 10px', fontSize: 12, color: 'var(--color-text-secondary)', cursor: 'pointer' }}>
              <i className="ti ti-refresh" aria-hidden="true" />
            </button>
            <button onClick={() => window.print()} style={{ background: 'var(--color-background-primary, white)', border: '0.5px solid var(--color-border-secondary, #d1d5db)', borderRadius: 8, padding: '6px 10px', fontSize: 12, color: 'var(--color-text-secondary)', cursor: 'pointer' }}>
              <i className="ti ti-printer" aria-hidden="true" />
            </button>
          </div>
        </div>

        {error && (
          <div style={{ background: T.red.bg, borderRadius: 8, padding: '10px 14px', marginBottom: 12, fontSize: 13, color: T.red.color }}>
            <i className="ti ti-alert-triangle" aria-hidden="true" style={{ marginRight: 6 }} />{error}
          </div>
        )}

        {/* Health score */}
        {health && (
          <div style={{ ...PANEL, marginBottom: 10 }}>
            <div style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ width: 52, height: 52, borderRadius: '50%', background: ringBg, border: `3px solid ${ringColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <span style={{ fontSize: 18, fontWeight: 500, color: ringText }}>{Math.round(health.health_score || 0)}</span>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6 }}>Organisation health score</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 12px' }}>
                  {health.components && Object.entries(health.components).map(([k, v]) => (
                    <div key={k} style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
                      {k} <strong style={{ color: 'var(--color-text-primary)', fontWeight: 500 }}>{Math.round(v.score)}%</strong>
                      <span style={{ color: 'var(--color-text-secondary)' }}> ({v.weight}%)</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Staff performance */}
        {panels?.panel_staff && (
          <Panel
            title="Staff performance" icon="users" iconVariant="teal"
            badge={panels.panel_staff.off_track > 0 ? `${panels.panel_staff.off_track} off track` : 'On track'}
            badgeVariant={panels.panel_staff.off_track > 0 ? 'red' : 'green'}
          >
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
              {[
                { label: 'On track', val: panels.panel_staff.on_track,  v: 'green' },
                { label: 'At risk',  val: panels.panel_staff.at_risk,   v: 'amber' },
                { label: 'Off track',val: panels.panel_staff.off_track, v: 'red'   },
              ].map(s => (
                <div key={s.label} style={{ background: 'var(--color-background-secondary, #f9fafb)', borderRadius: 8, padding: '10px 0', textAlign: 'center' }}>
                  <div style={{ fontSize: 22, fontWeight: 500, color: T[s.v].color, lineHeight: 1 }}>{s.val}</div>
                  <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginTop: 3 }}>{s.label}</div>
                </div>
              ))}
            </div>
            {panels.panel_staff.at_risk_list?.filter(s => s.score < 75).map(s => (
              <div key={s.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '0.5px solid var(--color-border-tertiary, #f3f4f6)' }}>
                <Avatar name={s.name} />
                <span style={{ fontSize: 12, color: 'var(--color-text-primary)', flex: 1 }}>{s.name}</span>
                <span style={pill(s.score >= 75 ? 'green' : s.score >= 50 ? 'amber' : 'red')}>{Math.round(s.score)}%</span>
              </div>
            ))}
            {panels.panel_staff.overdue_log_alert?.length > 0 && (
              <div style={{ background: T.amber.bg, borderRadius: 8, padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 11, color: T.amber.color }}>
                <i className="ti ti-alert-triangle" aria-hidden="true" />
                {panels.panel_staff.overdue_log_alert.length} staff member{panels.panel_staff.overdue_log_alert.length > 1 ? 's have' : ' has'} not logged today
              </div>
            )}
          </Panel>
        )}

        {/* Tasks health */}
        {panels?.panel_tasks && (
          <Panel
            title="Tasks health" icon="checkbox" iconVariant="amber"
            badge={panels.panel_tasks.overdue?.length > 0 ? `${panels.panel_tasks.overdue.length} overdue` : 'Clear'}
            badgeVariant={panels.panel_tasks.overdue?.length > 0 ? 'red' : 'green'}
          >
            <div style={{ ...STAT_ROW, borderBottom: '0.5px solid var(--color-border-tertiary, #f9fafb)' }}>
              <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>Due today — completed</span>
              <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text-primary)' }}>{panels.panel_tasks.due_today_completed}</span>
            </div>
            <div style={{ ...STAT_ROW, borderBottom: '0.5px solid var(--color-border-tertiary, #f9fafb)' }}>
              <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>Due today — pending</span>
              <span style={{ fontWeight: 500, fontSize: 13, color: panels.panel_tasks.due_today_pending > 0 ? T.amber.color : 'var(--color-text-primary)' }}>{panels.panel_tasks.due_today_pending}</span>
            </div>
            <div style={{ ...STAT_ROW, borderBottom: 'none' }}>
              <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>Overdue tasks</span>
              <span style={{ fontWeight: 500, fontSize: 13, color: (panels.panel_tasks.overdue?.length || 0) > 0 ? T.red.color : 'var(--color-text-primary)' }}>{panels.panel_tasks.overdue?.length || 0}</span>
            </div>
            {panels.panel_tasks.overdue?.slice(0, 3).length > 0 && (
              <div style={{ background: 'var(--color-background-secondary, #f9fafb)', borderRadius: 8, padding: '8px 10px', marginTop: 10 }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 5 }}>Top overdue</div>
                {panels.panel_tasks.overdue.slice(0, 3).map(t => (
                  <div key={t.id} style={{ fontSize: 11, color: 'var(--color-text-primary)', lineHeight: 1.8 }}>• {t.title}</div>
                ))}
              </div>
            )}
          </Panel>
        )}

        {/* Support & issues */}
        {panels?.panel_support && (
          <Panel
            title="Support & issues" icon="ticket" iconVariant="blue"
            badge={panels.panel_support.open_tickets === 0 && panels.panel_support.overdue_tickets === 0 ? 'All clear' : `${panels.panel_support.open_tickets} open`}
            badgeVariant={panels.panel_support.open_tickets === 0 ? 'green' : 'amber'}
          >
            <StatRow label="Open tickets"         value={panels.panel_support.open_tickets}                     variant={panels.panel_support.open_tickets > 0 ? 'amber' : null} />
            <StatRow label="SLA breached"          value={panels.panel_support.overdue_tickets}                  variant={panels.panel_support.overdue_tickets > 0 ? 'red' : null} />
            <div style={{ ...STAT_ROW, borderBottom: 'none' }}>
              <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>High-priority issues</span>
              <span style={{ fontWeight: 500, fontSize: 13, color: (panels.panel_support.high_priority_issues?.length || 0) > 0 ? T.red.color : 'var(--color-text-primary)' }}>
                {panels.panel_support.high_priority_issues?.length || 0}
              </span>
            </div>
          </Panel>
        )}

        {/* Daily log approvals */}
        {panels?.panel_approvals && (
          <Panel
            title="Daily log approvals" icon="clipboard-check" iconVariant="purple"
            badge={panels.panel_approvals.length === 0 ? 'All approved' : `${panels.panel_approvals.length} pending`}
            badgeVariant={panels.panel_approvals.length === 0 ? 'green' : 'amber'}
          >
            {panels.panel_approvals.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '10px 0', fontSize: 12, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                <i className="ti ti-circle-check" aria-hidden="true" style={{ color: '#10b981' }} /> All logs approved for today
              </div>
            ) : panels.panel_approvals.map(log => (
              <div key={log.log_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '0.5px solid var(--color-border-tertiary, #f9fafb)' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text-primary)' }}>{log.kpi_label || log.entity_type}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginTop: 1 }}>Value: {log.value} · {log.attendance_status}</div>
                </div>
                <button onClick={() => handleApprove(log.log_id)} disabled={actionLoading === log.log_id}
                  style={{ fontSize: 11, padding: '4px 9px', borderRadius: 6, cursor: 'pointer', border: 'none', fontWeight: 500, background: T.green.bg, color: T.green.color, minWidth: 64 }}>
                  {actionLoading === log.log_id ? '…' : <><i className="ti ti-check" aria-hidden="true" /> Approve</>}
                </button>
                <button onClick={() => { setFlagModal(log.log_id); setFlagNote('') }}
                  style={{ fontSize: 11, padding: '4px 9px', borderRadius: 6, cursor: 'pointer', border: 'none', fontWeight: 500, background: T.red.bg, color: T.red.color }}>
                  <i className="ti ti-flag" aria-hidden="true" /> Flag
                </button>
              </div>
            ))}
          </Panel>
        )}

        {/* Business goals */}
        {goals.length > 0 && (
          <Panel title="Business goals" icon="target" iconVariant="coral">
            {goals.map(g => <GoalBar key={g.id} goal={g} />)}
          </Panel>
        )}

      </div>

      {/* Flag modal — faux viewport pattern (no position:fixed) */}
      {flagModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <div style={{ background: 'var(--color-background-primary, white)', borderRadius: '14px 14px 0 0', padding: 22, width: '100%', maxWidth: 480 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontWeight: 500, fontSize: 15, color: 'var(--color-text-primary)' }}>
                <i className="ti ti-flag" aria-hidden="true" style={{ marginRight: 6, color: T.red.color }} />Flag this log
              </span>
              <button onClick={() => setFlagModal(null)} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: 'var(--color-text-secondary)' }}>
                <i className="ti ti-x" aria-hidden="true" />
              </button>
            </div>
            <textarea
              value={flagNote}
              onChange={e => setFlagNote(e.target.value)}
              placeholder="Describe the issue (e.g. numbers seem inflated)"
              maxLength={500} rows={3}
              style={{ width: '100%', border: '0.5px solid var(--color-border-secondary, #d1d5db)', borderRadius: 8, padding: '10px 12px', fontSize: 13, boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit', background: 'var(--color-background-primary)' }}
            />
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <button onClick={() => setFlagModal(null)} style={{ flex: 1, padding: '10px', border: '0.5px solid var(--color-border-secondary, #d1d5db)', borderRadius: 8, cursor: 'pointer', background: 'var(--color-background-primary)', fontSize: 13, color: 'var(--color-text-primary)' }}>Cancel</button>
              <button onClick={handleFlag} disabled={!flagNote.trim() || !!actionLoading}
                style={{ flex: 2, padding: '10px', border: 'none', borderRadius: 8, cursor: 'pointer', background: T.red.color, color: 'white', fontSize: 13, fontWeight: 500, opacity: !flagNote.trim() ? 0.5 : 1 }}>
                {actionLoading ? 'Flagging…' : 'Submit flag'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
