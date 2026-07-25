/**
 * frontend/src/modules/admin/TeamsConfig.jsx
 * OPS-1, extended REPORTS-DEPT-1 Phase 1 — Departments & Teams config panel.
 *
 * Was a flat string-list team editor. Now a two-level hierarchy:
 *   Departments (owner/ops_manager can add, rename, reorder, deactivate)
 *     -> Teams (assigned to a department, or left Unassigned)
 *
 * Departments commit immediately per action (granular POST/PATCH/DELETE
 * routes). Teams stay local-only until "Save Teams" is clicked, because
 * the backend only exposes a bulk PATCH /api/v1/admin/teams (replace the
 * whole array) — same pattern the original file used, just extended.
 *
 * These names populate:
 *   - The Team dropdown in UserManagement (assigning users to teams)
 *   - The Team dropdown in InternalOpsModule (creating issues, filtering logs)
 *   - The department-scoped Reports hub (REPORTS-DEPT-1 Phase 3, later)
 *
 * users.team is UNCHANGED — still a plain string matched against
 * teams[].name at read time. This panel never writes to users directly.
 *
 * Full rewrite (not incremental) per this file's own established convention
 * — Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  getTeams, updateTeams,
  getDepartments, createDepartment, updateDepartment, deleteDepartment,
} from '../../services/admin.service'

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

const ICON_BTN = {
  background:   'none',
  border:       'none',
  cursor:       'pointer',
  color:        '#7A9BAD',
  fontSize:     15,
  lineHeight:   1,
  padding:      '4px 6px',
  fontFamily:   'inherit',
}

function genLocalId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

// ── Department card ──────────────────────────────────────────────────────────

function DepartmentCard({
  dept, index, deptCount, teamsInDept,
  onRename, onMove, onDeactivate,
  onAddTeam, onRenameTeam, onMoveTeamDept, onToggleTeamActive, onRemoveTeam,
  allDepartments,
}) {
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft]      = useState(dept.name)
  const [newTeamName, setNewTeamName]  = useState('')

  const commitName = () => {
    const trimmed = nameDraft.trim()
    setEditingName(false)
    if (trimmed && trimmed !== dept.name) onRename(dept.id, trimmed)
    else setNameDraft(dept.name)
  }

  const handleAddTeam = () => {
    const trimmed = newTeamName.trim()
    if (!trimmed) return
    onAddTeam(trimmed, dept.id)
    setNewTeamName('')
  }

  return (
    <div style={{
      background:   '#F8FBFC',
      border:       '1px solid #D4E6EC',
      borderRadius: 12,
      padding:      '16px 18px',
      marginBottom: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <button
            onClick={() => onMove(index, -1)}
            disabled={index === 0}
            style={{ ...ICON_BTN, opacity: index === 0 ? 0.3 : 1, fontSize: 11, padding: '0 6px' }}
            title="Move up"
          >▲</button>
          <button
            onClick={() => onMove(index, 1)}
            disabled={index === deptCount - 1}
            style={{ ...ICON_BTN, opacity: index === deptCount - 1 ? 0.3 : 1, fontSize: 11, padding: '0 6px' }}
            title="Move down"
          >▼</button>
        </div>

        {editingName ? (
          <input
            autoFocus
            value={nameDraft}
            onChange={e => setNameDraft(e.target.value)}
            onBlur={commitName}
            onKeyDown={e => { if (e.key === 'Enter') commitName(); if (e.key === 'Escape') { setNameDraft(dept.name); setEditingName(false) } }}
            style={{ ...INPUT, flex: 1, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15 }}
          />
        ) : (
          <span
            onClick={() => setEditingName(true)}
            style={{ flex: 1, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', cursor: 'text' }}
            title="Click to rename"
          >
            {dept.name}
          </span>
        )}

        <button
          onClick={() => onDeactivate(dept.id)}
          style={{ ...ICON_BTN, fontSize: 12, color: '#B0453A' }}
          title="Deactivate department"
        >
          Deactivate
        </button>
      </div>

      {/* Teams within this department */}
      {teamsInDept.length === 0 ? (
        <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '0 0 10px' }}>
          No teams assigned yet.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
          {teamsInDept.map(team => (
            <TeamRow
              key={team.id}
              team={team}
              allDepartments={allDepartments}
              onRename={onRenameTeam}
              onMoveDept={onMoveTeamDept}
              onToggleActive={onToggleTeamActive}
              onRemove={onRemoveTeam}
            />
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={newTeamName}
          onChange={e => setNewTeamName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddTeam() } }}
          placeholder="e.g. Content Production"
          style={{ ...INPUT, flex: 1, fontSize: 13 }}
        />
        <button
          onClick={handleAddTeam}
          disabled={!newTeamName.trim()}
          style={{
            background:   newTeamName.trim() ? ds.teal : '#CBD5E1',
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '8px 16px',
            fontSize:     13,
            fontWeight:   600,
            cursor:       newTeamName.trim() ? 'pointer' : 'not-allowed',
            fontFamily:   'inherit',
            whiteSpace:   'nowrap',
          }}
        >
          + Add team
        </button>
      </div>
    </div>
  )
}

// ── Team row (used inside a department card, and in the Unassigned list) ────

function TeamRow({ team, allDepartments, onRename, onMoveDept, onToggleActive, onRemove }) {
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft]      = useState(team.name)

  const commitName = () => {
    const trimmed = nameDraft.trim()
    setEditingName(false)
    if (trimmed && trimmed !== team.name) onRename(team.id, trimmed)
    else setNameDraft(team.name)
  }

  return (
    <div style={{
      display:      'flex',
      alignItems:   'center',
      gap:          8,
      background:   'white',
      border:       '1px solid #E3EEF2',
      borderRadius: 8,
      padding:      '8px 10px',
      opacity:      team.is_active ? 1 : 0.5,
    }}>
      {editingName ? (
        <input
          autoFocus
          value={nameDraft}
          onChange={e => setNameDraft(e.target.value)}
          onBlur={commitName}
          onKeyDown={e => { if (e.key === 'Enter') commitName(); if (e.key === 'Escape') { setNameDraft(team.name); setEditingName(false) } }}
          style={{ ...INPUT, flex: 1, fontSize: 13, padding: '5px 8px' }}
        />
      ) : (
        <span
          onClick={() => setEditingName(true)}
          style={{ flex: 1, fontSize: 13.5, color: '#0a1a24', cursor: 'text' }}
          title="Click to rename"
        >
          {team.name}
        </span>
      )}

      <select
        value={team.department_id || ''}
        onChange={e => onMoveDept(team.id, e.target.value || null)}
        style={{ ...INPUT, fontSize: 12, padding: '5px 8px', maxWidth: 160 }}
      >
        <option value="">Unassigned</option>
        {allDepartments.map(d => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
      </select>

      <button
        onClick={() => onToggleActive(team.id)}
        style={{ ...ICON_BTN, fontSize: 11 }}
        title={team.is_active ? 'Deactivate team' : 'Reactivate team'}
      >
        {team.is_active ? 'Deactivate' : 'Reactivate'}
      </button>

      <button
        onClick={() => onRemove(team.id)}
        style={{ ...ICON_BTN, fontSize: 16, color: '#B0453A' }}
        title="Remove team (only if never saved)"
      >
        ×
      </button>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function TeamsConfig() {
  const [departments, setDepartments] = useState([])
  const [teams, setTeams]             = useState([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)

  const [savingTeams, setSavingTeams] = useState(false)
  const [teamsSaved, setTeamsSaved]   = useState(false)
  const [newDeptName, setNewDeptName] = useState('')
  const [deptBusy, setDeptBusy]       = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [deptData, teamData] = await Promise.all([getDepartments(), getTeams()])
      setDepartments((deptData?.departments ?? []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)))
      setTeams(teamData?.teams ?? [])
    } catch {
      setError('Failed to load departments and teams.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // ── Department actions (commit immediately) ───────────────────────────────

  const handleAddDepartment = async () => {
    const trimmed = newDeptName.trim()
    if (!trimmed) return
    if (departments.some(d => d.name.toLowerCase() === trimmed.toLowerCase())) {
      setError('A department with this name already exists.')
      return
    }
    setDeptBusy(true)
    setError(null)
    try {
      const result = await createDepartment({ name: trimmed })
      setDepartments((result?.departments ?? []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)))
      setNewDeptName('')
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to add department.')
    } finally {
      setDeptBusy(false)
    }
  }

  const handleRenameDepartment = async (id, name) => {
    setError(null)
    try {
      const result = await updateDepartment(id, { name })
      setDepartments((result?.departments ?? []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)))
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to rename department.')
      load()
    }
  }

  const handleMoveDepartment = async (index, direction) => {
    const target = index + direction
    if (target < 0 || target >= departments.length) return
    const a = departments[index]
    const b = departments[target]
    setError(null)
    try {
      await Promise.all([
        updateDepartment(a.id, { sort_order: b.sort_order ?? target }),
        updateDepartment(b.id, { sort_order: a.sort_order ?? index }),
      ])
      const reordered = departments.slice()
      ;[reordered[index], reordered[target]] = [reordered[target], reordered[index]]
      setDepartments(reordered.map((d, i) => ({ ...d, sort_order: i })))
    } catch {
      setError('Failed to reorder departments.')
      load()
    }
  }

  const handleDeactivateDepartment = async (id) => {
    if (!window.confirm('Deactivate this department? Its teams will move to Unassigned until reassigned.')) return
    setError(null)
    try {
      const result = await deleteDepartment(id)
      setDepartments((result?.departments ?? []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)))
      // Teams pointing at a now-inactive department fall back to Unassigned
      // in the UI via the activeDepartments filter below — no local team
      // mutation needed, department_id is left as-is until reassigned.
    } catch {
      setError('Failed to deactivate department.')
    }
  }

  // ── Team actions (local only, until Save Teams) ────────────────────────────

  const handleAddTeam = (name, departmentId) => {
    if (teams.some(t => t.name.toLowerCase() === name.toLowerCase())) {
      setError('A team with this name already exists.')
      return
    }
    setTeams(prev => [...prev, {
      id: genLocalId(), name, department_id: departmentId, is_active: true,
    }])
    setTeamsSaved(false)
  }

  const handleRenameTeam = (teamId, name) => {
    if (teams.some(t => t.id !== teamId && t.name.toLowerCase() === name.toLowerCase())) {
      setError('A team with this name already exists.')
      return
    }
    setTeams(prev => prev.map(t => t.id === teamId ? { ...t, name } : t))
    setTeamsSaved(false)
  }

  const handleMoveTeamDept = (teamId, departmentId) => {
    setTeams(prev => prev.map(t => t.id === teamId ? { ...t, department_id: departmentId } : t))
    setTeamsSaved(false)
  }

  const handleToggleTeamActive = (teamId) => {
    setTeams(prev => prev.map(t => t.id === teamId ? { ...t, is_active: !t.is_active } : t))
    setTeamsSaved(false)
  }

  const handleRemoveTeam = (teamId) => {
    setTeams(prev => prev.filter(t => t.id !== teamId))
    setTeamsSaved(false)
  }

  const handleSaveTeams = async () => {
    setSavingTeams(true)
    setError(null)
    setTeamsSaved(false)
    try {
      await updateTeams(teams)
      setTeamsSaved(true)
      setTimeout(() => setTeamsSaved(false), 2500)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to save teams.')
    } finally {
      setSavingTeams(false)
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading departments and teams…</div>
  }

  const activeDepartments = departments.filter(d => d.is_active)
  const unassignedTeams    = teams.filter(t => !t.department_id || !activeDepartments.some(d => d.id === t.department_id))

  return (
    <div style={{ maxWidth: 640 }}>
      <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 6px' }}>
        Departments &amp; Teams
      </h2>
      <p style={{ fontSize: 13, color: '#7A9BAD', margin: '0 0 24px', lineHeight: 1.6 }}>
        Group your teams under departments. This controls Reports hub tabs,
        who sees which reports, and where daily activity gets logged.
        Departments save immediately; team changes save when you click
        "Save Teams" below.
      </p>

      {error && (
        <p style={{ color: '#DC2626', fontSize: 13, margin: '0 0 16px' }}>⚠ {error}</p>
      )}

      {/* Departments */}
      <label style={LABEL}>Departments</label>
      {activeDepartments.length === 0 && (
        <div style={{
          padding: '16px 18px', background: '#F8FAFC',
          border: '1px dashed #CBD5E1', borderRadius: 8,
          fontSize: 13, color: '#7A9BAD', marginBottom: 16,
        }}>
          No departments yet. Add your first one below — teams can be sorted
          into it right away.
        </div>
      )}

      {activeDepartments.map((dept, index) => (
        <DepartmentCard
          key={dept.id}
          dept={dept}
          index={index}
          deptCount={activeDepartments.length}
          teamsInDept={teams.filter(t => t.department_id === dept.id)}
          allDepartments={activeDepartments}
          onRename={handleRenameDepartment}
          onMove={handleMoveDepartment}
          onDeactivate={handleDeactivateDepartment}
          onAddTeam={handleAddTeam}
          onRenameTeam={handleRenameTeam}
          onMoveTeamDept={handleMoveTeamDept}
          onToggleTeamActive={handleToggleTeamActive}
          onRemoveTeam={handleRemoveTeam}
        />
      ))}

      <div style={{ display: 'flex', gap: 8, marginBottom: 28 }}>
        <input
          value={newDeptName}
          onChange={e => setNewDeptName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddDepartment() } }}
          placeholder="e.g. Operations"
          style={{ ...INPUT, flex: 1 }}
          maxLength={80}
        />
        <button
          onClick={handleAddDepartment}
          disabled={!newDeptName.trim() || deptBusy}
          style={{
            background:   (newDeptName.trim() && !deptBusy) ? ds.teal : '#CBD5E1',
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '9px 18px',
            fontSize:     13.5,
            fontWeight:   600,
            cursor:       (newDeptName.trim() && !deptBusy) ? 'pointer' : 'not-allowed',
            fontFamily:   'inherit',
            whiteSpace:   'nowrap',
          }}
        >
          {deptBusy ? 'Adding…' : '+ Add department'}
        </button>
      </div>

      {/* Unassigned teams */}
      <label style={LABEL}>Unassigned teams</label>
      <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '-4px 0 10px' }}>
        Not yet sorted into a department — set one using the dropdown on
        each row above, or here.
      </p>
      {unassignedTeams.length === 0 ? (
        <div style={{
          padding: '14px 16px', background: '#F8FAFC',
          border: '1px dashed #CBD5E1', borderRadius: 8,
          fontSize: 13, color: '#7A9BAD', marginBottom: 20,
        }}>
          Every team is sorted into a department.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
          {unassignedTeams.map(team => (
            <TeamRow
              key={team.id}
              team={team}
              allDepartments={activeDepartments}
              onRename={handleRenameTeam}
              onMoveDept={handleMoveTeamDept}
              onToggleActive={handleToggleTeamActive}
              onRemove={handleRemoveTeam}
            />
          ))}
        </div>
      )}

      {/* Save Teams */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, borderTop: '1px solid #E3EEF2', paddingTop: 20 }}>
        <button
          onClick={handleSaveTeams}
          disabled={savingTeams}
          style={{
            background:   savingTeams ? '#aaa' : ds.teal,
            color:        'white',
            border:       'none',
            borderRadius: 8,
            padding:      '10px 24px',
            fontSize:     14,
            fontWeight:   600,
            cursor:       savingTeams ? 'not-allowed' : 'pointer',
            fontFamily:   ds.fontSyne,
          }}
        >
          {savingTeams ? 'Saving…' : 'Save Teams'}
        </button>
        {teamsSaved && (
          <span style={{ fontSize: 13, color: '#059669', fontWeight: 500 }}>
            ✓ Teams saved
          </span>
        )}
      </div>
    </div>
  )
}
