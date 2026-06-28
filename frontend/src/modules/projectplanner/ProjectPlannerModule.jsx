import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import {
  FolderKanban, Plus, ChevronDown, ChevronUp, ChevronLeft, ChevronRight,
  Trash2, Pencil, FileText, Link2, Upload, X, AlertTriangle, Check,
} from 'lucide-react'
import * as plannerApi from '../../services/projectPlanner.service'

const PHASES = [
  { value: 1, label: 'Foundation' },
  { value: 2, label: 'Build & launch' },
  { value: 3, label: 'Scale and embed' },
  { value: 4, label: 'Optimize and renew' },
]

const TASK_STATUS_ORDER = ['not_started', 'in_progress', 'done', 'blocked']
const TASK_STATUS_LABEL = { not_started: 'Not started', in_progress: 'In progress', done: 'Done', blocked: 'Blocked' }
const TASK_STATUS_COLOR = {
  not_started: { bg: ds.border, fg: ds.gray },
  in_progress: { bg: '#FFF3E0', fg: '#C05A00' },
  done:        { bg: '#E8F8EE', fg: ds.green },
  blocked:     { bg: '#FFE8E8', fg: ds.red },
}

const APPROVAL_COLOR = {
  draft:    { bg: ds.border, fg: ds.gray, label: 'Draft' },
  reviewed: { bg: '#FFF3E0', fg: '#C05A00', label: 'Reviewed' },
  approved: { bg: '#E8F8EE', fg: ds.green, label: 'Approved' },
}

function taskProgress(strategy) {
  const tasks = (strategy.phases || []).flatMap(p => p.tasks || [])
  const done = tasks.filter(t => t.status === 'done').length
  return { done, total: tasks.length }
}

export default function ProjectPlannerModule() {
  const isMobile = useIsMobile()

  const [plans, setPlans] = useState([])
  const [activePlanId, setActivePlanId] = useState(null)
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [newPlanName, setNewPlanName] = useState('')
  const [creatingPlan, setCreatingPlan] = useState(false)

  // Only one strategy's panel open at a time, like the original tool.
  const [expandedStrategyId, setExpandedStrategyId] = useState(null)
  const [expandedPanel, setExpandedPanel] = useState(null) // 'execution' | 'details' | null

  useEffect(() => {
    loadPlans()
  }, [])

  useEffect(() => {
    if (activePlanId) loadStrategies(activePlanId)
  }, [activePlanId])

  async function loadPlans() {
    setLoading(true)
    setError('')
    try {
      const res = await plannerApi.listPlans()
      const data = res.data
      setPlans(data)
      if (data.length > 0) {
        setActivePlanId(prev => prev || data[0].id)
      } else {
        setLoading(false)
      }
    } catch (e) {
      setError('Could not load plans. Please try again.')
      setLoading(false)
    }
  }

  async function loadStrategies(planId) {
    setLoading(true)
    setError('')
    try {
      const res = await plannerApi.listStrategies(planId)
      const data = res.data
      setStrategies(data)
    } catch (e) {
      setError('Could not load strategies for this plan.')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreatePlan() {
    if (!newPlanName.trim()) return
    setCreatingPlan(true)
    try {
      const res = await plannerApi.createPlan(newPlanName.trim())
      const plan = res.data
      setPlans(prev => [...prev, plan])
      setActivePlanId(plan.id)
      setNewPlanName('')
    } catch (e) {
      setError('Could not create plan.')
    } finally {
      setCreatingPlan(false)
    }
  }

  async function refreshStrategies() {
    if (activePlanId) await loadStrategies(activePlanId)
  }

  async function handleCreateStrategy(phase, title, channel) {
    if (!title.trim()) return
    try {
      await plannerApi.createStrategy({
        plan_id: activePlanId, phase, channel, title: title.trim(),
      })
      await refreshStrategies()
    } catch (e) {
      setError('Could not create strategy.')
    }
  }

  async function handleUpdateStrategy(strategy, payload) {
    try {
      await plannerApi.updateStrategy(strategy.id, payload)
      await refreshStrategies()
    } catch (e) {
      setError('Could not update strategy.')
    }
  }

  async function handleDeleteStrategy(strategy) {
    try {
      await plannerApi.deleteStrategy(strategy.id)
      if (expandedStrategyId === strategy.id) { setExpandedStrategyId(null); setExpandedPanel(null) }
      await refreshStrategies()
    } catch (e) {
      setError('Could not delete strategy.')
    }
  }

  async function handleApprove(strategy) {
    try {
      await plannerApi.approveStrategy(strategy.id)
      await refreshStrategies()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Could not advance approval status.')
    }
  }

  async function handleRevert(strategy) {
    try {
      await plannerApi.revertStrategy(strategy.id)
      await refreshStrategies()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Could not revert approval status.')
    }
  }

  function toggleExpand(strategyId, panel) {
    if (expandedStrategyId === strategyId && expandedPanel === panel) {
      setExpandedStrategyId(null)
      setExpandedPanel(null)
    } else {
      setExpandedStrategyId(strategyId)
      setExpandedPanel(panel)
    }
  }

  const activePlan = plans.find(p => p.id === activePlanId)

  // ── Empty state: no plans yet ───────────────────────────────────────────
  if (!loading && plans.length === 0) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        minHeight: 'calc(100vh - 60px)', padding: isMobile ? '32px 20px' : '40px 28px',
        textAlign: 'center', background: ds.light,
      }}>
        <div style={{
          marginBottom: 16, width: 64, height: 64, borderRadius: ds.radius.lg,
          background: ds.mint, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <FolderKanban size={30} color={ds.teal} strokeWidth={1.7} />
        </div>
        <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: isMobile ? 19 : 22, color: ds.dark, margin: '0 0 8px' }}>
          Project Planner
        </h1>
        <p style={{ fontFamily: ds.fontDm, fontSize: 14, color: ds.gray, lineHeight: 1.6, maxWidth: 380, margin: '0 0 24px' }}>
          Create your first plan to start laying out strategies, execution steps, and approvals.
        </p>
        <div style={{ display: 'flex', gap: 8, width: isMobile ? '100%' : 360, maxWidth: 360 }}>
          <input
            value={newPlanName}
            onChange={e => setNewPlanName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreatePlan() }}
            placeholder="e.g. Q3 Plan"
            style={{ flex: 1, fontFamily: ds.fontDm, fontSize: 14, padding: '10px 14px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.md }}
          />
          <button
            onClick={handleCreatePlan}
            disabled={creatingPlan || !newPlanName.trim()}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, background: ds.teal, color: ds.white,
              border: 'none', borderRadius: ds.radius.md, padding: '10px 16px', fontFamily: ds.fontSyne,
              fontWeight: 600, fontSize: 13.5, cursor: 'pointer', opacity: creatingPlan ? 0.6 : 1,
            }}
          >
            <Plus size={15} /> Create
          </button>
        </div>
        {error && <ErrorBanner message={error} />}
      </div>
    )
  }

  return (
    <div style={{ minHeight: 'calc(100vh - 60px)', background: ds.light, padding: isMobile ? '16px' : '24px 28px' }}>
      {/* ── Header: plan switcher ─────────────────────────────────────── */}
      <div style={{
        display: 'flex', flexDirection: isMobile ? 'column' : 'row',
        alignItems: isMobile ? 'stretch' : 'center', justifyContent: 'space-between',
        gap: 12, marginBottom: 20,
      }}>
        <div>
          <p style={{ fontFamily: ds.fontDm, fontSize: 12, color: ds.gray, margin: '0 0 4px', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
            Project Planner
          </p>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: isMobile ? 18 : 21, color: ds.dark, margin: 0 }}>
            {activePlan?.name || 'Plan'}
          </h1>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <select
            value={activePlanId || ''}
            onChange={e => setActivePlanId(e.target.value)}
            style={{ fontFamily: ds.fontDm, fontSize: 13.5, padding: '9px 12px', borderRadius: ds.radius.md, border: `1px solid ${ds.border}`, background: ds.white }}
          >
            {plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <NewPlanInline onCreate={(name) => { setNewPlanName(name); handleCreatePlan() }} />
        </div>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {loading ? (
        <p style={{ fontFamily: ds.fontDm, fontSize: 14, color: ds.gray }}>Loading…</p>
      ) : (
        <div>
          {PHASES.map(phase => {
            const phaseStrategies = strategies.filter(s => s.phase === phase.value)
            return (
              <div key={phase.value} style={{ marginBottom: 28 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
                  <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark, margin: 0 }}>
                    {phase.value}. {phase.label}
                  </h2>
                </div>

                {phaseStrategies.length === 0 && (
                  <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: ds.gray, fontStyle: 'italic', margin: '0 0 8px' }}>
                    No strategies here yet.
                  </p>
                )}

                {phaseStrategies.map(strategy => (
                  <StrategyCard
                    key={strategy.id}
                    strategy={strategy}
                    isMobile={isMobile}
                    expanded={expandedStrategyId === strategy.id ? expandedPanel : null}
                    onToggleExpand={(panel) => toggleExpand(strategy.id, panel)}
                    onUpdate={(payload) => handleUpdateStrategy(strategy, payload)}
                    onDelete={() => handleDeleteStrategy(strategy)}
                    onApprove={() => handleApprove(strategy)}
                    onRevert={() => handleRevert(strategy)}
                    onTaskChanged={refreshStrategies}
                    onDocumentChanged={refreshStrategies}
                  />
                ))}

                <AddStrategyForm phase={phase.value} onCreate={handleCreateStrategy} />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// =============================================================================
// Strategy card
// =============================================================================

function StrategyCard({ strategy, isMobile, expanded, onToggleExpand, onUpdate, onDelete, onApprove, onRevert, onTaskChanged, onDocumentChanged }) {
  const [editing, setEditing] = useState(false)
  const [titleDraft, setTitleDraft] = useState(strategy.title)
  const { done, total } = taskProgress(strategy)
  const approval = APPROVAL_COLOR[strategy.approval_status] || APPROVAL_COLOR.draft

  function saveTitle() {
    if (titleDraft.trim() && titleDraft.trim() !== strategy.title) {
      onUpdate({ title: titleDraft.trim() })
    }
    setEditing(false)
  }

  return (
    <div style={{
      background: ds.white, border: `1px solid ${ds.border}`, borderRadius: ds.radius.md,
      marginBottom: 10, boxShadow: ds.cardShadow, opacity: strategy.included === false ? 0.6 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', flexWrap: 'wrap' }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: strategy.channel === 'online' ? ds.teal : ds.accent, flexShrink: 0 }} />

        {editing ? (
          <input
            autoFocus
            value={titleDraft}
            onChange={e => setTitleDraft(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={e => { if (e.key === 'Enter') saveTitle() }}
            style={{ flex: '1 1 200px', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 500, padding: '4px 8px', border: `1px solid ${ds.teal}`, borderRadius: 6 }}
          />
        ) : (
          <span
            onClick={() => setEditing(true)}
            style={{ flex: '1 1 200px', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 500, color: ds.dark, cursor: 'pointer', textDecoration: strategy.included === false ? 'line-through' : 'none' }}
          >
            {strategy.title}
          </span>
        )}

        <span style={{ fontSize: 11.5, fontWeight: 500, color: ds.gray, background: ds.light, border: `1px solid ${ds.border}`, borderRadius: 999, padding: '3px 9px' }}>
          {done}/{total} tasks
        </span>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: approval.fg, background: approval.bg, borderRadius: 999, padding: '3px 9px' }}>
          {approval.label}
        </span>

        <button onClick={() => onToggleExpand('execution')} style={pillBtnStyle(expanded === 'execution')}>
          Execution plan
        </button>
        <button onClick={() => onToggleExpand('details')} style={linkBtnStyle}>
          View details
        </button>

        <button onClick={() => setEditing(true)} title="Rename" style={iconBtnStyle}><Pencil size={14} /></button>
        <button onClick={onDelete} title="Delete" style={{ ...iconBtnStyle, color: ds.red }}><Trash2 size={14} /></button>
        <button onClick={() => onToggleExpand(expanded ? null : 'execution')} style={iconBtnStyle}>
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      {expanded && (
        <div style={{ borderTop: `1px solid ${ds.border}`, padding: 14 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 14 }}>
            <select
              value={strategy.phase}
              onChange={e => onUpdate({ phase: parseInt(e.target.value, 10) })}
              style={{ fontFamily: ds.fontDm, fontSize: 13, padding: '6px 10px', borderRadius: 7, border: `1px solid ${ds.border}` }}
            >
              {PHASES.map(p => <option key={p.value} value={p.value}>{p.value} — {p.label}</option>)}
            </select>
            <button
              onClick={() => onUpdate({ included: strategy.included === false })}
              style={pillBtnStyle(strategy.included !== false)}
            >
              {strategy.included === false ? '✕ Removed' : '✓ Included'}
            </button>

            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
              {strategy.approval_status !== 'draft' && (
                <button onClick={onRevert} style={linkBtnStyle}>
                  Revert to {strategy.approval_status === 'approved' ? 'reviewed' : 'draft'}
                </button>
              )}
              {strategy.approval_status !== 'approved' && (
                <button onClick={onApprove} style={approveBtnStyle}>
                  {strategy.approval_status === 'draft' ? 'Mark reviewed' : 'Approve'}
                </button>
              )}
            </div>
          </div>

          {expanded === 'execution' && (
            <ExecutionPlanPanel strategy={strategy} onTaskChanged={onTaskChanged} />
          )}
          {expanded === 'details' && (
            <DetailsPanel strategy={strategy} onDocumentChanged={onDocumentChanged} />
          )}
        </div>
      )}
    </div>
  )
}

// =============================================================================
// Execution plan panel — phases & tasks
// =============================================================================

function ExecutionPlanPanel({ strategy, onTaskChanged }) {
  const phases = strategy.phases || []

  async function cycleStatus(task) {
    const idx = TASK_STATUS_ORDER.indexOf(task.status)
    const next = TASK_STATUS_ORDER[(idx + 1) % TASK_STATUS_ORDER.length]
    try {
      await plannerApi.updateTask(task.id, { status: next })
      await onTaskChanged()
    } catch (e) { /* surfaced via parent reload failure if it occurs */ }
  }

  async function saveTaskField(task, field, value) {
    try {
      await plannerApi.updateTask(task.id, { [field]: value })
      await onTaskChanged()
    } catch (e) { /* no-op — next reload will reflect true state */ }
  }

  async function removeTask(task) {
    try {
      await plannerApi.deleteTask(task.id)
      await onTaskChanged()
    } catch (e) { /* no-op */ }
  }

  return (
    <div>
      {phases.map(phase => (
        <div key={phase.id} style={{ marginBottom: 16 }}>
          <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13.5, color: ds.dark, margin: '0 0 6px' }}>
            {phase.title} <span style={{ color: ds.gray, fontWeight: 400 }}>· {phase.sub_label}</span>
          </p>
          {(phase.tasks || []).map(task => (
            <TaskRow
              key={task.id}
              task={task}
              onCycleStatus={() => cycleStatus(task)}
              onSaveField={(field, value) => saveTaskField(task, field, value)}
              onDelete={() => removeTask(task)}
            />
          ))}
          <AddTaskInline phaseId={phase.id} onCreated={onTaskChanged} />
        </div>
      ))}
    </div>
  )
}

function TaskRow({ task, onCycleStatus, onSaveField, onDelete }) {
  const color = TASK_STATUS_COLOR[task.status] || TASK_STATUS_COLOR.not_started
  const [owner, setOwner] = useState(task.owner_label || '')
  const [due, setDue] = useState(task.due_date || '')

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '6px 0', borderBottom: `1px solid ${ds.border}` }}>
      <button
        onClick={onCycleStatus}
        style={{ fontSize: 11.5, fontWeight: 600, color: color.fg, background: color.bg, border: 'none', borderRadius: 7, padding: '4px 9px', cursor: 'pointer', width: 100, flexShrink: 0 }}
      >
        {TASK_STATUS_LABEL[task.status]}
      </button>
      <span style={{ flex: '1 1 160px', fontFamily: ds.fontDm, fontSize: 13, color: ds.dark, textDecoration: task.status === 'done' ? 'line-through' : 'none' }}>
        {task.title}
      </span>
      <input
        value={owner}
        onChange={e => setOwner(e.target.value)}
        onBlur={() => onSaveField('owner_label', owner)}
        placeholder="Owner"
        style={{ width: 110, fontFamily: ds.fontDm, fontSize: 12, padding: '5px 8px', borderRadius: 6, border: `1px solid ${ds.border}` }}
      />
      <input
        type="date"
        value={due || ''}
        onChange={e => { setDue(e.target.value); onSaveField('due_date', e.target.value) }}
        style={{ width: 130, fontFamily: ds.fontDm, fontSize: 12, padding: '5px 8px', borderRadius: 6, border: `1px solid ${ds.border}` }}
      />
      <button onClick={onDelete} style={{ ...iconBtnStyle, color: ds.red }}><Trash2 size={13} /></button>
    </div>
  )
}

function AddTaskInline({ phaseId, onCreated }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')

  async function submit() {
    if (!title.trim()) return
    try {
      await plannerApi.createTask(phaseId, { title: title.trim() })
      setTitle('')
      setOpen(false)
      await onCreated()
    } catch (e) { /* no-op */ }
  }

  if (!open) {
    return <button onClick={() => setOpen(true)} style={linkBtnStyle}>+ Add task</button>
  }
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
      <input
        autoFocus
        value={title}
        onChange={e => setTitle(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }}
        placeholder="Task name"
        style={{ flex: 1, fontFamily: ds.fontDm, fontSize: 13, padding: '6px 10px', borderRadius: 6, border: `1px solid ${ds.border}` }}
      />
      <button onClick={submit} style={approveBtnStyle}>Add</button>
      <button onClick={() => setOpen(false)} style={linkBtnStyle}>Cancel</button>
    </div>
  )
}

// =============================================================================
// Details panel — documents & links
// =============================================================================

function DetailsPanel({ strategy, onDocumentChanged }) {
  const [link, setLink] = useState('')
  const [uploading, setUploading] = useState(false)
  const [localError, setLocalError] = useState('')
  const documents = strategy.documents || []

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setLocalError('')
    try {
      const formData = new FormData()
      formData.append('file', file)
      await plannerApi.uploadStrategyDocument(strategy.id, formData)
      await onDocumentChanged()
    } catch (err) {
      const status = err?.response?.status
      if (status === 415) setLocalError('That file type isn\'t supported. Allowed: JPG, PNG, GIF, WEBP, PDF, CSV.')
      else if (status === 413) setLocalError('That file is too large — 25MB max.')
      else setLocalError('Could not upload that file. Please try again.')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleSaveLink() {
    if (!link.trim()) return
    try {
      await plannerApi.setStrategyDocumentLink(strategy.id, link.trim())
      setLink('')
      await onDocumentChanged()
    } catch (e) {
      setLocalError('Could not save that link.')
    }
  }

  async function handleDownload(doc) {
    try {
      const res = await plannerApi.getDocumentDownloadUrl(doc.id)
      window.open(res.data.url, '_blank', 'noopener')
    } catch (e) {
      setLocalError('Could not open that document.')
    }
  }

  async function handleRemove(doc) {
    try {
      await plannerApi.deleteDocument(doc.id)
      await onDocumentChanged()
    } catch (e) {
      setLocalError('Could not remove that document.')
    }
  }

  return (
    <div>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13.5, color: ds.dark, margin: '0 0 8px' }}>
        Attached documents &amp; links
      </p>

      {documents.length === 0 && (
        <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: ds.gray, fontStyle: 'italic', margin: '0 0 10px' }}>
          Nothing attached yet.
        </p>
      )}

      {documents.map(doc => (
        <div key={doc.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: `1px solid ${ds.border}` }}>
          {doc.external_link ? <Link2 size={14} color={ds.teal} /> : <FileText size={14} color={ds.teal} />}
          <span style={{ flex: 1, fontFamily: ds.fontDm, fontSize: 13, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {doc.file_name || doc.external_link}
          </span>
          <button onClick={() => handleDownload(doc)} style={linkBtnStyle}>Open</button>
          <button onClick={() => handleRemove(doc)} style={{ ...iconBtnStyle, color: ds.red }}><Trash2 size={13} /></button>
        </div>
      ))}

      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <input
          value={link}
          onChange={e => setLink(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSaveLink() }}
          placeholder="Paste a link (Drive, Dropbox, etc.)"
          style={{ flex: '1 1 200px', fontFamily: ds.fontDm, fontSize: 13, padding: '7px 10px', borderRadius: 7, border: `1px solid ${ds.border}` }}
        />
        <button onClick={handleSaveLink} style={linkBtnStyle}>Save link</button>

        <label style={{ ...approveBtnStyle, display: 'inline-flex', alignItems: 'center', gap: 6, cursor: uploading ? 'default' : 'pointer', opacity: uploading ? 0.6 : 1 }}>
          <Upload size={13} />
          {uploading ? 'Uploading…' : 'Upload file'}
          <input type="file" onChange={handleUpload} disabled={uploading} style={{ display: 'none' }} />
        </label>
      </div>

      {localError && <p style={{ fontFamily: ds.fontDm, fontSize: 12.5, color: ds.red, marginTop: 8 }}>{localError}</p>}
    </div>
  )
}

// =============================================================================
// Small shared pieces
// =============================================================================

function AddStrategyForm({ phase, onCreate }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [channel, setChannel] = useState('online')

  async function submit() {
    await onCreate(phase, title, channel)
    setTitle('')
    setOpen(false)
  }

  if (!open) {
    return <button onClick={() => setOpen(true)} style={linkBtnStyle}>+ Add strategy</button>
  }
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
      <select value={channel} onChange={e => setChannel(e.target.value)} style={{ fontFamily: ds.fontDm, fontSize: 13, padding: '6px 8px', borderRadius: 6, border: `1px solid ${ds.border}` }}>
        <option value="online">Digital</option>
        <option value="offline">In-person</option>
      </select>
      <input
        autoFocus
        value={title}
        onChange={e => setTitle(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }}
        placeholder="Strategy name"
        style={{ flex: '1 1 200px', fontFamily: ds.fontDm, fontSize: 13, padding: '6px 10px', borderRadius: 6, border: `1px solid ${ds.border}` }}
      />
      <button onClick={submit} style={approveBtnStyle}>Add</button>
      <button onClick={() => setOpen(false)} style={linkBtnStyle}>Cancel</button>
    </div>
  )
}

function NewPlanInline({ onCreate }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} style={{ ...approveBtnStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
        <Plus size={14} /> New plan
      </button>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      <input
        autoFocus
        value={name}
        onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { onCreate(name); setName(''); setOpen(false) } }}
        placeholder="Plan name"
        style={{ fontFamily: ds.fontDm, fontSize: 13, padding: '8px 10px', borderRadius: 7, border: `1px solid ${ds.border}` }}
      />
      <button onClick={() => { onCreate(name); setName(''); setOpen(false) }} style={approveBtnStyle}>Create</button>
      <button onClick={() => setOpen(false)} style={iconBtnStyle}><X size={15} /></button>
    </div>
  )
}

function ErrorBanner({ message, onDismiss }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 16, maxWidth: 480,
      background: '#FFF3F0', border: `1px solid ${ds.red}33`, borderRadius: ds.radius.sm, padding: '10px 14px',
    }}>
      <AlertTriangle size={15} color={ds.red} strokeWidth={2} style={{ flexShrink: 0, marginTop: 2 }} />
      <p style={{ flex: 1, fontFamily: ds.fontDm, fontSize: 13, color: ds.red, margin: 0, lineHeight: 1.5 }}>{message}</p>
      {onDismiss && (
        <button onClick={onDismiss} style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.red, padding: 0 }}>
          <X size={14} />
        </button>
      )}
    </div>
  )
}

const iconBtnStyle = {
  background: 'none', border: 'none', cursor: 'pointer', color: ds.gray,
  display: 'flex', alignItems: 'center', padding: 4, flexShrink: 0,
}

const linkBtnStyle = {
  background: 'none', border: 'none', cursor: 'pointer', color: ds.teal,
  fontFamily: ds.fontDm, fontSize: 13, fontWeight: 500, padding: '4px 2px', flexShrink: 0,
}

const approveBtnStyle = {
  background: ds.teal, color: ds.white, border: 'none', borderRadius: 7,
  fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 12.5, padding: '6px 12px',
  cursor: 'pointer', flexShrink: 0,
}

function pillBtnStyle(active) {
  return {
    background: active ? '#E8F8EE' : ds.border, color: active ? ds.green : ds.gray,
    border: 'none', borderRadius: 999, fontFamily: ds.fontDm, fontSize: 12, fontWeight: 600,
    padding: '5px 11px', cursor: 'pointer', flexShrink: 0,
  }
}
