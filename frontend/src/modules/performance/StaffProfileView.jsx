/**
 * frontend/src/modules/performance/StaffProfileView.jsx
 *
 * Individual staff profile.
 * Used by manager (any userId) and self-view redirect from scorecard.
 * Shows: targets vs actuals per KPI with pace, 30-day log history,
 *        manager override drawer, acknowledge targets banner, month selector.
 */
import { useState, useEffect, useCallback } from 'react'
import { getStaffProfile, updateStaffLog } from '../../services/performance.service'
import { ds } from '../../utils/ds'

const _BADGE = (colour) => {
  if (colour === 'green') return { background: '#d1fae5', color: '#065f46' }
  if (colour === 'amber') return { background: '#fef3c7', color: '#92400e' }
  return { background: '#fee2e2', color: '#991b1b' }
}

const _PACE_COLOUR = (pace) => {
  if (pace === 'Ahead')    return '#10b981'
  if (pace === 'Behind')   return '#ef4444'
  return '#f59e0b'
}

function LogRow({ log, isManager, onOverride }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div style={{ borderBottom: '1px solid #f3f4f6' }}>
      <div
        onClick={() => setExpanded(p => !p)}
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', cursor: 'pointer', background: expanded ? '#f9fafb' : 'white' }}
      >
        <span style={{ fontSize: 12, color: '#6b7280', minWidth: 80 }}>{log.log_date}</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: ds.dark, flex: 1 }}>{log.kpi_label || log.kpi_key}</span>
        <span style={{ fontSize: 13, color: '#374151' }}>{log.value}</span>
        <span style={{ fontSize: 11, background: '#f3f4f6', borderRadius: 6, padding: '2px 8px', color: '#6b7280' }}>{log.attendance_status}</span>
        {log.approved_by_owner && <span style={{ fontSize: 10, background: '#d1fae5', color: '#065f46', borderRadius: 6, padding: '2px 6px' }}>✓ Approved</span>}
        {log.owner_flag_note   && <span style={{ fontSize: 10, background: '#fee2e2', color: '#991b1b', borderRadius: 6, padding: '2px 6px' }}>🚩 Flagged</span>}
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{expanded ? '▲' : '▼'}</span>
      </div>
      {expanded && (
        <div style={{ padding: '8px 14px 12px 106px', fontSize: 12, color: '#6b7280', lineHeight: 1.6, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {log.activity_outcome  && <div><strong>Outcome:</strong> {log.activity_outcome}</div>}
          {log.duration_minutes  && <div><strong>Duration:</strong> {log.duration_minutes} min</div>}
          {log.blocker_note      && <div><strong>Blocker:</strong> {log.blocker_note}</div>}
          {log.notes             && <div><strong>Notes:</strong> {log.notes}</div>}
          {log.owner_flag_note   && <div style={{ color: '#991b1b' }}><strong>🚩 Owner flag:</strong> {log.owner_flag_note}</div>}
          {isManager && (
            <button
              onClick={() => onOverride(log)}
              style={{ alignSelf: 'flex-start', marginTop: 6, background: 'none', border: '1px solid #d1d5db', borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer', color: '#374151' }}
            >
              ✏ Override
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function OverrideDrawer({ log, onClose, onSaved }) {
  const [value,    setValue]    = useState(log?.value ?? '')
  const [notes,    setNotes]    = useState(log?.notes ?? '')
  const [outcome,  setOutcome]  = useState(log?.activity_outcome ?? '')
  const [blocker,  setBlocker]  = useState(log?.blocker_note ?? '')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const handleSave = async () => {
    setLoading(true)
    setError(null)
    try {
      await updateStaffLog(log.id, {
        value: Number(value),
        notes,
        activity_outcome: outcome,
        blocker_note: blocker,
      })
      onSaved()
      onClose()
    } catch (e) {
      setError(e?.response?.data?.detail || 'Save failed')
    } finally {
      setLoading(false)
    }
  }

  const INPUT = { width: '100%', border: '1px solid #e5e7eb', borderRadius: 7, padding: '8px 10px', fontSize: 13, fontFamily: ds.fontDm, boxSizing: 'border-box', marginTop: 4 }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 1000, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
      <div style={{ background: 'white', borderRadius: '16px 16px 0 0', padding: 24, width: '100%', maxWidth: 520 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16 }}>Override log — {log?.log_date}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#6b7280' }}>✕</button>
        </div>
        {error && <p style={{ color: '#991b1b', fontSize: 13, marginBottom: 12 }}>⚠ {error}</p>}
        <label style={{ fontSize: 12, color: '#6b7280' }}>Value</label>
        <input type="number" value={value} onChange={e => setValue(e.target.value)} style={INPUT} />
        <label style={{ fontSize: 12, color: '#6b7280', marginTop: 10, display: 'block' }}>Activity outcome</label>
        <input value={outcome} onChange={e => setOutcome(e.target.value)} style={INPUT} maxLength={100} />
        <label style={{ fontSize: 12, color: '#6b7280', marginTop: 10, display: 'block' }}>Blocker note</label>
        <textarea value={blocker} onChange={e => setBlocker(e.target.value)} rows={2} style={{ ...INPUT, resize: 'vertical' }} maxLength={500} />
        <label style={{ fontSize: 12, color: '#6b7280', marginTop: 10, display: 'block' }}>Notes</label>
        <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} style={{ ...INPUT, resize: 'vertical' }} maxLength={5000} />
        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          <button onClick={onClose} style={{ flex: 1, padding: '10px', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer', background: 'white', fontSize: 13 }}>Cancel</button>
          <button onClick={handleSave} disabled={loading} style={{ flex: 2, padding: '10px', border: 'none', borderRadius: 8, cursor: 'pointer', background: ds.teal, color: 'white', fontSize: 13, fontWeight: 600 }}>
            {loading ? 'Saving…' : 'Save Override'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function StaffProfileView({ userId, month: initialMonth, onBack, isManager }) {
  const [month, setMonth] = useState(initialMonth || (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  }))
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [overrideLog, setOverrideLog] = useState(null)

  const fetchProfile = useCallback(async () => {
    if (!userId) return
    setLoading(true)
    setError(null)
    try {
      const data = await getStaffProfile(userId, month)
      setProfile(data)
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load profile')
    } finally {
      setLoading(false)
    }
  }, [userId, month])

  useEffect(() => { fetchProfile() }, [fetchProfile])

  if (!userId) return null

  return (
    <div>
      {/* Back + month selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
        {onBack && (
          <button onClick={onBack} style={{ background: 'none', border: '1px solid #e5e7eb', borderRadius: 7, padding: '6px 12px', fontSize: 13, cursor: 'pointer', color: '#374151' }}>
            ← Back
          </button>
        )}
        <input
          type="month"
          value={month}
          onChange={e => setMonth(e.target.value)}
          style={{ border: '1px solid #e5e7eb', borderRadius: 7, padding: '6px 10px', fontSize: 12, fontFamily: ds.fontDm }}
        />
      </div>

      {loading && <div style={{ textAlign: 'center', padding: 40, color: '#7A9BAD', fontSize: 13 }}>Loading profile…</div>}
      {error   && <div style={{ background: '#fee2e2', borderRadius: 8, padding: '10px 14px', color: '#991b1b', fontSize: 13, marginBottom: 16 }}>⚠ {error}</div>}

      {profile && !loading && (
        <>
          {/* Profile header */}
          <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', padding: 20, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 52, height: 52, borderRadius: '50%', background: ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, fontWeight: 700, color: 'white', fontFamily: ds.fontSyne, flexShrink: 0 }}>
              {(profile.full_name || '?')[0].toUpperCase()}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark }}>{profile.full_name}</div>
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>{profile.role?.replace(/_/g, ' ')} · {profile.month}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span style={{ ..._BADGE(profile.score_colour), borderRadius: 20, padding: '5px 14px', fontSize: 14, fontWeight: 700 }}>
                {profile.score_pct}%
              </span>
              <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>overall score</div>
            </div>
          </div>

          {/* Acknowledge targets banner */}
          {!profile.acknowledged && profile.kpis?.length > 0 && (
            <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#92400e' }}>
              ⚠ Targets for {profile.month} have not been acknowledged yet.
            </div>
          )}

          {/* KPI targets */}
          {profile.kpis?.length > 0 && (
            <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', marginBottom: 16, overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', fontWeight: 600, fontSize: 13, color: ds.dark }}>KPI Targets — {profile.month}</div>
              {profile.kpis.map((kpi, i) => (
                <div key={i} style={{ padding: '12px 16px', borderBottom: i < profile.kpis.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 13, fontWeight: 500, color: ds.dark }}>{kpi.kpi_name}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 12, color: '#6b7280' }}>{kpi.actual_value ?? 0} / {kpi.target_value} {kpi.kpi_unit}</span>
                      <span style={{ ..._BADGE(kpi.colour), borderRadius: 12, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>{kpi.achievement_pct}%</span>
                      <span style={{ fontSize: 11, fontWeight: 500, color: _PACE_COLOUR(kpi.pace) }}>{kpi.pace}</span>
                    </div>
                  </div>
                  {/* Progress bar */}
                  <div style={{ background: '#f3f4f6', borderRadius: 4, height: 6 }}>
                    <div style={{
                      background: kpi.colour === 'green' ? '#10b981' : kpi.colour === 'amber' ? '#f59e0b' : '#ef4444',
                      borderRadius: 4, height: 6,
                      width: `${Math.min(100, kpi.achievement_pct)}%`,
                      transition: 'width 0.4s ease',
                    }} />
                  </div>
                  {kpi.notes && <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>{kpi.notes}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Log history */}
          {profile.logs?.length > 0 && (
            <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', fontWeight: 600, fontSize: 13, color: ds.dark }}>Daily Log History (last 30 days)</div>
              {profile.logs.map(log => (
                <LogRow
                  key={log.id}
                  log={log}
                  isManager={isManager}
                  onOverride={setOverrideLog}
                />
              ))}
            </div>
          )}

          {profile.logs?.length === 0 && !loading && (
            <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', padding: 32, textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>
              No daily logs recorded in the last 30 days.
            </div>
          )}
        </>
      )}

      {overrideLog && (
        <OverrideDrawer
          log={overrideLog}
          onClose={() => setOverrideLog(null)}
          onSaved={fetchProfile}
        />
      )}
    </div>
  )
}
