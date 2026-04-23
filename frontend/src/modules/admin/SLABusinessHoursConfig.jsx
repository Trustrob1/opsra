/**
 * frontend/src/modules/admin/SLABusinessHoursConfig.jsx
 * CONFIG-3 — SLA Business Hours configuration.
 *
 * Lets Owner/Admin define which days and hours the SLA clock ticks.
 * Outside configured hours the SLA timer pauses — reps aren't breached
 * for tickets that arrive at 11pm Friday.
 *
 * GET/PATCH /api/v1/admin/sla-business-hours
 *
 * Matches dark styling of LeadSLASettings.jsx (same module, same palette).
 * Pattern 51: full rewrite required for any edit — never sed.
 */

import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getSlaBusinessHours, updateSlaBusinessHours } from '../../services/admin.service'

const DAYS = [
  { key: 'monday',    label: 'Monday' },
  { key: 'tuesday',   label: 'Tuesday' },
  { key: 'wednesday', label: 'Wednesday' },
  { key: 'thursday',  label: 'Thursday' },
  { key: 'friday',    label: 'Friday' },
  { key: 'saturday',  label: 'Saturday' },
  { key: 'sunday',    label: 'Sunday' },
]

const DEFAULT_HOURS = {
  monday:    { enabled: true,  open: '08:00', close: '18:00' },
  tuesday:   { enabled: true,  open: '08:00', close: '18:00' },
  wednesday: { enabled: true,  open: '08:00', close: '18:00' },
  thursday:  { enabled: true,  open: '08:00', close: '18:00' },
  friday:    { enabled: true,  open: '08:00', close: '18:00' },
  saturday:  { enabled: false, open: '09:00', close: '14:00' },
  sunday:    { enabled: false, open: null,    close: null     },
}

function pad(val) {
  // Ensure time value stays as HH:MM string
  return val || '08:00'
}

export default function SLABusinessHoursConfig() {
  const [loading,  setLoading]  = useState(true)
  const [saving,   setSaving]   = useState(false)
  const [error,    setError]    = useState(null)
  const [success,  setSuccess]  = useState(false)

  const [timezone, setTimezone] = useState('Africa/Lagos')
  const [days, setDays]         = useState({ ...DEFAULT_HOURS })

  useEffect(() => {
    getSlaBusinessHours()
      .then(data => {
        const cfg = data?.sla_business_hours
        if (cfg) {
          setTimezone(cfg.timezone || 'Africa/Lagos')
          if (cfg.days) {
            setDays(prev => ({ ...prev, ...cfg.days }))
          }
        }
      })
      .catch(() => setError('Failed to load business hours settings.'))
      .finally(() => setLoading(false))
  }, [])

  function toggleDay(key) {
    setDays(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        enabled: !prev[key].enabled,
        // Set sensible defaults when enabling a previously null day
        open:  prev[key].open  || '08:00',
        close: prev[key].close || '18:00',
      },
    }))
  }

  function updateTime(key, field, value) {
    setDays(prev => ({
      ...prev,
      [key]: { ...prev[key], [field]: value },
    }))
  }

  function handleSave() {
    setError(null)
    setSuccess(false)

    // Validate: enabled days must have open < close
    for (const { key, label } of DAYS) {
      const d = days[key]
      if (!d?.enabled) continue
      if (!d.open || !d.close) {
        setError(`${label}: open and close times are required.`)
        return
      }
      if (d.open >= d.close) {
        setError(`${label}: open time must be before close time.`)
        return
      }
    }

    if (!timezone.includes('/')) {
      setError('Timezone must be a valid IANA timezone e.g. Africa/Lagos')
      return
    }

    setSaving(true)
    updateSlaBusinessHours({ timezone, days })
      .then(() => {
        setSuccess(true)
        setTimeout(() => setSuccess(false), 3000)
      })
      .catch(() => setError('Failed to save business hours settings.'))
      .finally(() => setSaving(false))
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#5a8a9f', fontSize: 14 }}>
        Loading business hours…
      </div>
    )
  }

  const enabledCount = DAYS.filter(d => days[d.key]?.enabled).length

  return (
    <div style={{ maxWidth: 680 }}>

      {/* Section header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17,
          color: 'white', margin: '0 0 6px',
        }}>
          🕐 SLA Business Hours
        </h2>
        <p style={{ fontSize: 13, color: '#5a8a9f', margin: 0, lineHeight: 1.6 }}>
          The SLA clock only ticks during your configured business hours.
          Leads that arrive outside these windows won't trigger breach alerts
          until the next working period begins.
        </p>
      </div>

      {/* Info callout */}
      <div style={{
        background: '#0a1e2b', border: '1px solid #1a3545',
        borderRadius: 8, padding: '14px 16px', marginBottom: 24,
        display: 'flex', gap: 12, alignItems: 'flex-start',
      }}>
        <span style={{ fontSize: 18, flexShrink: 0 }}>💡</span>
        <div style={{ fontSize: 12, color: '#4a7a8a', lineHeight: 1.7, fontFamily: ds.fontDm }}>
          <strong style={{ color: '#6a9aaa' }}>How it works:</strong> When checking SLA
          targets, the system counts only hours that fall within your enabled windows.
          A lead created at 5pm Friday won't appear overdue until enough business hours
          have elapsed on Monday morning. Orgs without business hours configured fall
          back to 24/7 wall-clock timing.
        </div>
      </div>

      {/* Timezone */}
      <div style={{
        background: '#0d2231', border: '1px solid #1a3545',
        borderRadius: 10, padding: '16px 20px', marginBottom: 20,
      }}>
        <label style={{
          display: 'block', fontFamily: ds.fontSyne, fontWeight: 600,
          fontSize: 13, color: '#7aafc0', marginBottom: 10,
        }}>
          🌍 Timezone
        </label>
        <input
          type="text"
          value={timezone}
          onChange={e => setTimezone(e.target.value)}
          placeholder="e.g. Africa/Lagos"
          style={{
            width: '100%', boxSizing: 'border-box',
            padding: '9px 12px', background: '#091620',
            border: '1px solid #1a3545', borderRadius: 6,
            color: 'white', fontFamily: ds.fontDm, fontSize: 13,
            outline: 'none',
          }}
        />
        <p style={{ fontSize: 11, color: '#3a5a6a', margin: '6px 0 0', fontFamily: ds.fontDm }}>
          Use IANA timezone format. Examples: Africa/Lagos · Europe/London · America/New_York
        </p>
      </div>

      {/* Day schedule */}
      <div style={{
        background: '#0d2231', border: '1px solid #1a3545',
        borderRadius: 10, overflow: 'hidden', marginBottom: 20,
      }}>
        {/* Header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '110px 64px 1fr 16px 1fr',
          gap: 10, padding: '10px 16px',
          background: '#091620', alignItems: 'center',
        }}>
          {['Day', 'Active', 'Opens', '', 'Closes'].map((h, i) => (
            <div key={i} style={{
              fontSize: 10, color: '#3a6a7a', fontWeight: 600,
              textTransform: 'uppercase', letterSpacing: '0.5px',
              fontFamily: ds.fontDm,
            }}>{h}</div>
          ))}
        </div>

        {/* Day rows */}
        {DAYS.map(({ key, label }, idx) => {
          const d       = days[key] || { enabled: false, open: '08:00', close: '18:00' }
          const isOn    = !!d.enabled
          const isLast  = idx === DAYS.length - 1

          return (
            <div
              key={key}
              style={{
                display: 'grid',
                gridTemplateColumns: '110px 64px 1fr 16px 1fr',
                gap: 10, padding: '12px 16px',
                borderBottom: isLast ? 'none' : '1px solid #0f2535',
                alignItems: 'center',
                opacity: isOn ? 1 : 0.45,
                transition: 'opacity 0.15s',
              }}
            >
              {/* Day label */}
              <div style={{
                fontFamily: ds.fontDm, fontSize: 13,
                color: isOn ? 'white' : '#3a5a6a', fontWeight: isOn ? 600 : 400,
              }}>
                {label}
              </div>

              {/* Toggle */}
              <div>
                <button
                  onClick={() => toggleDay(key)}
                  style={{
                    width: 44, height: 24, borderRadius: 12,
                    background: isOn ? ds.teal : '#1a3545',
                    border: 'none', cursor: 'pointer',
                    position: 'relative', transition: 'background 0.2s',
                    flexShrink: 0,
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 3,
                    left: isOn ? 22 : 3,
                    width: 18, height: 18, borderRadius: '50%',
                    background: 'white',
                    transition: 'left 0.2s',
                  }} />
                </button>
              </div>

              {/* Open time */}
              <input
                type="time"
                value={pad(d.open)}
                disabled={!isOn}
                onChange={e => updateTime(key, 'open', e.target.value)}
                style={{
                  padding: '7px 10px', background: '#091620',
                  border: '1px solid #1a3545', borderRadius: 6,
                  color: isOn ? 'white' : '#3a5a6a',
                  fontFamily: ds.fontDm, fontSize: 13,
                  outline: 'none', width: '100%',
                  boxSizing: 'border-box',
                  cursor: isOn ? 'auto' : 'not-allowed',
                }}
              />

              {/* Separator */}
              <div style={{
                textAlign: 'center', fontSize: 12,
                color: '#3a5a6a', fontFamily: ds.fontDm,
              }}>→</div>

              {/* Close time */}
              <input
                type="time"
                value={pad(d.close)}
                disabled={!isOn}
                onChange={e => updateTime(key, 'close', e.target.value)}
                style={{
                  padding: '7px 10px', background: '#091620',
                  border: '1px solid #1a3545', borderRadius: 6,
                  color: isOn ? 'white' : '#3a5a6a',
                  fontFamily: ds.fontDm, fontSize: 13,
                  outline: 'none', width: '100%',
                  boxSizing: 'border-box',
                  cursor: isOn ? 'auto' : 'not-allowed',
                }}
              />
            </div>
          )
        })}
      </div>

      {/* Summary */}
      <div style={{
        background: '#0a1e2b', border: '1px solid #1a3545',
        borderRadius: 8, padding: '12px 16px', marginBottom: 24,
        fontSize: 12, color: '#4a7a8a', fontFamily: ds.fontDm,
      }}>
        <strong style={{ color: '#6a9aaa' }}>Active schedule:</strong>
        {' '}{enabledCount} working day{enabledCount !== 1 ? 's' : ''} configured.
        {enabledCount === 0 && (
          <span style={{ color: '#e05252', marginLeft: 6 }}>
            ⚠ No active days — SLA worker will fall back to 24/7 wall-clock timing.
          </span>
        )}
      </div>

      {/* Feedback */}
      {error && (
        <div style={{
          background: '#2a0a0a', border: '1px solid #6a2020',
          borderRadius: 6, padding: '10px 14px',
          color: '#e05252', fontSize: 13, marginBottom: 16, fontFamily: ds.fontDm,
        }}>
          {error}
        </div>
      )}
      {success && (
        <div style={{
          background: '#0a2a1a', border: '1px solid #206a40',
          borderRadius: 6, padding: '10px 14px',
          color: '#3dc47a', fontSize: 13, marginBottom: 16, fontFamily: ds.fontDm,
        }}>
          ✅ Business hours saved successfully.
        </div>
      )}

      {/* Save */}
      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          background:   saving ? '#1a3545' : ds.teal,
          color:        'white', border: 'none',
          borderRadius: 8, padding: '11px 28px',
          fontFamily:   ds.fontSyne, fontWeight: 700,
          fontSize:     14,
          cursor:       saving ? 'not-allowed' : 'pointer',
          opacity:      saving ? 0.7 : 1,
          transition:   'all 0.15s',
        }}
      >
        {saving ? 'Saving…' : 'Save Business Hours'}
      </button>
    </div>
  )
}
