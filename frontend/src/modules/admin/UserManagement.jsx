/**
 * frontend/src/modules/admin/UserManagement.jsx
 * User Management — Phase 8B
 *
 * Loads users + roles on mount.
 * Features:
 *   - User table: name, email, role, last login, status, out-of-office badge
 *   - + New User → CreateUserModal (email, full_name, password, role)
 *   - Edit per row → EditUserModal (full_name, role, is_active, is_out_of_office)
 *   - Force Logout per active user (inline confirm step)
 *   - Deactivate / Reactivate toggle per row
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

// ── Shared modal styles ───────────────────────────────────────────────────────
const OVERLAY = {
  position:       'fixed', inset: 0,
  background:     'rgba(0,0,0,0.45)',
  display:        'flex', alignItems: 'center', justifyContent: 'center',
  zIndex:         1000,
}
const MODAL = {
  background:    'white',
  borderRadius:  14,
  padding:       '28px 32px',
  width:         460,
  maxHeight:     '85vh',
  overflowY:     'auto',
  boxShadow:     '0 24px 60px rgba(0,0,0,0.25)',
}
const LABEL = {
  display:        'block',
  fontSize:       11,
  fontWeight:     600,
  color:          '#4a7a8a',
  textTransform:  'uppercase',
  letterSpacing:  '0.7px',
  marginTop:      16,
  marginBottom:   6,
}
const INPUT = {
  width:        '100%',
  padding:      '9px 12px',
  border:       '1px solid #D4E6EC',
  borderRadius: 8,
  fontSize:     13.5,
  fontFamily:   'inherit',
  color:        '#0a1a24',
  background:   'white',
  boxSizing:    'border-box',
}
const GHOST_BTN = {
  background:   'white',
  border:       '1px solid #CBD5E1',
  borderRadius: 6,
  padding:      '5px 10px',
  fontSize:     12,
  fontWeight:   500,
  color:        '#4a7a8a',
  cursor:       'pointer',
  fontFamily:   'inherit',
}


// ── Main component ────────────────────────────────────────────────────────────

export default function UserManagement() {
  const [users, setUsers]             = useState([])
  const [roles, setRoles]             = useState([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)
  const [showCreate, setShowCreate]   = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [confirmLogout, setConfirmLogout] = useState(null)  // user id

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [u, r] = await Promise.all([adminSvc.listUsers(), adminSvc.listRoles()])
      setUsers(u ?? [])
      setRoles(r ?? [])
    } catch {
      setError('Failed to load users.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleToggleActive = async (u) => {
    try {
      await adminSvc.updateUser(u.id, { is_active: !u.is_active })
      load()
    } catch {
      setError('Failed to update user status.')
    }
  }

  const handleForceLogout = async (userId) => {
    try { await adminSvc.forceLogout(userId) } catch {}
    setConfirmLogout(null)
  }

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading users…</div>
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}>⚠ {error} <button onClick={load} style={{ ...GHOST_BTN, marginLeft: 10 }}>Retry</button></div>

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>
            Team Members
          </h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>
            {users.length} user{users.length !== 1 ? 's' : ''} in this organisation
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          style={{
            background: ds.teal, color: 'white', border: 'none',
            borderRadius: 8, padding: '9px 18px',
            fontSize: 13.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer',
          }}
        >
          + New User
        </button>
      </div>

      {/* Table */}
      <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#F5F9FA' }}>
              {['Name', 'Role', 'Last Login', 'Status', 'Actions'].map(h => (
                <th key={h} style={{ padding: '11px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: 32, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
                  No users found.
                </td>
              </tr>
            ) : users.map((u, i) => (
              <tr key={u.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none' }}>
                {/* Name */}
                <td style={{ padding: '13px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: '50%',
                      background: '#01606D', display: 'flex', alignItems: 'center',
                      justifyContent: 'center', fontFamily: ds.fontSyne,
                      fontWeight: 700, fontSize: 13, color: 'white', flexShrink: 0,
                    }}>
                      {(u.full_name?.[0] ?? u.email?.[0] ?? '?').toUpperCase()}
                    </div>
                    <div>
                      <div style={{ fontSize: 13.5, fontWeight: 600, color: '#0a1a24' }}>
                        {u.full_name}
                      </div>
                      <div style={{ fontSize: 12, color: '#7A9BAD' }}>{u.email}</div>
                      {u.is_out_of_office && (
                        <span style={{ fontSize: 10, background: '#FEF9C3', color: '#854D0E', borderRadius: 4, padding: '1px 6px', fontWeight: 600 }}>
                          OUT OF OFFICE
                        </span>
                      )}
                    </div>
                  </div>
                </td>

                {/* Role */}
                <td style={{ padding: '13px 16px' }}>
                  <span style={{ fontSize: 12, background: '#EEF8FA', color: ds.teal, borderRadius: 6, padding: '3px 9px', fontWeight: 600 }}>
                    {u.roles?.name ?? '—'}
                  </span>
                  {u.roles?.template && (
                    <div style={{ fontSize: 11, color: '#7A9BAD', marginTop: 3 }}>{u.roles.template}</div>
                  )}
                </td>

                {/* Last login */}
                <td style={{ padding: '13px 16px', fontSize: 12, color: '#7A9BAD' }}>
                  {u.last_login_at
                    ? new Date(u.last_login_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
                    : 'Never'}
                </td>

                {/* Status */}
                <td style={{ padding: '13px 16px' }}>
                  <span style={{
                    fontSize: 11, fontWeight: 600, borderRadius: 6, padding: '3px 9px',
                    background: u.is_active ? '#ECFDF5' : '#FEF2F2',
                    color:      u.is_active ? '#059669' : '#DC2626',
                  }}>
                    {u.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>

                {/* Actions */}
                <td style={{ padding: '13px 16px' }}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    <button onClick={() => setEditingUser(u)} style={GHOST_BTN}>✏ Edit</button>

                    {u.is_active && confirmLogout !== u.id && (
                      <button
                        onClick={() => setConfirmLogout(u.id)}
                        style={{ ...GHOST_BTN, color: '#DC2626', borderColor: '#FECACA' }}
                      >
                        ⊗ Logout
                      </button>
                    )}
                    {confirmLogout === u.id && (
                      <>
                        <button
                          onClick={() => handleForceLogout(u.id)}
                          style={{ ...GHOST_BTN, background: '#DC2626', color: 'white', borderColor: '#DC2626' }}
                        >
                          Confirm
                        </button>
                        <button onClick={() => setConfirmLogout(null)} style={GHOST_BTN}>Cancel</button>
                      </>
                    )}

                    <button
                      onClick={() => handleToggleActive(u)}
                      style={{
                        ...GHOST_BTN,
                        color:       u.is_active ? '#7A9BAD' : '#059669',
                        borderColor: u.is_active ? '#CBD5E1' : '#A7F3D0',
                      }}
                    >
                      {u.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modals */}
      {showCreate && (
        <UserModal
          mode="create"
          roles={roles}
          onSave={async (data) => { await adminSvc.createUser(data); setShowCreate(false); load() }}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editingUser && (
        <UserModal
          mode="edit"
          user={editingUser}
          roles={roles}
          onSave={async (data) => { await adminSvc.updateUser(editingUser.id, data); setEditingUser(null); load() }}
          onClose={() => setEditingUser(null)}
        />
      )}
    </div>
  )
}


// ── User modal (shared create / edit) ─────────────────────────────────────────

function UserModal({ mode, user, roles, onSave, onClose }) {
  const isCreate = mode === 'create'
  const [form, setForm] = useState({
    email:            user?.email            ?? '',
    full_name:        user?.full_name        ?? '',
    password:         '',
    role_id:          user?.role_id          ?? roles[0]?.id ?? '',
    is_active:        user?.is_active        ?? true,
    is_out_of_office: user?.is_out_of_office ?? false,
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr]       = useState(null)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async () => {
    if (!form.full_name.trim()) { setErr('Full name is required.'); return }
    if (isCreate && (!form.email.trim() || !form.password.trim())) {
      setErr('Email and password are required.'); return
    }
    setSaving(true)
    setErr(null)
    try {
      if (isCreate) {
        await onSave({ email: form.email, full_name: form.full_name, password: form.password, role_id: form.role_id })
      } else {
        const payload = {}
        if (form.full_name        !== user.full_name)        payload.full_name        = form.full_name
        if (form.role_id          !== user.role_id)          payload.role_id          = form.role_id
        if (form.is_active        !== user.is_active)        payload.is_active        = form.is_active
        if (form.is_out_of_office !== user.is_out_of_office) payload.is_out_of_office = form.is_out_of_office
        if (Object.keys(payload).length === 0) { onClose(); return }
        await onSave(payload)
      }
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Save failed. Please try again.')
      setSaving(false)
    }
  }

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={MODAL} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>
            {isCreate ? 'New User' : 'Edit User'}
          </h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD', lineHeight: 1 }}>×</button>
        </div>

        {isCreate && (
          <>
            <label style={LABEL}>Email address *</label>
            <input type="email" value={form.email} onChange={e => set('email', e.target.value)} style={INPUT} placeholder="user@example.com" />
            <label style={LABEL}>Password *</label>
            <input type="password" value={form.password} onChange={e => set('password', e.target.value)} style={INPUT} placeholder="Min 8 characters" />
          </>
        )}

        <label style={LABEL}>Full name *</label>
        <input value={form.full_name} onChange={e => set('full_name', e.target.value)} style={INPUT} placeholder="First Last" />

        <label style={LABEL}>Role</label>
        <select value={form.role_id} onChange={e => set('role_id', e.target.value)} style={INPUT}>
          {roles.map(r => (
            <option key={r.id} value={r.id}>{r.name} ({r.template})</option>
          ))}
        </select>

        {!isCreate && (
          <div style={{ display: 'flex', gap: 20, marginTop: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, color: '#4a7a8a', cursor: 'pointer' }}>
              <input type="checkbox" checked={form.is_active} onChange={e => set('is_active', e.target.checked)} />
              Active account
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, color: '#4a7a8a', cursor: 'pointer' }}>
              <input type="checkbox" checked={form.is_out_of_office} onChange={e => set('is_out_of_office', e.target.checked)} />
              Out of office
            </label>
          </div>
        )}

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 12 }}>⚠ {err}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={{ ...GHOST_BTN, padding: '9px 18px' }}>Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            style={{
              background: saving ? '#aaa' : ds.teal, color: 'white',
              border: 'none', borderRadius: 8, padding: '9px 20px',
              fontSize: 14, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer',
              fontFamily: ds.fontSyne,
            }}
          >
            {saving ? 'Saving…' : (isCreate ? 'Create User' : 'Save Changes')}
          </button>
        </div>
      </div>
    </div>
  )
}
