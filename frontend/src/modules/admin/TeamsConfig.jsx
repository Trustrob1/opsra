/**
 * frontend/src/modules/admin/TeamsConfig.jsx
 * OPS-1 — Teams configuration panel in Admin Dashboard.
 *
 * Allows owner/ops_manager to define the org's team names.
 * These names populate:
 *   - The Team dropdown in UserManagement (assigning users to teams)
 *   - The Team dropdown in InternalOpsModule (creating issues, filtering logs)
 *
 * Follows ticket-categories backend pattern (CONFIG-1).
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getTeams, updateTeams } from '../../services/admin.service'

const LABEL = {
  display:       'block',
  fontSize:      11,
  fontWeight:    600,
  color:         '#4a7a8a',
  textTransform: 'uppercase',
  letterSpacing: '0.7px',
  marginBottom:  8,
}

const INPUT = {
  padding:      '9px 12px',
  border:       '1px solid #D4E6EC',
  borderRadius: 8,
  fontSize:     13.5,
  fontFamily:   'inherit',
  color:        '#0a1a24',
  background:   'white',
  outline:      'none',
}

export default function TeamsConfig() {
  const [teams, setTeams]     = useState([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState(null)
  const [saved, setSaved]     = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTeams()
      setTeams(data?.teams ?? [])
    } catch {
      setError('Failed to load teams.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleAdd = () => {
    const trimmed = newName.trim()
    if (!trimmed) return
    if (teams.map(t => t.toLowerCase()).includes(trimmed.toLowerCase())) {
      setError('A team with this name already exists.')
      return
    }
    setTeams(prev => [...prev, trimmed])
    setNewName('')
    setError(null)
  }

  const handleRemove = (index) => {
    setTeams(prev => prev.filter((_, i) => i !== index))
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); handleAdd() }
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await updateTeams(teams)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to save teams.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading teams…</div>
  }

  return (
    <div style={{ maxWidth: 560 }}>
      <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 6px' }}>
        Teams
      </h2>
      <p style={{ fontSize: 13, color: '#7A9BAD', margin: '0 0 28px', lineHeight: 1.6 }}>
        Define your organisation's team names. These appear when assigning users to teams
        and when logging or filtering internal ops issues and activity logs.
      </p>

      {/* Current teams list */}
      <label style={LABEL}>Current teams</label>
      {teams.length === 0 ? (
        <div style={{
          padding: '16px 18px', background: '#F8FAFC',
          border: '1px dashed #CBD5E1', borderRadius: 8,
          fontSize: 13, color: '#7A9BAD', marginBottom: 20,
        }}>
          No teams configured yet. Add your first team below.
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
          {teams.map((team, i) => (
            <div
              key={i}
              style={{
                display:      'flex',
                alignItems:   'center',
                gap:          6,
                background:   '#EEF8FA',
                border:       `1px solid #B2DDE8`,
                borderRadius: 20,
                padding:      '5px 12px 5px 14px',
                fontSize:     13,
                fontWeight:   500,
                color:        ds.teal,
              }}
            >
              {team}
              <button
                onClick={() => handleRemove(i)}
                style={{
                  background:  'none',
                  border:      'none',
                  cursor:      'pointer',
                  color:       '#7A9BAD',
                  fontSize:    16,
                  lineHeight:  1,
                  padding:     '0 2px',
                  fontFamily:  'inherit',
                }}
                title={`Remove ${team}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add new team */}
      <label style={LABEL}>Add a team</label>
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        <input
          value={newName}
          onChange={e => { setNewName(e.target.value); setError(null) }}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Sales, Media, Content, Website"
          style={{ ...INPUT, flex: 1 }}
          maxLength={100}
        />
        <button
          onClick={handleAdd}
          disabled={!newName.trim()}
          style={{
            background:   newName.trim() ? ds.teal : '#CBD5E1',
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '9px 18px',
            fontSize:     13.5,
            fontWeight:   600,
            cursor:       newName.trim() ? 'pointer' : 'not-allowed',
            fontFamily:   'inherit',
            whiteSpace:   'nowrap',
          }}
        >
          + Add
        </button>
      </div>

      {error && (
        <p style={{ color: '#DC2626', fontSize: 13, margin: '-14px 0 16px' }}>⚠ {error}</p>
      )}

      {/* Save */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background:   saving ? '#aaa' : ds.teal,
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '10px 24px',
            fontSize:     14,
            fontWeight:   600,
            cursor:       saving ? 'not-allowed' : 'pointer',
            fontFamily:   ds.fontSyne,
          }}
        >
          {saving ? 'Saving…' : 'Save Teams'}
        </button>
        {saved && (
          <span style={{ fontSize: 13, color: '#059669', fontWeight: 500 }}>
            ✓ Teams saved
          </span>
        )}
      </div>
    </div>
  )
}
