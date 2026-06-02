/**
 * frontend/src/modules/performance/KpiTemplateManager.jsx
 *
 * Admin KPI template editor (owner / ops_manager only).
 * Role types are expandable. Add / edit / remove KPI per role type.
 * Changes apply to new targets only — existing targets are never retroactively modified.
 */
import { useState, useEffect, useCallback } from 'react'
import { getKpiTemplates, createKpiTemplate, updateKpiTemplate, deleteKpiTemplate } from '../../services/performance.service'
import { ds } from '../../utils/ds'

const ROLE_TEMPLATES = ['sales_agent', 'support_agent', 'ops_manager', 'content_creator', 'website_manager', 'general_staff']
const KPI_UNITS      = ['count', 'currency', 'percentage', 'minutes']

const INPUT = {
  border: '1px solid #e5e7eb', borderRadius: 7, padding: '7px 10px',
  fontSize: 13, fontFamily: 'inherit', boxSizing: 'border-box',
}

function AddKpiRow({ role, onAdded }) {
  const [name,  setName]  = useState('')
  const [unit,  setUnit]  = useState('count')
  const [order, setOrder] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const handleAdd = async () => {
    if (!name.trim()) { setError('KPI name is required'); return }
    setLoading(true)
    setError(null)
    try {
      await createKpiTemplate({ role_template: role, kpi_name: name.trim(), kpi_unit: unit, sort_order: order })
      setName('')
      setUnit('count')
      setOrder(0)
      onAdded()
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to add KPI')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, padding: '10px 14px', background: '#f9fafb', alignItems: 'flex-end', flexWrap: 'wrap' }}>
      <div style={{ flex: 2, minWidth: 160 }}>
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 3 }}>KPI name *</div>
        <input value={name} onChange={e => setName(e.target.value)} maxLength={100} placeholder="e.g. Leads Contacted" style={{ ...INPUT, width: '100%' }} />
      </div>
      <div style={{ flex: 1, minWidth: 100 }}>
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 3 }}>Unit</div>
        <select value={unit} onChange={e => setUnit(e.target.value)} style={{ ...INPUT, width: '100%' }}>
          {KPI_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
        </select>
      </div>
      <div style={{ width: 70 }}>
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 3 }}>Order</div>
        <input type="number" min="0" value={order} onChange={e => setOrder(Number(e.target.value))} style={{ ...INPUT, width: '100%' }} />
      </div>
      <button
        onClick={handleAdd}
        disabled={loading}
        style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 7, padding: '7px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' }}
      >
        {loading ? 'Adding…' : '+ Add KPI'}
      </button>
      {error && <div style={{ width: '100%', fontSize: 12, color: '#991b1b' }}>⚠ {error}</div>}
    </div>
  )
}

function KpiRow({ kpi, onUpdated, onDeleted }) {
  const [editing,  setEditing]  = useState(false)
  const [name,     setName]     = useState(kpi.kpi_name)
  const [unit,     setUnit]     = useState(kpi.kpi_unit || 'count')
  const [order,    setOrder]    = useState(kpi.sort_order || 0)
  const [loading,  setLoading]  = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateKpiTemplate(kpi.id, { kpi_name: name, kpi_unit: unit, sort_order: order })
      setEditing(false)
      onUpdated()
    } catch {}
    finally { setLoading(false) }
  }

  const handleDelete = async () => {
    if (!window.confirm(`Remove "${kpi.kpi_name}" from this role template? Existing targets are unaffected.`)) return
    setDeleting(true)
    try {
      await deleteKpiTemplate(kpi.id)
      onDeleted()
    } catch {}
    finally { setDeleting(false) }
  }

  if (editing) {
    return (
      <div style={{ display: 'flex', gap: 8, padding: '8px 14px', alignItems: 'center', background: '#fffbeb', flexWrap: 'wrap' }}>
        <input value={name} onChange={e => setName(e.target.value)} maxLength={100} style={{ ...INPUT, flex: 2, minWidth: 120 }} />
        <select value={unit} onChange={e => setUnit(e.target.value)} style={{ ...INPUT, minWidth: 90 }}>
          {KPI_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
        </select>
        <input type="number" min="0" value={order} onChange={e => setOrder(Number(e.target.value))} style={{ ...INPUT, width: 60 }} />
        <button onClick={handleSave} disabled={loading} style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 6, padding: '5px 12px', fontSize: 12, cursor: 'pointer' }}>{loading ? '…' : 'Save'}</button>
        <button onClick={() => setEditing(false)} style={{ background: 'none', border: '1px solid #e5e7eb', borderRadius: 6, padding: '5px 10px', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', padding: '8px 14px', borderTop: '1px solid #f3f4f6' }}>
      <span style={{ flex: 1, fontSize: 13, color: kpi.is_active ? ds.dark : '#9ca3af', textDecoration: kpi.is_active ? 'none' : 'line-through' }}>{kpi.kpi_name}</span>
      <span style={{ fontSize: 11, color: '#9ca3af', marginRight: 12 }}>{kpi.kpi_unit}</span>
      <span style={{ fontSize: 11, color: '#9ca3af', marginRight: 16 }}>#{kpi.sort_order}</span>
      <button onClick={() => setEditing(true)} style={{ background: 'none', border: '1px solid #e5e7eb', borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer', color: '#374151', marginRight: 6 }}>Edit</button>
      <button onClick={handleDelete} disabled={deleting} style={{ background: 'none', border: '1px solid #fca5a5', borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer', color: '#dc2626' }}>
        {deleting ? '…' : 'Remove'}
      </button>
    </div>
  )
}

export default function KpiTemplateManager() {
  const [templates, setTemplates] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [expanded,  setExpanded]  = useState({})

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getKpiTemplates()
      setTemplates(data || [])
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load KPI templates')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const byRole = ROLE_TEMPLATES.reduce((acc, role) => {
    acc[role] = templates.filter(t => t.role_template === role && t.is_active)
    return acc
  }, {})

  const toggleRole = (role) => setExpanded(p => ({ ...p, [role]: !p[role] }))

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <p style={{ fontSize: 13, color: '#6b7280', margin: 0 }}>
          Define KPIs per role type. Changes apply to <strong>new targets only</strong> — existing targets are never retroactively modified.
        </p>
      </div>

      {loading && <div style={{ textAlign: 'center', padding: 40, color: '#7A9BAD', fontSize: 13 }}>Loading templates…</div>}
      {error   && <div style={{ background: '#fee2e2', borderRadius: 8, padding: '10px 14px', color: '#991b1b', fontSize: 13, marginBottom: 16 }}>⚠ {error}</div>}

      {!loading && ROLE_TEMPLATES.map(role => {
        const isOpen = !!expanded[role]
        const kpis   = byRole[role] || []
        return (
          <div key={role} style={{ background: 'white', borderRadius: 10, border: '1px solid #e5e7eb', marginBottom: 10, overflow: 'hidden' }}>
            <div
              onClick={() => toggleRole(role)}
              style={{ display: 'flex', alignItems: 'center', padding: '12px 16px', cursor: 'pointer', userSelect: 'none' }}
            >
              <span style={{ flex: 1, fontWeight: 600, fontSize: 13, color: ds.dark }}>{role.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
              <span style={{ fontSize: 11, color: '#9ca3af', marginRight: 10 }}>{kpis.length} KPI{kpis.length !== 1 ? 's' : ''}</span>
              <span style={{ fontSize: 13, color: '#9ca3af' }}>{isOpen ? '▲' : '▼'}</span>
            </div>
            {isOpen && (
              <>
                {kpis.map(kpi => (
                  <KpiRow key={kpi.id} kpi={kpi} onUpdated={fetchTemplates} onDeleted={fetchTemplates} />
                ))}
                {kpis.length === 0 && (
                  <div style={{ padding: '8px 14px', fontSize: 12, color: '#9ca3af', borderTop: '1px solid #f3f4f6' }}>No active KPIs — add one below.</div>
                )}
                <AddKpiRow role={role} onAdded={fetchTemplates} />
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
