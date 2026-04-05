/**
 * SubscriptionDetail.jsx — Full subscription record with payment history
 *
 * Props:
 *   subscriptionId  {string}   — UUID of the subscription to display
 *   user            {object}   — authenticated user (role-aware action gating)
 *   onBack          {function} — () => void; returns to list view
 *   onUpdated       {function} — () => void; called after any mutation that should
 *                                 reset the detail view and refresh the list
 *
 * Actions:
 *   Confirm Payment — opens ConfirmPaymentModal (all roles)
 *   Edit Subscription — inline form for Admin/Owner (PATCH)
 *   Cancel Subscription — Owner only (CancelSubscriptionRequest)
 *
 * SECURITY:
 *   F2 — org_id never in any payload; server derives from JWT.
 *   Backend enforces role guards — frontend buttons are UX-only hints.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getSubscription, updateSubscription, cancelSubscription } from '../../services/renewal.service'
import ConfirmPaymentModal from './ConfirmPaymentModal'

// ─── Constants ────────────────────────────────────────────────────────────────

const PLAN_TIERS      = ['starter', 'basic', 'pro', 'enterprise']
const BILLING_CYCLES  = ['monthly', 'annual']
const CANCELLATION_REASONS = [
  { value: 'too_expensive',        label: 'Too expensive' },
  { value: 'switching_competitor', label: 'Switching to competitor' },
  { value: 'business_closed',      label: 'Business closed' },
  { value: 'missing_features',     label: 'Missing features' },
  { value: 'poor_support',         label: 'Poor support' },
  { value: 'other',                label: 'Other' },
]

const PAYMENT_CHANNEL_LABELS = {
  bank_transfer: 'Bank Transfer', card: 'Card', cash: 'Cash',
  ussd: 'USSD', pos: 'POS', paystack: 'Paystack', flutterwave: 'Flutterwave',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

function fmtAmount(n) {
  if (n == null) return '—'
  return `₦${Number(n).toLocaleString('en-NG', { minimumFractionDigits: 0 })}`
}

function daysLabel(iso) {
  if (!iso) return null
  const d = Math.ceil((new Date(iso) - Date.now()) / 86400000)
  if (d < 0) return { text: `${Math.abs(d)} days overdue`, warn: true }
  if (d === 0) return { text: 'Expires today', warn: true }
  return { text: `${d} days remaining`, warn: d <= 7 }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

const STATUS_MAP = {
  trial:        { bg: ds.teal,  label: 'Trial' },
  active:       { bg: ds.green, label: 'Active' },
  grace_period: { bg: ds.amber, label: 'Grace Period' },
  expired:      { bg: ds.gray,  label: 'Expired' },
  suspended:    { bg: ds.amber, label: 'Suspended' },
  cancelled:    { bg: ds.gray,  label: 'Cancelled' },
}

function StatusBadge({ status, large = false }) {
  const { bg, label } = STATUS_MAP[status] ?? { bg: ds.gray, label: status }
  return (
    <span style={{
      display: 'inline-block', background: bg, color: 'white',
      borderRadius: 20, padding: large ? '6px 16px' : '3px 10px',
      fontSize: large ? 13 : 11, fontWeight: 600,
      textTransform: 'capitalize', whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

const PAYMENT_STATUS_MAP = {
  confirmed:            { color: ds.green,  label: 'Confirmed' },
  pending_confirmation: { color: ds.amber,  label: 'Pending' },
  failed:               { color: '#B91C1C', label: 'Failed' },
}

function PaymentStatusPill({ status }) {
  const { color, label } = PAYMENT_STATUS_MAP[status] ?? { color: ds.gray, label: status }
  return <span style={{ fontSize: 11, fontWeight: 600, color }}>{label}</span>
}

// ─────────────────────────────────────────────────────────────────────────────

export default function SubscriptionDetail({ subscriptionId, user, onBack, onUpdated }) {
  const [detail, setDetail]         = useState(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [showEdit, setShowEdit]     = useState(false)
  const [showCancel, setShowCancel] = useState(false)

  // Role derivation — best-effort from user object; backend enforces either way
  const userRole = user?.role ?? user?.roles?.template ?? ''
  const isOwner  = userRole === 'owner'
  const isAdmin  = ['owner', 'admin', 'ops_manager'].includes(userRole)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getSubscription(subscriptionId)
      if (res.success) setDetail(res.data)
      else setError(res.error ?? 'Failed to load subscription')
    } catch (err) {
      setError(err?.response?.data?.detail ?? 'Failed to load subscription')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId])

  useEffect(() => { load() }, [load])

  // get_subscription returns a flat subscription object with a `payments` array
  // attached by the service: data["payments"] = payments_result.data or []
  const sub     = detail
  const history = detail?.payments ?? []

  const renewalLabel = sub ? daysLabel(sub.current_period_end) : null
  const customerName = sub?.customer?.full_name ?? sub?.customer?.phone ?? '—'

  if (loading) return <LoadingState />
  if (error)   return <ErrorState error={error} onBack={onBack} />

  return (
    <div>
      {/* ── Back + header ──────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <button onClick={onBack} style={backBtn}>← Back</button>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: ds.dark, margin: 0 }}>
              {customerName}
            </h2>
            <StatusBadge status={sub?.status} large />
          </div>
          <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
            Subscription ID: {sub?.id}
          </p>
        </div>
        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={() => setShowConfirm(true)} style={primaryBtn}>
            + Confirm Payment
          </button>
          {isAdmin && (
            <button onClick={() => setShowEdit(true)} style={secondaryBtn}>
              ✏ Edit
            </button>
          )}
          {isOwner && sub?.status !== 'cancelled' && (
            <button onClick={() => setShowCancel(true)} style={dangerBtn}>
              Cancel Subscription
            </button>
          )}
          <button onClick={load} style={secondaryBtn} title="Refresh">↻</button>
        </div>
      </div>

      {/* ── Two-column layout ─────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 20, alignItems: 'start' }}>

        {/* Left — Subscription info */}
        <div style={card}>
          <h3 style={cardTitle}>Subscription Details</h3>

          <InfoRow label="Plan"           value={<PlanChip plan={sub?.plan_tier} />} />
          <InfoRow label="Billing Cycle"  value={sub?.billing_cycle ? `${sub.billing_cycle.charAt(0).toUpperCase()}${sub.billing_cycle.slice(1)}` : '—'} />
          <InfoRow label="Amount"         value={<strong style={{ color: ds.teal }}>{fmtAmount(sub?.amount)}</strong>} />
          <InfoRow label="Period Start"   value={fmtDate(sub?.current_period_start)} />
          <InfoRow label="Period End"     value={
            <span>
              {fmtDate(sub?.current_period_end)}
              {renewalLabel && (
                <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: renewalLabel.warn ? ds.amber : ds.gray }}>
                  ({renewalLabel.text})
                </span>
              )}
            </span>
          } />
          {sub?.suspended_at && (
            <InfoRow label="Suspended At"  value={fmtDate(sub.suspended_at)} />
          )}
          <InfoRow label="Created"        value={fmtDate(sub?.created_at)} />
          {sub?.notes && (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f5f8' }}>
              <p style={{ fontSize: 11, fontWeight: 700, color: '#7a9bad', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: 6 }}>Notes</p>
              <p style={{ fontSize: 13, color: ds.dark, lineHeight: 1.6, margin: 0 }}>{sub.notes}</p>
            </div>
          )}

          {/* Customer info */}
          {sub?.customer && (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f5f8' }}>
              <p style={{ fontSize: 11, fontWeight: 700, color: '#7a9bad', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: 10 }}>Customer</p>
              {sub.customer.full_name && <InfoRow label="Name"  value={sub.customer.full_name} />}
              {sub.customer.phone     && <InfoRow label="Phone" value={sub.customer.phone} />}
              {sub.customer.email     && <InfoRow label="Email" value={sub.customer.email} />}
            </div>
          )}
        </div>

        {/* Right — Payment history */}
        <div style={card}>
          <h3 style={cardTitle}>Payment History ({history.length})</h3>

          {history.length === 0 ? (
            <p style={{ fontSize: 13, color: ds.gray, textAlign: 'center', padding: '24px 0', margin: 0 }}>
              No payment records yet.
            </p>
          ) : (
            <div>
              {/* Payment table header */}
              <div style={payHistHeader}>
                <span style={{ flex: '0 0 90px' }}>Date</span>
                <span style={{ flex: 1 }}>Amount</span>
                <span style={{ flex: 1 }}>Channel</span>
                <span style={{ flex: 1 }}>Reference</span>
                <span style={{ flex: '0 0 80px', textAlign: 'right' }}>Status</span>
              </div>

              <div style={{ maxHeight: 420, overflowY: 'auto' }}>
                {history.map((p, i) => (
                  <div
                    key={p.id ?? i}
                    style={{
                      display: 'flex', alignItems: 'center',
                      padding: '12px 16px',
                      borderBottom: i < history.length - 1 ? '1px solid #f0f5f8' : 'none',
                      background: i % 2 === 0 ? 'white' : '#fafcfd',
                    }}
                  >
                    <span style={{ flex: '0 0 90px', fontSize: 12, color: ds.gray }}>{fmtDate(p.payment_date)}</span>
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: ds.dark }}>{fmtAmount(p.amount)}</span>
                    <span style={{ flex: 1, fontSize: 12, color: ds.gray, textTransform: 'capitalize' }}>
                      {PAYMENT_CHANNEL_LABELS[p.payment_channel] ?? p.payment_channel ?? '—'}
                    </span>
                    <span style={{ flex: 1, fontSize: 11, color: ds.gray, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.reference ?? '—'}
                    </span>
                    <span style={{ flex: '0 0 80px', textAlign: 'right' }}>
                      <PaymentStatusPill status={p.status} />
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Modals ────────────────────────────────────────────────────────── */}
      {showConfirm && (
        <ConfirmPaymentModal
          subscriptionId={subscriptionId}
          onClose={() => setShowConfirm(false)}
          onConfirmed={() => { setShowConfirm(false); load() }}
        />
      )}
      {showEdit && (
        <EditSubscriptionModal
          sub={sub}
          onClose={() => setShowEdit(false)}
          onSaved={() => { setShowEdit(false); load() }}
        />
      )}
      {showCancel && (
        <CancelModal
          subscriptionId={subscriptionId}
          onClose={() => setShowCancel(false)}
          onCancelled={() => { setShowCancel(false); onUpdated() }}
        />
      )}
    </div>
  )
}

// ─── Loading / Error states ───────────────────────────────────────────────────

function LoadingState() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 240 }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ width: 36, height: 36, border: `4px solid rgba(0,140,160,0.2)`, borderTopColor: ds.teal, borderRadius: '50%', animation: 'spin 0.9s linear infinite', margin: '0 auto 12px' }} />
        <p style={{ fontSize: 13, color: ds.gray }}>Loading subscription…</p>
      </div>
    </div>
  )
}

function ErrorState({ error, onBack }) {
  return (
    <div style={{ padding: '32px 0' }}>
      <button onClick={onBack} style={backBtn}>← Back</button>
      <div style={{ marginTop: 24, background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 12, padding: 24, color: '#B91C1C' }}>
        ⚠ {error}
      </div>
    </div>
  )
}

// ─── Edit Subscription Modal (Admin) ─────────────────────────────────────────

function EditSubscriptionModal({ sub, onClose, onSaved }) {
  const [form, setForm] = useState({
    plan_tier:            sub?.plan_tier            ?? '',
    billing_cycle:        sub?.billing_cycle        ?? '',
    amount:               sub?.amount               ?? '',
    current_period_end:   sub?.current_period_end?.slice(0, 10) ?? '',
    notes:                sub?.notes                ?? '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))

  const handleSave = async () => {
    setLoading(true)
    setError(null)
    try {
      const payload = {}
      if (form.plan_tier)           payload.plan_tier           = form.plan_tier
      if (form.billing_cycle)       payload.billing_cycle       = form.billing_cycle
      if (form.amount)              payload.amount              = parseFloat(form.amount)
      if (form.current_period_end)  payload.current_period_end  = form.current_period_end
      if (form.notes.trim())        payload.notes               = form.notes.trim()
      await updateSubscription(sub.id, payload)
      onSaved()
    } catch (err) {
      setError(err?.response?.data?.detail ?? 'Update failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={overlayStyle} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div style={modalStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: 0 }}>Edit Subscription</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 18, color: ds.gray, cursor: 'pointer' }}>✕</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <label style={inlineLabel}>Plan Tier</label>
            <select value={form.plan_tier} onChange={set('plan_tier')} style={inlineInput}>
              <option value="">— unchanged —</option>
              {PLAN_TIERS.map(p => <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label style={inlineLabel}>Billing Cycle</label>
            <select value={form.billing_cycle} onChange={set('billing_cycle')} style={inlineInput}>
              <option value="">— unchanged —</option>
              {BILLING_CYCLES.map(b => <option key={b} value={b}>{b.charAt(0).toUpperCase() + b.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label style={inlineLabel}>Amount (₦)</label>
            <input type="number" min="0" value={form.amount} onChange={set('amount')} style={inlineInput} />
          </div>
          <div>
            <label style={inlineLabel}>Period End</label>
            <input type="date" value={form.current_period_end} onChange={set('current_period_end')} style={inlineInput} />
          </div>
        </div>
        <div style={{ marginBottom: 20 }}>
          <label style={inlineLabel}>Notes</label>
          <textarea value={form.notes} onChange={set('notes')} rows={3} maxLength={5000} style={{ ...inlineInput, resize: 'vertical' }} />
        </div>

        {error && <div style={errBox}>⚠ {error}</div>}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={loading} style={cancelStyle}>Cancel</button>
          <button onClick={handleSave} disabled={loading} style={{ ...saveStyle, opacity: loading ? 0.7 : 1 }}>
            {loading ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Cancel Subscription Modal (Owner only) ───────────────────────────────────

function CancelModal({ subscriptionId, onClose, onCancelled }) {
  const [reason, setReason] = useState('')
  const [notes, setNotes]   = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const handleCancel = async () => {
    if (!reason) { setError('Please select a cancellation reason.'); return }
    setLoading(true)
    setError(null)
    try {
      const payload = { reason }
      if (notes.trim()) payload.notes = notes.trim()
      await cancelSubscription(subscriptionId, payload)
      onCancelled()
    } catch (err) {
      setError(err?.response?.data?.detail ?? 'Cancellation failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={overlayStyle} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{ ...modalStyle, maxWidth: 440 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#B91C1C', margin: '0 0 8px' }}>
          Cancel Subscription
        </h2>
        <p style={{ fontSize: 13, color: ds.gray, marginBottom: 20 }}>
          This will mark the subscription as cancelled. This action cannot be undone.
        </p>

        <div style={{ marginBottom: 16 }}>
          <label style={inlineLabel}>Cancellation Reason *</label>
          <select value={reason} onChange={e => setReason(e.target.value)} style={inlineInput}>
            <option value="">— Select reason —</option>
            {CANCELLATION_REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
        <div style={{ marginBottom: 20 }}>
          <label style={inlineLabel}>Notes (optional)</label>
          <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3} maxLength={5000} style={{ ...inlineInput, resize: 'vertical' }} placeholder="Additional context…" />
        </div>

        {error && <div style={errBox}>⚠ {error}</div>}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={loading} style={cancelStyle}>Go Back</button>
          <button onClick={handleCancel} disabled={loading} style={{ background: '#DC2626', color: 'white', border: 'none', borderRadius: 9, padding: '10px 22px', fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne, opacity: loading ? 0.7 : 1 }}>
            {loading ? 'Cancelling…' : 'Confirm Cancellation'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Info row ─────────────────────────────────────────────────────────────────

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
      <span style={{ fontSize: 12, color: '#7a9bad', fontWeight: 500, minWidth: 110, textAlign: 'right', paddingTop: 1 }}>
        {label}
      </span>
      <span style={{ fontSize: 13, color: ds.dark, flex: 1 }}>{value}</span>
    </div>
  )
}

function PlanChip({ plan }) {
  const colors = { enterprise: ds.tealDark, pro: ds.teal, basic: '#4B7A8A', starter: ds.gray }
  return (
    <span style={{ background: colors[plan] ?? ds.gray, color: 'white', borderRadius: 6, padding: '2px 10px', fontSize: 12, fontWeight: 600, textTransform: 'capitalize' }}>
      {plan ?? '—'}
    </span>
  )
}

// ─── Shared modal styles ──────────────────────────────────────────────────────

const overlayStyle = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  zIndex: ds.z?.modal ?? 1000, padding: 24,
}

const modalStyle = {
  background: 'white', borderRadius: 16, padding: '28px 32px',
  width: '100%', maxWidth: 580,
  boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
  fontFamily: ds.fontDm,
}

const inlineLabel = {
  display: 'block', fontSize: 12, fontWeight: 500,
  color: '#5a7080', textTransform: 'uppercase',
  letterSpacing: '0.7px', marginBottom: 6,
}

const inlineInput = {
  width: '100%', border: '1.5px solid #d1dde4', borderRadius: 9,
  padding: '10px 14px', fontSize: 13, fontFamily: ds.fontDm,
  color: ds.dark, background: 'white', outline: 'none',
  boxSizing: 'border-box',
}

const errBox = {
  background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 8,
  padding: '10px 14px', fontSize: 13, color: '#B91C1C', marginBottom: 16,
}

const cancelStyle = {
  background: 'white', border: '1.5px solid #d1dde4', borderRadius: 9,
  padding: '10px 20px', fontSize: 14, fontWeight: 500, color: ds.gray,
  cursor: 'pointer', fontFamily: ds.fontDm,
}

const saveStyle = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 9,
  padding: '10px 22px', fontSize: 14, fontWeight: 600,
  cursor: 'pointer', fontFamily: ds.fontSyne,
}

// ─── Page-level styles ────────────────────────────────────────────────────────

const card = {
  background: 'white', borderRadius: 12,
  border: '1px solid #e2ecf0', padding: '24px',
  boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
}

const cardTitle = {
  fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15,
  color: ds.dark, margin: '0 0 20px',
  paddingBottom: 12, borderBottom: '1px solid #f0f5f8',
}

const payHistHeader = {
  display: 'flex', alignItems: 'center',
  padding: '10px 16px',
  background: '#f7fbfc', borderBottom: '1px solid #e2ecf0',
  fontSize: 10, fontWeight: 700, color: '#7a9bad',
  textTransform: 'uppercase', letterSpacing: '0.8px',
  borderRadius: '4px 4px 0 0',
}

const backBtn = {
  background: 'white', border: '1.5px solid #d1dde4',
  borderRadius: 8, padding: '8px 16px',
  fontSize: 13, color: ds.gray, cursor: 'pointer',
  fontFamily: ds.fontDm, flexShrink: 0,
}

const primaryBtn = {
  background: ds.teal, color: 'white', border: 'none',
  borderRadius: 9, padding: '9px 18px',
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
  fontFamily: ds.fontSyne, whiteSpace: 'nowrap',
}

const secondaryBtn = {
  background: 'white', border: '1.5px solid #d1dde4',
  borderRadius: 9, padding: '9px 16px',
  fontSize: 13, color: ds.gray, cursor: 'pointer',
  fontFamily: ds.fontDm, whiteSpace: 'nowrap',
}

const dangerBtn = {
  background: 'white', border: '1.5px solid #FECACA',
  borderRadius: 9, padding: '9px 16px',
  fontSize: 13, color: '#B91C1C', cursor: 'pointer',
  fontFamily: ds.fontDm, whiteSpace: 'nowrap',
}
