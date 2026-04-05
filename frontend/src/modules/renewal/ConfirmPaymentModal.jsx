/**
 * ConfirmPaymentModal.jsx — Manual payment confirmation (Method 2)
 *
 * Fields map directly to the backend's ConfirmPaymentRequest model.
 * Backend enforces duplicate-reference check per DRD §6.4.
 *
 * SECURITY:
 *   F2 — org_id never in payload; derived server-side from JWT.
 */
import { useState } from 'react'
import { ds } from '../../utils/ds'
import { confirmPayment } from '../../services/renewal.service'

const PAYMENT_CHANNELS = [
  { value: 'bank_transfer', label: 'Bank Transfer' },
  { value: 'card',          label: 'Card' },
  { value: 'cash',          label: 'Cash' },
  { value: 'ussd',          label: 'USSD' },
  { value: 'pos',           label: 'POS Terminal' },
  { value: 'paystack',      label: 'Paystack' },
  { value: 'flutterwave',   label: 'Flutterwave' },
]

const today = () => new Date().toISOString().slice(0, 10)

// ─────────────────────────────────────────────────────────────────────────────

export default function ConfirmPaymentModal({ subscriptionId, onClose, onConfirmed }) {
  const [form, setForm] = useState({
    amount_paid:       '',
    payment_channel:   '',
    payment_reference: '',
    payment_date:      today(),
    notes:             '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))

  const handleSubmit = async () => {
    if (!form.amount_paid || !form.payment_channel || !form.payment_date) {
      setError('Amount, payment channel, and payment date are required.')
      return
    }
    const amount = parseFloat(form.amount_paid)
    if (isNaN(amount) || amount <= 0) {
      setError('Amount must be a positive number.')
      return
    }

    setLoading(true)
    setError(null)
    try {
      const payload = {
        amount:          amount,
        payment_channel: form.payment_channel,
        payment_date:    form.payment_date,
      }
      if (form.payment_reference.trim()) payload.reference = form.payment_reference.trim()
      if (form.notes.trim())             payload.notes     = form.notes.trim()

      await confirmPayment(subscriptionId, payload)
      onConfirmed()
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Payment confirmation failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={overlay} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div style={modal}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: 0 }}>
              Confirm Payment
            </h2>
            <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
              Manual payment confirmation — all fields validated server-side
            </p>
          </div>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        {/* Amount & Channel row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Amount Paid (₦) *</label>
            <input
              type="number"
              min="0"
              step="0.01"
              placeholder="e.g. 15000"
              value={form.amount_paid}
              onChange={set('amount_paid')}
              style={inputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Payment Channel *</label>
            <select value={form.payment_channel} onChange={set('payment_channel')} style={inputStyle}>
              <option value="">— Select channel —</option>
              {PAYMENT_CHANNELS.map(c => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Date & Reference row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Payment Date *</label>
            <input
              type="date"
              value={form.payment_date}
              onChange={set('payment_date')}
              style={inputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Payment Reference <span style={{ color: ds.gray }}>(optional)</span></label>
            <input
              type="text"
              placeholder="e.g. TRF-20240315-001"
              value={form.payment_reference}
              onChange={set('payment_reference')}
              maxLength={255}
              style={inputStyle}
            />
          </div>
        </div>

        {/* Notes */}
        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>Notes <span style={{ color: ds.gray }}>(optional)</span></label>
          <textarea
            placeholder="Any additional notes about this payment..."
            value={form.notes}
            onChange={set('notes')}
            maxLength={5000}
            rows={3}
            style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.5 }}
          />
          <p style={{ fontSize: 11, color: ds.gray, marginTop: 4, textAlign: 'right' }}>
            {form.notes.length}/5000
          </p>
        </div>

        {/* Error */}
        {error && (
          <div style={errorBox}>⚠ {error}</div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={loading} style={cancelBtn}>Cancel</button>
          <button onClick={handleSubmit} disabled={loading} style={{ ...submitBtn, opacity: loading ? 0.7 : 1 }}>
            {loading ? 'Confirming…' : '✓ Confirm Payment'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const overlay = {
  position: 'fixed', inset: 0,
  background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  zIndex: ds.z?.modal ?? 1000,
  padding: 24,
}

const modal = {
  background: 'white',
  borderRadius: 16,
  padding: '28px 32px',
  width: '100%',
  maxWidth: 540,
  boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
  fontFamily: ds.fontDm,
}

const closeBtn = {
  background: 'none', border: 'none', fontSize: 18,
  color: ds.gray, cursor: 'pointer', padding: 4, lineHeight: 1,
}

const labelStyle = {
  display: 'block', fontSize: 12, fontWeight: 500,
  color: '#5a7080', textTransform: 'uppercase',
  letterSpacing: '0.7px', marginBottom: 6,
}

const inputStyle = {
  width: '100%',
  border: '1.5px solid #d1dde4',
  borderRadius: 9,
  padding: '11px 14px',
  fontSize: 14,
  fontFamily: ds.fontDm,
  color: ds.dark,
  background: 'white',
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.2s',
}

const errorBox = {
  background: '#FEF2F2',
  border: '1px solid #FECACA',
  borderRadius: 8,
  padding: '10px 14px',
  fontSize: 13,
  color: '#B91C1C',
  marginBottom: 16,
}

const cancelBtn = {
  background: 'white', border: '1.5px solid #d1dde4',
  borderRadius: 9, padding: '10px 20px',
  fontSize: 14, fontWeight: 500,
  color: ds.gray, cursor: 'pointer',
  fontFamily: ds.fontDm,
}

const submitBtn = {
  background: ds.teal, color: 'white',
  border: 'none', borderRadius: 9,
  padding: '10px 22px', fontSize: 14,
  fontWeight: 600, cursor: 'pointer',
  fontFamily: ds.fontSyne,
  transition: 'opacity 0.2s',
}
