/**
 * frontend/src/modules/admin/RoutingRules.jsx
 * Routing Rules — Phase 8B
 *
 * Table of all routing rules for the org.
 * + New Rule → modal (event_type, channel, route_to_role_id, escalation)
 * Edit per row → same modal pre-filled
 * Delete per row → inline confirm
 *
 * Uses individual CRUD routes (POST/PATCH/DELETE) added in Phase 8A.
 * The existing full-replace PUT is not used here — individual operations
 * give better UX and avoid accidental data loss.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

// Common event types based on system notifications and workers.
const EVENT_TYPES = [
  'new_hot_lead',
  'new_lead',
  'lead_aging',
  'churn_alert',
  'sla_breach',
  'ticket_created',
  'new_whatsapp_message',
  'subscription_expiring',
  'nps_response',
  'other',
]

const CHANNELS = ['whatsapp_inapp', 'whatsapp_only', 'email', 'inapp_only']

const OVERLAY = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
}
const MODAL = {
  background: 'white', borderRadius: 14, padding: '28px 32px',
  width: 480, maxHeight: '85vh', overflowY: 'auto',
  boxShadow: '0 24px 60px rgba(0,0,0,0.25)',
}
const LABEL = {
  display: 'block', fontSize: 11, fontWeight: 600, color: '#4a7a8a',
  textTransform: 'uppercase', letterSpacing: '0.7px', marginTop: 16, marginBottom: 6,
}
const INPUT = {
  width: '100%', padding: '9px 12px', border: '1px solid #D4E6EC',
  borderRadius: 8, fontSize: 13.5, fontFamily: 'inherit',
  color: '#0a1a24', background: 'white', boxSizing: 'border-box',
}
const GHOST = {
  background: 'white', border: '1px solid #CBD5E1', borderRadius: 6,
  padding: '5px 10px', fontSize: 12, fontWeight: 500, color: '#4a7a8a',
  cursor: 'pointer', fontFamily: 'inherit',
}

export default function RoutingRules() {
  const [rules, setRules]           = useState([])
  const [roles, setRoles]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editingRule, setEditingRule] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)  // rule id

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [r, ro] = await Promise.all([adminSvc.listRoutingRules(), adminSvc.listRoles()])
      setRules(r  ?? [])
      setRoles(ro ?? [])
    } catch {
      setError('Failed to load routing rules.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (ruleId) => {
    try {
      await adminSvc.deleteRoutingRule(ruleId)
      setConfirmDelete(null)
      load()
    } catch {
      setError('Delete failed.')
    }
  }

  const roleName = (id) => roles.find(r => r.id === id)?.name ?? id ?? '—'

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading routing rules…</div>
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}>⚠ {error}</div>

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Routing Rules</h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>
            Controls which role or user is notified for each system event
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '9px 18px', fontSize: 13.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer' }}
        >
          + New Rule
        </button>
      </div>

      {/* Table */}
      <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#F5F9FA' }}>
              {['Event Type', 'Route To', 'Channel', 'Also Notify', 'Escalation', 'Actions'].map(h => (
                <th key={h} style={{ padding: '11px 14px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rules.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
                  No routing rules configured. Add one to control event notifications.
                </td>
              </tr>
            ) : rules.map((rule, i) => (
              <tr key={rule.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none' }}>
                <td style={{ padding: '12px 14px' }}>
                  <code style={{ fontSize: 12, background: '#F1F5F9', borderRadius: 5, padding: '2px 7px', color: '#0a1a24' }}>
                    {rule.event_type}
                  </code>
                </td>
                <td style={{ padding: '12px 14px', fontSize: 13, color: '#0a1a24' }}>
                  {rule.route_to_role_id
                    ? <span>Role: <strong>{roleName(rule.route_to_role_id)}</strong></span>
                    : rule.route_to_user_id
                    ? <span>User: <em>{rule.route_to_user_id.slice(0, 8)}…</em></span>
                    : <span style={{ color: '#7A9BAD' }}>—</span>}
                </td>
                <td style={{ padding: '12px 14px' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, background: '#EEF8FA', color: ds.teal, borderRadius: 6, padding: '3px 8px' }}>
                    {rule.channel ?? 'whatsapp_inapp'}
                  </span>
                </td>
                <td style={{ padding: '12px 14px', fontSize: 12, color: '#7A9BAD' }}>
                  {rule.also_notify_role_id ? roleName(rule.also_notify_role_id) : '—'}
                </td>
                <td style={{ padding: '12px 14px', fontSize: 12, color: '#7A9BAD' }}>
                  {rule.escalate_after_minutes
                    ? `${rule.escalate_after_minutes} min → ${roleName(rule.escalate_to_role_id)}`
                    : '—'}
                </td>
                <td style={{ padding: '12px 14px' }}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button onClick={() => setEditingRule(rule)} style={GHOST}>✏ Edit</button>
                    {confirmDelete !== rule.id ? (
                      <button onClick={() => setConfirmDelete(rule.id)} style={{ ...GHOST, color: '#DC2626', borderColor: '#FECACA' }}>✕</button>
                    ) : (
                      <>
                        <button onClick={() => handleDelete(rule.id)} style={{ ...GHOST, background: '#DC2626', color: 'white', borderColor: '#DC2626' }}>Delete</button>
                        <button onClick={() => setConfirmDelete(null)} style={GHOST}>Cancel</button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modals */}
      {showCreate && (
        <RuleModal
          mode="create"
          roles={roles}
          onSave={async (data) => { await adminSvc.createRoutingRule(data); setShowCreate(false); load() }}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editingRule && (
        <RuleModal
          mode="edit"
          rule={editingRule}
          roles={roles}
          onSave={async (data) => { await adminSvc.updateRoutingRule(editingRule.id, data); setEditingRule(null); load() }}
          onClose={() => setEditingRule(null)}
        />
      )}
    </div>
  )
}


// ── Rule modal ────────────────────────────────────────────────────────────────

function RuleModal({ mode, rule, roles, onSave, onClose }) {
  const isCreate = mode === 'create'
  const [form, setForm] = useState({
    event_type:             rule?.event_type             ?? EVENT_TYPES[0],
    channel:                rule?.channel                ?? 'whatsapp_inapp',
    route_to_role_id:       rule?.route_to_role_id       ?? '',
    route_to_user_id:       rule?.route_to_user_id       ?? '',
    also_notify_role_id:    rule?.also_notify_role_id    ?? '',
    within_hours_only:      rule?.within_hours_only      ?? true,
    escalate_after_minutes: rule?.escalate_after_minutes ?? '',
    escalate_to_role_id:    rule?.escalate_to_role_id    ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr]       = useState(null)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async () => {
    if (!form.event_type) { setErr('Event type is required.'); return }
    setSaving(true)
    setErr(null)

    // Build payload — strip empty strings to avoid sending blank UUIDs
    const payload = {
      event_type:          form.event_type,
      channel:             form.channel,
      within_hours_only:   form.within_hours_only,
      route_to_role_id:    form.route_to_role_id    || null,
      route_to_user_id:    form.route_to_user_id    || null,
      also_notify_role_id: form.also_notify_role_id || null,
      escalate_after_minutes: form.escalate_after_minutes
        ? Number(form.escalate_after_minutes) : null,
      escalate_to_role_id: form.escalate_to_role_id || null,
    }

    try {
      await onSave(payload)
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Save failed.')
      setSaving(false)
    }
  }

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={MODAL} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>
            {isCreate ? 'New Routing Rule' : 'Edit Rule'}
          </h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD', lineHeight: 1 }}>×</button>
        </div>

        <label style={LABEL}>Event type *</label>
        <select value={form.event_type} onChange={e => set('event_type', e.target.value)} style={INPUT}>
          {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        <label style={LABEL}>Notification channel</label>
        <select value={form.channel} onChange={e => set('channel', e.target.value)} style={INPUT}>
          {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        <label style={LABEL}>Route to role</label>
        <select value={form.route_to_role_id} onChange={e => set('route_to_role_id', e.target.value)} style={INPUT}>
          <option value="">— None (use user below) —</option>
          {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>

        <label style={LABEL}>Also notify role (optional)</label>
        <select value={form.also_notify_role_id} onChange={e => set('also_notify_role_id', e.target.value)} style={INPUT}>
          <option value="">— None —</option>
          {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>

        <div style={{ marginTop: 16 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13.5, color: '#0a1a24', cursor: 'pointer' }}>
            <input type="checkbox" checked={form.within_hours_only} onChange={e => set('within_hours_only', e.target.checked)} />
            Only notify during business hours
          </label>
        </div>

        <label style={LABEL}>Escalate after (minutes, optional)</label>
        <input
          type="number"
          min={1}
          value={form.escalate_after_minutes}
          onChange={e => set('escalate_after_minutes', e.target.value)}
          style={INPUT}
          placeholder="e.g. 60"
        />

        {form.escalate_after_minutes && (
          <>
            <label style={LABEL}>Escalate to role</label>
            <select value={form.escalate_to_role_id} onChange={e => set('escalate_to_role_id', e.target.value)} style={INPUT}>
              <option value="">— None —</option>
              {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </>
        )}

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 12 }}>⚠ {err}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={{ ...GHOST, padding: '9px 18px' }}>Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            style={{ background: saving ? '#aaa' : ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '9px 20px', fontSize: 14, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer', fontFamily: ds.fontSyne }}
          >
            {saving ? 'Saving…' : (isCreate ? 'Create Rule' : 'Save Changes')}
          </button>
        </div>
      </div>
    </div>
  )
}
