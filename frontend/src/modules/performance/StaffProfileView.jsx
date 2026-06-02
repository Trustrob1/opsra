/**
 * frontend/src/modules/performance/StaffProfileView.jsx
 *
 * Individual staff profile.
 * Used by manager (any userId) and self-view redirect from scorecard.
 * Shows: targets vs actuals per KPI with pace, 30-day log history,
 *        manager override drawer, set-targets drawer, acknowledge targets banner,
 *        month selector.
 *
 * Owner + ops_manager can:
 *   - Set / update monthly targets for the staff member
 *   - Override any daily log entry
 */
import { useState, useEffect, useCallback } from 'react'
import {
  getStaffProfile,
  updateStaffLog,
  setTargets,
  getKpiTemplates,
} from '../../services/performance.service'
import { ds } from '../../utils/ds'

const _BADGE = (colour) => {
  if (colour === 'green') return { background: '#d1fae5', color: '#065f46' }
  if (colour === 'amber') return { background: '#fef3c7', color: '#92400e' }
  return { background: '#fee2e2', color: '#991b1b' }
}

const _PACE_COLOUR = (pace) => {
  if (pace === 'Ahead')  return '#10b981'
  if (pace === 'Behind') return '#ef4444'
  return '#f59e0b'
}

const INPUT = {
  width: '100%', border: '1px solid #e5e7eb', borderRadius: 7,
  padding: '8px 10px', fontSize: 13, fontFamily: 'inherit', boxSizing: 'border-box',
}

// ── Log row (expandable) ────────────────────────────────────────────────────

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
          {log.activity_outcome && <div><strong>Outcome:</strong> {log.activity_outcome}</div>}
          {log.duration_minutes && <div><strong>Duration:</strong> {log.duration_minutes} min</div>}
          {log.blocker_note     && <div><strong>Blocker:</strong> {log.blocker_note}</div>}
          {log.notes            && <div><strong>Notes:</strong> {log.notes}</div>}
          {log.owner_flag_note  && <div style={{ color: '#991b1b' }}><strong>🚩 Owner flag:</strong> {log.owner_flag_note}</div>}
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

// ── Log override drawer ─────────────────────────────────────────────────────

function OverrideDrawer({ log, onClose, onSaved }) {
  const [value,   setValue]   = useState(log?.value ?? '')
  const [notes,   setNotes]   = useState(log?.notes ?? '')
  const [outcome, setOutcome] = useState(log?.activity_outcome ?? '')
  const [blocker, setBlocker] = useState(log?.blocker_note ?? '')
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

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

// ── Set targets drawer ──────────────────────────────────────────────────────

function SetTargetsDrawer({ userId, month, existingKpis, onClose, onSaved }) {
  // Pre-populate from existing targets; allow adding new rows from templates
  const [rows, setRows]       = useState(() =>
    existingKpis.length > 0
      ? existingKpis.map(k => ({
          kpi_name:     k.kpi_name,
          kpi_unit:     k.kpi_unit || 'count',
          target_value: k.target_value ?? '',
          notes:        k.notes || '',
        }))
      : [{ kpi_name: '', kpi_unit: 'count', target_value: '', notes: '' }]
  )
  const [templates, setTemplates] = useState([])
  const [loading,   setLoading]   = useState(false)
  const [saving,    setSaving]    = useState(false)
  const [error,     setError]     = useState(null)

  useEffect(() => {
    getKpiTemplates()
      .then(data => setTemplates(data || []))
      .catch(() => {})
  }, [])

  const updateRow = (i, field, val) => setRows(prev => prev.map((r, idx) => idx === i ? { ...r, [field]: val } : r))
  const addRow    = () => setRows(prev => [...prev, { kpi_name: '', kpi_unit: 'count', target_value: '', notes: '' }])
  const removeRow = (i) => setRows(prev => prev.filter((_, idx) => idx !== i))

  // Quick-add from template dropdown
  const addFromTemplate = (templateKpiName, templateUnit) => {
    if (rows.some(r => r.kpi_name === templateKpiName)) return
    setRows(prev => [...prev, { kpi_name: templateKpiName, kpi_unit: templateUnit || 'count', target_value: '', notes: '' }])
  }

  const handleSave = async () => {
    const valid = rows.filter(r => r.kpi_name.trim() && r.target_value !== '')
    if (valid.length === 0) { setError('Add at least one KPI with a target value.'); return }
    setSaving(true)
    setError(null)
    try {
      await setTargets(userId, month, valid.map(r => ({
        kpi_name:     r.kpi_name.trim(),
        kpi_unit:     r.kpi_unit,
        target_value: Number(r.target_value),
        notes:        r.notes || null,
      })))
      onSaved()
      onClose()
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to save targets')
    } finally {
      setSaving(false)
    }
  }

  const uniqueTemplateKpis = templates.filter(
    t => !rows.some(r => r.kpi_name === t.kpi_name)
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
      <div style={{ background: 'white', borderRadius: '16px 16px 0 0', padding: 24, width: '100%', maxWidth: 600, maxHeight: '85vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <h3 style={{ margin: 0, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16 }}>Set Targets — {month}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#6b7280' }}>✕</button>
        </div>
        <p style={{ fontSize: 12, color: '#9ca3af', marginBottom: 16, marginTop: 4 }}>
          Set monthly KPI targets for this staff member. Existing logs are not affected.
        </p>

        {error && <p style={{ color: '#991b1b', fontSize: 13, marginBottom: 12 }}>⚠ {error}</p>}

        {/* Quick-add from templates */}
        {uniqueTemplateKpis.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6 }}>Quick-add from KPI templates:</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {uniqueTemplateKpis.map(t => (
                <button
                  key={t.id}
                  onClick={() => addFromTemplate(t.kpi_name, t.kpi_unit)}
                  style={{ background: '#f3f4f6', border: '1px solid #e5e7eb', borderRadius: 20, padding: '3px 10px', fontSize: 11, cursor: 'pointer', color: '#374151' }}
                >
                  + {t.kpi_name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Target rows */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 14 }}>
          {rows.map((row, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: 8, alignItems: 'end' }}>
              <div>
                {i === 0 && <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 3 }}>KPI name *</div>}
                <input
                  value={row.kpi_name}
                  onChange={e => updateRow(i, 'kpi_name', e.target.value)}
                  placeholder="e.g. Leads Contacted"
                  maxLength={100}
                  style={INPUT}
                />
              </div>
              <div>
                {i === 0 && <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 3 }}>Unit</div>}
                <select value={row.kpi_unit} onChange={e => updateRow(i, 'kpi_unit', e.target.value)} style={INPUT}>
                  <option value="count">count</option>
                  <option value="currency">currency</option>
                  <option value="percentage">percentage</option>
                  <option value="minutes">minutes</option>
                </select>
              </div>
              <div>
                {i === 0 && <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 3 }}>Target *</div>}
                <input
                  type="number" min="0"
                  value={row.target_value}
                  onChange={e => updateRow(i, 'target_value', e.target.value)}
                  placeholder="0"
                  style={INPUT}
                />
              </div>
              <button
                onClick={() => removeRow(i)}
                disabled={rows.length === 1}
                style={{ background: 'none', border: '1px solid #fca5a5', borderRadius: 6, padding: '7px 10px', fontSize: 13, cursor: 'pointer', color: '#dc2626', opacity: rows.length === 1 ? 0.3 : 1, marginTop: i === 0 ? 18 : 0 }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        <button
          onClick={addRow}
          style={{ background: 'none', border: '1px dashed #d1d5db', borderRadius: 7, padding: '7px 14px', fontSize: 12, cursor: 'pointer', color: '#6b7280', width: '100%', marginBottom: 16 }}
        >
          + Add another KPI
        </button>

        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onClose} style={{ flex: 1, padding: '10px', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer', background: 'white', fontSize: 13 }}>Cancel</button>
          <button onClick={handleSave} disabled={saving} style={{ flex: 2, padding: '10px', border: 'none', borderRadius: 8, cursor: 'pointer', background: ds.teal, color: 'white', fontSize: 13, fontWeight: 600 }}>
            {saving ? 'Saving…' : 'Save Targets'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────

export default function StaffProfileView({ userId, month: initialMonth, onBack, isManager }) {
  const [month, setMonth] = useState(initialMonth || (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  }))
  const [profile,     setProfile]     = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [overrideLog, setOverrideLog] = useState(null)
  const [setTargetsOpen, setSetTargetsOpen] = useState(false)

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
      {/* Back + month selector + Set Targets button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
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
        {isManager && (
          <button
            onClick={() => setSetTargetsOpen(true)}
            style={{ marginLeft: 'auto', background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '7px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            🎯 Set Targets
          </button>
        )}
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
              ⚠ Targets for {profile.month} have not been acknowledged by this staff member yet.
            </div>
          )}

          {/* No targets set yet — prompt manager */}
          {isManager && profile.kpis?.length === 0 && (
            <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: '12px 16px', marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#1e40af' }}>No targets set for {profile.month} yet.</span>
              <button
                onClick={() => setSetTargetsOpen(true)}
                style={{ background: '#2563eb', color: 'white', border: 'none', borderRadius: 7, padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
              >
                Set Targets Now
              </button>
            </div>
          )}

          {/* KPI targets */}
          {profile.kpis?.length > 0 && (
            <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', marginBottom: 16, overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', fontWeight: 600, fontSize: 13, color: ds.dark, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>KPI Targets — {profile.month}</span>
                {isManager && (
                  <button
                    onClick={() => setSetTargetsOpen(true)}
                    style={{ background: 'none', border: '1px solid #e5e7eb', borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer', color: '#374151' }}
                  >
                    ✏ Edit Targets
                  </button>
                )}
              </div>
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
                <LogRow key={log.id} log={log} isManager={isManager} onOverride={setOverrideLog} />
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

      {/* Drawers */}
      {overrideLog && (
        <OverrideDrawer log={overrideLog} onClose={() => setOverrideLog(null)} onSaved={fetchProfile} />
      )}

      {setTargetsOpen && profile && (
        <SetTargetsDrawer
          userId={userId}
          month={month}
          existingKpis={profile.kpis || []}
          onClose={() => setSetTargetsOpen(false)}
          onSaved={fetchProfile}
        />
      )}
    </div>
  )
}
