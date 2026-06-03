/**
 * frontend/src/pages/PublicLogPage.jsx
 * CPM-1B — PIN-gated public daily log form for contractors.
 *
 * Standalone page — no AppShell, no sidebar, no auth required.
 * Registered in App.jsx via URL pattern match: /log/:token
 *
 * States:
 *   loading   — fetching contractor + KPI info from public endpoint
 *   pin_entry — PIN input form (before first valid submit or after wrong PIN)
 *   form      — main log form (KPI inputs + date selector)
 *   success   — submitted successfully
 *   error     — link invalid / expired
 *   locked    — too many PIN attempts
 */

import { useState, useEffect } from 'react'
import { getPublicLogForm, submitPublicLog, submitPublicActivities } from '../services/performance_logs.service'

// ── Minimal inline styles (no Tailwind — standalone page outside AppShell) ───
const S = {
  page: {
    minHeight: '100vh',
    background: '#f0f4f7',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    fontFamily: "'DM Sans', system-ui, sans-serif",
  },
  header: {
    width: '100%',
    background: '#0a1f2e',
    padding: '16px 24px',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  logo: {
    fontFamily: "'Syne', system-ui, sans-serif",
    fontWeight: 800,
    fontSize: 18,
    color: '#1dc8a4',
    letterSpacing: '-0.5px',
  },
  logoSub: {
    fontSize: 11,
    color: '#6B8FA0',
    marginTop: 1,
  },
  card: {
    background: 'white',
    borderRadius: 12,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    padding: '28px 32px',
    width: '100%',
    maxWidth: 520,
    margin: '32px 16px',
  },
  name: {
    fontSize: 20,
    fontWeight: 700,
    color: '#0a1f2e',
    margin: '0 0 4px',
  },
  role: {
    fontSize: 13,
    color: '#6B8FA0',
    margin: '0 0 24px',
  },
  label: {
    fontSize: 12,
    fontWeight: 600,
    color: '#4a6375',
    marginBottom: 6,
    display: 'block',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  input: {
    width: '100%',
    padding: '10px 12px',
    border: '1.5px solid #dde4e8',
    borderRadius: 8,
    fontSize: 14,
    color: '#0a1f2e',
    outline: 'none',
    boxSizing: 'border-box',
    background: 'white',
  },
  pinInput: {
    width: '100%',
    padding: '12px 16px',
    border: '1.5px solid #dde4e8',
    borderRadius: 8,
    fontSize: 24,
    letterSpacing: 8,
    textAlign: 'center',
    color: '#0a1f2e',
    outline: 'none',
    boxSizing: 'border-box',
  },
  btn: {
    width: '100%',
    padding: '12px 16px',
    background: '#1dc8a4',
    color: 'white',
    border: 'none',
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 600,
    cursor: 'pointer',
    marginTop: 16,
  },
  btnDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  kpiRow: {
    marginBottom: 20,
  },
  kpiLabel: {
    fontSize: 14,
    fontWeight: 600,
    color: '#0a1f2e',
    marginBottom: 4,
  },
  kpiTarget: {
    fontSize: 12,
    color: '#6B8FA0',
    marginBottom: 8,
  },
  fieldGroup: {
    marginBottom: 20,
  },
  error: {
    background: '#fff0f0',
    border: '1px solid #ffc0c0',
    borderRadius: 8,
    padding: '10px 14px',
    fontSize: 13,
    color: '#c0392b',
    marginBottom: 16,
  },
  success: {
    textAlign: 'center',
    padding: '16px 0',
  },
  successIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  successTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#0a1f2e',
    margin: '0 0 8px',
  },
  successSub: {
    fontSize: 14,
    color: '#6B8FA0',
  },
  divider: {
    borderTop: '1px solid #edf1f4',
    margin: '20px 0',
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: 700,
    color: '#4a6375',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: 16,
  },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function todayISO() {
  return new Date().toISOString().split('T')[0]
}

// ── Sub-components ────────────────────────────────────────────────────────────

function OpsraHeader() {
  return (
    <div style={S.header}>
      <div>
        <div style={S.logo}>Opsra</div>
        <div style={S.logoSub}>Contractor Performance Log</div>
      </div>
    </div>
  )
}

function PinGate({ onVerified, contractorName, error, loading }) {
  const [pin, setPin] = useState('')

  function handleSubmit() {
    if (pin.length >= 4) onVerified(pin)
  }

  return (
    <div style={S.card}>
      <p style={S.name}>{contractorName}</p>
      <p style={S.role}>Enter your PIN to log today's performance</p>

      {error && <div style={S.error}>{error}</div>}

      <div style={S.fieldGroup}>
        <label style={S.label}>PIN</label>
        <input
          type="password"
          inputMode="numeric"
          maxLength={6}
          value={pin}
          onChange={e => setPin(e.target.value.replace(/\D/g, ''))}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          placeholder="••••"
          style={S.pinInput}
          autoFocus
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={pin.length < 4 || loading}
        style={{ ...S.btn, ...(pin.length < 4 || loading ? S.btnDisabled : {}) }}
      >
        {loading ? 'Verifying…' : 'Continue →'}
      </button>
    </div>
  )
}

function TasksSection({ tasks }) {
  const [expanded, setExpanded] = useState(false)
  if (!tasks || tasks.length === 0) return null

  const today = new Date().toISOString().split('T')[0]
  const blocked = tasks.filter(t => t.status === 'blocked').length
  const overdue  = tasks.filter(t => t.due_date && t.due_date < today).length
  const total    = tasks.length

  // Summary pill colors
  const hasAlert = blocked > 0 || overdue > 0
  const summaryBg = blocked > 0 ? '#fff0f0' : overdue > 0 ? '#fff8f0' : '#f0f9f6'
  const summaryBorder = blocked > 0 ? '#ffc0c0' : overdue > 0 ? '#fde8c8' : '#b2e8d8'
  const summaryColor = blocked > 0 ? '#c0392b' : overdue > 0 ? '#b45309' : '#1dc8a4'

  // Group by phase for expanded view
  const grouped = {}
  tasks.forEach(t => {
    const phase = t.phase || 'General'
    if (!grouped[phase]) grouped[phase] = []
    grouped[phase].push(t)
  })

  const statusIcon = { not_started: '⬜', in_progress: '🔄', blocked: '🔴', done: '✅' }
  const statusLabel = { not_started: 'Not Started', in_progress: 'In Progress', blocked: 'Blocked', done: 'Done' }

  return (
    <div style={{ marginBottom: 20 }}>
      {/* Collapsed summary pill — always visible at top */}
      <button
        onClick={() => setExpanded(p => !p)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: summaryBg,
          border: `1px solid ${summaryBorder}`,
          borderRadius: 10,
          padding: '10px 14px',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: summaryColor }}>
            ✅ Tasks this week: {total}
          </span>
          {blocked > 0 && (
            <span style={{ fontSize: 12, fontWeight: 600, color: '#c0392b', background: '#fce8e6', padding: '2px 8px', borderRadius: 5 }}>
              🔴 {blocked} blocked
            </span>
          )}
          {overdue > 0 && (
            <span style={{ fontSize: 12, fontWeight: 600, color: '#b45309', background: '#fef3e2', padding: '2px 8px', borderRadius: 5 }}>
              ⚠️ {overdue} overdue
            </span>
          )}
        </div>
        <span style={{ fontSize: 12, color: '#6B8FA0', flexShrink: 0, marginLeft: 8 }}>
          {expanded ? '▲ Hide' : '▼ View'}
        </span>
      </button>

      {/* Expanded task list */}
      {expanded && (
        <div style={{ marginTop: 8, border: '1px solid #dde4e8', borderRadius: 10, overflow: 'hidden' }}>
          {Object.entries(grouped).map(([phase, phaseTasks]) => (
            <div key={phase}>
              <div style={{ padding: '8px 14px', background: '#f8fafc', borderBottom: '1px solid #edf1f4', fontSize: 11, fontWeight: 700, color: '#4a6375', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                {phase}
              </div>
              {phaseTasks.map((task, i) => {
                const isOverdue = task.due_date && task.due_date < today
                const isBlocked = task.status === 'blocked'
                return (
                  <div key={task.id} style={{
                    padding: '10px 14px',
                    background: isBlocked ? '#fff8f8' : isOverdue ? '#fffbf5' : 'white',
                    borderBottom: i < phaseTasks.length - 1 ? '1px solid #f1f3f4' : 'none',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8,
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: '#0a1f2e', marginBottom: 3 }}>
                        {statusIcon[task.status] || '⬜'} {task.task_description}
                      </div>
                      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        {task.due_date && (
                          <span style={{ fontSize: 11, color: isOverdue ? '#c0392b' : '#6B8FA0', fontWeight: isOverdue ? 600 : 400 }}>
                            {isOverdue ? '⚠ Overdue: ' : 'Due: '}{task.due_date}
                          </span>
                        )}
                        {task.week_number && <span style={{ fontSize: 11, color: '#6B8FA0' }}>Week {task.week_number}</span>}
                        {task.owner && <span style={{ fontSize: 11, color: '#6B8FA0' }}>Owner: {task.owner}</span>}
                      </div>
                      {task.notes && (
                        <div style={{ fontSize: 11, color: '#6B8FA0', marginTop: 3, fontStyle: 'italic' }}>"{task.notes}"</div>
                      )}
                    </div>
                    <div style={{
                      fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap',
                      color: isBlocked ? '#c0392b' : isOverdue ? '#b45309' : '#6B8FA0',
                      background: isBlocked ? '#fce8e6' : isOverdue ? '#fef3e2' : '#f1f3f4',
                      padding: '3px 8px', borderRadius: 5,
                    }}>
                      {statusLabel[task.status] || task.status}
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function LogForm({ contractor, token, pin, onSuccess }) {
  const kpis = contractor.kpi_targets || []
  const [logDate, setLogDate] = useState(todayISO())
  const [values, setValues] = useState(() =>
    Object.fromEntries(kpis.map(k => [k.key, '']))
  )
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  function setKpiValue(key, val) {
    setValues(prev => ({ ...prev, [key]: val }))
  }

  async function handleSubmit() {
    setSubmitting(true)
    setError(null)
    try {
      const entries = kpis.map(k => ({
        kpi_key: k.key,
        kpi_label: k.label,
        value: values[k.key] !== '' && k.kpi_type !== 'manual'
          ? parseFloat(values[k.key])
          : null,
        label_value: k.kpi_type === 'manual' ? values[k.key] || null : null,
        notes: null,
      })).filter(e => e.value !== null || e.label_value !== null)

      if (entries.length === 0) {
        setError('Please fill in at least one KPI value before submitting.')
        setSubmitting(false)
        return
      }

      await submitPublicLog(token, { pin, log_date: logDate, entries })
      onSuccess(logDate, contractor.full_name)
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Submission failed. Please try again.'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={S.card}>
      <p style={S.name}>{contractor.full_name}</p>
      <p style={S.role}>{contractor.role_title}</p>

      <TasksSection tasks={contractor.tasks || []} />

      <div style={S.fieldGroup}>
        <label style={S.label}>Log Date</label>
        <input
          type="date"
          value={logDate}
          max={todayISO()}
          onChange={e => setLogDate(e.target.value)}
          style={S.input}
        />
      </div>

      <div style={S.divider} />
      <div style={S.sectionTitle}>KPI Entries</div>

      {error && <div style={S.error}>{error}</div>}

      {kpis.map(kpi => (
        <div key={kpi.key} style={S.kpiRow}>
          <div style={S.kpiLabel}>{kpi.label}</div>
          {kpi.target_value != null && (
            <div style={S.kpiTarget}>
              Target: {kpi.target_label || kpi.target_value}
            </div>
          )}
          {kpi.kpi_type === 'manual' ? (
            <input
              type="text"
              value={values[kpi.key] || ''}
              onChange={e => setKpiValue(kpi.key, e.target.value)}
              placeholder="e.g. Delivered, Not Started…"
              style={S.input}
            />
          ) : (
            <input
              type="number"
              min={0}
              step={kpi.kpi_type === 'conversion_rate' ? 0.01 : 1}
              value={values[kpi.key] || ''}
              onChange={e => setKpiValue(kpi.key, e.target.value)}
              placeholder={kpi.kpi_type === 'conversion_rate' ? 'e.g. 0.35' : 'Enter value'}
              style={S.input}
            />
          )}
        </div>
      ))}

      <button
        onClick={handleSubmit}
        disabled={submitting}
        style={{ ...S.btn, ...(submitting ? S.btnDisabled : {}) }}
      >
        {submitting ? 'Submitting…' : '✓ Submit Log'}
      </button>

      </div>
  )
}

const ACTIVITY_TYPES = [
  'Content Creation', 'Research', 'Client Communication',
  'Design', 'Development', 'Strategy', 'Admin', 'Meeting', 'Other',
]

function ActivityLogForm({ contractor, token, pin, onSuccess }) {
  const today = new Date().toISOString().split('T')[0]
  const [logDate, setLogDate] = useState(today)
  const [entries, setEntries] = useState([
    { activity_description: '', activity_type: 'General', duration_minutes: '', has_blocker: false, blocker_note: '' }
  ])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const addEntry = () => setEntries(prev => [
    ...prev,
    { activity_description: '', activity_type: 'General', duration_minutes: '', has_blocker: false, blocker_note: '' }
  ])

  const removeEntry = (i) => setEntries(prev => prev.filter((_, idx) => idx !== i))

  const updateEntry = (i, field, val) => setEntries(prev => {
    const next = [...prev]
    next[i] = { ...next[i], [field]: val }
    return next
  })

  async function handleSubmit() {
    const valid = entries.filter(e => e.activity_description.trim())
    if (valid.length === 0) { setError('Add at least one activity description.'); return }
    setSubmitting(true); setError(null)
    try {
      await submitPublicActivities(token, {
        pin,
        log_date: logDate,
        activities: valid.map(e => ({
          activity_description: e.activity_description.trim(),
          activity_type:        e.activity_type || 'General',
          duration_minutes:     e.duration_minutes ? parseInt(e.duration_minutes) : null,
          has_blocker:          e.has_blocker,
          blocker_note:         e.has_blocker ? (e.blocker_note.trim() || null) : null,
        })),
      })
      onSuccess(logDate, contractor.full_name)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Submission failed. Please try again.')
    } finally { setSubmitting(false) }
  }

  return (
    <div style={S.card}>
      <p style={S.name}>{contractor.full_name}</p>
      <p style={S.role}>{contractor.role_title}</p>

      <div style={S.fieldGroup}>
        <label style={S.label}>Log Date</label>
        <input type="date" value={logDate} max={today}
          onChange={e => setLogDate(e.target.value)} style={S.input} />
      </div>

      <div style={{ borderTop: '1px solid #edf1f4', margin: '16px 0' }} />
      <div style={{ fontSize: 13, fontWeight: 700, color: '#4a6375', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 16 }}>
        Activities
      </div>

      {error && <div style={S.error}>{error}</div>}

      {entries.map((entry, i) => (
        <div key={i} style={{ background: '#f8fafc', borderRadius: 10, border: '1px solid #dde4e8', padding: '14px 16px', marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#4a6375' }}>Activity {i + 1}</span>
            {entries.length > 1 && (
              <button onClick={() => removeEntry(i)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: '#c0392b', padding: 0 }}>✕</button>
            )}
          </div>

          <label style={S.label}>What did you work on? *</label>
          <textarea
            value={entry.activity_description}
            onChange={e => updateEntry(i, 'activity_description', e.target.value)}
            placeholder="Describe what you worked on…"
            rows={3}
            style={{ ...S.input, resize: 'vertical', marginBottom: 10 }}
          />

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
            <div>
              <label style={S.label}>Activity type</label>
              <select value={entry.activity_type} onChange={e => updateEntry(i, 'activity_type', e.target.value)}
                style={{ ...S.input, background: 'white' }}>
                {ACTIVITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label style={S.label}>Hours worked</label>
              <input type="number" min="0" max="24" step="0.5"
                value={entry.duration_minutes}
                onChange={e => updateEntry(i, 'duration_minutes', e.target.value)}
                placeholder="e.g. 2"
                style={S.input} />
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: entry.has_blocker ? 10 : 0 }}>
            <input type="checkbox" id={`blocker-${i}`} checked={entry.has_blocker}
              onChange={e => updateEntry(i, 'has_blocker', e.target.checked)}
              style={{ accentColor: '#c0392b', width: 16, height: 16 }} />
            <label htmlFor={`blocker-${i}`} style={{ fontSize: 13, color: entry.has_blocker ? '#c0392b' : '#4a6375', fontWeight: entry.has_blocker ? 600 : 400, cursor: 'pointer' }}>
              🔴 This activity has a blocker
            </label>
          </div>

          {entry.has_blocker && (
            <textarea
              value={entry.blocker_note}
              onChange={e => updateEntry(i, 'blocker_note', e.target.value)}
              placeholder="Describe the blocker — what is preventing progress?"
              rows={2}
              style={{ ...S.input, resize: 'vertical', borderColor: '#ffc0c0', marginTop: 8 }}
            />
          )}
        </div>
      ))}

      <button onClick={addEntry}
        style={{ width: '100%', padding: '10px', background: 'none', border: '1.5px dashed #dde4e8', borderRadius: 8, cursor: 'pointer', fontSize: 13, color: '#6B8FA0', fontWeight: 600 }}>
        + Add another activity
      </button>

      <button onClick={handleSubmit} disabled={submitting}
        style={{ ...S.btn, ...(submitting ? S.btnDisabled : {}) }}>
        {submitting ? 'Submitting…' : '✓ Submit Activities'}
      </button>
    </div>
  )
}

function SuccessState({ logDate, contractorName, onLogAnother }) {
  return (
    <div style={S.card}>
      <div style={S.success}>
        <div style={S.successIcon}>✅</div>
        <p style={S.successTitle}>Log submitted!</p>
        <p style={S.successSub}>
          Logged for <strong>{logDate}</strong>. Thank you, {contractorName}.
        </p>
        <button
          onClick={onLogAnother}
          style={{ ...S.btn, marginTop: 24, background: '#0a1f2e' }}
        >
          Log another day
        </button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PublicLogPage({ token }) {
  const [pageState, setPageState] = useState('loading') // loading|pin_entry|form|success|error|locked
  const [contractor, setContractor] = useState(null)
  const [pinError, setPinError] = useState(null)
  const [verifiedPin, setVerifiedPin] = useState(null)
  const [successDate, setSuccessDate] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)
  const [pinLoading, setPinLoading] = useState(false)
  const [formTab, setFormTab] = useState('kpi')

  useEffect(() => {
    async function load() {
      try {
        const data = await getPublicLogForm(token)
        setContractor(data)
        setPageState('pin_entry')
      } catch (err) {
        const msg = err?.response?.data?.detail || 'This log link is invalid or has expired.'
        setErrorMsg(msg)
        setPageState('error')
      }
    }
    load()
  }, [token])

  async function handlePinVerified(pin) {
    // We verify the PIN by attempting a dummy submit — but to avoid a wasted
    // round-trip we optimistically proceed to the form. The real PIN check
    // happens on submit. For UX we pre-verify with a test call only if the
    // user explicitly hits Continue before the form.
    // Simpler approach: trust PIN on form submit, show error inline there.
    setVerifiedPin(pin)
    setPinError(null)
    setPageState('form')
  }

  function handleSuccess(logDate, name) {
    setSuccessDate(logDate)
    setPageState('success')
  }

  function handleLogAnother() {
    setPageState('form')
  }

  return (
    <div style={S.page}>
      <OpsraHeader />

      {pageState === 'loading' && (
        <div style={{ ...S.card, textAlign: 'center', color: '#6B8FA0', padding: 48 }}>
          Loading…
        </div>
      )}

      {pageState === 'error' && (
        <div style={S.card}>
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🔗</div>
            <p style={S.successTitle}>Link unavailable</p>
            <p style={S.successSub}>{errorMsg}</p>
          </div>
        </div>
      )}

      {pageState === 'locked' && (
        <div style={S.card}>
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🔒</div>
            <p style={S.successTitle}>Access locked</p>
            <p style={S.successSub}>
              Too many incorrect PIN attempts. Please try again in 15 minutes or
              contact your manager.
            </p>
          </div>
        </div>
      )}

      {pageState === 'pin_entry' && contractor && (
        <PinGate
          contractorName={contractor.full_name}
          error={pinError}
          loading={pinLoading}
          onVerified={handlePinVerified}
        />
      )}

      {pageState === 'form' && contractor && (
        <div style={{ width: '100%', maxWidth: 520, margin: '0 16px' }}>
          {/* Tab switcher */}
          <div style={{ display: 'flex', background: 'white', borderRadius: '12px 12px 0 0', border: '1px solid #dde4e8', borderBottom: 'none', overflow: 'hidden' }}>
            <button
              onClick={() => setFormTab('kpi')}
              style={{ flex: 1, padding: '12px 0', background: formTab === 'kpi' ? '#0a1f2e' : 'white', color: formTab === 'kpi' ? 'white' : '#6B8FA0', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
              📊 KPI Log
            </button>
            <button
              onClick={() => setFormTab('activity')}
              style={{ flex: 1, padding: '12px 0', background: formTab === 'activity' ? '#0a1f2e' : 'white', color: formTab === 'activity' ? 'white' : '#6B8FA0', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600, borderLeft: '1px solid #dde4e8' }}>
              📝 Daily Activity
            </button>
          </div>
          <div style={{ marginTop: 0 }}>
            {formTab === 'kpi' ? (
              <LogForm contractor={contractor} token={token} pin={verifiedPin} onSuccess={handleSuccess} />
            ) : (
              <ActivityLogForm contractor={contractor} token={token} pin={verifiedPin} onSuccess={handleSuccess} />
            )}
          </div>
        </div>
      )}

      {pageState === 'success' && contractor && (
        <SuccessState
          logDate={successDate}
          contractorName={contractor.full_name}
          onLogAnother={handleLogAnother}
        />
      )}
    </div>
  )
}
