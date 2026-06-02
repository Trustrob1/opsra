/**
 * frontend/src/modules/performance/BusinessGoalsTab.jsx
 *
 * PERF-1C — In-app business goals management tab.
 * Owner / ops_manager can set, edit, and remove org-level goals.
 * Live progress computed by the backend from existing data.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  getBusinessGoals,
  upsertBusinessGoal,
  deleteBusinessGoal,
} from '../../services/performance.service'
import { ds } from '../../utils/ds'

const CATEGORIES = [
  { value: 'sales',     label: 'Revenue / Sales' },
  { value: 'leads',     label: 'Leads Contacted' },
  { value: 'support',   label: 'Tickets Resolved' },
  { value: 'tasks',     label: 'Tasks Completed' },
  { value: 'content',   label: 'Posts Published' },
  { value: 'campaigns', label: 'Campaigns Launched' },
  { value: 'custom',    label: 'Custom (manual tracking)' },
]

const UNITS    = ['count', 'currency', 'percentage', 'minutes']
const PERIODS  = ['monthly', 'quarterly', 'annual']

const BADGE = (colour) => {
  if (colour === 'green') return { background: '#d1fae5', color: '#065f46' }
  if (colour === 'amber') return { background: '#fef3c7', color: '#92400e' }
  return { background: '#fee2e2', color: '#991b1b' }
}

const INPUT = {
  border: '1px solid #e5e7eb', borderRadius: 7, padding: '8px 10px',
  fontSize: 13, fontFamily: 'inherit', boxSizing: 'border-box', width: '100%',
}

function GoalRow({ goal, onDelete, onEdit }) {
  const pct    = Math.min(100, goal.achievement_pct || 0)
  const colour = goal.colour === 'green' ? '#10b981' : goal.colour === 'amber' ? '#f59e0b' : '#ef4444'

  return (
    <div style={{ padding: '14px 16px', borderBottom: '1px solid #f3f4f6' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: ds.dark }}>{goal.goal_name}</div>
          <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
            {CATEGORIES.find(c => c.value === goal.goal_category)?.label || goal.goal_category}
            {' · '}{goal.period_type}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#6b7280' }}>
            {Number(goal.current_value)?.toLocaleString()} / {Number(goal.target_value)?.toLocaleString()} {goal.unit}
          </span>
          <span style={{ ...BADGE(goal.colour), borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
            {goal.achievement_pct}%
          </span>
          <span style={{ fontSize: 11, fontWeight: 500, color: goal.pace === 'Ahead' ? '#10b981' : goal.pace === 'Behind' ? '#ef4444' : '#f59e0b' }}>
            {goal.pace}
          </span>
          <button onClick={() => onEdit(goal)} style={ICON_BTN}>✏</button>
          <button onClick={() => onDelete(goal)} style={{ ...ICON_BTN, color: '#dc2626', borderColor: '#fca5a5' }}>✕</button>
        </div>
      </div>
      <div style={{ background: '#f3f4f6', borderRadius: 4, height: 7 }}>
        <div style={{ background: colour, borderRadius: 4, height: 7, width: `${pct}%`, transition: 'width 0.4s ease' }} />
      </div>
      {goal.notes && <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 5 }}>{goal.notes}</div>}
    </div>
  )
}

function GoalForm({ initial, periodStart, onSaved, onCancel }) {
  const [goalName,  setGoalName]  = useState(initial?.goal_name     || '')
  const [category,  setCategory]  = useState(initial?.goal_category || 'sales')
  const [target,    setTarget]    = useState(initial?.target_value   || '')
  const [unit,      setUnit]      = useState(initial?.unit           || 'count')
  const [period,    setPeriod]    = useState(initial?.period_type    || 'monthly')
  const [notes,     setNotes]     = useState(initial?.notes          || '')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState(null)

  const handleSave = async () => {
    if (!goalName.trim() || !target) { setError('Goal name and target are required.'); return }
    setLoading(true)
    setError(null)
    try {
      await upsertBusinessGoal({
        goal_name:     goalName.trim(),
        goal_category: category,
        target_value:  Number(target),
        unit,
        period_type:   period,
        period_start:  periodStart,
        notes:         notes || null,
      })
      onSaved()
    } catch (e) {
      setError(e?.response?.data?.detail || 'Save failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ background: '#f9fafb', borderRadius: 10, border: '1px solid #e5e7eb', padding: 20, marginBottom: 16 }}>
      <div style={{ fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
        {initial ? 'Edit Goal' : 'Add New Goal'}
      </div>
      {error && <p style={{ color: '#991b1b', fontSize: 13, marginBottom: 10 }}>⚠ {error}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
        <div>
          <label style={LBL}>Goal name *</label>
          <input value={goalName} onChange={e => setGoalName(e.target.value)} maxLength={150} placeholder="e.g. Monthly Revenue" style={INPUT} />
        </div>
        <div>
          <label style={LBL}>Category *</label>
          <select value={category} onChange={e => setCategory(e.target.value)} style={INPUT}>
            {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
        <div>
          <label style={LBL}>Target *</label>
          <input type="number" min="0" value={target} onChange={e => setTarget(e.target.value)} placeholder="0" style={INPUT} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 10, marginBottom: 14 }}>
        <div>
          <label style={LBL}>Unit</label>
          <select value={unit} onChange={e => setUnit(e.target.value)} style={INPUT}>
            {UNITS.map(u => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div>
          <label style={LBL}>Period</label>
          <select value={period} onChange={e => setPeriod(e.target.value)} style={INPUT}>
            {PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label style={LBL}>Notes (optional)</label>
          <input value={notes} onChange={e => setNotes(e.target.value)} maxLength={500} style={INPUT} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onCancel} style={{ flex: 1, padding: '8px', border: '1px solid #e5e7eb', borderRadius: 7, cursor: 'pointer', background: 'white', fontSize: 13 }}>Cancel</button>
        <button onClick={handleSave} disabled={loading} style={{ flex: 2, padding: '8px', border: 'none', borderRadius: 7, cursor: 'pointer', background: ds.teal, color: 'white', fontSize: 13, fontWeight: 600 }}>
          {loading ? 'Saving…' : 'Save Goal'}
        </button>
      </div>
    </div>
  )
}

export default function BusinessGoalsTab() {
  const [goals,     setGoals]     = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [showForm,  setShowForm]  = useState(false)
  const [editGoal,  setEditGoal]  = useState(null)

  const periodStart = (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
  })()

  const fetchGoals = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getBusinessGoals(periodStart)
      setGoals(data || [])
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load goals')
    } finally {
      setLoading(false)
    }
  }, [periodStart])

  useEffect(() => { fetchGoals() }, [fetchGoals])

  const handleDelete = async (goal) => {
    if (!window.confirm(`Remove goal "${goal.goal_name}"?`)) return
    try {
      await deleteBusinessGoal(goal.id, periodStart)
      fetchGoals()
    } catch {}
  }

  const handleEdit = (goal) => {
    setEditGoal(goal)
    setShowForm(true)
  }

  const handleFormSaved = () => {
    setShowForm(false)
    setEditGoal(null)
    fetchGoals()
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <p style={{ fontSize: 13, color: '#6b7280', margin: 0 }}>
          Set org-level goals. Live progress is computed automatically from your data — no manual updates needed.
        </p>
        {!showForm && (
          <button
            onClick={() => { setShowForm(true); setEditGoal(null) }}
            style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '7px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap', marginLeft: 16 }}
          >
            + Add Goal
          </button>
        )}
      </div>

      {showForm && (
        <GoalForm
          initial={editGoal}
          periodStart={periodStart}
          onSaved={handleFormSaved}
          onCancel={() => { setShowForm(false); setEditGoal(null) }}
        />
      )}

      {loading && <div style={{ textAlign: 'center', padding: 40, color: '#7A9BAD', fontSize: 13 }}>Loading goals…</div>}
      {error   && <div style={{ background: '#fee2e2', borderRadius: 8, padding: '10px 14px', color: '#991b1b', fontSize: 13, marginBottom: 16 }}>⚠ {error}</div>}

      {!loading && goals.length === 0 && !showForm && (
        <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🎯</div>
          <div style={{ fontWeight: 600, fontSize: 15, color: ds.dark, marginBottom: 6 }}>No goals set for this period</div>
          <p style={{ fontSize: 13, color: '#9ca3af', margin: '0 0 16px' }}>Add your first business goal to start tracking progress.</p>
          <button
            onClick={() => setShowForm(true)}
            style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '8px 20px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            + Add First Goal
          </button>
        </div>
      )}

      {goals.length > 0 && (
        <div style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', overflow: 'hidden' }}>
          {goals.map(g => (
            <GoalRow key={g.id} goal={g} onDelete={handleDelete} onEdit={handleEdit} />
          ))}
        </div>
      )}
    </div>
  )
}

const LBL = { fontSize: 11, color: '#6b7280', display: 'block', marginBottom: 3 }
const ICON_BTN = {
  background: 'none', border: '1px solid #e5e7eb', borderRadius: 5,
  padding: '3px 8px', fontSize: 12, cursor: 'pointer', color: '#374151',
}
