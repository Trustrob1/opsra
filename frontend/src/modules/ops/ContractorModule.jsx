/**
 * frontend/src/modules/ops/ContractorModule.jsx
 * CPM-1 + CPM-1A — Contractor Performance Management
 *
 * Three-tab module:
 *   📋 Scorecard   — one card per contractor, KPI status, termination risk banner
 *   🤝 Contractors — list + ContractorDetailPanel drawer (Overview / KPI Tracker / Tasks)
 *   ✅ Tasks        — all tasks across contractors, filterable, overdue highlighted
 *
 * Pattern 11: JWT via Zustand only
 * Pattern 12: org_id never in payloads
 * Pattern 13: useState navigation — no react-router-dom
 * Pattern 26: mount-and-hide for tab panels
 * Pattern 56: role check via user?.roles?.template
 *
 * CPM-1A additions:
 *   ContractorCreateModal Step 3 — "📄 Parse from Contract" + "📋 Load Template ▾"
 *   Step 4 — risk clauses auto-filled from parser result
 *
 * Props:
 *   user — current user object from Zustand auth store
 */

import { useState, useEffect, useRef } from 'react'
import { ds } from '../../utils/ds'
import {
  getContractorScorecard,
  listContractors,
  createContractor,
  getContractor,
  updateContractor,
  deleteContractor,
  getKpiActuals,
  logKpiActual,
  getContractorTasks,
  createContractorTask,
  updateContractorTask,
  generateContractorTasks,
  parseContractKpis,
} from '../../services/contractors.service'
import { KPI_TEMPLATES } from './contractorKpiTemplates'

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_COLORS = {
  active:     { bg: '#e6f4ea', color: '#1e7e34' },
  completed:  { bg: '#e8f0fe', color: '#1a56db' },
  terminated: { bg: '#fce8e6', color: '#c5221f' },
  paused:     { bg: '#fef3e2', color: '#b45309' },
}

const KPI_STATUS_COLORS = {
  on_track: { bg: '#e6f4ea', color: '#1e7e34', label: 'On Track' },
  at_risk:  { bg: '#fef3e2', color: '#b45309', label: 'At Risk'  },
  off_track:{ bg: '#fce8e6', color: '#c5221f', label: 'Off Track'},
  pending:  { bg: '#f1f3f4', color: '#5f6368', label: 'Pending'  },
}

const TASK_STATUS_OPTIONS = [
  { value: 'not_started', label: 'Not Started', color: '#5f6368' },
  { value: 'in_progress', label: 'In Progress', color: '#1a56db' },
  { value: 'done',        label: 'Done',        color: '#1e7e34' },
  { value: 'blocked',     label: 'Blocked',     color: '#c5221f' },
]

const KPI_TYPE_OPTIONS = [
  { value: 'leads_generated', label: 'Count / Leads Generated' },
  { value: 'conversion_rate', label: 'Conversion Rate (%)' },
  { value: 'response_time',   label: 'Response Time (lower is better)' },
  { value: 'manual',          label: 'Manual (no numeric comparison)' },
]

const FEE_STRUCTURE_OPTIONS = [
  { value: 'monthly_retainer', label: 'Monthly Retainer' },
  { value: 'fixed_total',      label: 'Fixed Total' },
  { value: 'milestone',        label: 'Milestone' },
]

// ── Shared small components ───────────────────────────────────────────────────

function Badge({ bg, color, children }) {
  return (
    <span style={{
      background: bg, color, borderRadius: 6,
      padding: '2px 8px', fontSize: 11, fontWeight: 600,
      fontFamily: ds.fontDm, whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

function KpiStatusBadge({ statusKey }) {
  const s = KPI_STATUS_COLORS[statusKey] || KPI_STATUS_COLORS.pending
  return <Badge bg={s.bg} color={s.color}>{s.label}</Badge>
}

function Spinner() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
      <div style={{
        width: 28, height: 28, border: `3px solid #e0e0e0`,
        borderTop: `3px solid ${ds.teal}`, borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

function EmptyState({ icon, title, sub }) {
  return (
    <div style={{ textAlign: 'center', padding: '56px 24px', color: ds.gray }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>{icon}</div>
      <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13 }}>{sub}</div>
    </div>
  )
}

function SectionHeader({ title, action }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
      <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: ds.dark, margin: 0 }}>{title}</h3>
      {action}
    </div>
  )
}

function Btn({ onClick, children, variant = 'primary', small, disabled, style: extraStyle }) {
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: small ? '6px 12px' : '9px 18px',
    borderRadius: 8, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: ds.fontDm, fontWeight: 600,
    fontSize: small ? 12 : 13, transition: 'opacity 0.15s',
    opacity: disabled ? 0.5 : 1,
    ...extraStyle,
  }
  if (variant === 'primary')   return <button onClick={onClick} disabled={disabled} style={{ ...base, background: ds.teal, color: 'white' }}>{children}</button>
  if (variant === 'secondary') return <button onClick={onClick} disabled={disabled} style={{ ...base, background: '#f1f3f4', color: ds.dark }}>{children}</button>
  if (variant === 'danger')    return <button onClick={onClick} disabled={disabled} style={{ ...base, background: '#fce8e6', color: '#c5221f' }}>{children}</button>
  if (variant === 'ghost')     return <button onClick={onClick} disabled={disabled} style={{ ...base, background: 'none', color: ds.teal, padding: small ? '4px 8px' : '7px 14px' }}>{children}</button>
  return <button onClick={onClick} disabled={disabled} style={base}>{children}</button>
}

function Input({ label, value, onChange, type = 'text', placeholder, required, style: s }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...s }}>
      {label && <label style={{ fontSize: 12, fontWeight: 600, color: ds.dark, fontFamily: ds.fontDm }}>{label}{required && <span style={{ color: '#c5221f' }}> *</span>}</label>}
      <input
        type={type} value={value ?? ''} onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          border: '1px solid #dde4e8', borderRadius: 8, padding: '8px 12px',
          fontSize: 13, fontFamily: ds.fontDm, outline: 'none',
          background: 'white', color: ds.dark,
        }}
      />
    </div>
  )
}

function Select({ label, value, onChange, options, required, style: s }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...s }}>
      {label && <label style={{ fontSize: 12, fontWeight: 600, color: ds.dark, fontFamily: ds.fontDm }}>{label}{required && <span style={{ color: '#c5221f' }}> *</span>}</label>}
      <select
        value={value ?? ''} onChange={e => onChange(e.target.value)}
        style={{
          border: '1px solid #dde4e8', borderRadius: 8, padding: '8px 12px',
          fontSize: 13, fontFamily: ds.fontDm, outline: 'none',
          background: 'white', color: ds.dark,
        }}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

function Textarea({ label, value, onChange, placeholder, rows = 3, style: s }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...s }}>
      {label && <label style={{ fontSize: 12, fontWeight: 600, color: ds.dark, fontFamily: ds.fontDm }}>{label}</label>}
      <textarea
        value={value ?? ''} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} rows={rows}
        style={{
          border: '1px solid #dde4e8', borderRadius: 8, padding: '8px 12px',
          fontSize: 13, fontFamily: ds.fontDm, outline: 'none',
          background: 'white', color: ds.dark, resize: 'vertical',
        }}
      />
    </div>
  )
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

function TabBar({ active, onChange, tabs }) {
  return (
    <div style={{
      display: 'flex', gap: 4, borderBottom: '1px solid #dde4e8',
      padding: '0 28px', background: 'white',
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.id
        return (
          <button key={tab.id} onClick={() => onChange(tab.id)} style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '12px 14px 10px', background: 'none', border: 'none',
            borderBottom: isActive ? `2px solid ${ds.teal}` : '2px solid transparent',
            cursor: 'pointer', fontSize: 13, fontWeight: isActive ? 600 : 400,
            fontFamily: ds.fontDm, color: isActive ? ds.teal : ds.gray,
            transition: 'all 0.15s', whiteSpace: 'nowrap', marginBottom: -1,
          }}>
            <span>{tab.icon}</span>{tab.label}
          </button>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 1 — SCORECARD
// ─────────────────────────────────────────────────────────────────────────────

function ScorecardTab({ onSelectContractor }) {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  useEffect(() => {
    getContractorScorecard()
      .then(d => setData(d))
      .catch(() => setError('Could not load scorecard'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />
  if (error)   return <div style={{ padding: 32, color: '#c5221f', fontSize: 13 }}>{error}</div>
  if (!data?.items?.length) return (
    <EmptyState icon="📋" title="No contractors yet" sub="Add a contractor to start tracking performance" />
  )

  return (
    <div style={{ padding: 28 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 20 }}>
        {data.items.map(c => <ScorecardCard key={c.id} contractor={c} onSelect={() => onSelectContractor(c)} />)}
      </div>
    </div>
  )
}

function ScorecardCard({ contractor: c, onSelect }) {
  const risk    = c.risk_summary || {}
  const targets = c.kpi_targets  || []
  const months  = c.kpi_months   || {}
  const monthLabels = Object.keys(months).sort((a, b) => {
    const n = s => parseInt(s.replace('Month', '').trim()) || 0
    return n(a) - n(b)
  })
  const sc = STATUS_COLORS[c.status] || STATUS_COLORS.active

  return (
    <div
      onClick={onSelect}
      style={{
        background: 'white', borderRadius: 12, border: '1px solid #dde4e8',
        overflow: 'hidden', cursor: 'pointer', transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.08)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
    >
      {/* Risk banner */}
      {risk.at_termination_risk && (
        <div style={{
          background: '#fce8e6', borderBottom: '1px solid #f5c6c2',
          padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 14 }}>⚠️</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#c5221f', fontFamily: ds.fontDm }}>
            Termination Risk — {risk.consecutive_months_off_track}+ consecutive months below target
          </span>
        </div>
      )}

      <div style={{ padding: 20 }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark }}>{c.full_name}</div>
            <div style={{ fontSize: 12, color: ds.gray, marginTop: 2 }}>{c.role_title}</div>
          </div>
          <Badge bg={sc.bg} color={sc.color}>{c.status}</Badge>
        </div>

        {/* Contract dates */}
        <div style={{ fontSize: 12, color: ds.gray, marginBottom: 14 }}>
          {c.contract_start} — {c.contract_end || 'Ongoing'}
          <span style={{ marginLeft: 12, fontWeight: 600, color: ds.dark }}>
            {new Intl.NumberFormat('en-NG', { style: 'currency', currency: c.fee_currency || 'NGN', maximumFractionDigits: 0 }).format(c.fee_amount)}
            <span style={{ fontWeight: 400, color: ds.gray }}> / {c.fee_structure?.replace('_', ' ')}</span>
          </span>
        </div>

        {/* KPI summary — last month */}
        {targets.length > 0 && monthLabels.length > 0 && (() => {
          const lastMonth = monthLabels[monthLabels.length - 1]
          const monthData = months[lastMonth] || {}
          return (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: ds.gray, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                {lastMonth} KPIs
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {targets.map(kpi => {
                  const kd = monthData[kpi.key] || {}
                  return (
                    <div key={kpi.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{ fontSize: 11, color: ds.dark }}>{kpi.label}:</span>
                      <KpiStatusBadge statusKey={kd.status || 'pending'} />
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {targets.length === 0 && (
          <div style={{ fontSize: 12, color: ds.gray, fontStyle: 'italic' }}>No KPI targets defined</div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 2 — CONTRACTORS LIST + DETAIL PANEL
// ─────────────────────────────────────────────────────────────────────────────

function ContractorsTab({ user, onOpenCreate, refreshKey }) {
  const [contractors, setContractors] = useState([])
  const [loading, setLoading]         = useState(true)
  const [selected, setSelected]       = useState(null)
  const [detailOpen, setDetailOpen]   = useState(false)

  const load = () => {
    setLoading(true)
    listContractors()
      .then(d => setContractors(d.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [refreshKey])

  const handleSelect = (c) => {
    setSelected(c)
    setDetailOpen(true)
  }

  const handleClose = (didUpdate) => {
    setDetailOpen(false)
    if (didUpdate) load()
  }

  if (loading) return <Spinner />

  return (
    <div style={{ padding: 28 }}>
      <SectionHeader
        title={`Contractors (${contractors.length})`}
        action={<Btn onClick={onOpenCreate} small>+ Add Contractor</Btn>}
      />

      {!contractors.length ? (
        <EmptyState icon="🤝" title="No contractors added yet" sub='Click "+ Add Contractor" to create your first contractor profile' />
      ) : (
        <div style={{ background: 'white', borderRadius: 12, border: '1px solid #dde4e8', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#f8fafc' }}>
                {['Name', 'Role', 'Contract Period', 'Fee', 'Status', ''].map(h => (
                  <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: ds.gray, fontFamily: ds.fontDm, textTransform: 'uppercase', letterSpacing: 0.4 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {contractors.map((c, i) => {
                const sc = STATUS_COLORS[c.status] || STATUS_COLORS.active
                return (
                  <tr
                    key={c.id}
                    onClick={() => handleSelect(c)}
                    style={{
                      borderTop: i > 0 ? '1px solid #f1f3f4' : 'none',
                      cursor: 'pointer', transition: 'background 0.1s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                    onMouseLeave={e => e.currentTarget.style.background = 'white'}
                  >
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: ds.dark, fontFamily: ds.fontDm }}>{c.full_name}</div>
                      {c.email && <div style={{ fontSize: 11, color: ds.gray }}>{c.email}</div>}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: 13, color: ds.dark }}>{c.role_title}</td>
                    <td style={{ padding: '12px 16px', fontSize: 12, color: ds.gray }}>
                      {c.contract_start} — {c.contract_end || 'Ongoing'}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: 13, color: ds.dark }}>
                      {new Intl.NumberFormat('en-NG', { style: 'currency', currency: c.fee_currency || 'NGN', maximumFractionDigits: 0 }).format(c.fee_amount)}
                      <span style={{ fontSize: 11, color: ds.gray, marginLeft: 4 }}>/ {c.fee_structure?.replace('_', ' ')}</span>
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <Badge bg={sc.bg} color={sc.color}>{c.status}</Badge>
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <span style={{ color: ds.teal, fontSize: 13 }}>›</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {detailOpen && selected && (
        <ContractorDetailPanel
          contractorId={selected.id}
          user={user}
          onClose={handleClose}
        />
      )}
    </div>
  )
}

// ── Contractor Detail Panel (right drawer) ────────────────────────────────────

function ContractorDetailPanel({ contractorId, user, onClose }) {
  const [contractor, setContractor] = useState(null)
  const [loading, setLoading]       = useState(true)
  const [activeTab, setActiveTab]   = useState('overview')
  const [didUpdate, setDidUpdate]   = useState(false)

  const load = () => {
    setLoading(true)
    getContractor(contractorId)
      .then(d => setContractor(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [contractorId])

  const handleUpdate = () => { setDidUpdate(true); load() }

  const detailTabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'kpis',     label: 'KPI Tracker' },
    { id: 'tasks',    label: 'Tasks' },
  ]

  return (
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0,
      width: 580, background: 'white', boxShadow: '-4px 0 24px rgba(0,0,0,0.12)',
      zIndex: 200, display: 'flex', flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{ padding: '20px 24px', borderBottom: '1px solid #dde4e8', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <div>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark }}>
            {loading ? 'Loading…' : contractor?.full_name}
          </div>
          {!loading && contractor && (
            <div style={{ fontSize: 12, color: ds.gray, marginTop: 2 }}>{contractor.role_title}</div>
          )}
        </div>
        <button onClick={() => onClose(didUpdate)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: ds.gray, padding: 4 }}>✕</button>
      </div>

      {/* Sub-tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid #dde4e8', flexShrink: 0 }}>
        {detailTabs.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            flex: 1, padding: '10px 0', background: 'none', border: 'none',
            borderBottom: activeTab === t.id ? `2px solid ${ds.teal}` : '2px solid transparent',
            cursor: 'pointer', fontSize: 13, fontWeight: activeTab === t.id ? 600 : 400,
            fontFamily: ds.fontDm, color: activeTab === t.id ? ds.teal : ds.gray,
            marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {loading ? <Spinner /> : !contractor ? (
          <div style={{ color: ds.gray, fontSize: 13 }}>Could not load contractor.</div>
        ) : (
          <>
            <div style={{ display: activeTab === 'overview' ? 'block' : 'none' }}>
              <OverviewPanel contractor={contractor} onUpdate={handleUpdate} />
            </div>
            <div style={{ display: activeTab === 'kpis' ? 'block' : 'none' }}>
              <KpiTrackerPanel contractor={contractor} onUpdate={handleUpdate} />
            </div>
            <div style={{ display: activeTab === 'tasks' ? 'block' : 'none' }}>
              <TasksPanel contractor={contractor} onUpdate={handleUpdate} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Overview sub-panel ────────────────────────────────────────────────────────

function OverviewPanel({ contractor: c, onUpdate }) {
  const fmt = (val) => val || '—'
  const fmtCurrency = (amount, currency) =>
    new Intl.NumberFormat('en-NG', { style: 'currency', currency: currency || 'NGN', maximumFractionDigits: 0 }).format(amount)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Contract Terms */}
      <Section title="Contract Terms">
        <Grid2>
          <Field label="Start Date"      value={fmt(c.contract_start)} />
          <Field label="End Date"        value={fmt(c.contract_end)} />
          <Field label="Duration"        value={c.contract_months ? `${c.contract_months} months` : '—'} />
          <Field label="Status">
            {(() => { const s = STATUS_COLORS[c.status] || STATUS_COLORS.active; return <Badge bg={s.bg} color={s.color}>{c.status}</Badge> })()}
          </Field>
        </Grid2>
      </Section>

      {/* Fee Structure */}
      <Section title="Fee Structure">
        <Grid2>
          <Field label="Fee"             value={`${fmtCurrency(c.fee_amount, c.fee_currency)} (${c.fee_currency})`} />
          <Field label="Structure"       value={fmt(c.fee_structure?.replace(/_/g, ' '))} />
          <Field label="Payment Schedule" value={fmt(c.payment_schedule)} span={2} />
          {c.fee_notes && <Field label="Notes" value={c.fee_notes} span={2} />}
        </Grid2>
      </Section>

      {/* Contact */}
      <Section title="Contact">
        <Grid2>
          <Field label="Email" value={fmt(c.email)} />
          <Field label="Phone" value={fmt(c.phone)} />
        </Grid2>
      </Section>

      {/* Risk Clauses */}
      {c.risk_clauses?.length > 0 && (
        <Section title="Contract Risk Clauses">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {c.risk_clauses.map((rc, i) => (
              <div key={i} style={{ background: '#fff8f0', border: '1px solid #fde8c8', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#b45309', marginBottom: 4 }}>{rc.clause_ref}</div>
                <div style={{ fontSize: 12, color: ds.dark, marginBottom: 4 }}><strong>Trigger:</strong> {rc.trigger_description}</div>
                <div style={{ fontSize: 12, color: ds.dark }}><strong>Consequence:</strong> {rc.consequence}</div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: ds.gray, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  )
}

function Grid2({ children }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 16px' }}>
      {children}
    </div>
  )
}

function Field({ label, value, children, span }) {
  return (
    <div style={{ gridColumn: span === 2 ? '1 / -1' : undefined }}>
      <div style={{ fontSize: 11, color: ds.gray, fontWeight: 600, marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 13, color: ds.dark }}>{children || value}</div>
    </div>
  )
}

// ── KPI Tracker sub-panel ─────────────────────────────────────────────────────

function KpiTrackerPanel({ contractor, onUpdate }) {
  const [actuals, setActuals]       = useState([])
  const [saving, setSaving]         = useState(false)
  const [editCell, setEditCell]     = useState(null) // { month_label, kpi_key }
  const [editValue, setEditValue]   = useState('')
  const [editNotes, setEditNotes]   = useState('')
  const [monthInput, setMonthInput] = useState({ label: '', start: '' })
  const [showAddMonth, setShowAddMonth] = useState(false)

  const targets = contractor.kpi_targets || []
  const months  = contractor.kpi_months  || {}
  const risk    = contractor.risk_summary || {}

  const monthLabels = Object.keys(months).sort((a, b) => {
    const n = s => parseInt(s.replace('Month', '').trim()) || 0
    return n(a) - n(b)
  })

  const getActualValue = (monthLabel, kpiKey) => {
    const m = months[monthLabel] || {}
    return m[kpiKey]?.actual_value ?? ''
  }

  const handleSaveActual = async () => {
    if (!editCell) return
    setSaving(true)
    try {
      const { month_label, kpi_key } = editCell
      // Derive month_start from existing data or use today as fallback
      const existing = contractor.kpi_actuals_raw?.find(
        a => a.month_label === month_label && a.kpi_key === kpi_key
      )
      const month_start = existing?.month_start || new Date().toISOString().split('T')[0]
      await logKpiActual(contractor.id, {
        month_label,
        month_start,
        kpi_key,
        actual_value: editValue === '' ? null : parseFloat(editValue),
        notes: editNotes || null,
      })
      setEditCell(null)
      onUpdate()
    } catch {
      alert('Failed to save KPI actual.')
    } finally {
      setSaving(false)
    }
  }

  if (!targets.length) return (
    <EmptyState icon="📊" title="No KPI targets defined" sub="Edit this contractor to add KPI targets" />
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Risk summary */}
      {risk.at_termination_risk && (
        <div style={{ background: '#fce8e6', border: '1px solid #f5c6c2', borderRadius: 8, padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#c5221f' }}>
            ⚠️ Termination Risk — {risk.consecutive_months_off_track} consecutive months below target
          </div>
          <div style={{ fontSize: 12, color: '#c5221f', marginTop: 4 }}>
            Off-track months: {risk.missed_kpi_months?.join(', ')}
          </div>
        </div>
      )}

      {/* KPI table */}
      {monthLabels.length === 0 ? (
        <EmptyState icon="📅" title="No actuals logged yet" sub="Add a month below to start logging KPI actuals" />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#f8fafc' }}>
                <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 700, color: ds.gray, borderBottom: '1px solid #dde4e8' }}>KPI</th>
                <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 700, color: ds.gray, borderBottom: '1px solid #dde4e8' }}>Target</th>
                {monthLabels.map(ml => (
                  <th key={ml} style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, color: ds.gray, borderBottom: '1px solid #dde4e8', whiteSpace: 'nowrap' }}>{ml}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {targets.map(kpi => (
                <tr key={kpi.key} style={{ borderBottom: '1px solid #f1f3f4' }}>
                  <td style={{ padding: '8px 12px', fontWeight: 600, color: ds.dark }}>{kpi.label}</td>
                  <td style={{ padding: '8px 12px', color: ds.gray }}>{kpi.target_label || kpi.target_value || '—'}</td>
                  {monthLabels.map(ml => {
                    const md = months[ml]?.[kpi.key] || {}
                    const isEditing = editCell?.month_label === ml && editCell?.kpi_key === kpi.key
                    return (
                      <td key={ml} style={{ padding: '6px 8px', textAlign: 'center' }}>
                        {isEditing ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 100 }}>
                            <input
                              type="number" value={editValue} autoFocus
                              onChange={e => setEditValue(e.target.value)}
                              style={{ border: `1px solid ${ds.teal}`, borderRadius: 6, padding: '4px 6px', fontSize: 12, width: '100%' }}
                            />
                            <input
                              type="text" value={editNotes} placeholder="Notes (optional)"
                              onChange={e => setEditNotes(e.target.value)}
                              style={{ border: '1px solid #dde4e8', borderRadius: 6, padding: '4px 6px', fontSize: 11, width: '100%' }}
                            />
                            <div style={{ display: 'flex', gap: 4 }}>
                              <Btn onClick={handleSaveActual} small disabled={saving}>✓</Btn>
                              <Btn onClick={() => setEditCell(null)} small variant="secondary">✕</Btn>
                            </div>
                          </div>
                        ) : (
                          <div
                            onClick={() => { setEditCell({ month_label: ml, kpi_key: kpi.key }); setEditValue(md.actual_value ?? ''); setEditNotes('') }}
                            style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}
                          >
                            {md.actual_value != null ? (
                              <>
                                <span style={{ fontWeight: 600, color: ds.dark }}>{md.actual_value}</span>
                                <KpiStatusBadge statusKey={md.status || 'pending'} />
                              </>
                            ) : (
                              <span style={{ color: '#c0c7cc', fontSize: 11 }}>— click to log</span>
                            )}
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add month */}
      {!showAddMonth ? (
        <Btn onClick={() => setShowAddMonth(true)} variant="secondary" small>+ Log New Month</Btn>
      ) : (
        <div style={{ background: '#f8fafc', border: '1px solid #dde4e8', borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: ds.dark }}>Log actuals for a new month</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Input label="Month Label" value={monthInput.label} onChange={v => setMonthInput(p => ({ ...p, label: v }))} placeholder="e.g. Month 3" />
            <Input label="Month Start Date" type="date" value={monthInput.start} onChange={v => setMonthInput(p => ({ ...p, start: v }))} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {targets.map(kpi => (
              <Btn
                key={kpi.key}
                small variant="secondary"
                onClick={() => {
                  if (!monthInput.label || !monthInput.start) { alert('Enter month label and start date first.'); return }
                  setEditCell({ month_label: monthInput.label, kpi_key: kpi.key })
                  setEditValue('')
                  setEditNotes('')
                  setShowAddMonth(false)
                }}
              >
                Log {kpi.label}
              </Btn>
            ))}
            <Btn onClick={() => setShowAddMonth(false)} small variant="ghost">Cancel</Btn>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tasks sub-panel ───────────────────────────────────────────────────────────

function TasksPanel({ contractor, onUpdate }) {
  const [tasks, setTasks]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving]     = useState(null)

  const load = () => {
    setLoading(true)
    getContractorTasks(contractor.id)
      .then(d => setTasks(d.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [contractor.id])

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const r = await generateContractorTasks(contractor.id)
      load()
      if (r.created === 0) alert('No new tasks to generate (all template tasks already exist).')
    } catch {
      alert('Failed to generate tasks.')
    } finally {
      setGenerating(false)
    }
  }

  const handleStatusChange = async (task, newStatus) => {
    setSaving(task.id)
    try {
      await updateContractorTask(contractor.id, task.id, { status: newStatus })
      load()
    } catch {
      alert('Failed to update task.')
    } finally {
      setSaving(null)
    }
  }

  const today = new Date().toISOString().split('T')[0]
  const overdue = (task) => task.due_date && task.due_date < today && task.status !== 'done'

  if (loading) return <Spinner />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SectionHeader
        title={`Tasks (${tasks.length})`}
        action={
          <div style={{ display: 'flex', gap: 8 }}>
            {contractor.task_template?.length > 0 && (
              <Btn onClick={handleGenerate} small variant="secondary" disabled={generating}>
                {generating ? 'Generating…' : '⚡ Generate Tasks'}
              </Btn>
            )}
          </div>
        }
      />

      {!tasks.length ? (
        <EmptyState icon="✅" title="No tasks yet" sub={contractor.task_template?.length ? 'Click "Generate Tasks" to create from template' : 'No task template defined on this contractor'} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tasks.map(task => {
            const isOverdue = overdue(task)
            const sc = TASK_STATUS_OPTIONS.find(s => s.value === task.status) || TASK_STATUS_OPTIONS[0]
            return (
              <div key={task.id} style={{
                background: isOverdue ? '#fff8f0' : 'white',
                border: `1px solid ${isOverdue ? '#fde8c8' : '#dde4e8'}`,
                borderRadius: 8, padding: '12px 14px',
                display: 'flex', alignItems: 'flex-start', gap: 12,
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: ds.dark }}>{task.task_description}</div>
                  <div style={{ fontSize: 11, color: ds.gray, marginTop: 3, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    {task.phase && <span>Phase: {task.phase}</span>}
                    {task.week_number && <span>Week {task.week_number}</span>}
                    {task.due_date && <span style={{ color: isOverdue ? '#c5221f' : ds.gray }}>Due: {task.due_date}{isOverdue ? ' ⚠' : ''}</span>}
                    {task.owner && <span>Owner: {task.owner}</span>}
                  </div>
                </div>
                <select
                  value={task.status}
                  disabled={saving === task.id}
                  onChange={e => handleStatusChange(task, e.target.value)}
                  style={{
                    border: '1px solid #dde4e8', borderRadius: 6, padding: '4px 8px',
                    fontSize: 11, fontWeight: 600, color: sc.color, fontFamily: ds.fontDm,
                    background: 'white', cursor: 'pointer', flexShrink: 0,
                  }}
                >
                  {TASK_STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 3 — ALL TASKS
// ─────────────────────────────────────────────────────────────────────────────

function AllTasksTab({ refreshKey }) {
  const [contractors, setContractors] = useState([])
  const [taskMap, setTaskMap]         = useState({})
  const [loading, setLoading]         = useState(true)
  const [filterContractor, setFilterContractor] = useState('all')
  const [filterStatus, setFilterStatus]         = useState('all')
  const [saving, setSaving]           = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const list = await listContractors()
      const ctrs = list.items || []
      setContractors(ctrs)
      const results = await Promise.all(
        ctrs.map(c => getContractorTasks(c.id).then(d => ({ id: c.id, tasks: d.items || [] })))
      )
      const map = {}
      results.forEach(r => { map[r.id] = r.tasks })
      setTaskMap(map)
    } catch {}
    setLoading(false)
  }

  useEffect(() => { load() }, [refreshKey])

  const handleStatusChange = async (contractorId, task, newStatus) => {
    setSaving(task.id)
    try {
      await updateContractorTask(contractorId, task.id, { status: newStatus })
      load()
    } catch { alert('Failed to update task.') }
    finally { setSaving(null) }
  }

  const today = new Date().toISOString().split('T')[0]
  const overdue = (task) => task.due_date && task.due_date < today && task.status !== 'done'

  const visibleContractors = contractors.filter(c =>
    filterContractor === 'all' || c.id === filterContractor
  )

  if (loading) return <Spinner />

  const hasAnyTasks = contractors.some(c => (taskMap[c.id] || []).length > 0)

  return (
    <div style={{ padding: 28 }}>
      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <select
          value={filterContractor}
          onChange={e => setFilterContractor(e.target.value)}
          style={{ border: '1px solid #dde4e8', borderRadius: 8, padding: '7px 12px', fontSize: 13, fontFamily: ds.fontDm, background: 'white' }}
        >
          <option value="all">All Contractors</option>
          {contractors.map(c => <option key={c.id} value={c.id}>{c.full_name}</option>)}
        </select>
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          style={{ border: '1px solid #dde4e8', borderRadius: 8, padding: '7px 12px', fontSize: 13, fontFamily: ds.fontDm, background: 'white' }}
        >
          <option value="all">All Statuses</option>
          {TASK_STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {!hasAnyTasks ? (
        <EmptyState icon="✅" title="No tasks found" sub="Generate tasks from contractor profiles to see them here" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {visibleContractors.map(c => {
            let tasks = taskMap[c.id] || []
            if (filterStatus !== 'all') tasks = tasks.filter(t => t.status === filterStatus)
            if (!tasks.length) return null
            return (
              <div key={c.id}>
                <div style={{ fontSize: 13, fontWeight: 700, color: ds.dark, fontFamily: ds.fontSyne, marginBottom: 10 }}>
                  {c.full_name} <span style={{ color: ds.gray, fontWeight: 400, fontFamily: ds.fontDm }}>— {c.role_title}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {tasks.map(task => {
                    const isOverdue = overdue(task)
                    const sc = TASK_STATUS_OPTIONS.find(s => s.value === task.status) || TASK_STATUS_OPTIONS[0]
                    return (
                      <div key={task.id} style={{
                        background: isOverdue ? '#fff8f0' : 'white',
                        border: `1px solid ${isOverdue ? '#fde8c8' : '#dde4e8'}`,
                        borderRadius: 8, padding: '10px 14px',
                        display: 'flex', alignItems: 'center', gap: 12,
                      }}>
                        <div style={{ flex: 1 }}>
                          <span style={{ fontSize: 13, color: ds.dark }}>{task.task_description}</span>
                          <div style={{ fontSize: 11, color: ds.gray, marginTop: 2, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            {task.week_number && <span>Week {task.week_number}</span>}
                            {task.due_date && <span style={{ color: isOverdue ? '#c5221f' : ds.gray }}>Due: {task.due_date}{isOverdue ? ' ⚠' : ''}</span>}
                          </div>
                        </div>
                        <select
                          value={task.status}
                          disabled={saving === task.id}
                          onChange={e => handleStatusChange(c.id, task, e.target.value)}
                          style={{
                            border: '1px solid #dde4e8', borderRadius: 6, padding: '4px 8px',
                            fontSize: 11, fontWeight: 600, color: sc.color,
                            fontFamily: ds.fontDm, background: 'white', cursor: 'pointer',
                          }}
                        >
                          {TASK_STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// CONTRACTOR CREATE MODAL (5 steps + CPM-1A enhancements on Steps 3 + 4)
// ─────────────────────────────────────────────────────────────────────────────

function ContractorCreateModal({ onClose, onCreated }) {
  const STEPS = ['Identity', 'Contract', 'KPI Targets', 'Risk Clauses', 'Task Template']
  const [step, setStep]     = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  // Step 1
  const [fullName, setFullName]   = useState('')
  const [roleTitle, setRoleTitle] = useState('')
  const [email, setEmail]         = useState('')
  const [phone, setPhone]         = useState('')

  // Step 2
  const [contractStart, setContractStart]       = useState('')
  const [contractEnd, setContractEnd]           = useState('')
  const [contractMonths, setContractMonths]     = useState('')
  const [feeStructure, setFeeStructure]         = useState('monthly_retainer')
  const [feeAmount, setFeeAmount]               = useState('')
  const [feeCurrency, setFeeCurrency]           = useState('NGN')
  const [feeNotes, setFeeNotes]                 = useState('')
  const [paymentSchedule, setPaymentSchedule]   = useState('')

  // Step 3 — KPI targets + CPM-1A
  const [kpiTargets, setKpiTargets]   = useState([])
  const [parsing, setParsing]         = useState(false)
  const [parseError, setParseError]   = useState('')
  const [showTemplates, setShowTemplates] = useState(false)
  const fileRef = useRef(null)

  // Step 4 — Risk clauses
  const [riskClauses, setRiskClauses] = useState([])

  // Step 5 — Task template
  const [taskTemplate, setTaskTemplate]         = useState([])
  const [generateNow, setGenerateNow]           = useState(false)

  // ── KPI helpers ───────────────────────────────────────────────────────────

  const addKpi = () => setKpiTargets(prev => [...prev, {
    key: '', label: '', kpi_type: 'manual', target_value: '', target_label: '', weight_pct: '',
  }])

  const updateKpi = (i, field, val) => setKpiTargets(prev => {
    const next = [...prev]
    next[i] = { ...next[i], [field]: val }
    // Auto-generate key from label
    if (field === 'label') {
      next[i].key = val.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
    }
    return next
  })

  const removeKpi = (i) => setKpiTargets(prev => prev.filter((_, idx) => idx !== i))

  const totalWeight = kpiTargets.reduce((s, k) => s + (parseFloat(k.weight_pct) || 0), 0)

  // CPM-1A: load template
  const handleLoadTemplate = (templateId) => {
    const tmpl = KPI_TEMPLATES.find(t => t.id === templateId)
    if (!tmpl) return
    if (kpiTargets.length > 0) {
      if (!window.confirm('Replace existing KPIs with this template?')) return
    }
    setKpiTargets(tmpl.kpis.map(k => ({ ...k, target_value: k.target_value ?? '' })))
    setShowTemplates(false)
    setParseError('')
  }

  // CPM-1A: parse contract
  const handleParseContract = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setParsing(true)
    setParseError('')
    try {
      const result = await parseContractKpis(file)
      if (result.kpis?.length > 0) {
        if (kpiTargets.length > 0) {
          if (!window.confirm(`Replace existing KPIs with ${result.kpis.length} extracted from contract?`)) {
            setParsing(false)
            return
          }
        }
        setKpiTargets(result.kpis.map(k => ({ ...k, target_value: k.target_value ?? '' })))
      } else {
        setParseError('No KPIs found in the document. Please add them manually.')
      }
      // Also pre-fill risk clauses if extracted
      if (result.risk_clauses?.length > 0) {
        if (riskClauses.length === 0 || window.confirm(`Also pre-fill ${result.risk_clauses.length} risk clauses from contract?`)) {
          setRiskClauses(result.risk_clauses)
        }
      }
    } catch {
      setParseError('Could not extract KPIs — please add them manually.')
    } finally {
      setParsing(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // ── Risk clause helpers ───────────────────────────────────────────────────

  const addClause = () => setRiskClauses(prev => [...prev, { clause_ref: '', trigger_description: '', consequence: '' }])
  const updateClause = (i, field, val) => setRiskClauses(prev => { const n = [...prev]; n[i] = { ...n[i], [field]: val }; return n })
  const removeClause = (i) => setRiskClauses(prev => prev.filter((_, idx) => idx !== i))

  // ── Task template helpers ─────────────────────────────────────────────────

  const addTask = () => setTaskTemplate(prev => [...prev, { week_number: '', phase: '', task_description: '', due_day: '', owner: '' }])
  const updateTask = (i, field, val) => setTaskTemplate(prev => { const n = [...prev]; n[i] = { ...n[i], [field]: val }; return n })
  const removeTask = (i) => setTaskTemplate(prev => prev.filter((_, idx) => idx !== i))

  // ── Navigation ────────────────────────────────────────────────────────────

  const canNext = () => {
    if (step === 0) return fullName.trim() && roleTitle.trim()
    if (step === 1) return contractStart && feeAmount
    return true
  }

  const handleSubmit = async () => {
    setSaving(true)
    setError('')
    try {
      const payload = {
        full_name:        fullName.trim(),
        role_title:       roleTitle.trim(),
        email:            email || null,
        phone:            phone || null,
        contract_start:   contractStart,
        contract_end:     contractEnd || null,
        contract_months:  contractMonths ? parseInt(contractMonths) : null,
        fee_structure:    feeStructure,
        fee_amount:       parseFloat(feeAmount),
        fee_currency:     feeCurrency,
        fee_notes:        feeNotes || null,
        payment_schedule: paymentSchedule || null,
        kpi_targets: kpiTargets.map(k => ({
          key:          k.key || k.label.toLowerCase().replace(/[^a-z0-9]+/g, '_'),
          label:        k.label,
          kpi_type:     k.kpi_type,
          target_value: k.target_value === '' ? null : parseFloat(k.target_value),
          target_label: k.target_label || null,
          weight_pct:   parseFloat(k.weight_pct) || 0,
        })),
        risk_clauses: riskClauses.filter(r => r.clause_ref || r.trigger_description),
        task_template: taskTemplate
          .filter(t => t.task_description?.trim())
          .map(t => ({
            week_number:      t.week_number ? parseInt(t.week_number) : null,
            phase:            t.phase || null,
            task_description: t.task_description.trim(),
            due_day:          t.due_day ? parseInt(t.due_day) : null,
            owner:            t.owner || null,
          })),
      }

      const created = await createContractor(payload)

      if (generateNow && payload.task_template.length > 0) {
        try { await generateContractorTasks(created.id) } catch {}
      }

      onCreated()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Failed to create contractor.')
    } finally {
      setSaving(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
      zIndex: 300, display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: 'white', borderRadius: 16, width: '100%', maxWidth: 620,
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)', overflow: 'hidden',
      }}>
        {/* Modal header */}
        <div style={{ padding: '20px 24px', borderBottom: '1px solid #dde4e8', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark }}>Add Contractor</div>
            <div style={{ fontSize: 12, color: ds.gray, marginTop: 2 }}>Step {step + 1} of {STEPS.length} — {STEPS[step]}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: ds.gray }}>✕</button>
        </div>

        {/* Step indicator */}
        <div style={{ display: 'flex', padding: '12px 24px', gap: 6, borderBottom: '1px solid #f1f3f4', flexShrink: 0 }}>
          {STEPS.map((s, i) => (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{
                width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: i < step ? ds.teal : i === step ? ds.teal : '#e0e0e0',
                color: i <= step ? 'white' : ds.gray, fontSize: 11, fontWeight: 700,
              }}>{i < step ? '✓' : i + 1}</div>
              <div style={{ fontSize: 10, color: i === step ? ds.teal : ds.gray, fontWeight: i === step ? 600 : 400, textAlign: 'center', whiteSpace: 'nowrap' }}>{s}</div>
            </div>
          ))}
        </div>

        {/* Step body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
          {/* STEP 1 — Identity */}
          {step === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <Input label="Full Name" value={fullName} onChange={setFullName} required placeholder="e.g. Emmanuel Ukairo" />
                <Input label="Role Title" value={roleTitle} onChange={setRoleTitle} required placeholder="e.g. Digital Marketing Lead" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <Input label="Email" value={email} onChange={setEmail} type="email" placeholder="contractor@email.com" />
                <Input label="Phone" value={phone} onChange={setPhone} placeholder="+234..." />
              </div>
            </div>
          )}

          {/* STEP 2 — Contract */}
          {step === 1 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <Input label="Contract Start" type="date" value={contractStart} onChange={setContractStart} required />
                <Input label="Contract End" type="date" value={contractEnd} onChange={setContractEnd} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14 }}>
                <Input label="Duration (months)" type="number" value={contractMonths} onChange={setContractMonths} placeholder="e.g. 6" />
                <Select label="Fee Structure" value={feeStructure} onChange={setFeeStructure} options={FEE_STRUCTURE_OPTIONS} required />
                <Select label="Currency" value={feeCurrency} onChange={setFeeCurrency} options={[{value:'NGN',label:'NGN'},{value:'USD',label:'USD'},{value:'GBP',label:'GBP'}]} />
              </div>
              <Input label="Fee Amount" type="number" value={feeAmount} onChange={setFeeAmount} required placeholder="e.g. 500000" />
              <Textarea label="Fee Notes" value={feeNotes} onChange={setFeeNotes} placeholder="e.g. Ad spend funded separately by Company" rows={2} />
              <Textarea label="Payment Schedule" value={paymentSchedule} onChange={setPaymentSchedule} placeholder="e.g. ₦3M advance + ₦2M on team confirmation" rows={2} />
            </div>
          )}

          {/* STEP 3 — KPI Targets (CPM-1A enhanced) */}
          {step === 2 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* CPM-1A toolbar */}
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {/* AI Parser */}
                <div>
                  <input ref={fileRef} type="file" accept=".pdf,.docx" style={{ display: 'none' }} onChange={handleParseContract} />
                  <Btn
                    onClick={() => fileRef.current?.click()}
                    variant="secondary" small
                    disabled={parsing}
                  >
                    {parsing ? '⏳ Parsing…' : '📄 Parse from Contract'}
                  </Btn>
                </div>

                {/* Template dropdown */}
                <div style={{ position: 'relative' }}>
                  <Btn onClick={() => setShowTemplates(p => !p)} variant="secondary" small>
                    📋 Load Template ▾
                  </Btn>
                  {showTemplates && (
                    <div style={{
                      position: 'absolute', top: '100%', left: 0, marginTop: 4,
                      background: 'white', border: '1px solid #dde4e8', borderRadius: 8,
                      boxShadow: '0 4px 16px rgba(0,0,0,0.1)', zIndex: 10, minWidth: 220,
                    }}>
                      {KPI_TEMPLATES.map(t => (
                        <button
                          key={t.id}
                          onClick={() => handleLoadTemplate(t.id)}
                          style={{
                            display: 'block', width: '100%', textAlign: 'left',
                            padding: '10px 14px', background: 'none', border: 'none',
                            cursor: 'pointer', fontSize: 13, fontFamily: ds.fontDm,
                            color: ds.dark, borderBottom: '1px solid #f1f3f4',
                          }}
                          onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                          onMouseLeave={e => e.currentTarget.style.background = 'none'}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <Btn onClick={addKpi} small>+ Add KPI</Btn>
              </div>

              {/* Parse error */}
              {parseError && (
                <div style={{ background: '#fce8e6', borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#c5221f' }}>
                  {parseError}
                </div>
              )}

              {/* Weight warning */}
              {kpiTargets.length > 0 && Math.abs(totalWeight - 100) > 0.5 && (
                <div style={{ background: '#fef3e2', borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#b45309' }}>
                  ⚠ Weights sum to {totalWeight.toFixed(0)}% — should total 100%
                </div>
              )}

              {kpiTargets.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '24px 0', color: ds.gray, fontSize: 13 }}>
                  No KPIs yet. Parse a contract, load a template, or add manually.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {kpiTargets.map((kpi, i) => (
                    <div key={i} style={{ background: '#f8fafc', borderRadius: 8, padding: 12, border: '1px solid #dde4e8' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                        <Input label="Label" value={kpi.label} onChange={v => updateKpi(i, 'label', v)} placeholder="e.g. Monthly Leads" />
                        <Select label="KPI Type" value={kpi.kpi_type} onChange={v => updateKpi(i, 'kpi_type', v)} options={KPI_TYPE_OPTIONS} />
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 80px', gap: 10 }}>
                        <Input label="Target Value" type="number" value={kpi.target_value} onChange={v => updateKpi(i, 'target_value', v)} placeholder="e.g. 50" />
                        <Input label="Target Label" value={kpi.target_label} onChange={v => updateKpi(i, 'target_label', v)} placeholder="e.g. 50 leads/month" />
                        <Input label="Weight %" type="number" value={kpi.weight_pct} onChange={v => updateKpi(i, 'weight_pct', v)} placeholder="40" />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                        <Btn onClick={() => removeKpi(i)} variant="danger" small>Remove</Btn>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* STEP 4 — Risk Clauses */}
          {step === 3 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 13, color: ds.gray }}>
                  {riskClauses.length > 0
                    ? `${riskClauses.length} clause${riskClauses.length > 1 ? 's' : ''}${riskClauses.length > 0 ? ' (pre-filled from contract parser)' : ''}`
                    : 'No clauses yet — add manually or parse from contract in Step 3'}
                </div>
                <Btn onClick={addClause} small>+ Add Clause</Btn>
              </div>
              {riskClauses.map((rc, i) => (
                <div key={i} style={{ background: '#f8fafc', borderRadius: 8, padding: 12, border: '1px solid #dde4e8', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <Input label="Clause Reference" value={rc.clause_ref} onChange={v => updateClause(i, 'clause_ref', v)} placeholder="e.g. Clause 7.2" />
                  <Textarea label="Trigger" value={rc.trigger_description} onChange={v => updateClause(i, 'trigger_description', v)} placeholder="What triggers this clause?" rows={2} />
                  <Textarea label="Consequence" value={rc.consequence} onChange={v => updateClause(i, 'consequence', v)} placeholder="What happens when triggered?" rows={2} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <Btn onClick={() => removeClause(i)} variant="danger" small>Remove</Btn>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* STEP 5 — Task Template */}
          {step === 4 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 13, color: ds.gray }}>{taskTemplate.length} task{taskTemplate.length !== 1 ? 's' : ''} in template</div>
                <Btn onClick={addTask} small>+ Add Task</Btn>
              </div>
              {taskTemplate.map((t, i) => (
                <div key={i} style={{ background: '#f8fafc', borderRadius: 8, padding: 12, border: '1px solid #dde4e8', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <Input label="Task Description" value={t.task_description} onChange={v => updateTask(i, 'task_description', v)} placeholder="e.g. Complete onboarding pack" />
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10 }}>
                    <Input label="Week #" type="number" value={t.week_number} onChange={v => updateTask(i, 'week_number', v)} placeholder="1" />
                    <Input label="Phase" value={t.phase} onChange={v => updateTask(i, 'phase', v)} placeholder="Onboarding" />
                    <Input label="Due Day" type="number" value={t.due_day} onChange={v => updateTask(i, 'due_day', v)} placeholder="7" />
                    <Input label="Owner" value={t.owner} onChange={v => updateTask(i, 'owner', v)} placeholder="Contractor" />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <Btn onClick={() => removeTask(i)} variant="danger" small>Remove</Btn>
                  </div>
                </div>
              ))}

              {taskTemplate.length > 0 && (
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: ds.dark, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={generateNow}
                    onChange={e => setGenerateNow(e.target.checked)}
                    style={{ accentColor: ds.teal }}
                  />
                  Generate tasks immediately after saving
                </label>
              )}
            </div>
          )}

          {error && (
            <div style={{ marginTop: 12, background: '#fce8e6', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#c5221f' }}>
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: '1px solid #dde4e8', display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
          <Btn onClick={step === 0 ? onClose : () => setStep(p => p - 1)} variant="secondary">
            {step === 0 ? 'Cancel' : '← Back'}
          </Btn>
          {step < STEPS.length - 1 ? (
            <Btn onClick={() => setStep(p => p + 1)} disabled={!canNext()}>
              Next →
            </Btn>
          ) : (
            <Btn onClick={handleSubmit} disabled={saving}>
              {saving ? 'Saving…' : '✓ Save Contractor'}
            </Btn>
          )}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ROOT: ContractorModule
// ─────────────────────────────────────────────────────────────────────────────

export default function ContractorModule({ user }) {
  const TABS = [
    { id: 'scorecard',   label: 'Scorecard',   icon: '📋' },
    { id: 'contractors', label: 'Contractors',  icon: '🤝' },
    { id: 'tasks',       label: 'All Tasks',    icon: '✅' },
  ]

  const [activeTab, setActiveTab]     = useState('scorecard')
  const [showCreate, setShowCreate]   = useState(false)
  const [refreshKey, setRefreshKey]   = useState(0)
  const [scorecardContractor, setScorecardContractor] = useState(null)

  const handleCreated = () => {
    setShowCreate(false)
    setRefreshKey(k => k + 1)
    setActiveTab('contractors')
  }

  // Allow scorecard card click to open detail via Contractors tab
  const handleScorecardSelect = (contractor) => {
    setScorecardContractor(contractor)
    setActiveTab('contractors')
  }

  return (
    <div style={{ minHeight: '100%', background: ds.light }}>
      <TabBar active={activeTab} onChange={setActiveTab} tabs={TABS} />

      {/* Pattern 26: mount-and-hide */}
      <div style={{ display: activeTab === 'scorecard' ? 'block' : 'none' }}>
        <ScorecardTab onSelectContractor={handleScorecardSelect} />
      </div>

      <div style={{ display: activeTab === 'contractors' ? 'block' : 'none' }}>
        <ContractorsTab
          user={user}
          onOpenCreate={() => setShowCreate(true)}
          refreshKey={refreshKey}
          initialSelected={scorecardContractor}
        />
      </div>

      <div style={{ display: activeTab === 'tasks' ? 'block' : 'none' }}>
        <AllTasksTab refreshKey={refreshKey} />
      </div>

      {showCreate && (
        <ContractorCreateModal
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
