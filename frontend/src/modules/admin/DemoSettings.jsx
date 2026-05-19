/**
 * frontend/src/modules/admin/DemoSettings.jsx
 * DEMO-TMPL — Demo Template Settings
 *
 * Allows owner/ops_manager to configure:
 *   - Showroom address (injected into {{4}} of the confirmation template)
 *   - Confirmation template name (must match Meta-approved template exactly)
 *   - Reminder template name (must match Meta-approved template exactly)
 *
 * Follows the CONFIG-3 admin settings pattern:
 *   - Loads on mount via GET /api/v1/admin/demo-settings
 *   - Saves via PATCH /api/v1/admin/demo-settings
 *   - Pattern 50: admin.service.js (axios + _h()) only
 *   - Pattern 51: full rewrite only — never sed
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getDemoSettings, updateDemoSettings } from '../../services/admin.service'

export default function DemoSettings() {
  const [loading, setSaving]         = useState(false)
  const [fetching, setFetching]      = useState(true)
  const [error, setError]            = useState(null)
  const [success, setSuccess]        = useState(false)

  const [showroomAddress,           setShowroomAddress]           = useState('')
  const [confirmationTemplateName,  setConfirmationTemplateName]  = useState('showroom_visit_confirmation')
  const [reminderTemplateName,      setReminderTemplateName]      = useState('showroom_visit_reminder')

  useEffect(() => {
    getDemoSettings()
      .then(data => {
        setShowroomAddress(data?.showroom_address ?? '')
        setConfirmationTemplateName(data?.demo_confirmation_template ?? 'showroom_visit_confirmation')
        setReminderTemplateName(data?.demo_reminder_template ?? 'showroom_visit_reminder')
      })
      .catch(() => setError('Failed to load demo settings.'))
      .finally(() => setFetching(false))
  }, [])

  const handleSave = async () => {
    setError(null)
    setSuccess(false)
    setSaving(true)
    try {
      await updateDemoSettings({
        showroom_address:           showroomAddress.trim() || null,
        demo_confirmation_template: confirmationTemplateName.trim() || 'showroom_visit_confirmation',
        demo_reminder_template:     reminderTemplateName.trim()     || 'showroom_visit_reminder',
      })
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
    } catch (err) {
      setError(
        err?.response?.data?.error?.message
        ?? err?.response?.data?.detail
        ?? 'Failed to save demo settings.'
      )
    } finally {
      setSaving(false)
    }
  }

  // ── Styles ──────────────────────────────────────────────────────────────────

  const card = {
    background: 'white',
    border: `1px solid ${ds.border}`,
    borderRadius: ds.radius.xl,
    padding: '24px 28px',
    marginBottom: 20,
    boxShadow: '0 2px 12px rgba(2,128,144,0.05)',
  }

  const labelStyle = {
    display: 'block',
    fontSize: 11,
    fontWeight: 600,
    color: ds.gray,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: 6,
  }

  const inputStyle = {
    width: '100%',
    boxSizing: 'border-box',
    padding: '10px 14px',
    border: `1.5px solid ${ds.border}`,
    borderRadius: ds.radius.md,
    fontSize: 13.5,
    color: ds.dark,
    fontFamily: ds.fontDm,
    background: 'white',
    outline: 'none',
  }

  const hintStyle = {
    fontSize: 11.5,
    color: ds.gray,
    marginTop: 5,
    lineHeight: 1.5,
  }

  const sectionTitle = {
    fontFamily: ds.fontSyne,
    fontWeight: 700,
    fontSize: 13,
    color: ds.dark,
    margin: '0 0 16px',
    paddingBottom: 10,
    borderBottom: `1px solid ${ds.border}`,
  }

  if (fetching) {
    return (
      <div style={{ padding: '48px 0', textAlign: 'center', color: ds.gray, fontSize: 13 }}>
        Loading demo settings…
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 640 }}>

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: '0 0 6px' }}>
          📅 Demo Settings
        </h2>
        <p style={{ fontSize: 13, color: ds.gray, margin: 0, lineHeight: 1.6 }}>
          Configure the WhatsApp templates used for visit confirmation and reminders.
          Template names must match exactly what is approved in Meta Business Manager.
        </p>
      </div>

      {/* ── Showroom / Location ──────────────────────────────────────── */}
      <div style={card}>
        <p style={sectionTitle}>📍 Location</p>

        <label style={labelStyle}>Showroom / Visit Address</label>
        <input
          style={inputStyle}
          type="text"
          value={showroomAddress}
          onChange={e => setShowroomAddress(e.target.value)}
          placeholder="e.g. 14 Admiralty Way, Lekki Phase 1, Lagos"
          maxLength={500}
        />
        <p style={hintStyle}>
          This address is injected into the confirmation and reminder templates as the visit location.
          Leave blank if your templates do not include a location variable.
        </p>
      </div>

      {/* ── Template Names ───────────────────────────────────────────── */}
      <div style={card}>
        <p style={sectionTitle}>💬 WhatsApp Template Names</p>

        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>Confirmation Template Name</label>
          <input
            style={inputStyle}
            type="text"
            value={confirmationTemplateName}
            onChange={e => setConfirmationTemplateName(e.target.value)}
            placeholder="showroom_visit_confirmation"
            maxLength={100}
          />
          <p style={hintStyle}>
            Sent immediately when a visit is confirmed. Must be an approved{' '}
            <strong>Utility</strong> template in Meta Business Manager.
            Default: <code style={{ background: ds.light, padding: '1px 5px', borderRadius: 4, fontSize: 11 }}>showroom_visit_confirmation</code>
          </p>
        </div>

        <div>
          <label style={labelStyle}>Reminder Template Name</label>
          <input
            style={inputStyle}
            type="text"
            value={reminderTemplateName}
            onChange={e => setReminderTemplateName(e.target.value)}
            placeholder="showroom_visit_reminder"
            maxLength={100}
          />
          <p style={hintStyle}>
            Sent 24 hours and 1 hour before a confirmed visit. Same template is used for both —
            the time context variable ("tomorrow" / "in about an hour") distinguishes them.
            Default: <code style={{ background: ds.light, padding: '1px 5px', borderRadius: 4, fontSize: 11 }}>showroom_visit_reminder</code>
          </p>
        </div>
      </div>

      {/* ── Variable reference ───────────────────────────────────────── */}
      <div style={{
        background: '#F0FFF4',
        border: '1px solid #9AE6B4',
        borderRadius: ds.radius.lg,
        padding: '16px 20px',
        marginBottom: 24,
        fontSize: 12.5,
        color: '#276749',
        lineHeight: 1.8,
      }}>
        <p style={{ fontWeight: 700, margin: '0 0 8px', fontFamily: ds.fontSyne, fontSize: 12 }}>
          📎 Template Variable Reference
        </p>
        <p style={{ margin: '0 0 4px' }}>
          <strong>Confirmation template</strong> variables in order:
        </p>
        <p style={{ margin: '0 0 10px', fontFamily: 'monospace', fontSize: 11.5 }}>
          {'{{name}}'} Lead name &nbsp;·&nbsp; {'{{1}}'} Date &nbsp;·&nbsp; {'{{2}}'} Time &nbsp;·&nbsp;
          {'{{3}}'} Address &nbsp;·&nbsp; {'{{4}}'} Rep name &nbsp;·&nbsp; {'{{5}}'} Brand name
        </p>
        <p style={{ margin: '0 0 4px' }}>
          <strong>Reminder template</strong> variables in order:
        </p>
        <p style={{ margin: 0, fontFamily: 'monospace', fontSize: 11.5 }}>
          {'{{name}}'} Lead name &nbsp;·&nbsp; {'{{1}}'} Time context &nbsp;·&nbsp; {'{{2}}'} Date &nbsp;·&nbsp;
          {'{{3}}'} Time &nbsp;·&nbsp; {'{{4}}'} Address &nbsp;·&nbsp; {'{{5}}'} Rep name &nbsp;·&nbsp; {'{{6}}'} Brand name
        </p>
      </div>

      {/* ── Error / success ──────────────────────────────────────────── */}
      {error && (
        <div style={{
          background: '#FFF5F5', border: `1px solid #FED7D7`,
          borderRadius: ds.radius.md, padding: '10px 14px',
          fontSize: 13, color: ds.red, marginBottom: 16,
        }}>
          ⚠ {error}
        </div>
      )}
      {success && (
        <div style={{
          background: '#F0FFF4', border: `1px solid #9AE6B4`,
          borderRadius: ds.radius.md, padding: '10px 14px',
          fontSize: 13, color: '#276749', marginBottom: 16,
        }}>
          ✓ Demo settings saved.
        </div>
      )}

      {/* ── Save button ──────────────────────────────────────────────── */}
      <button
        onClick={handleSave}
        disabled={loading}
        style={{
          background: loading ? '#9ca3af' : ds.teal,
          color: 'white', border: 'none',
          borderRadius: ds.radius.md,
          padding: '10px 24px',
          fontSize: 13.5, fontWeight: 600,
          fontFamily: ds.fontSyne,
          cursor: loading ? 'not-allowed' : 'pointer',
        }}
      >
        {loading ? 'Saving…' : '✓ Save Settings'}
      </button>

    </div>
  )
}
