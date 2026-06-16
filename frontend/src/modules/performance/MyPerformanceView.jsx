/**
 * frontend/src/modules/performance/MyPerformanceView.jsx
 *
 * Staff self-view: own scorecard, targets, and daily log entry form.
 * Submit locks the form for the day (manager can still override).
 * Acknowledge Targets button visible at month start if not yet acknowledged.
 */
import { useState, useEffect, useCallback } from 'react'
import { AlertTriangle, ClipboardList, FileEdit, Check } from 'lucide-react'
import useAuthStore from '../../store/authStore'
import {
  getStaffProfile,
  createStaffLog,
  getKpiTemplates,
  acknowledgeTargets,
} from '../../services/performance.service'
import { ds } from '../../utils/ds'

const _BADGE = (colour) => {
  if (colour === 'green') return { background: '#d1fae5', color: '#065f46' }
  if (colour === 'amber') return { background: '#fef3c7', color: '#92400e' }
  return { background: '#fee2e2', color: '#991b1b' }
}

const INPUT = {
  width: '100%', border: '1px solid #e5e7eb', borderRadius: 7,
  padding: '8px 10px', fontSize: 13, fontFamily: 'inherit', boxSizing: 'border-box',
}

export default function MyPerformanceView({ user }) {
  const userId = useAuthStore.getState().user?.id
  const roleTemplate = useAuthStore.getState().user?.roles?.template ?? 'general_staff'

  const [month] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  const [today] = useState(() => new Date().toISOString().split('T')[0])

  const [profile,   setProfile]   = useState(null)
  const [templates, setTemplates] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)

  // Log form state
  const [logValues,      setLogValues]      = useState({})
  const [attendance,     setAttendance]     = useState('present')
  const [activityOutcome, setActivityOutcome] = useState('')
  const [durationMins,   setDurationMins]   = useState('')
  const [blockerNote,    setBlockerNote]    = useState('')
  const [loggedToday,    setLoggedToday]    = useState(false)
  const [submitting,     setSubmitting]     = useState(false)
  const [submitError,    setSubmitError]    = useState(null)
  const [submitSuccess,  setSubmitSuccess]  = useState(false)

  // Acknowledge state
  const [ackLoading, setAckLoading] = useState(false)

  const fetchData = useCallback(async () => {
    if (!userId) return
    setLoading(true)
    setError(null)
    try {
      const [profileData, tmplData] = await Promise.all([
        getStaffProfile(userId, month),
        getKpiTemplates().catch(() => []),
      ])
      setProfile(profileData)
      // Check if already logged today
      const todayLogs = (profileData.logs || []).filter(l => l.log_date === today)
      setLoggedToday(todayLogs.length > 0)
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load your performance data')
    } finally {
      setLoading(false)
    }
  }, [userId, month, today])

  useEffect(() => { fetchData() }, [fetchData])

  // Build active KPIs for log form from profile targets
  const activeKpis = profile?.kpis ?? []

  // KPIs that are now auto-computed from Opsra data — hide input fields for these
  const AUTO_COMPUTED_KPIS = new Set([
    // Sales Agent
    'Leads Contacted', 'Response Time', 'Deals Closed',
    'Conversion Rate', 'Revenue Generated', 'Attendance Days',
    // Ops Manager
    'Issues Resolved', 'Team Conversion Rate', 'Team Revenue vs Target',
    'Lead Distribution Rate', 'Rep Activity Compliance', 'Tasks Completed',
    'Time to Close', 'Win / Loss Ratio', 'Pipeline Value',
  ])

  // Only show input fields for KPIs that are still manually entered
  const manualKpis = activeKpis.filter(k => !AUTO_COMPUTED_KPIS.has(k.kpi_name))

  const handleLogSubmit = async () => {
    if (loggedToday) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      // Submit one log entry per KPI that has a value entered
      const entries = manualKpis.filter(k => logValues[k.kpi_name] !== undefined && logValues[k.kpi_name] !== '')
      // Allow submission even with no manual KPI values — attendance alone is valid
      for (const kpi of entries) {
        await createStaffLog({
          log_date: today,
          kpi_key:  kpi.kpi_name,
          kpi_label: kpi.kpi_name,
          value: Number(logValues[kpi.kpi_name] || 0),
          attendance_status: attendance,
          activity_outcome:  activityOutcome || null,
          duration_minutes:  durationMins ? parseInt(durationMins) : null,
          blocker_note:      blockerNote || null,
        })
      }
      setLoggedToday(true)
      setSubmitSuccess(true)
      fetchData()
    } catch (e) {
      setSubmitError(e?.response?.data?.detail || 'Log submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleAcknowledge = async () => {
    setAckLoading(true)
    try {
      await acknowledgeTargets(month)
      fetchData()
    } catch {}
    finally { setAckLoading(false) }
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: '#7A9BAD', fontSize: 13 }}>Loading your performance data…</div>
  if (error)   return <div style={{ background: '#fee2e2', borderRadius: 8, padding: '10px 14px', color: '#991b1b', fontSize: 13 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{error}</span></div>

  return (
    <div style={{ maxWidth: 680 }}>
      {/* Header */}
      <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', padding: 20, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 16 }}>
        <div style={{ width: 48, height: 48, borderRadius: '50%', background: ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700, color: 'white', fontFamily: ds.fontSyne, flexShrink: 0 }}>
          {(profile?.full_name || '?')[0].toUpperCase()}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark }}>{profile?.full_name}</div>
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>{roleTemplate.replace(/_/g, ' ')} · {month}</div>
        </div>
        {profile?.score_pct != null && (
          <span style={{ ..._BADGE(profile.score_colour), borderRadius: 20, padding: '5px 14px', fontSize: 14, fontWeight: 700 }}>
            {profile.score_pct}%
          </span>
        )}
      </div>

      {/* Acknowledge banner */}
      {!profile?.acknowledged && activeKpis.length > 0 && (
        <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: '12px 16px', marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: '#92400e', display:'inline-flex', alignItems:'center', gap:5 }}><ClipboardList size={13} />Please acknowledge your targets for {month} to confirm you've reviewed them.</span>
          <button
            onClick={handleAcknowledge}
            disabled={ackLoading}
            style={{ background: '#f59e0b', color: 'white', border: 'none', borderRadius: 7, padding: '7px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer', flexShrink: 0, marginLeft: 12 }}
          >
            {ackLoading ? 'Confirming…' : 'Acknowledge'}
          </button>
        </div>
      )}

      {/* Daily log form */}
      <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', padding: 20, marginBottom: 16 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{display:"inline-flex",alignItems:"center",gap:5}}><FileEdit size={13} />Log Today — {today}</span>
          {loggedToday && <span style={{ fontSize: 11, background: '#d1fae5', color: '#065f46', borderRadius: 6, padding: '3px 10px' }}>✓ Submitted for today</span>}
        </div>

        {submitSuccess && (
          <div style={{ background: '#d1fae5', border: '1px solid #6ee7b7', borderRadius: 8, padding: '10px 14px', marginBottom: 14, fontSize: 13, color: '#065f46' }}>
            <span style={{display:"inline-flex",alignItems:"center",gap:5}}><Check size={13} />Daily log submitted successfully.</span>
          </div>
        )}
        {submitError && (
          <div style={{ background: '#fee2e2', borderRadius: 8, padding: '10px 14px', marginBottom: 14, fontSize: 13, color: '#991b1b' }}>
            <span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{submitError}</span>
          </div>
        )}

        {/* KPI entries — manual only (auto-computed KPIs are hidden here, shown in progress below) */}
        {manualKpis.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>KPI values</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
              {manualKpis.map(kpi => (
                <div key={kpi.kpi_name}>
                  <label style={{ fontSize: 11, color: '#6b7280', display: 'block', marginBottom: 3 }}>
                    {kpi.kpi_name} ({kpi.kpi_unit || 'count'})
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={logValues[kpi.kpi_name] ?? ''}
                    onChange={e => setLogValues(p => ({ ...p, [kpi.kpi_name]: e.target.value }))}
                    disabled={loggedToday}
                    placeholder="0"
                    style={{ ...INPUT, opacity: loggedToday ? 0.6 : 1 }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Attendance */}
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, color: '#6b7280', display: 'block', marginBottom: 3 }}>Attendance</label>
          <select
            value={attendance}
            onChange={e => setAttendance(e.target.value)}
            disabled={loggedToday}
            style={{ ...INPUT, opacity: loggedToday ? 0.6 : 1 }}
          >
            <option value="present">Present</option>
            <option value="wfh">Working from home</option>
            <option value="absent">Absent</option>
            <option value="half_day">Half day</option>
          </select>
        </div>

        {/* Activity outcome */}
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, color: '#6b7280', display: 'block', marginBottom: 3 }}>Activity outcome <span style={{ color: '#9ca3af' }}>(optional)</span></label>
          <input
            value={activityOutcome}
            onChange={e => setActivityOutcome(e.target.value)}
            disabled={loggedToday}
            placeholder="e.g. Demo booked, No answer, Follow-up scheduled"
            maxLength={100}
            style={{ ...INPUT, opacity: loggedToday ? 0.6 : 1 }}
          />
        </div>

        {/* Duration + blocker */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 10, marginBottom: 14 }}>
          <div>
            <label style={{ fontSize: 11, color: '#6b7280', display: 'block', marginBottom: 3 }}>Duration (min) <span style={{ color: '#9ca3af' }}>(optional)</span></label>
            <input
              type="number" min="0"
              value={durationMins}
              onChange={e => setDurationMins(e.target.value)}
              disabled={loggedToday}
              style={{ ...INPUT, opacity: loggedToday ? 0.6 : 1 }}
            />
          </div>
          <div>
            <label style={{ fontSize: 11, color: '#6b7280', display: 'block', marginBottom: 3 }}>Blocker note <span style={{ color: '#9ca3af' }}>(optional)</span></label>
            <input
              value={blockerNote}
              onChange={e => setBlockerNote(e.target.value)}
              disabled={loggedToday}
              maxLength={500}
              placeholder="What prevented completion?"
              style={{ ...INPUT, opacity: loggedToday ? 0.6 : 1 }}
            />
          </div>
        </div>

        {!loggedToday && (
          <button
            onClick={handleLogSubmit}
            disabled={submitting}
            style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '10px 20px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            {submitting ? 'Submitting…' : 'Submit Daily Log'}
          </button>
        )}
      </div>

      {/* KPI progress summary */}
      {activeKpis.length > 0 && (
        <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', overflow: 'hidden', marginBottom: 16 }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', fontWeight: 600, fontSize: 13, color: ds.dark }}>
            Progress — {month}
          </div>
          {activeKpis.map((kpi, i) => (
            <div key={kpi.kpi_name} style={{ padding: '12px 16px', borderBottom: i < activeKpis.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: ds.dark }}>{kpi.kpi_name}</span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: '#6b7280' }}>{kpi.actual_value ?? 0} / {kpi.target_value}</span>
                  <span style={{ ..._BADGE(kpi.colour), borderRadius: 12, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>{kpi.achievement_pct}%</span>
                </div>
              </div>
              <div style={{ background: '#f3f4f6', borderRadius: 4, height: 5 }}>
                <div style={{
                  background: kpi.colour === 'green' ? '#10b981' : kpi.colour === 'amber' ? '#f59e0b' : '#ef4444',
                  borderRadius: 4, height: 5, width: `${Math.min(100, kpi.achievement_pct)}%`,
                  transition: 'width 0.4s ease',
                }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
