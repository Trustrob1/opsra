/**
 * DemoQueue.jsx — M01-7a Admin Demo Queue
 *
 * Full-page view showing all pending_assignment demos across the entire org.
 * Accessible only to owner / admin / ops_manager (enforced backend + frontend).
 *
 * Workflow (distinct, as per spec):
 *   1. Admin sees a table of all pending demos with lead details
 *   2. Clicking "Confirm Demo" opens ConfirmDemoModal (from DemoScheduler)
 *   3. Admin fills in: exact date/time, medium, assigned rep, duration, notes
 *   4. On submit: WA auto-sent to lead, rep notified in-app, row disappears
 *
 * API:
 *   GET  /api/v1/leads/demos/pending         — getPendingDemos()
 *   POST /api/v1/leads/{id}/demos/{id}/confirm — confirmDemo() (from leads.service)
 *
 * Pattern 13: no react-router — view state passed via props.
 * Pattern 12: org_id never in payload.
 * Pattern 51: full file, no sed edits.
 */
import { useState, useEffect, useCallback } from 'react'
import { getPendingDemos, confirmDemo } from '../../services/leads.service'
import { ds } from '../../utils/ds'
import UserSelect from '../../shared/UserSelect'

const MEDIUM_LABELS = {
  virtual:   '💻 Virtual',
  in_person: '🤝 In Person',
}

const fmtDate = (iso) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const fmtRelative = (iso) => {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1)  return 'Just now'
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DemoQueue({ onBack, onOpenLead }) {
  const [demos, setDemos]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [confirmModal, setConfirmModal] = useState(null) // { demo } | null

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getPendingDemos()
      if (res.success) setDemos(res.data || [])
      else setError(res.error?.message ?? 'Failed to load demo queue')
    } catch (e) {
      setError(e?.response?.data?.error?.message ?? 'Failed to load demo queue')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleConfirmed = (demoId) => {
    // Remove confirmed demo from queue immediately
    setDemos(prev => prev.filter(d => d.id !== demoId))
    setConfirmModal(null)
  }

  const S = {
    page: { padding: 28, minHeight: 'calc(100vh - 60px)' },
    header: {
      display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24,
    },
    backBtn: {
      background: 'white', border: `1.5px solid ${ds.border}`,
      borderRadius: ds.radius.md, padding: '8px 14px',
      fontSize: 13, color: ds.gray, cursor: 'pointer',
      fontFamily: ds.fontDm, display: 'flex', alignItems: 'center', gap: 6,
    },
    badge: {
      width: 44, height: 44, background: ds.teal, borderRadius: 11,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 15, color: 'white',
      flexShrink: 0,
    },
    countPill: {
      background: demos.length > 0 ? '#FEF3C7' : ds.mint,
      color:      demos.length > 0 ? '#92400E' : ds.tealDark,
      border:     `1px solid ${demos.length > 0 ? '#FCD34D' : '#9AE6B4'}`,
      borderRadius: 20, padding: '4px 12px',
      fontSize: 12, fontWeight: 700, fontFamily: ds.fontSyne,
    },
    tableWrap: {
      background: 'white', border: `1px solid ${ds.border}`,
      borderRadius: 14, overflow: 'hidden',
      boxShadow: '0 2px 12px rgba(2,128,144,0.05)',
    },
    th: {
      background: '#E0F4F6', color: '#015F6B', fontWeight: 600,
      padding: '11px 16px', textAlign: 'left',
      fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.6px',
      whiteSpace: 'nowrap',
    },
    td: {
      padding: '13px 16px', borderBottom: `1px solid ${ds.border}`,
      color: ds.dark, verticalAlign: 'middle', fontSize: 13,
    },
    emptyCell: {
      padding: 56, textAlign: 'center', color: ds.gray, fontSize: 14,
    },
    confirmBtn: {
      background: ds.teal, color: 'white', border: 'none',
      borderRadius: ds.radius.md, padding: '7px 16px',
      fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne,
      cursor: 'pointer', whiteSpace: 'nowrap',
    },
    viewLeadBtn: {
      background: 'white', color: ds.teal,
      border: `1.5px solid ${ds.teal}`,
      borderRadius: ds.radius.md, padding: '6px 12px',
      fontSize: 12, fontWeight: 600, fontFamily: ds.fontSyne,
      cursor: 'pointer', whiteSpace: 'nowrap',
    },
  }

  return (
    <div style={S.page}>

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div style={S.header}>
        <button style={S.backBtn} onClick={onBack}>
          ← Back
        </button>
        <div style={S.badge}>📅</div>
        <div>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: 0 }}>
            Demo Queue
          </h1>
          <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
            Pending demos awaiting your confirmation
          </p>
        </div>
        {!loading && (
          <span style={S.countPill}>
            {demos.length === 0 ? '✓ All clear' : `${demos.length} pending`}
          </span>
        )}
      </div>

      {/* ── Error ───────────────────────────────────────────────────── */}
      {error && (
        <div style={{
          background: '#FFF5F5', border: `1px solid #FED7D7`,
          borderRadius: ds.radius.md, padding: '10px 14px',
          fontSize: 13, color: ds.red, marginBottom: 16,
        }}>
          ⚠ {error}
        </div>
      )}

      {/* ── Table ───────────────────────────────────────────────────── */}
      <div style={S.tableWrap}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['Lead', 'Phone', 'Preferred Time', 'Medium', 'Requested', 'Actions'].map(h => (
                <th key={h} style={S.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={S.emptyCell}>
                  <span style={{ color: ds.teal }}>Loading demo queue…</span>
                </td>
              </tr>
            ) : demos.length === 0 ? (
              <tr>
                <td colSpan={6} style={S.emptyCell}>
                  <div>
                    <p style={{ fontSize: 32, margin: '0 0 8px' }}>✅</p>
                    <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, color: ds.dark, fontSize: 15, margin: '0 0 4px' }}>
                      All caught up
                    </p>
                    <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
                      No demos are currently pending confirmation.
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              demos.map(demo => (
                <tr
                  key={demo.id}
                  onMouseEnter={e => e.currentTarget.style.background = '#F5FAFB'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}
                >
                  {/* Lead name */}
                  <td style={S.td}>
                    <div style={{ fontWeight: 600, color: ds.dark }}>{demo.lead_full_name}</div>
                  </td>

                  {/* Phone */}
                  <td style={S.td}>
                    <span style={{ color: ds.gray, fontFamily: ds.fontDm }}>
                      {demo.lead_phone || '—'}
                    </span>
                  </td>

                  {/* Preferred time */}
                  <td style={S.td}>
                    {demo.lead_preferred_time ? (
                      <span style={{
                        background: '#FFFBEB', color: '#92400E',
                        border: '1px solid #FCD34D',
                        borderRadius: 8, padding: '3px 8px',
                        fontSize: 12, fontWeight: 500,
                      }}>
                        {demo.lead_preferred_time}
                      </span>
                    ) : (
                      <span style={{ color: ds.border, fontStyle: 'italic', fontSize: 12 }}>
                        Not specified
                      </span>
                    )}
                  </td>

                  {/* Medium */}
                  <td style={S.td}>
                    <span style={{ fontSize: 12.5, color: ds.gray }}>
                      {demo.medium ? (MEDIUM_LABELS[demo.medium] ?? demo.medium) : '—'}
                    </span>
                  </td>

                  {/* Requested ago */}
                  <td style={S.td}>
                    <span style={{ fontSize: 12, color: ds.gray }}>
                      {fmtRelative(demo.created_at)}
                    </span>
                    <div style={{ fontSize: 11, color: ds.border, marginTop: 2 }}>
                      {fmtDate(demo.created_at)}
                    </div>
                  </td>

                  {/* Actions */}
                  <td style={{ ...S.td, borderBottom: `1px solid ${ds.border}` }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <button
                        style={S.confirmBtn}
                        onClick={() => setConfirmModal(demo)}
                      >
                        ✓ Confirm Demo
                      </button>
                      {onOpenLead && (
                        <button
                          style={S.viewLeadBtn}
                          onClick={() => onOpenLead(demo.lead_id)}
                        >
                          View Lead
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ── Confirm Demo Modal ───────────────────────────────────────── */}
      {confirmModal && (
        <ConfirmDemoModal
          demo={confirmModal}
          onConfirmed={() => handleConfirmed(confirmModal.id)}
          onClose={() => setConfirmModal(null)}
        />
      )}
    </div>
  )
}

// ── Confirm Demo Modal ────────────────────────────────────────────────────────
// Distinct confirmation workflow — admin must fill all fields before committing.
// Mirrors ConfirmDemoModal in DemoScheduler.jsx but takes leadId from demo.lead_id.

function ConfirmDemoModal({ demo, onConfirmed, onClose }) {
  const [scheduledAt, setScheduledAt] = useState('')
  const [medium, setMedium]           = useState(demo.medium || '')
  const [assignedTo, setAssignedTo]   = useState(demo.lead_assigned_to || '')
  const [duration, setDuration]       = useState(30)
  const [notes, setNotes]             = useState(demo.notes || '')
  const [saving, setSaving]           = useState(false)
  const [formError, setFormError]     = useState(null)

  const handleSubmit = async () => {
    if (!scheduledAt) { setFormError('Please select a date and time.'); return }
    if (!medium)      { setFormError('Please select a medium.'); return }
    if (!assignedTo)  { setFormError('Please assign a rep.'); return }
    setFormError(null)
    setSaving(true)
    try {
      const isoScheduled = new Date(scheduledAt).toISOString()
      const res = await confirmDemo(demo.lead_id, demo.id, {
        scheduled_at:     isoScheduled,
        medium,
        assigned_to:      assignedTo,
        duration_minutes: duration,
        notes:            notes || undefined,
      })
      if (res.success) onConfirmed(res.data)
      else setFormError(res.error?.message ?? 'Failed to confirm demo')
    } catch (e) {
      setFormError(e?.response?.data?.error?.message ?? 'Failed to confirm demo')
    } finally {
      setSaving(false)
    }
  }

  const labelStyle = {
    display: 'block', fontSize: 11, fontWeight: 600, color: ds.gray,
    textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 5,
  }
  const inputStyle = {
    width: '100%', padding: '9px 12px',
    border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
    fontSize: 13.5, color: ds.dark, fontFamily: 'inherit',
    background: 'white', outline: 'none', marginBottom: 12,
    boxSizing: 'border-box',
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100 }}
      />
      {/* Modal */}
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        background: 'white', borderRadius: ds.radius.xl,
        padding: '28px 28px 24px',
        width: 'min(480px, 94vw)', zIndex: 101,
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
        maxHeight: '90vh', overflowY: 'auto',
      }}>
        <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark, margin: '0 0 4px' }}>
          ✓ Confirm Demo
        </h3>
        <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 20px' }}>
          For <strong style={{ color: ds.dark }}>{demo.lead_full_name}</strong>
        </p>

        {/* Lead's preference — shown if set */}
        {demo.lead_preferred_time && (
          <div style={{
            background: '#FFFBEB', border: '1px solid #F6E05E',
            borderRadius: 8, padding: '10px 12px', marginBottom: 16, fontSize: 13,
          }}>
            <strong>Lead's preference:</strong> {demo.lead_preferred_time}
          </div>
        )}

        {formError && (
          <p style={{ color: ds.red, fontSize: 13, marginBottom: 10 }}>⚠ {formError}</p>
        )}

        <label style={labelStyle}>Date & Time *</label>
        <input
          type="datetime-local"
          value={scheduledAt}
          onChange={e => setScheduledAt(e.target.value)}
          style={inputStyle}
        />

        <label style={labelStyle}>Medium *</label>
        <select value={medium} onChange={e => setMedium(e.target.value)} style={inputStyle}>
          <option value="">— Select —</option>
          <option value="virtual">💻 Virtual (Online)</option>
          <option value="in_person">🤝 In Person</option>
        </select>

        <label style={labelStyle}>Assign Rep *</label>
        <div style={{ marginBottom: 12 }}>
          <UserSelect value={assignedTo} onChange={setAssignedTo} placeholder="— Select rep —" />
        </div>

        <label style={labelStyle}>Duration</label>
        <select value={duration} onChange={e => setDuration(Number(e.target.value))} style={inputStyle}>
          {[15, 30, 45, 60, 90, 120].map(m => (
            <option key={m} value={m}>{m} minutes</option>
          ))}
        </select>

        <label style={labelStyle}>Notes (optional)</label>
        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder="Agenda, topics to cover…"
          maxLength={5000} rows={2}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: ds.fontDm }}
        />

        <p style={{ fontSize: 12, color: '#276749', margin: '0 0 16px', lineHeight: 1.5 }}>
          ℹ️ A WhatsApp confirmation will be sent to the lead. The rep will receive an in-app notification only.
        </p>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={handleSubmit}
            disabled={saving}
            style={{
              background: saving ? '#9ca3af' : ds.teal,
              color: 'white', border: 'none',
              borderRadius: ds.radius.md, padding: '9px 18px',
              fontSize: 13, fontWeight: 600, fontFamily: ds.fontSyne,
              cursor: saving ? 'not-allowed' : 'pointer', flex: 1,
            }}
          >
            {saving ? 'Confirming…' : '✓ Confirm & Notify Lead'}
          </button>
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              background: 'white', color: ds.gray,
              border: `1.5px solid ${ds.border}`,
              borderRadius: ds.radius.md, padding: '9px 18px',
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    </>
  )
}
