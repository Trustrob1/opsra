/**
 * frontend/src/modules/admin/RoleBuilder.jsx
 * Role Builder — Phase 8B
 *
 * Displays all org roles as expandable cards.
 * Each card shows: name, template badge, expand button for permissions + overrides.
 *
 * Owner role: locked — only name is editable; permissions + template cannot be changed.
 * All other roles: name + permissions editable via modal.
 *
 * Permissions: displayed as toggles for a standard set of permission keys.
 * User Overrides: per-role panel to list, add, and remove individual overrides.
 *   Requires users in that role — loaded lazily when panel opens.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

// Standard permission keys displayed in the permissions editor.
// Only keys defined here appear as toggles — backend stores arbitrary jsonb.
const PERMISSION_KEYS = [
  { key: 'is_admin',               label: 'Full Admin Access',          group: 'Admin' },
  { key: 'manage_users',           label: 'Manage Users',               group: 'Admin' },
  { key: 'manage_roles',           label: 'Manage Roles',               group: 'Admin' },
  { key: 'manage_routing_rules',   label: 'Manage Routing Rules',       group: 'Admin' },
  { key: 'manage_integrations',    label: 'Manage Integrations',        group: 'Admin' },
  { key: 'force_logout_users',     label: 'Force Logout Users',         group: 'Admin' },
  { key: 'view_revenue',           label: 'View Revenue & MRR',         group: 'Operations' },
  { key: 'manage_tasks',           label: 'Manage All Tasks (Team)',     group: 'Tasks' },
]

const VALID_TEMPLATES = [
  'owner', 'ops_manager', 'sales_agent',
  'customer_success', 'support_agent', 'finance', 'read_only',
]

const OVERLAY = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
}
const MODAL = {
  background: 'white', borderRadius: 14, padding: '28px 32px',
  width: 500, maxHeight: '85vh', overflowY: 'auto',
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
const TMPL_COLOR = {
  owner: { bg: '#FEF3C7', color: '#92400E' },
  ops_manager: { bg: '#DBEAFE', color: '#1E40AF' },
  sales_agent: { bg: '#DCFCE7', color: '#166534' },
  customer_success: { bg: '#E0E7FF', color: '#3730A3' },
  support_agent: { bg: '#FCE7F3', color: '#9D174D' },
  finance: { bg: '#D1FAE5', color: '#065F46' },
  read_only: { bg: '#F1F5F9', color: '#475569' },
}

export default function RoleBuilder() {
  const [roles, setRoles]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editingRole, setEditingRole] = useState(null)
  const [expandedId, setExpandedId] = useState(null)   // role id with open overrides panel

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRoles((await adminSvc.listRoles()) ?? [])
    } catch {
      setError('Failed to load roles.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading roles…</div>
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}>⚠ {error}</div>

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Roles</h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>
            {roles.length} role{roles.length !== 1 ? 's' : ''} · Click a card to manage permissions and overrides
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '9px 18px', fontSize: 13.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer' }}
        >
          + New Role
        </button>
      </div>

      {/* Role cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {roles.map(role => {
          const isOwner   = role.template === 'owner'
          const isExpanded = expandedId === role.id
          const tc        = TMPL_COLOR[role.template] ?? { bg: '#F1F5F9', color: '#475569' }

          return (
            <div key={role.id} style={{ background: 'white', borderRadius: 12, border: `1px solid ${isExpanded ? ds.teal : '#E4EEF2'}`, overflow: 'hidden', transition: 'border-color 0.15s' }}>
              {/* Card header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '16px 20px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24' }}>{role.name}</span>
                    {isOwner && <span style={{ fontSize: 10, background: '#FEF3C7', color: '#92400E', borderRadius: 4, padding: '2px 7px', fontWeight: 700 }}>OWNER · LOCKED</span>}
                  </div>
                  <span style={{ display: 'inline-block', marginTop: 4, fontSize: 11, fontWeight: 600, borderRadius: 5, padding: '2px 8px', background: tc.bg, color: tc.color }}>
                    {role.template}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={() => setEditingRole(role)} style={GHOST}>✏ Edit</button>
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : role.id)}
                    style={{ ...GHOST, color: isExpanded ? ds.teal : '#4a7a8a', borderColor: isExpanded ? ds.teal : '#CBD5E1' }}
                  >
                    {isExpanded ? '▲ Hide' : '▼ Overrides'}
                  </button>
                </div>
              </div>

              {/* Overrides panel */}
              {isExpanded && (
                <div style={{ borderTop: '1px solid #F0F7FA', padding: '16px 20px', background: '#FAFEFF' }}>
                  <OverridesPanel role={role} />
                </div>
              )}
            </div>
          )
        })}
        {roles.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>No roles found.</div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <RoleModal
          mode="create"
          onSave={async (data) => { await adminSvc.createRole(data); setShowCreate(false); load() }}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Edit modal */}
      {editingRole && (
        <RoleModal
          mode="edit"
          role={editingRole}
          onSave={async (data) => { await adminSvc.updateRole(editingRole.id, data); setEditingRole(null); load() }}
          onClose={() => setEditingRole(null)}
        />
      )}
    </div>
  )
}


// ── Overrides panel ───────────────────────────────────────────────────────────

function OverridesPanel({ role }) {
  const [overrides, setOverrides] = useState([])
  const [users, setUsers]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [form, setForm]           = useState({ user_id: '', permission_key: PERMISSION_KEYS[0]?.key ?? '', granted: true })
  const [saving, setSaving]       = useState(false)
  const [err, setErr]             = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [ov, us] = await Promise.all([
        adminSvc.listUserOverrides(role.id),
        adminSvc.listUsers(),
      ])
      setOverrides(ov ?? [])
      // Only show users in this role
      setUsers((us ?? []).filter(u => u.role_id === role.id))
    } catch {
      // Silent — show empty state
    } finally {
      setLoading(false)
    }
  }, [role.id])

  useEffect(() => { load() }, [load])

  const handleAdd = async () => {
    if (!form.user_id) { setErr('Select a user.'); return }
    setSaving(true)
    setErr(null)
    try {
      await adminSvc.createUserOverride(role.id, form)
      setForm(f => ({ ...f, user_id: '' }))
      load()
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Failed to add override.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (overrideId) => {
    try {
      await adminSvc.deleteUserOverride(role.id, overrideId)
      load()
    } catch { /* silent */ }
  }

  if (loading) return <p style={{ fontSize: 13, color: '#7A9BAD' }}>Loading overrides…</p>

  return (
    <div>
      <p style={{ fontSize: 13, fontWeight: 600, color: '#4a7a8a', margin: '0 0 12px' }}>
        Individual Permission Overrides
        <span style={{ fontWeight: 400, color: '#7A9BAD', marginLeft: 8, fontSize: 12 }}>
          Grant or deny a specific permission for one user in this role
        </span>
      </p>

      {/* Existing overrides */}
      {overrides.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {overrides.map(ov => (
            <div key={ov.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid #F0F7FA' }}>
              <span style={{ fontSize: 13, color: '#0a1a24', flex: 1 }}>
                <strong>{ov.user?.full_name ?? ov.user_id}</strong>
                <span style={{ color: '#7A9BAD', margin: '0 8px' }}>·</span>
                {ov.permission_key}
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, borderRadius: 5, padding: '2px 8px', background: ov.granted ? '#ECFDF5' : '#FEF2F2', color: ov.granted ? '#059669' : '#DC2626' }}>
                {ov.granted ? 'GRANTED' : 'DENIED'}
              </span>
              <button onClick={() => handleDelete(ov.id)} style={{ ...GHOST, color: '#DC2626', borderColor: '#FECACA', padding: '3px 8px' }}>✕</button>
            </div>
          ))}
        </div>
      )}
      {overrides.length === 0 && (
        <p style={{ fontSize: 13, color: '#7A9BAD', marginBottom: 12 }}>No overrides set.</p>
      )}

      {/* Add override form */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <select
          value={form.user_id}
          onChange={e => setForm(f => ({ ...f, user_id: e.target.value }))}
          style={{ ...INPUT, width: 'auto', minWidth: 160 }}
        >
          <option value="">— Select user —</option>
          {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </select>
        <select
          value={form.permission_key}
          onChange={e => setForm(f => ({ ...f, permission_key: e.target.value }))}
          style={{ ...INPUT, width: 'auto', minWidth: 180 }}
        >
          {PERMISSION_KEYS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
        <select
          value={form.granted ? 'true' : 'false'}
          onChange={e => setForm(f => ({ ...f, granted: e.target.value === 'true' }))}
          style={{ ...INPUT, width: 'auto' }}
        >
          <option value="true">Grant</option>
          <option value="false">Deny</option>
        </select>
        <button
          onClick={handleAdd}
          disabled={saving}
          style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer', fontFamily: ds.fontSyne }}
        >
          {saving ? 'Adding…' : '+ Add'}
        </button>
      </div>
      {err && <p style={{ color: '#DC2626', fontSize: 12, marginTop: 8 }}>⚠ {err}</p>}
      {users.length === 0 && (
        <p style={{ fontSize: 12, color: '#7A9BAD', marginTop: 6 }}>No users assigned to this role yet.</p>
      )}
    </div>
  )
}


// ── Role modal (create / edit) ────────────────────────────────────────────────

function RoleModal({ mode, role, onSave, onClose }) {
  const isCreate = mode === 'create'
  const isOwner  = role?.template === 'owner'

  const initPerms = () => {
    const base = {}
    PERMISSION_KEYS.forEach(p => { base[p.key] = false })
    return { ...base, ...(role?.permissions ?? {}) }
  }

  const [name,     setName]     = useState(role?.name ?? '')
  const [template, setTemplate] = useState(role?.template ?? VALID_TEMPLATES[1])
  const [perms,    setPerms]    = useState(initPerms)
  const [saving,   setSaving]   = useState(false)
  const [err,      setErr]      = useState(null)

  const togglePerm = (key) => setPerms(p => ({ ...p, [key]: !p[key] }))

  const handleSubmit = async () => {
    if (!name.trim()) { setErr('Role name is required.'); return }
    setSaving(true)
    setErr(null)
    try {
      if (isCreate) {
        await onSave({ name, template, permissions: perms })
      } else {
        const payload = {}
        if (name !== role.name) payload.name = name
        if (!isOwner) payload.permissions = perms
        if (Object.keys(payload).length === 0) { onClose(); return }
        await onSave(payload)
      }
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Save failed.')
      setSaving(false)
    }
  }

  // Group permission keys
  const groups = [...new Set(PERMISSION_KEYS.map(p => p.group))]

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={MODAL} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>
            {isCreate ? 'New Role' : `Edit: ${role.name}`}
          </h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD', lineHeight: 1 }}>×</button>
        </div>

        <label style={LABEL}>Role name *</label>
        <input value={name} onChange={e => setName(e.target.value)} style={INPUT} placeholder="e.g. Senior Sales Agent" />

        {isCreate && (
          <>
            <label style={LABEL}>Base template</label>
            <select value={template} onChange={e => setTemplate(e.target.value)} style={INPUT}>
              {VALID_TEMPLATES.filter(t => t !== 'owner').map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </>
        )}

        {/* Permissions */}
        {!isOwner ? (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#4a7a8a', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: 10 }}>
              Permission Overrides
            </div>
            {groups.map(group => (
              <div key={group} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 11, color: '#7A9BAD', fontWeight: 600, marginBottom: 6 }}>{group}</div>
                {PERMISSION_KEYS.filter(p => p.group === group).map(p => (
                  <label key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13.5, color: '#0a1a24', cursor: 'pointer', marginBottom: 6 }}>
                    <input
                      type="checkbox"
                      checked={!!perms[p.key]}
                      onChange={() => togglePerm(p.key)}
                    />
                    {p.label}
                  </label>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 13, color: '#7A9BAD', marginTop: 16, padding: '10px 14px', background: '#FEF9C3', borderRadius: 8 }}>
            🔒 Owner role permissions are locked and cannot be modified.
          </p>
        )}

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 12 }}>⚠ {err}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={{ ...GHOST, padding: '9px 18px' }}>Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            style={{ background: saving ? '#aaa' : ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '9px 20px', fontSize: 14, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer', fontFamily: ds.fontSyne }}
          >
            {saving ? 'Saving…' : (isCreate ? 'Create Role' : 'Save Changes')}
          </button>
        </div>
      </div>
    </div>
  )
}
