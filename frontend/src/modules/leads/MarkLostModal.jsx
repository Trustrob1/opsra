/**
 * MarkLostModal
 *
 * Calls POST /api/v1/leads/{id}/mark-lost
 * Payload: { lost_reason: LostReason (required), reengagement_date?: date }
 *
 * Lost reasons (from models/leads.py LostReason enum):
 *   not_ready | price | competitor | wrong_size | wrong_contact | other
 *
 * reengagement_date is shown only when lost_reason === 'not_ready'
 * (DRD §5: "Re-engagement queue — leads marked Not Ready auto-return to active
 *  pipeline at set future date, configurable by the rep at the time of marking")
 */
import { useState } from 'react'
import { markLost } from '../../services/leads.service'
import { ds, LOST_REASON_LABELS } from '../../utils/ds'

const LOST_REASONS = Object.entries(LOST_REASON_LABELS)

export default function MarkLostModal({ leadId, leadName, defaultReason = '', onClose, onMarked }) {
  const [reason, setReason]         = useState(defaultReason)
  const [reengageDate, setReengageDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState(null)

  const isNotReady = reason === 'not_ready'

  const handleSubmit = async () => {
    if (!reason) { setError('Please select a reason.'); return }
    setSubmitting(true)
    setError(null)
    try {
      const payload = { lost_reason: reason }
      if (isNotReady && reengageDate) payload.reengagement_date = reengageDate
      const res = await markLost(leadId, payload)
      if (res.success) {
        onMarked?.(res.data)
        onClose()
      } else {
        setError(res.error ?? 'Could not mark lead as lost')
      }
    } catch (err) {
      setError(err?.response?.data?.error ?? 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalOverlay onClose={onClose}>
      {/* Header */}
      <div style={{ padding: '20px 24px', borderBottom: `1px solid ${ds.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: 0 }}>
            Mark as Lost
          </h2>
          {leadName && (
            <p style={{ fontSize: 13, color: ds.gray, margin: '2px 0 0' }}>{leadName}</p>
          )}
        </div>
        <button onClick={onClose} style={closeBtn}>✕</button>
      </div>

      {/* Body */}
      <div style={{ padding: '24px' }}>
        {/* Lost reason */}
        <div style={{ marginBottom: 18 }}>
          <label style={labelStyle}>
            Lost Reason <span style={{ color: ds.red }}>*</span>
          </label>
          <select
            value={reason}
            onChange={(e) => { setReason(e.target.value); setError(null) }}
            style={inputStyle}
          >
            <option value="">— Select a reason —</option>
            {LOST_REASONS.map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </div>

        {/* Re-engagement date — only shown when not_ready */}
        {isNotReady && (
          <div style={{ marginBottom: 18 }}>
            <label style={labelStyle}>
              Re-engagement Date <span style={{ color: ds.gray, fontWeight: 400 }}>(optional)</span>
            </label>
            <p style={{ fontSize: 12, color: ds.gray, marginBottom: 6, lineHeight: 1.5 }}>
              This lead will automatically return to the active pipeline on this date.
            </p>
            <input
              type="date"
              value={reengageDate}
              onChange={(e) => setReengageDate(e.target.value)}
              min={today()}
              style={inputStyle}
            />
          </div>
        )}

        {/* Error */}
        {error && (
          <p style={{ color: ds.red, fontSize: 13, marginBottom: 14 }}>⚠ {error}</p>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={submitting} style={secondaryBtn}>
            Cancel
          </button>
          <button onClick={handleSubmit} disabled={submitting || !reason} style={{
            ...primaryBtn,
            background: ds.red,
            opacity:    (!reason || submitting) ? 0.5 : 1,
          }}>
            {submitting ? 'Saving…' : 'Mark as Lost'}
          </button>
        </div>
      </div>
    </ModalOverlay>
  )
}

// ─── Shared helpers ───────────────────────────────────────────────────────────

function ModalOverlay({ children, onClose }) {
  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        position:        'fixed',
        inset:           0,
        background:      'rgba(0,0,0,0.45)',
        zIndex:          ds.z.modal,
        display:         'flex',
        alignItems:      'center',
        justifyContent:  'center',
        padding:         16,
      }}
    >
      <div style={{
        background:   'white',
        borderRadius: ds.radius.xxl,
        width:        480,
        maxWidth:     '100%',
        maxHeight:    '88vh',
        overflowY:    'auto',
        boxShadow:    ds.modalShadow,
      }}>
        {children}
      </div>
    </div>
  )
}

const today = () => new Date().toISOString().split('T')[0]

const labelStyle = {
  display:       'block',
  fontSize:      12,
  fontWeight:    500,
  color:         ds.gray,
  textTransform: 'uppercase',
  letterSpacing: '0.6px',
  marginBottom:  6,
}

const inputStyle = {
  width:        '100%',
  border:       `1.5px solid ${ds.border}`,
  borderRadius: ds.radius.md,
  padding:      '11px 14px',
  fontSize:     13.5,
  color:        ds.dark,
  fontFamily:   ds.fontDm,
  background:   'white',
  outline:      'none',
  boxSizing:    'border-box',
}

const closeBtn = {
  background: 'none',
  border:     'none',
  fontSize:   20,
  color:      ds.gray,
  cursor:     'pointer',
  padding:    '4px 8px',
}

const primaryBtn = {
  display:      'inline-flex',
  alignItems:   'center',
  gap:          8,
  padding:      '11px 22px',
  borderRadius: ds.radius.md,
  border:       'none',
  background:   ds.teal,
  color:        'white',
  fontSize:     13.5,
  fontWeight:   600,
  fontFamily:   ds.fontSyne,
  cursor:       'pointer',
}

const secondaryBtn = {
  ...primaryBtn,
  background: ds.mint,
  color:      ds.tealDark,
  border:     `1px solid ${ds.border}`,
}
