/**
 * frontend/src/modules/admin/LeadSLASettings.jsx
 * M01-6 — Lead Response SLA & Speed Alerts
 *
 * Lets Owner/Admin users configure the per-tier response time targets
 * that trigger breach notifications and manager escalations.
 *
 * Tiers:  🔴 Hot  (default 1h)  |  🟡 Warm (default 4h)  |  🔵 Cold (default 24h)
 *
 * GET  /api/v1/admin/sla-config  — load current values on mount
 * PATCH /api/v1/admin/sla-config — save on submit
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getSlaConfig, updateSlaConfig } from '../../services/admin.service'

// ── small inline helpers ──────────────────────────────────────────────────────

function SlaField({ label, emoji, color, value, onChange, min, max, hint }) {
  return (
    <div style={{
      background:   '#0d2231',
      border:       `1px solid ${color}33`,
      borderRadius: 10,
      padding:      '18px 20px',
      flex:         1,
      minWidth:     200,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 20 }}>{emoji}</span>
        <span style={{
          fontFamily: ds.fontSyne,
          fontWeight: 700,
          fontSize:   14,
          color:      color,
        }}>{label}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={e => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
          style={{
            width:        72,
            padding:      '8px 10px',
            background:   '#091620',
            border:       `1px solid ${color}55`,
            borderRadius: 6,
            color:        'white',
            fontFamily:   ds.fontDm,
            fontSize:     18,
            fontWeight:   700,
            textAlign:    'center',
            outline:      'none',
          }}
        />
        <span style={{ color: '#5a8a9f', fontSize: 13, fontFamily: ds.fontDm }}>hours</span>
      </div>
      <p style={{ fontSize: 11, color: '#4a6a7a', margin: '8px 0 0', fontFamily: ds.fontDm }}>
        {hint}
      </p>
    </div>
  )
}


// ── Main component ────────────────────────────────────────────────────────────

export default function LeadSLASettings() {
  const [loading,  setLoading]  = useState(true)
  const [saving,   setSaving]   = useState(false)
  const [error,    setError]    = useState(null)
  const [success,  setSuccess]  = useState(false)

  const [hotHours,  setHotHours]  = useState(1)
  const [warmHours, setWarmHours] = useState(4)
  const [coldHours, setColdHours] = useState(24)

  // ── Load current config ─────────────────────────────────────────────────
  useEffect(() => {
    getSlaConfig()
      .then(d => {
        setHotHours(d?.sla_hot_hours   ?? 1)
        setWarmHours(d?.sla_warm_hours ?? 4)
        setColdHours(d?.sla_cold_hours ?? 24)
      })
      .catch(() => setError('Failed to load SLA settings.'))
      .finally(() => setLoading(false))
  }, [])

  // ── Save ────────────────────────────────────────────────────────────────
  function handleSave() {
    setSaving(true)
    setError(null)
    setSuccess(false)
    updateSlaConfig({
      sla_hot_hours:  hotHours,
      sla_warm_hours: warmHours,
      sla_cold_hours: coldHours,
    })
      .then(() => setSuccess(true))
      .catch(() => setError('Failed to save SLA settings.'))
      .finally(() => setSaving(false))
  }

  // ── Render ──────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#5a8a9f', fontSize: 14 }}>
        Loading SLA settings…
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 780 }}>

      {/* Section header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17,
          color: 'white', margin: '0 0 6px',
        }}>
          ⏱️ Lead Response SLA Targets
        </h2>
        <p style={{ fontSize: 13, color: '#5a8a9f', margin: 0, lineHeight: 1.6 }}>
          Set how long reps have to make first contact with each lead tier before
          a breach alert is sent. At <strong style={{ color: '#7aafc0' }}>2× the target</strong>,
          the alert escalates to a manager automatically.
        </p>
      </div>

      {/* How it works callout */}
      <div style={{
        background:   '#0a1e2b',
        border:       '1px solid #1a3545',
        borderRadius: 8,
        padding:      '14px 16px',
        marginBottom: 24,
        display:      'flex',
        gap:          12,
        alignItems:   'flex-start',
      }}>
        <span style={{ fontSize: 18, flexShrink: 0 }}>💡</span>
        <div style={{ fontSize: 12, color: '#4a7a8a', lineHeight: 1.7, fontFamily: ds.fontDm }}>
          <strong style={{ color: '#6a9aaa' }}>How it works:</strong> A background check
          runs every 15 minutes. If a scored, assigned lead hasn't been contacted within the
          target window, the rep receives a breach alert. At double the window, the manager
          is also notified. "Contacted" means any stage move to <em>contacted</em>, outbound
          WhatsApp message, or interaction logged on the lead.
        </div>
      </div>

      {/* Tier config cards */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 28 }}>
        <SlaField
          label="Hot Leads"
          emoji="🔴"
          color="#e05252"
          value={hotHours}
          onChange={setHotHours}
          min={1}
          max={72}
          hint="Typically 1–2 hrs. Hot leads go cold fast."
        />
        <SlaField
          label="Warm Leads"
          emoji="🟡"
          color="#d4a437"
          value={warmHours}
          onChange={setWarmHours}
          min={1}
          max={168}
          hint="Typically 4–8 hrs. Still high intent."
        />
        <SlaField
          label="Cold Leads"
          emoji="🔵"
          color="#4a9abf"
          value={coldHours}
          onChange={setColdHours}
          min={1}
          max={720}
          hint="Typically 24–48 hrs. Lower urgency."
        />
      </div>

      {/* Escalation reminder */}
      <div style={{
        background:   '#0a1e2b',
        border:       '1px solid #1a3545',
        borderRadius: 8,
        padding:      '12px 16px',
        marginBottom: 24,
        fontSize:     12,
        color:        '#4a7a8a',
        fontFamily:   ds.fontDm,
        lineHeight:   1.6,
      }}>
        <strong style={{ color: '#6a9aaa' }}>Escalation thresholds:</strong>
        {' '}🔴 Hot escalates at{' '}
        <span style={{ color: '#e05252', fontWeight: 700 }}>{hotHours * 2}h</span>
        {'  •  '}🟡 Warm at{' '}
        <span style={{ color: '#d4a437', fontWeight: 700 }}>{warmHours * 2}h</span>
        {'  •  '}🔵 Cold at{' '}
        <span style={{ color: '#4a9abf', fontWeight: 700 }}>{coldHours * 2}h</span>
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
          ✅ SLA targets saved successfully.
        </div>
      )}

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          background:    saving ? '#1a3545' : ds.teal,
          color:         'white',
          border:        'none',
          borderRadius:  8,
          padding:       '11px 28px',
          fontFamily:    ds.fontSyne,
          fontWeight:    700,
          fontSize:      14,
          cursor:        saving ? 'not-allowed' : 'pointer',
          opacity:       saving ? 0.7 : 1,
          transition:    'all 0.15s',
        }}
      >
        {saving ? 'Saving…' : 'Save SLA Targets'}
      </button>
    </div>
  )
}
