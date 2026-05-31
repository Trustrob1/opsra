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
import { getPublicLogForm, submitPublicLog } from '../services/performance_logs.service'

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
        <LogForm
          contractor={contractor}
          token={token}
          pin={verifiedPin}
          onSuccess={handleSuccess}
        />
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
