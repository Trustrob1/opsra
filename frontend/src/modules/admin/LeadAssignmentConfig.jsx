/**
 * frontend/src/modules/admin/LeadAssignmentConfig.jsx
 * ASSIGN-1 — Lead Assignment Engine configuration.
 *
 * Section 1 — Mode Toggle (Manual / Auto)
 * Section 2 — Shift List (auto mode only)
 * Section 3 — Shift Editor (inline expand)
 * Section 4 — Coverage Preview (24-hour bar)
 * Section 5 — Status Banner
 *
 * Pattern 50: axios + _h() only via admin.service.js
 * Pattern 51: full rewrite only
 * Pattern 26: mount-and-hide tabs
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const DAY_LABELS = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' }
const STRATEGIES = ['least_loaded', 'round_robin', 'fixed']
const STRATEGY_LABELS = { least_loaded: 'Least Loaded', round_robin: 'Round Robin', fixed: 'Fixed Rep' }

const EMPTY_FORM = {
  shift_name:    '',
  shift_start:   '08:00',
  shift_end:     '18:00',
  days_active:   ['mon', 'tue', 'wed', 'thu', 'fri'],
  assignee_ids:  [],
  strategy:      'least_loaded',
  fixed_user_id: null,
}

export default function LeadAssignmentConfig() {
  const [mode,       setMode]       = useState('manual')
  const [shifts,     setShifts]     = useState([])
  const [users,      setUsers]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [saving,     setSaving]     = useState(false)
  const [error,      setError]      = useState(null)

  // Editor state
  const [editingId,  setEditingId]  = useState(null) // null = closed, 'new' = new shift
  const [form,       setForm]       = useState(EMPTY_FORM)
  const [formErr,    setFormErr]    = useState(null)

  // ── Load ────────────────────────────────────────────────────────────────
  useEffect(() => {
    load()
    loadUsers()
  }, [])

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await adminSvc.getLeadAssignment()
      setMode(res.mode || 'manual')
      setShifts(res.shifts || [])
    } catch (err) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      if (status === 404 || status === 500) {
        setError('Backend not deployed yet — run assign1_migrations.sql and redeploy.')
      } else if (status === 403) {
        setError('Access denied — Owner or Ops Manager role required.')
      } else {
        setError(
          typeof detail === 'string'
            ? detail
            : `Failed to load assignment config (${status || 'network error'}).`
        )
      }
    }
    setLoading(false)
  }

  const loadUsers = async () => {
    try {
      const res = await adminSvc.listUsers()
      // Filter to sales reps and customer success roles
      const eligible = (res || []).filter(u =>
        u.is_active &&
        ['sales_agent', 'customer_success', 'owner', 'ops_manager'].includes(
          u.roles?.template
        )
      )
      setUsers(eligible)
    } catch {}
  }

  // ── Mode toggle ──────────────────────────────────────────────────────────
  const handleModeToggle = async (newMode) => {
    if (newMode === mode) return
    setSaving(true)
    try {
      const res = await adminSvc.updateAssignmentMode(newMode)
      setMode(res.mode || newMode)
      await load()
    } catch (err) {
      setError('Failed to update mode.')
    }
    setSaving(false)
  }

  // ── Shift editor ─────────────────────────────────────────────────────────
  const openNew = () => {
    setForm(EMPTY_FORM)
    setFormErr(null)
    setEditingId('new')
  }

  // AFTER
  const openEdit = (shift) => {
    setForm({
      shift_name:    shift.shift_name,
      shift_start:   (shift.shift_start || '').slice(0, 5),
      shift_end:     (shift.shift_end   || '').slice(0, 5),
      days_active:   shift.days_active || [],
      assignee_ids:  shift.assignee_ids || [],
      strategy:      shift.strategy || 'least_loaded',
      fixed_user_id: shift.fixed_user_id || null,
    })
    setFormErr(null)
    setEditingId(shift.id)
  }

  const closeEditor = () => { setEditingId(null); setFormErr(null) }

  const toggleDay = (day) => {
    setForm(f => ({
      ...f,
      days_active: f.days_active.includes(day)
        ? f.days_active.filter(d => d !== day)
        : [...f.days_active, day],
    }))
  }

  const toggleAssignee = (userId) => {
    setForm(f => ({
      ...f,
      assignee_ids: f.assignee_ids.includes(userId)
        ? f.assignee_ids.filter(id => id !== userId)
        : [...f.assignee_ids, userId],
    }))
  }

  const validateForm = () => {
    if (!form.shift_name.trim()) return 'Shift name is required.'
    if (!form.days_active.length) return 'Select at least one active day.'
    if (form.strategy === 'fixed' && !form.fixed_user_id) return 'Select a fixed rep.'
    if (form.strategy === 'fixed' && !form.assignee_ids.includes(form.fixed_user_id))
      return 'Fixed rep must be in the reps list.'
    return null
  }

  const handleSaveShift = async () => {
    const err = validateForm()
    if (err) { setFormErr(err); return }
    setSaving(true)
    setFormErr(null)
    try {
      if (editingId === 'new') {
        await adminSvc.createShift(form)
      } else {
        await adminSvc.updateShift(editingId, form)
      }
      closeEditor()
      await load()
    } catch (err) {
      const detail = err?.response?.data?.detail
      setFormErr(typeof detail === 'string' ? detail : 'Failed to save shift.')
    }
    setSaving(false)
  }

  const handleDeleteShift = async (shiftId) => {
    setSaving(true)
    try {
      await adminSvc.deleteShift(shiftId)
      await load()
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to delete shift.')
    }
    setSaving(false)
  }

  // ── Coverage preview helpers ──────────────────────────────────────────────
  const activeShifts = shifts.filter(s => s.is_active)

  const _timeToFrac = (t) => {
    const [h, m] = (t || '00:00').split(':').map(Number)
    return (h * 60 + m) / (24 * 60)
  }

  const COLORS = ['#22d3a5', '#38bdf8', '#a78bfa', '#fb923c', '#f472b6', '#facc15']

  // ── Status banner ─────────────────────────────────────────────────────────
  const statusBanner = () => {
    if (mode !== 'auto') return null
    if (!activeShifts.length)
      return { color: '#f59e0b', text: 'Auto-assignment is on but no shifts configured.' }
    const hasNoReps = activeShifts.some(s => !(s.assignee_ids || []).length)
    if (hasNoReps)
      return { color: '#f59e0b', text: 'One or more shifts have no reps assigned.' }
    return { color: '#22d3a5', text: 'Auto-assignment is active and fully configured.' }
  }

  const banner = statusBanner()

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ padding: 32, color: '#7A9BAD', fontSize: 13 }}>
        Loading assignment config…
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 720, fontFamily: ds.fontDm }}>

      {/* Status banner */}
      {banner && (
        <div style={{
          background: banner.color + '18',
          border: `1px solid ${banner.color}44`,
          borderRadius: 10, padding: '10px 16px',
          fontSize: 13, color: banner.color,
          marginBottom: 20,
        }}>
          {banner.color === '#22d3a5' ? '✅' : '⚠️'} {banner.text}
        </div>
      )}

      {error && (
        <div style={{
          background: '#ef444420', border: '1px solid #ef444444',
          borderRadius: 10, padding: '10px 16px',
          fontSize: 13, color: '#ef4444', marginBottom: 20,
        }}>
          ❌ {error}
        </div>
      )}

      {/* ── Section 1: Mode Toggle ──────────────────────────────────────── */}
      <div style={{
        background: '#0a1a24', border: '1px solid #1e3a4f',
        borderRadius: 12, padding: '20px 22px', marginBottom: 20,
      }}>
        <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: 'white', margin: '0 0 14px' }}>
          Assignment Mode
        </h3>
        <div style={{ display: 'flex', gap: 10 }}>
          {['manual', 'auto'].map(m => (
            <button
              key={m}
              onClick={() => handleModeToggle(m)}
              disabled={saving}
              style={{
                flex: 1, padding: '12px 0',
                background: mode === m ? ds.teal : 'transparent',
                color: mode === m ? 'white' : '#7A9BAD',
                border: `1.5px solid ${mode === m ? ds.teal : '#1e3a4f'}`,
                borderRadius: 10, fontFamily: ds.fontSyne,
                fontWeight: 600, fontSize: 13, cursor: saving ? 'not-allowed' : 'pointer',
                transition: 'all 0.18s',
              }}
            >
              {m === 'manual' ? '👤 Manual Assignment' : '⚡ Auto Assignment'}
            </button>
          ))}
        </div>
        {mode === 'manual' && (
          <p style={{ fontSize: 12, color: '#3a5a6a', marginTop: 10, marginBottom: 0 }}>
            Leads are assigned manually by admins and managers. No shift config is applied.
          </p>
        )}
        {mode === 'auto' && (
          <p style={{ fontSize: 12, color: '#3a6a7a', marginTop: 10, marginBottom: 0 }}>
            New leads are automatically assigned to the rep with the fewest open leads on the active shift.
          </p>
        )}
      </div>

      {/* ── Section 2–4: Shifts (auto mode only) ────────────────────────── */}
      {mode === 'auto' && (
        <>
          {/* Coverage preview */}
          {activeShifts.length > 0 && (
            <div style={{
              background: '#0a1a24', border: '1px solid #1e3a4f',
              borderRadius: 12, padding: '18px 22px', marginBottom: 20,
            }}>
              <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: 'white', margin: '0 0 12px' }}>
                Coverage Preview
              </h3>
              <div style={{ position: 'relative', height: 32, background: '#ef444420', borderRadius: 6, overflow: 'hidden', border: '1px solid #1e3a4f' }}>
                {activeShifts.map((s, i) => {
                  const start = _timeToFrac(s.shift_start)
                  const end   = _timeToFrac(s.shift_end)
                  const isMidnight = start > end
                  const color = COLORS[i % COLORS.length]
                  if (isMidnight) {
                    return (
                      <span key={s.id}>
                        <span style={{ position: 'absolute', left: `${start * 100}%`, width: `${(1 - start) * 100}%`, top: 0, bottom: 0, background: color + 'aa', borderRadius: 4 }} />
                        <span style={{ position: 'absolute', left: 0, width: `${end * 100}%`, top: 0, bottom: 0, background: color + 'aa', borderRadius: 4 }} />
                      </span>
                    )
                  }
                  return (
                    <span key={s.id} style={{
                      position: 'absolute',
                      left: `${start * 100}%`,
                      width: `${(end - start) * 100}%`,
                      top: 0, bottom: 0,
                      background: color + 'aa',
                      borderRadius: 4,
                    }} />
                  )
                })}
              </div>
              {/* Time axis */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                {['00:00', '06:00', '12:00', '18:00', '24:00'].map(t => (
                  <span key={t} style={{ fontSize: 10, color: '#3a5a6a' }}>{t}</span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
                {activeShifts.map((s, i) => (
                  <span key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#A0BDC8' }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: COLORS[i % COLORS.length], display: 'inline-block' }} />
                    {s.shift_name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Shift list */}
          <div style={{
            background: '#0a1a24', border: '1px solid #1e3a4f',
            borderRadius: 12, padding: '18px 22px', marginBottom: 20,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: 'white', margin: 0 }}>
                Shift Configuration
              </h3>
              <button
                onClick={openNew}
                style={{
                  background: ds.teal, color: 'white', border: 'none',
                  borderRadius: 8, padding: '7px 14px', fontSize: 12,
                  fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne,
                }}
              >
                + Add Shift
              </button>
            </div>

            {shifts.filter(s => s.is_active).length === 0 && editingId !== 'new' && (
              <div style={{ textAlign: 'center', padding: '24px 0', fontSize: 13, color: '#3a5a6a' }}>
                No shifts configured yet. Add a shift to enable auto-assignment.
              </div>
            )}

            {shifts.filter(s => s.is_active).map(shift => (
              <div key={shift.id}>
                {/* Shift card */}
                <div style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${shift.is_active ? '#1e3a4f' : '#0e1f2a'}`,
                  borderRadius: 10, padding: '14px 16px', marginBottom: 8,
                  opacity: shift.is_active ? 1 : 0.5,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <span style={{ fontWeight: 600, color: 'white', fontSize: 13 }}>{shift.shift_name}</span>
                        {!shift.is_active && (
                          <span style={{ fontSize: 10, color: '#3a5a6a', border: '1px solid #1e3a4f', borderRadius: 4, padding: '1px 6px' }}>Inactive</span>
                        )}
                        <span style={{
                          fontSize: 11, color: ds.teal,
                          background: ds.teal + '18', border: `1px solid ${ds.teal}44`,
                          borderRadius: 4, padding: '1px 8px',
                        }}>
                          {shift.shift_start} – {shift.shift_end}
                          {shift.shift_start > shift.shift_end ? ' (spans midnight)' : ''}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                        {(shift.days_active || []).map(d => (
                          <span key={d} style={{
                            fontSize: 10, color: '#A0BDC8',
                            background: '#1e3a4f', borderRadius: 4, padding: '2px 7px',
                          }}>{DAY_LABELS[d]}</span>
                        ))}
                        <span style={{ fontSize: 11, color: '#7A9BAD', marginLeft: 4 }}>
                          {(shift.assignee_ids || []).length} rep{(shift.assignee_ids || []).length !== 1 ? 's' : ''}
                        </span>
                        <span style={{ fontSize: 11, color: '#3a5a6a' }}>
                          · {STRATEGY_LABELS[shift.strategy] || shift.strategy}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => openEdit(shift)}
                      style={{ background: 'transparent', border: '1px solid #1e3a4f', borderRadius: 7, padding: '5px 10px', fontSize: 12, color: '#7A9BAD', cursor: 'pointer' }}
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => { if (window.confirm('Remove this shift?')) handleDeleteShift(shift.id) }}
                      style={{ background: 'transparent', border: '1px solid #2a1a1a', borderRadius: 7, padding: '5px 10px', fontSize: 12, color: '#ef4444', cursor: 'pointer' }}
                      title="Remove shift"
                    >
                      🗑
                    </button>
                  </div>
                </div>

                {/* Inline editor for this shift */}
                {editingId === shift.id && (
                  <ShiftEditor
                    form={form}
                    setForm={setForm}
                    formErr={formErr}
                    users={users}
                    saving={saving}
                    onSave={handleSaveShift}
                    onCancel={closeEditor}
                    onToggleDay={toggleDay}
                    onToggleAssignee={toggleAssignee}
                  />
                )}
              </div>
            ))}

            {/* New shift editor */}
            {editingId === 'new' && (
              <ShiftEditor
                form={form}
                setForm={setForm}
                formErr={formErr}
                users={users}
                saving={saving}
                onSave={handleSaveShift}
                onCancel={closeEditor}
                onToggleDay={toggleDay}
                onToggleAssignee={toggleAssignee}
                isNew
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ─── Shift Editor ─────────────────────────────────────────────────────────────

function ShiftEditor({ form, setForm, formErr, users, saving, onSave, onCancel, onToggleDay, onToggleAssignee, isNew }) {
  const isMidnight = form.shift_start > form.shift_end && form.shift_end !== '00:00'

  return (
    <div style={{
      background: '#0e1f2a', border: '1px solid #1e3a4f',
      borderRadius: 10, padding: '18px 20px', marginBottom: 12, marginTop: 4,
    }}>
      <h4 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: 'white', margin: '0 0 16px' }}>
        {isNew ? 'New Shift' : 'Edit Shift'}
      </h4>

      {/* Name */}
      <FieldLabel>Shift Name</FieldLabel>
      <input
        value={form.shift_name}
        onChange={e => setForm(f => ({ ...f, shift_name: e.target.value }))}
        maxLength={100}
        placeholder="e.g. Day Shift"
        style={inputStyle}
      />

      {/* Times */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <div>
          <FieldLabel>Start Time</FieldLabel>
          <input type="time" value={form.shift_start}
            onChange={e => setForm(f => ({ ...f, shift_start: e.target.value.slice(0, 5) }))}
            style={inputStyle} />
        </div>
        <div>
          <FieldLabel>End Time</FieldLabel>
          <input type="time" value={form.shift_end}
            onChange={e => setForm(f => ({ ...f, shift_end: e.target.value.slice(0, 5) }))}
            style={inputStyle} />
        </div>
      </div>
      {isMidnight && (
        <div style={{ fontSize: 12, color: ds.teal, marginBottom: 12 }}>
          🌙 This shift spans midnight
        </div>
      )}

      {/* Days */}
      <FieldLabel>Days Active</FieldLabel>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        {['mon','tue','wed','thu','fri','sat','sun'].map(d => (
          <button
            key={d}
            onClick={() => onToggleDay(d)}
            style={{
              padding: '5px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600,
              cursor: 'pointer', border: 'none',
              background: form.days_active.includes(d) ? ds.teal : '#1e3a4f',
              color: form.days_active.includes(d) ? 'white' : '#7A9BAD',
              transition: 'all 0.15s',
            }}
          >
            {d.charAt(0).toUpperCase() + d.slice(1)}
          </button>
        ))}
      </div>

      {/* Reps */}
      <FieldLabel>Reps on this shift</FieldLabel>
      {users.length === 0 ? (
        <p style={{ fontSize: 12, color: '#3a5a6a', marginBottom: 14 }}>No eligible reps found.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
          {users.map(u => (
            <label key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: '#A0BDC8' }}>
              <input
                type="checkbox"
                checked={form.assignee_ids.includes(u.id)}
                onChange={() => onToggleAssignee(u.id)}
                style={{ accentColor: ds.teal }}
              />
              {u.full_name || u.email}
              <span style={{ fontSize: 11, color: '#3a5a6a' }}>{u.roles?.template}</span>
            </label>
          ))}
        </div>
      )}

      {/* Strategy */}
      <FieldLabel>Assignment Strategy</FieldLabel>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        {['least_loaded', 'round_robin', 'fixed'].map(s => (
          <button
            key={s}
            onClick={() => setForm(f => ({ ...f, strategy: s }))}
            style={{
              padding: '7px 14px', borderRadius: 8, fontSize: 12, fontWeight: 500,
              cursor: 'pointer', border: `1px solid ${form.strategy === s ? ds.teal : '#1e3a4f'}`,
              background: form.strategy === s ? ds.teal + '22' : 'transparent',
              color: form.strategy === s ? ds.teal : '#7A9BAD',
              transition: 'all 0.15s',
            }}
          >
            {s === 'least_loaded' ? 'Least Loaded' : s === 'round_robin' ? 'Round Robin' : 'Fixed Rep'}
          </button>
        ))}
      </div>

      {/* Fixed rep dropdown */}
      {form.strategy === 'fixed' && (
        <>
          <FieldLabel>Fixed Rep</FieldLabel>
          <select
            value={form.fixed_user_id || ''}
            onChange={e => setForm(f => ({ ...f, fixed_user_id: e.target.value || null }))}
            style={{ ...inputStyle, marginBottom: 14 }}
          >
            <option value="">Select a rep…</option>
            {users.filter(u => form.assignee_ids.includes(u.id)).map(u => (
              <option key={u.id} value={u.id}>{u.full_name || u.email}</option>
            ))}
          </select>
        </>
      )}

      {formErr && (
        <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 12 }}>❌ {formErr}</div>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <button
          onClick={onSave}
          disabled={saving}
          style={{
            background: saving ? '#015F6B' : ds.teal,
            color: 'white', border: 'none', borderRadius: 9,
            padding: '10px 22px', fontSize: 13, fontWeight: 600,
            fontFamily: ds.fontSyne, cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving…' : 'Save Shift'}
        </button>
        <button
          onClick={onCancel}
          style={{
            background: 'transparent', border: '1px solid #1e3a4f',
            borderRadius: 9, padding: '10px 18px', fontSize: 13,
            color: '#7A9BAD', cursor: 'pointer', fontFamily: ds.fontDm,
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function FieldLabel({ children }) {
  return (
    <p style={{
      fontSize: 11, fontWeight: 600, color: '#3a5a6a',
      textTransform: 'uppercase', letterSpacing: '1px', margin: '0 0 7px',
    }}>
      {children}
    </p>
  )
}

const inputStyle = {
  width: '100%', background: '#0a1a24',
  border: '1.5px solid #1e3a4f', borderRadius: 9,
  padding: '10px 13px', fontSize: 13, color: 'white',
  fontFamily: 'DM Sans, sans-serif', outline: 'none',
  marginBottom: 14, boxSizing: 'border-box',
}
