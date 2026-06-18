/**
 * frontend/src/pages/OwnerDashboardContent.jsx
 *
 * Daily Executive Brief — PERF-1D redesign.
 * Mobile-first, responsive desktop layout (auto-fit 2-col on wide screens).
 * Single API call: GET /public/owner-dashboard/{token}/brief
 * Sections: Health score, Revenue, Pipeline, Goals,
 *           Actions needed, Sales team, Contractors.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { getOwnerBrief } from '../services/performance.service'
import { resolveActivityLog } from '../services/performance_logs.service'

const REFRESH_MS = 2 * 60 * 1000

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------
function toISODate(d) {
  return d.toISOString().slice(0, 10)
}
function yesterday() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  return d
}
function isToday(d) {
  return toISODate(d) === toISODate(new Date())
}
function fmtDateLabel(d) {
  const today = new Date()
  const yest  = yesterday()
  if (toISODate(d) === toISODate(today)) return 'Today'
  if (toISODate(d) === toISODate(yest))  return 'Yesterday'
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
}

const T = {
  green:  { bg: '#EAF3DE', color: '#3B6D11', bar: '#10b981' },
  amber:  { bg: '#FAEEDA', color: '#854F0B', bar: '#F59E0B' },
  red:    { bg: '#FCEBEB', color: '#A32D2D', bar: '#E24B4A' },
  blue:   { bg: '#E6F1FB', color: '#185FA5' },
  purple: { bg: '#EEEDFE', color: '#534AB7' },
  teal:   { bg: '#E1F5EE', color: '#0F6E56' },
  coral:  { bg: '#FAECE7', color: '#993C1D' },
}
const pill = (v, sz = 11) => ({
  display: 'inline-flex', alignItems: 'center', gap: 3,
  fontSize: sz, fontWeight: 500, padding: '3px 9px',
  borderRadius: 20, background: T[v].bg, color: T[v].color,
  whiteSpace: 'nowrap',
})
const fmt  = (n) => (n === null || n === undefined) ? '—' : Number(n).toLocaleString('en-NG', { maximumFractionDigits: 0 })
const fmtN = (n) => `₦${fmt(n)}`

function Section({ title, icon, badge, badgeV, children, accent = '#01919E' }) {
  return (
    <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '12px 16px', borderBottom: '1px solid #f3f4f6', borderLeft: `3px solid ${accent}` }}>
        <i className={`ti ti-${icon}`} style={{ fontSize: 15, color: accent }} aria-hidden="true" />
        <span style={{ fontWeight: 500, fontSize: 13, color: '#0f2535', flex: 1 }}>{title}</span>
        {badge && <span style={pill(badgeV || 'green', 11)}>{badge}</span>}
      </div>
      <div style={{ padding: '14px 16px' }}>{children}</div>
    </div>
  )
}

function DataRow({ label, value, valueStyle, icon }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #f9fafb', fontSize: 13 }}>
      <span style={{ color: '#6b7280', display: 'flex', alignItems: 'center', gap: 6 }}>
        {icon && <i className={`ti ti-${icon}`} style={{ fontSize: 13 }} aria-hidden="true" />}{label}
      </span>
      <span style={{ fontWeight: 500, color: '#0f2535', ...valueStyle }}>{value}</span>
    </div>
  )
}

function ProgressBar({ current, target, colour, label, unit, pct, pace, daysLeft }) {
  const v    = colour === 'green' ? 'green' : colour === 'amber' ? 'amber' : 'red'
  const paceV = pace === 'Ahead' ? 'green' : pace === 'Behind' ? 'red' : 'amber'
  const w    = Math.min(100, Math.round(pct || 0))
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 5 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: '#0f2535' }}>{label}</div>
          <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 1 }}>
            {fmtN(current)} of {fmtN(target)}{unit !== 'currency' ? ` ${unit}` : ''}
            {daysLeft !== undefined && <span style={{ marginLeft: 6 }}>· {daysLeft} days left</span>}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 10, flexShrink: 0 }}>
          <span style={pill(v)}>{w}%</span>
          {pace && <span style={{ fontSize: 10, fontWeight: 500, color: T[paceV].color }}>{pace}</span>}
        </div>
      </div>
      <div style={{ background: '#f3f4f6', borderRadius: 4, height: 7 }}>
        <div style={{ background: T[v].bar, borderRadius: 4, height: 7, width: `${w}%`, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

function Avatar({ name, size = 28 }) {
  const i = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div style={{ width: size, height: size, borderRadius: '50%', flexShrink: 0, background: T.teal.bg, color: T.teal.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: Math.round(size * 0.38), fontWeight: 500 }}>{i}</div>
  )
}

function KpiTrackerRow({ row, expanded, onToggle }) {
  const statusV = row.status === 'on_track' ? 'green' : row.status === 'at_risk' ? 'amber' : row.status === 'off_track' ? 'red' : 'blue'
  const statusLabel = { on_track: 'On track', at_risk: 'At risk', off_track: 'Off track', pending: 'Pending' }[row.status] || 'Pending'
  const flagV = row.flag?.severity === 'danger' ? 'red' : 'amber'
  const isContractor = row.type === 'contractor'
  const pct = row.key_kpi?.pct != null ? Math.min(100, Math.round(row.key_kpi.pct)) : 0

  return (
    <div style={{ borderBottom: '1px solid #f3f4f6' }}>
      <div
        onClick={isContractor ? onToggle : undefined}
        style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 4px', cursor: isContractor ? 'pointer' : 'default' }}
      >
        <Avatar name={row.name} size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: '#0f2535', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</div>
          <div style={{ fontSize: 10, color: '#9ca3af' }}>{isContractor ? 'Contractor' : 'Sales agent'}{row.key_kpi ? ` · ${row.key_kpi.label}` : ''}</div>
        </div>
        {row.key_kpi && (
          <div style={{ width: 90, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: '#9ca3af', textAlign: 'right', marginBottom: 2 }}>
              {fmt(row.key_kpi.actual)}{row.key_kpi.target ? ` / ${fmt(row.key_kpi.target)}` : ''}
            </div>
            <div style={{ background: '#f3f4f6', borderRadius: 4, height: 5 }}>
              <div style={{ background: T[statusV].bar || T[statusV].color, borderRadius: 4, height: 5, width: `${pct}%` }} />
            </div>
          </div>
        )}
        <span style={{ ...pill(statusV, 10), flexShrink: 0 }}>{statusLabel}</span>
        <span style={{ fontSize: 10, color: '#9ca3af', width: 56, textAlign: 'right', flexShrink: 0 }}>
          {row.last_log_date ? fmtDateLabel(new Date(row.last_log_date + 'T00:00:00')) : '—'}
        </span>
        <div style={{ width: 120, flexShrink: 0, textAlign: 'right' }}>
          {row.flag ? <span style={pill(flagV, 10)}>{row.flag.label}</span> : <span style={{ fontSize: 10, color: '#d1d5db' }}>—</span>}
        </div>
        {isContractor && (
          <i className={`ti ti-chevron-${expanded ? 'up' : 'down'}`} style={{ fontSize: 13, color: '#9ca3af', flexShrink: 0 }} aria-hidden="true" />
        )}
      </div>
      {isContractor && expanded && row.profile && (
        <div style={{ background: '#f9fafb', borderRadius: 8, padding: '10px 12px', margin: '0 4px 10px', fontSize: 11 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
            <div>
              <div style={{ color: '#9ca3af', marginBottom: 2 }}>Contract</div>
              <div style={{ color: '#374151' }}>
                {row.profile.fee_structure?.replace(/_/g, ' ') || '—'}
                {row.profile.fee_amount ? ` · ${row.profile.fee_currency === 'NGN' ? '₦' : row.profile.fee_currency + ' '}${fmt(row.profile.fee_amount)}` : ''}
              </div>
            </div>
            <div>
              <div style={{ color: '#9ca3af', marginBottom: 2 }}>3-month trend</div>
              <div style={{ display: 'flex', gap: 8 }}>
                {row.profile.kpi_trend?.length
                  ? row.profile.kpi_trend.map((t, i) => (
                      <span key={i} style={{ color: i === row.profile.kpi_trend.length - 1 ? T.red.color : '#6b7280' }}>
                        {t.month}: {t.score_pct !== null ? `${t.score_pct}%` : '—'}
                      </span>
                    ))
                  : <span style={{ color: '#9ca3af' }}>No history yet</span>}
              </div>
            </div>
          </div>
          {row.profile.risk_summary?.at_termination_risk && (
            <div style={{ color: '#A32D2D', marginBottom: 6 }}>
              {row.profile.risk_summary.consecutive_months_off_track} consecutive months off-track — flagged for termination review.
            </div>
          )}
          {row.profile.pending_tasks?.length > 0 && (
            <div style={{ color: '#6b7280' }}>
              Pending: {row.profile.pending_tasks.map(t => t.task).join(' · ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AttentionIssueCard({ iss, onResolved, sessionToken }) {
  const [resolving, setResolving] = useState(false)
  const [showResolve, setShowResolve] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const isActivityLog = iss.source === 'activity_log'

  const handleResolve = async () => {
    if (!note.trim()) { setErr('Resolution note is required'); return }
    setSaving(true); setErr(null)
    try {
      await resolveActivityLog(iss.contractor_id, iss.id, note.trim(), sessionToken)
      setShowResolve(false)
      onResolved()
    } catch (e) {
      const detail = e?.response?.data?.detail
      setErr(typeof detail === 'string' ? detail : 'Failed to resolve')
    } finally { setSaving(false) }
  }

  return (
    <div style={{ background: 'rgba(255,255,255,0.6)', borderRadius: 8, marginBottom: 6, border: '1px solid #fca5a5', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 9, padding: '8px 10px' }}>
        <i className={`ti ti-${isActivityLog ? 'flag-2' : 'flag'}`} style={{ fontSize: 14, color: '#A32D2D', flexShrink: 0, marginTop: 1 }} aria-hidden="true" />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: '#A32D2D' }}>{iss.reference} — {iss.title}</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 1 }}>
            {iss.priority} priority · {iss.status?.replace(/_/g, ' ')}
            {isActivityLog && iss.blocker_note && (
              <span style={{ marginLeft: 6, color: '#A32D2D' }}>· Blocker: {iss.blocker_note}</span>
            )}
          </div>
        </div>
        {isActivityLog && !showResolve && (
          <button
            onClick={() => setShowResolve(true)}
            style={{ flexShrink: 0, fontSize: 11, fontWeight: 600, padding: '3px 8px', background: '#fff', border: '1px solid #fca5a5', borderRadius: 5, cursor: 'pointer', color: '#A32D2D' }}
          >
            Resolve
          </button>
        )}
      </div>
      {showResolve && (
        <div style={{ borderTop: '1px solid #fca5a5', padding: '10px 10px 10px 33px', background: '#fff8f8' }}>
          {err && <div style={{ fontSize: 11, color: '#A32D2D', marginBottom: 6 }}>{err}</div>}
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="Describe how this was resolved…"
            rows={2}
            autoFocus
            style={{ width: '100%', border: '1px solid #fca5a5', borderRadius: 6, padding: '6px 8px', fontSize: 12, fontFamily: 'inherit', resize: 'vertical', outline: 'none', boxSizing: 'border-box' }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 6, justifyContent: 'flex-end' }}>
            <button onClick={() => { setShowResolve(false); setNote(''); setErr(null) }} style={{ padding: '4px 10px', fontSize: 11, background: '#f3f4f6', border: 'none', borderRadius: 5, cursor: 'pointer' }}>Cancel</button>
            <button onClick={handleResolve} disabled={saving} style={{ padding: '4px 10px', fontSize: 11, fontWeight: 600, background: '#01919E', color: 'white', border: 'none', borderRadius: 5, cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Saving…' : '✓ Mark Resolved'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function OwnerDashboardContent({ token, sessionToken, orgName, onSessionExpired }) {
  const [data,         setData]         = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)
  const [refresh,      setRefresh]      = useState(null)
  // Default to yesterday so the morning view is always populated
  const [selectedDate, setSelectedDate] = useState(yesterday)
  const [kpiFilter,    setKpiFilter]    = useState('all')
  const [expandedContractor, setExpandedContractor] = useState(null)
  const timerRef = useRef(null)

  const fetchBrief = useCallback(async (dateOverride) => {
    const d = dateOverride !== undefined ? dateOverride : selectedDate
    try {
      const res = await getOwnerBrief(token, sessionToken, toISODate(d))
      setData(res)
      setRefresh(new Date())
      setError(null)
    } catch (e) {
      if (e?.response?.status === 401) onSessionExpired()
      else setError('Failed to load. Retrying in 2 minutes.')
    } finally { setLoading(false) }
  }, [token, sessionToken, onSessionExpired, selectedDate])

  // On date change: refetch immediately and restart the auto-refresh timer
  const changeDate = useCallback((newDate) => {
    setSelectedDate(newDate)
    setLoading(true)
    clearInterval(timerRef.current)
    fetchBrief(newDate)
    // Only auto-refresh when viewing today (past dates won't change)
    if (isToday(newDate)) {
      timerRef.current = setInterval(() => fetchBrief(newDate), REFRESH_MS)
    }
  }, [fetchBrief])

  const goBack = () => {
    const d = new Date(selectedDate)
    d.setDate(d.getDate() - 1)
    changeDate(d)
  }
  const goForward = () => {
    if (isToday(selectedDate)) return
    const d = new Date(selectedDate)
    d.setDate(d.getDate() + 1)
    changeDate(d)
  }

  useEffect(() => {
    fetchBrief(selectedDate)
    // Only auto-refresh today; past dates are static
    if (isToday(selectedDate)) {
      timerRef.current = setInterval(() => fetchBrief(selectedDate), REFRESH_MS)
    }
    return () => clearInterval(timerRef.current)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ textAlign: 'center' }}>
        <i className="ti ti-loader-2" style={{ fontSize: 32, color: '#01919E' }} aria-hidden="true" />
        <div style={{ fontSize: 13, color: '#6b7280', marginTop: 10 }}>Preparing your brief…</div>
      </div>
    </div>
  )

  const brief  = data?.brief
  const health = data?.health
  const hv     = health?.colour === 'green' ? 'green' : health?.colour === 'amber' ? 'amber' : 'red'
  const hColor = T[hv].bar

  const contractorActions = (brief?.contractors || []).reduce((a, c) => a + (c.needs_company_action?.length || 0), 0)
  const totalActions = (brief?.attention_issues?.length || 0) + contractorActions
  // attention_issues now includes both internal_issues (source:'issue') and
  // flagged activity logs (source:'activity_log') — totalActions is already correct

  return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9', fontFamily: 'system-ui, -apple-system, sans-serif' }}>

      {/* Top bar */}
      <div style={{ background: 'white', borderBottom: '1px solid #e5e7eb', padding: '11px 16px', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ maxWidth: 1000, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 34, height: 34, borderRadius: 9, background: '#01919E', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 500, fontSize: 14, flexShrink: 0 }}>
              {(orgName || 'O')[0].toUpperCase()}
            </div>
            <div>
              <div style={{ fontWeight: 500, fontSize: 14, color: '#0f2535' }}>{orgName || 'Daily Brief'}</div>
              {/* Date navigation */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                <button
                  onClick={goBack}
                  aria-label="Previous day"
                  style={{ width: 20, height: 20, borderRadius: 4, border: '1px solid #e5e7eb', background: '#f9fafb', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: '#6b7280', fontSize: 11, padding: 0 }}
                >
                  <i className="ti ti-chevron-left" aria-hidden="true" />
                </button>
                <span style={{ fontSize: 11, color: isToday(selectedDate) ? '#01919E' : '#6b7280', fontWeight: isToday(selectedDate) ? 600 : 400, minWidth: 100, textAlign: 'center' }}>
                  {fmtDateLabel(selectedDate)}
                </span>
                <button
                  onClick={goForward}
                  disabled={isToday(selectedDate)}
                  aria-label="Next day"
                  style={{ width: 20, height: 20, borderRadius: 4, border: '1px solid #e5e7eb', background: isToday(selectedDate) ? '#f3f4f6' : '#f9fafb', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: isToday(selectedDate) ? 'not-allowed' : 'pointer', color: isToday(selectedDate) ? '#d1d5db' : '#6b7280', fontSize: 11, padding: 0 }}
                >
                  <i className="ti ti-chevron-right" aria-hidden="true" />
                </button>
              </div>
              <div style={{ fontSize: 10, color: '#9ca3af' }}>
                {refresh ? `Updated ${refresh.toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit' })}` : '…'}
                {brief?.days_remaining !== undefined && ` · ${brief.days_remaining} days left this month`}
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {totalActions > 0 && (
              <span style={{ ...pill('red', 11) }}>
                <i className="ti ti-alert-circle" style={{ fontSize: 12 }} aria-hidden="true" />
                {totalActions} action{totalActions > 1 ? 's' : ''}
              </span>
            )}
            <button onClick={() => fetchBrief(selectedDate)} aria-label="Refresh" style={{ width: 32, height: 32, borderRadius: 8, background: '#f9fafb', border: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, cursor: 'pointer', color: '#6b7280' }}>
              <i className="ti ti-refresh" aria-hidden="true" />
            </button>
            <button onClick={() => window.print()} aria-label="Print" style={{ width: 32, height: 32, borderRadius: 8, background: '#f9fafb', border: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, cursor: 'pointer', color: '#6b7280' }}>
              <i className="ti ti-printer" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 1000, margin: '0 auto', padding: '16px 14px 40px' }}>
        {error && (
          <div style={{ background: '#FCEBEB', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', marginBottom: 12, fontSize: 13, color: '#A32D2D', display: 'flex', alignItems: 'center', gap: 8 }}>
            <i className="ti ti-alert-circle" style={{ fontSize: 15 }} aria-hidden="true" />{error}
          </div>
        )}

        {/* Actions needed — full width, only if present */}
        {totalActions > 0 && (
          <div style={{ background: '#FCEBEB', border: '1px solid #fca5a5', borderRadius: 12, padding: '12px 16px', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 500, fontSize: 13, color: '#A32D2D', marginBottom: 10 }}>
              <i className="ti ti-alert-circle" style={{ fontSize: 16 }} aria-hidden="true" />
              {totalActions} item{totalActions > 1 ? 's' : ''} need your attention
            </div>
            {brief?.attention_issues?.map(iss => (
              <AttentionIssueCard
                key={iss.id}
                iss={iss}
                sessionToken={sessionToken}
                onResolved={() => fetchBrief(selectedDate)}
              />
            ))}
            {brief?.contractors?.flatMap(c =>
              (c.needs_company_action || []).map((t, i) => (
                <div key={`${c.contractor_id}-${i}`} style={{ display: 'flex', alignItems: 'flex-start', gap: 9, padding: '8px 10px', background: 'rgba(255,255,255,0.6)', borderRadius: 8, marginBottom: 6, border: '1px solid #fca5a5' }}>
                  <i className="ti ti-lock" style={{ fontSize: 14, color: '#A32D2D', flexShrink: 0, marginTop: 1 }} aria-hidden="true" />
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 500, color: '#A32D2D' }}>Blocked: {t.task}</div>
                    <div style={{ fontSize: 11, color: '#6b7280', marginTop: 1 }}>{c.name} · Due {t.due || 'TBD'} · Owner: {t.owner}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* Health score — full width */}
        {health && (
          <div style={{ background: 'white', border: `2px solid ${hColor}`, borderRadius: 12, padding: '14px 16px', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 56, height: 56, borderRadius: '50%', border: `3px solid ${hColor}`, background: T[hv].bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <span style={{ fontSize: 20, fontWeight: 500, color: T[hv].color }}>{Math.round(health.health_score || 0)}</span>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 5 }}>Organisation health</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '5px 16px' }}>
                {health.components && Object.entries(health.components).map(([k, v]) => {
                  const iconMap = { revenue: 'currency-naira', staff: 'users', leads: 'git-merge', support: 'ticket' }
                  const cv = health.colour === 'green' ? 'green' : health.colour === 'amber' ? 'amber' : 'red'
                  const compV = v.score >= 75 ? 'green' : v.score >= 50 ? 'amber' : 'red'
                  return (
                    <div key={k} style={{ fontSize: 11 }}>
                      <div style={{ color: '#6b7280', display: 'flex', alignItems: 'center', gap: 4, marginBottom: 1 }}>
                        <i className={`ti ti-${iconMap[k] || 'chart-bar'}`} style={{ fontSize: 11 }} aria-hidden="true" />
                        <span style={{ textTransform: 'capitalize' }}>{k}</span>
                        <strong style={{ color: T[compV].color, fontWeight: 600, marginLeft: 2 }}>{Math.round(v.score)}%</strong>
                      </div>
                      {v.label && <div style={{ fontSize: 10, color: '#9ca3af', paddingLeft: 15 }}>{v.label}</div>}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {/* Team & contractor KPI tracker */}
        {brief?.kpi_tracker?.length > 0 && (
          <Section title="Team & contractor KPI tracker" icon="chart-bar" accent="#534AB7">
            <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
              {['all', 'staff', 'contractor'].map(f => (
                <button
                  key={f}
                  onClick={() => setKpiFilter(f)}
                  style={{
                    fontSize: 11, padding: '4px 10px', borderRadius: 14, cursor: 'pointer',
                    border: kpiFilter === f ? 'none' : '1px solid #e5e7eb',
                    background: kpiFilter === f ? '#0f2535' : 'white',
                    color: kpiFilter === f ? 'white' : '#6b7280',
                  }}
                >
                  {f === 'all' ? `All (${brief.kpi_tracker.length})`
                    : f === 'staff' ? `Staff (${brief.kpi_tracker.filter(r => r.type === 'staff').length})`
                    : `Contractors (${brief.kpi_tracker.filter(r => r.type === 'contractor').length})`}
                </button>
              ))}
            </div>
            {brief.kpi_tracker
              .filter(r => kpiFilter === 'all' || r.type === kpiFilter)
              .map(row => (
                <KpiTrackerRow
                  key={row.entity_id}
                  row={row}
                  expanded={expandedContractor === row.entity_id}
                  onToggle={() => setExpandedContractor(p => p === row.entity_id ? null : row.entity_id)}
                />
              ))}
          </Section>
        )}

        {/* 2-column grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 0 }}>
          <div style={{ paddingRight: 6 }}>

            {/* Goals — above Revenue */}
            {brief?.goals?.length > 0 && (
              <Section title="Business goals" icon="target" accent="#993C1D">
                {brief.goals.map(g => (
                  <ProgressBar key={g.id}
                    current={g.current_value} target={g.target_value}
                    colour={g.colour} label={g.goal_name} unit={g.unit}
                    pct={g.achievement_pct} pace={g.pace} daysLeft={g.days_remaining}
                  />
                ))}
              </Section>
            )}

            {/* Revenue */}
            {brief?.revenue_snapshot && (
              <Section title="Revenue this month" icon="currency-naira" accent="#0F6E56"
                badge={brief.revenue_snapshot.revenue_pace || undefined}
                badgeV={brief.revenue_snapshot.revenue_pace === 'Ahead' ? 'green' : brief.revenue_snapshot.revenue_pace === 'Behind' ? 'red' : 'amber'}
              >
                {brief.revenue_snapshot.revenue_target > 0 && (
                  <ProgressBar
                    current={brief.revenue_snapshot.revenue_mtd}
                    target={brief.revenue_snapshot.revenue_target}
                    colour={brief.revenue_snapshot.revenue_pace === 'Ahead' ? 'green' : brief.revenue_snapshot.revenue_pace === 'Behind' ? 'red' : 'amber'}
                    label="Revenue vs target" unit="currency"
                    pct={brief.revenue_snapshot.revenue_pct}
                    pace={brief.revenue_snapshot.revenue_pace}
                    daysLeft={brief.revenue_snapshot.days_remaining}
                  />
                )}
                <DataRow label="Revenue MTD"     value={fmtN(brief.revenue_snapshot.revenue_mtd)}     icon="coin" />
                <DataRow label="Total leads"      value={fmt(brief.revenue_snapshot.total_leads)}       icon="users" />
                <DataRow label="Conversions"      value={fmt(brief.revenue_snapshot.total_converted)}   icon="check" />
                <DataRow label="Conversion rate"  value={`${brief.revenue_snapshot.conversion_rate}%`}  icon="percentage"
                  valueStyle={{ color: brief.revenue_snapshot.conversion_rate >= 20 ? '#0F6E56' : '#854F0B' }} />
              </Section>
            )}

            {/* Pipeline */}
            {brief?.pipeline?.length > 0 && (
              <Section title="Pipeline" icon="git-branch" accent="#185FA5">
                <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 10 }}>
                  Total: <strong style={{ color: '#0f2535' }}>{fmtN(brief.total_pipeline_value)}</strong>
                </div>
                {brief.pipeline.map(p => (
                  <div key={p.stage} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid #f9fafb', fontSize: 12 }}>
                    <span style={{ color: '#6b7280', textTransform: 'capitalize' }}>{p.stage?.replace(/_/g, ' ')}</span>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                      <span style={{ color: '#9ca3af' }}>{p.count} leads</span>
                      <span style={{ fontWeight: 500, color: '#0f2535' }}>{fmtN(p.value)}</span>
                    </div>
                  </div>
                ))}
              </Section>
            )}

          </div>
          <div style={{ paddingLeft: 6 }}>

            {/* Sales team */}
            {brief?.sales_team?.length > 0 && (
              <Section title="Sales team" icon="trophy" accent="#854F0B"
                badge={brief.top_performer ? `${brief.top_performer.name.split(' ')[0]} leading` : undefined}
                badgeV="amber"
              >
                {brief.sales_team.map((rep, i) => (
                  <div key={rep.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f9fafb' }}>
                    <div style={{ fontSize: 11, color: '#9ca3af', width: 16, textAlign: 'center', flexShrink: 0 }}>#{i + 1}</div>
                    <Avatar name={rep.name} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 500, color: '#0f2535', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rep.name}</div>
                      <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 1 }}>{rep.leads} leads · {rep.converted} closed · {rep.conversion_rate}% CR</div>
                    </div>
                    <div style={{ fontWeight: 500, fontSize: 13, color: rep.revenue > 0 ? '#0F6E56' : '#9ca3af', flexShrink: 0 }}>{fmtN(rep.revenue)}</div>
                  </div>
                ))}
              </Section>
            )}

            {/* Contractors */}
            {brief?.contractors?.filter(c => c.tasks_total > 0 || c.kpi_actuals?.length > 0).length > 0 && (
              <Section title="Contractors" icon="users-group" accent="#534AB7">
                {brief.contractors
                  .filter(c => c.tasks_total > 0 || c.kpi_actuals?.length > 0)
                  .map(c => (
                    <div key={c.contractor_id} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid #f3f4f6' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 8 }}>
                        <Avatar name={c.name} size={30} />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 12, fontWeight: 500, color: '#0f2535' }}>{c.name}</div>
                          <div style={{ fontSize: 11, color: '#9ca3af' }}>{c.role}</div>
                        </div>
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                          {c.tasks_blocked > 0 && <span style={pill('red', 10)}><i className="ti ti-lock" style={{ fontSize: 10 }} aria-hidden="true" />{c.tasks_blocked} blocked</span>}
                          <span style={pill('teal', 10)}>{c.tasks_done}/{c.tasks_total} done</span>
                        </div>
                      </div>
                      {c.kpi_actuals?.length > 0 && (
                        <div style={{ background: '#f9fafb', borderRadius: 7, padding: '7px 10px', marginBottom: 7 }}>
                          <div style={{ fontSize: 10, color: '#9ca3af', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.4px' }}>KPI actuals</div>
                          {c.kpi_actuals.map((k, i) => (
                            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0' }}>
                              <span style={{ color: '#6b7280' }}>{k.kpi_key}</span>
                              <span style={{ fontWeight: 500, color: '#0f2535' }}>{k.actual_label || fmt(k.actual_value)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {c.todays_activity_summary?.length > 0 && (
                        <div style={{ marginBottom: 8 }}>
                          <div style={{ fontSize: 10, color: '#9ca3af', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.4px', display: 'flex', alignItems: 'center', gap: 5 }}>
                            <i className="ti ti-pencil" style={{ fontSize: 10 }} aria-hidden="true" />
                            {isToday(selectedDate) ? "Today's activities" : `${fmtDateLabel(selectedDate)} activities`}
                          </div>
                          {c.todays_activity_summary.map((a, i) => (
                            <div key={i} style={{ fontSize: 11, color: '#374151', marginBottom: 3, display: 'flex', alignItems: 'flex-start', gap: 5 }}>
                              <i className={`ti ti-${a.blocker ? 'lock' : 'circle-check'}`} style={{ fontSize: 11, color: a.blocker ? '#E24B4A' : '#F59E0B', flexShrink: 0, marginTop: 1 }} aria-hidden="true" />
                              <span style={{ lineHeight: 1.4 }}>{a.type && <strong>{a.type}: </strong>}{a.notes}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {!c.todays_activity_summary?.length && c.activities_today === 0 && (
                        <div style={{ fontSize: 11, color: '#9ca3af', fontStyle: 'italic', marginBottom: 6 }}>No activity logged {isToday(selectedDate) ? 'today' : fmtDateLabel(selectedDate).toLowerCase()}</div>
                      )}
                      {c.in_progress_tasks?.length > 0 && (
                        <div>
                          <div style={{ fontSize: 10, color: '#9ca3af', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.4px' }}>In progress</div>
                          {c.in_progress_tasks.map((t, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 11, color: '#374151', marginBottom: 3 }}>
                              <i className="ti ti-clock" style={{ fontSize: 11, color: '#F59E0B', flexShrink: 0, marginTop: 1 }} aria-hidden="true" />
                              <span style={{ lineHeight: 1.4 }}>{t.task}{t.due && <span style={{ color: '#9ca3af' }}> · due {t.due}</span>}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
              </Section>
            )}

          </div>
        </div>
      </div>
    </div>
  )
}
