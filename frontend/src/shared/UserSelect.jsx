/**
 * frontend/src/shared/UserSelect.jsx
 * Shared user assignment dropdown — Phase 9C assignment wiring.
 *
 * Loads all active users from GET /api/v1/admin/users and filters
 * client-side to role templates in the `allowedTemplates` prop.
 *
 * Default: shows only sales_agent and affiliate_partner users.
 * Pass allowedTemplates={null} to show all active users.
 *
 * Props:
 *   value           {string}   — current assigned_to user UUID (or '')
 *   onChange        {fn}       — called with new user UUID string
 *   allowedTemplates {array}   — role templates to show (default: sales_agent + affiliate_partner)
 *   placeholder     {string}   — select placeholder text
 *   style           {object}   — optional style overrides on the select element
 *   disabled        {bool}     — disable the select
 */
import { useState, useEffect } from 'react'
import { listUsers } from '../services/admin.service'

const DEFAULT_TEMPLATES = ['sales_agent', 'affiliate_partner']

export default function UserSelect({
  value        = '',
  onChange,
  allowedTemplates = DEFAULT_TEMPLATES,
  placeholder  = '— Assign to —',
  style        = {},
  disabled     = false,
}) {
  const [users,   setUsers]   = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listUsers()
      .then(data => {
        let active = (data ?? []).filter(u => u.is_active)
        if (allowedTemplates) {
          active = active.filter(u =>
            allowedTemplates.includes(u.roles?.template)
          )
        }
        setUsers(active)
      })
      .catch(() => setUsers([]))
      .finally(() => setLoading(false))
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const baseStyle = {
    width:        '100%',
    border:       '1.5px solid #D4E6EC',
    borderRadius: 8,
    padding:      '9px 12px',
    fontSize:     13.5,
    fontFamily:   'inherit',
    color:        '#0a1a24',
    background:   disabled ? '#F8FAFC' : 'white',
    boxSizing:    'border-box',
    cursor:       disabled ? 'not-allowed' : 'pointer',
    ...style,
  }

  return (
    <select
      value={value}
      onChange={e => onChange?.(e.target.value)}
      disabled={disabled || loading}
      style={baseStyle}
    >
      <option value="">{loading ? 'Loading users…' : placeholder}</option>
      {users.map(u => (
        <option key={u.id} value={u.id}>
          {u.full_name}
          {u.roles?.template === 'affiliate_partner' ? ' (Affiliate)' : ''}
        </option>
      ))}
      {!loading && users.length === 0 && (
        <option disabled value="">No eligible users found</option>
      )}
    </select>
  )
}
