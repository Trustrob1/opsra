/**
 * frontend/src/modules/admin/MessagingLimitsConfig.jsx
 * 9E-D — Messaging Limits configuration.
 *
 * Lets Owner/Admin configure:
 *   - Daily customer message limit (1–20, system ceiling enforced)
 *   - Quiet hours window (start + end HH:MM)
 *   - Timezone for quiet hours interpretation
 *
 * GET/PATCH /api/v1/admin/messaging-limits
 *
 * Error pattern: toast (matches CommerceSettings.jsx — most polished pattern).
 * Error reads err?.response?.data?.detail?.message — correct envelope read.
 * Pattern 50: admin.service.js calls only.
 * Pattern 51: full rewrite required for any edit — never sed.
 */

import { useState, useEffect, useCallback } from 'react'
import { getMessagingLimits, updateMessagingLimits } from '../../services/admin.service'

// ─── Icons ────────────────────────────────────────────────────────────────────

function IconCheck() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
      style={{ width: 16, height: 16 }}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  )
}

function IconWarning() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}
      style={{ width: 18, height: 18 }}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  )
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ toast, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 3500)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 50,
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '12px 16px', borderRadius: 10,
      boxShadow: '0 4px 20px rgba(0,0,0,0.25)',
      background: toast.type === 'success' ? '#0d7a5f' : '#c0392b',
      color: 'white', fontSize: 13, fontWeight: 500,
      maxWidth: 420,
    }}>
      {toast.type === 'success' ? <IconCheck /> : <IconWarning />}
      <span>{toast.message}</span>
    </div>
  )
}

// ─── Field error ──────────────────────────────────────────────────────────────

function FieldError({ message }) {
  if (!message) return null
  return (
    <p style={{
      fontSize: 12, color: '#e05252', margin: '5px 0 0',
      display: 'flex', alignItems: 'center', gap: 5,
    }}>
      <IconWarning />
      {message}
    </p>
  )
}

// ─── Input styles (shared) ────────────────────────────────────────────────────

const inputStyle = (hasError) => ({
  width: '100%', boxSizing: 'border-box',
  padding: '9px 12px', background: '#091620',
  border: `1px solid ${hasError ? '#c0392b' : '#1a3545'}`,
  borderRadius: 6, color: 'white',
  fontSize: 13, outline: 'none',
  fontFamily: 'inherit',
  transition: 'border-color 0.15s',
})

// ─── Main component ───────────────────────────────────────────────────────────

export default function MessagingLimitsConfig() {
  const [loading,  setLoading]  = useState(true)
  const [saving,   setSaving]   = useState(false)
  const [toast,    setToast]    = useState(null)

  // Field-level errors (populated from 422 responses)
  const [fieldErrors, setFieldErrors] = useState({})

  // System ceiling returned by the API
  const [ceiling, setCeiling] = useState(20)

  // Form state
  const [dailyLimit,    setDailyLimit]    = useState(3)
  const [quietStart,    setQuietStart]    = useState('')
  const [quietEnd,      setQuietEnd]      = useState('')
  const [timezone,      setTimezone]      = useState('Africa/Lagos')
  const [quietEnabled,  setQuietEnabled]  = useState(false)

  // Saved state for dirty tracking
  const [saved, setSaved] = useState({})

  const isDirty = (
    dailyLimit   !== (saved.dailyLimit   ?? 3)           ||
    quietEnabled !== (saved.quietEnabled ?? false)        ||
    quietStart   !== (saved.quietStart   ?? '')           ||
    quietEnd     !== (saved.quietEnd     ?? '')           ||
    timezone     !== (saved.timezone     ?? 'Africa/Lagos')
  )

  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type })
  }, [])

  // ── Load ───────────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getMessagingLimits()
      .then(data => {
        if (cancelled) return
        const limit  = data?.daily_customer_message_limit ?? 3
        const start  = data?.quiet_hours_start ?? ''
        const end    = data?.quiet_hours_end   ?? ''
        const tz     = data?.timezone          ?? 'Africa/Lagos'
        const qOn    = Boolean(start && end)
        const ceil   = data?.system_ceiling    ?? 20

        setDailyLimit(limit)
        setQuietStart(start)
        setQuietEnd(end)
        setTimezone(tz)
        setQuietEnabled(qOn)
        setCeiling(ceil)
        setSaved({ dailyLimit: limit, quietStart: start, quietEnd: end,
                   timezone: tz, quietEnabled: qOn })
      })
      .catch(() => showToast('Failed to load messaging limits', 'error'))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [showToast])

  // ── Client-side validation ────────────────────────────────────────────────

  function validate() {
    const errors = {}

    if (dailyLimit < 1 || dailyLimit > ceiling) {
      errors.daily_customer_message_limit =
        `Must be between 1 and ${ceiling}`
    }

    if (quietEnabled) {
      if (!quietStart) {
        errors.quiet_hours_start = 'Start time is required when quiet hours are enabled'
      }
      if (!quietEnd) {
        errors.quiet_hours_end = 'End time is required when quiet hours are enabled'
      }
      if (quietStart && quietEnd && quietStart === quietEnd) {
        errors.quiet_hours_start = 'Start and end times cannot be the same'
      }
      if (!timezone || !timezone.includes('/')) {
        errors.timezone = 'Enter a valid IANA timezone e.g. Africa/Lagos'
      }
    }

    return errors
  }

  // ── Save ───────────────────────────────────────────────────────────────────

  async function handleSave() {
    if (!isDirty || saving) return

    setFieldErrors({})

    const clientErrors = validate()
    if (Object.keys(clientErrors).length > 0) {
      setFieldErrors(clientErrors)
      return
    }

    setSaving(true)
    try {
      const payload = {
        daily_customer_message_limit: dailyLimit,
        quiet_hours_start: quietEnabled ? quietStart : null,
        quiet_hours_end:   quietEnabled ? quietEnd   : null,
        timezone,
      }
      // Remove null fields if quiet hours disabled — send explicit nulls to clear
      await updateMessagingLimits(payload)
      setSaved({ dailyLimit, quietStart, quietEnd, timezone, quietEnabled })
      showToast('Messaging limits saved')
    } catch (err) {
      // Correctly reads the FastAPI HTTPException envelope:
      //   err.response.data.detail = { code, message, field } | string
      const detail = err?.response?.data?.detail
      const msg =
        (typeof detail === 'object' ? detail?.message : detail)
        ?? 'Failed to save messaging limits'

      // If the error has a field key, show it inline on that field
      if (detail?.field) {
        setFieldErrors({ [detail.field]: msg })
      } else {
        showToast(msg, 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  function handleDiscard() {
    setDailyLimit(saved.dailyLimit ?? 3)
    setQuietStart(saved.quietStart ?? '')
    setQuietEnd(saved.quietEnd     ?? '')
    setTimezone(saved.timezone     ?? 'Africa/Lagos')
    setQuietEnabled(saved.quietEnabled ?? false)
    setFieldErrors({})
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#5a8a9f', fontSize: 14 }}>
        Loading messaging limits…
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 640 }}>

      {toast && <Toast toast={toast} onDismiss={() => setToast(null)} />}

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontWeight: 700, fontSize: 17, color: 'white',
          margin: '0 0 6px',
        }}>
          💬 Messaging Limits
        </h2>
        <p style={{ fontSize: 13, color: '#5a8a9f', margin: 0, lineHeight: 1.6 }}>
          Control how many automated messages a customer can receive per day,
          and set quiet hours to pause outbound messaging overnight.
        </p>
      </div>

      {/* ── Daily limit card ─────────────────────────────────────────────── */}
      <div style={{
        background: '#0d2231', border: '1px solid #1a3545',
        borderRadius: 10, padding: '20px 24px', marginBottom: 16,
      }}>
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontWeight: 600, fontSize: 14, color: 'white', margin: '0 0 4px' }}>
            Daily message limit per customer
          </p>
          <p style={{ fontSize: 12, color: '#5a8a9f', margin: 0, lineHeight: 1.6 }}>
            Maximum automated messages any single customer can receive in one day,
            across all workers (broadcasts, drip, renewals, NPS, cart reminders).
            System maximum is {ceiling}.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <input
            type="number"
            min={1}
            max={ceiling}
            value={dailyLimit}
            onChange={e => {
              setDailyLimit(Number(e.target.value))
              setFieldErrors(prev => ({ ...prev, daily_customer_message_limit: undefined }))
            }}
            style={{ ...inputStyle(!!fieldErrors.daily_customer_message_limit), width: 100 }}
          />
          <span style={{ fontSize: 12, color: '#5a8a9f' }}>
            messages / customer / day
          </span>
        </div>
        <FieldError message={fieldErrors.daily_customer_message_limit} />

        {/* Info callout */}
        <div style={{
          marginTop: 14, background: '#0a1e2b', border: '1px solid #1a3545',
          borderRadius: 8, padding: '12px 14px',
          display: 'flex', gap: 10, alignItems: 'flex-start',
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>💡</span>
          <p style={{ fontSize: 12, color: '#4a7a8a', margin: 0, lineHeight: 1.7 }}>
            <strong style={{ color: '#6a9aaa' }}>Default is 3.</strong> If a customer
            hits this limit, remaining messages are silently skipped for that day —
            they are not queued or retried. Keep this low to avoid overwhelming customers
            who are in multiple automated sequences simultaneously.
          </p>
        </div>
      </div>

      {/* ── Quiet hours card ─────────────────────────────────────────────── */}
      <div style={{
        background: '#0d2231', border: '1px solid #1a3545',
        borderRadius: 10, padding: '20px 24px', marginBottom: 24,
      }}>
        {/* Toggle header */}
        <div style={{
          display: 'flex', alignItems: 'flex-start',
          justifyContent: 'space-between', gap: 16, marginBottom: quietEnabled ? 20 : 0,
        }}>
          <div>
            <p style={{ fontWeight: 600, fontSize: 14, color: 'white', margin: '0 0 4px' }}>
              Quiet hours
            </p>
            <p style={{ fontSize: 12, color: '#5a8a9f', margin: 0, lineHeight: 1.6 }}>
              Messages triggered outside this window are held and sent when quiet
              hours end — they are never dropped.
            </p>
          </div>
          {/* Toggle */}
          <button
            onClick={() => {
              setQuietEnabled(prev => !prev)
              setFieldErrors({})
            }}
            style={{
              flexShrink: 0, width: 44, height: 24, borderRadius: 12,
              background: quietEnabled ? '#0d7a5f' : '#1a3545',
              border: 'none', cursor: 'pointer',
              position: 'relative', transition: 'background 0.2s',
            }}
          >
            <span style={{
              position: 'absolute', top: 3,
              left: quietEnabled ? 22 : 3,
              width: 18, height: 18, borderRadius: '50%',
              background: 'white', transition: 'left 0.2s',
            }} />
          </button>
        </div>

        {quietEnabled && (
          <>
            {/* Time window row */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 24px 1fr',
              gap: 10, alignItems: 'center', marginBottom: 16,
            }}>
              <div>
                <label style={{ fontSize: 11, color: '#5a8a9f', display: 'block', marginBottom: 5 }}>
                  START TIME
                </label>
                <input
                  type="time"
                  value={quietStart}
                  onChange={e => {
                    setQuietStart(e.target.value)
                    setFieldErrors(prev => ({ ...prev, quiet_hours_start: undefined }))
                  }}
                  style={inputStyle(!!fieldErrors.quiet_hours_start)}
                />
                <FieldError message={fieldErrors.quiet_hours_start} />
              </div>

              <div style={{ textAlign: 'center', color: '#3a5a6a', fontSize: 14, paddingTop: 20 }}>
                →
              </div>

              <div>
                <label style={{ fontSize: 11, color: '#5a8a9f', display: 'block', marginBottom: 5 }}>
                  END TIME
                </label>
                <input
                  type="time"
                  value={quietEnd}
                  onChange={e => {
                    setQuietEnd(e.target.value)
                    setFieldErrors(prev => ({ ...prev, quiet_hours_end: undefined }))
                  }}
                  style={inputStyle(!!fieldErrors.quiet_hours_end)}
                />
                <FieldError message={fieldErrors.quiet_hours_end} />
              </div>
            </div>

            {/* Overnight hint */}
            {quietStart && quietEnd && quietStart > quietEnd && (
              <div style={{
                marginBottom: 16, padding: '10px 12px',
                background: '#0a1e2b', borderRadius: 6,
                fontSize: 12, color: '#6a9aaa',
                border: '1px solid #1a3545',
              }}>
                🌙 Overnight window — quiet from {quietStart} until {quietEnd} the next day.
              </div>
            )}

            {/* Timezone */}
            <div>
              <label style={{ fontSize: 11, color: '#5a8a9f', display: 'block', marginBottom: 5 }}>
                TIMEZONE
              </label>
              <input
                type="text"
                value={timezone}
                onChange={e => {
                  setTimezone(e.target.value)
                  setFieldErrors(prev => ({ ...prev, timezone: undefined }))
                }}
                placeholder="e.g. Africa/Lagos"
                style={inputStyle(!!fieldErrors.timezone)}
              />
              <p style={{ fontSize: 11, color: '#3a5a6a', margin: '5px 0 0' }}>
                Use IANA format. Examples: Africa/Lagos · Europe/London · America/New_York
              </p>
              <FieldError message={fieldErrors.timezone} />
            </div>
          </>
        )}
      </div>

      {/* ── Action bar ───────────────────────────────────────────────────── */}
      {isDirty && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 40,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 16, padding: '14px 24px',
          background: 'white', borderTop: '1px solid #e2eff4',
          boxShadow: '0 -4px 20px rgba(0,0,0,0.08)',
        }}>
          <p style={{ fontSize: 13, color: '#5a8a9f', margin: 0 }}>
            You have unsaved changes
          </p>
          <div style={{ display: 'flex', gap: 12 }}>
            <button
              onClick={handleDiscard}
              disabled={saving}
              style={{
                padding: '8px 16px', borderRadius: 8, border: 'none',
                background: 'transparent', cursor: saving ? 'not-allowed' : 'pointer',
                fontSize: 13, fontWeight: 500, color: '#4a7a8a',
                opacity: saving ? 0.5 : 1,
              }}
            >
              Discard
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 20px', borderRadius: 8, border: 'none',
                background: saving ? '#1a3545' : '#0d7a5f',
                color: 'white', cursor: saving ? 'not-allowed' : 'pointer',
                fontSize: 13, fontWeight: 600,
                opacity: saving ? 0.7 : 1,
                transition: 'all 0.15s',
              }}
            >
              {saving ? (
                <>
                  <span style={{
                    width: 14, height: 14, borderRadius: '50%',
                    border: '2px solid rgba(255,255,255,0.4)',
                    borderTopColor: 'white',
                    display: 'inline-block',
                    animation: 'spin 0.7s linear infinite',
                  }} />
                  Saving…
                </>
              ) : (
                <><IconCheck /> Save changes</>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
