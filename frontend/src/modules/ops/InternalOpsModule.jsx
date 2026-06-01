/**
 * frontend/src/modules/ops/InternalOpsModule.jsx
 * OPS-1 — Internal Ops Module (Issue Tracker + Activity Log)
 *
 * Tabs:
 *   🏗️ Issues       — log and track internal team issues
 *   📅 Activity Log — daily/weekly staff activity entries
 *
 * Pattern 26: all tab panels stay mounted, hidden with display:none.
 * Pattern 13: tab state is local useState — no URL routing.
 * Pattern 56: role check via user?.roles?.template
 * Pattern 11/12: org_id/user_id never sent in payloads — derived from JWT.
 * Pattern 51: full rewrite if editing — never partial sed.
 *
 * Props:
 *   user — current user object from Zustand auth store
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  listIssues, createIssue, updateIssue, deleteIssue, getIssuesSummary,
  listActivityLogs, submitActivityLog, updateActivityLog, getActivityLogsSummary,
  downloadInternalOpsReport,
} from '../../services/internal_ops.service'
import { getTeams, getInternalIssueCategories, listUsers } from '../../services/admin.service'

const PRIORITIES  = ['critical', 'high', 'medium', 'low']
const STATUSES    = ['open', 'in_progress', 'resolved']
const LOG_TYPES   = ['daily', 'weekly']

const PRIORITY_COLOURS = {
  critical: { bg: '#FEE2E2', text: '#991B1B' },
  high:     { bg: '#FEF3C7', text: '#92400E' },
  medium:   { bg: '#EEF8FA', text: '#0D9488' },
  low:      { bg: '#F1F5F9', text: '#64748B' },
}
const STATUS_COLOURS = {
  open:        { bg: '#FEF3C7', text: '#92400E' },
  in_progress: { bg: '#EEF8FA', text: '#0D9488' },
  resolved:    { bg: '#D1FAE5', text: '#065F46' },
}

// ── Shared styles ─────────────────────────────────────────────────────────────
const OVERLAY = {
  position: 'fixed', inset: 0,
  background: 'rgba(13,27,42,0.55)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  zIndex: 200,
}
const MODAL = {
  background: '#fff', borderRadius: 16, padding: 32,
  width: '100%', maxWidth: 560,
  boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
  maxHeight: '90vh', overflowY: 'auto',
}
const LBL = {
  display: 'block', fontSize: 11, fontWeight: 600, color: '#4a7a8a',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 6, marginTop: 14,
}
const INP = {
  width: '100%', border: '1.5px solid #D4E6EC', borderRadius: 9,
  padding: '10px 13px', fontSize: 13.5, color: '#0a1a24',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
  background: '#fff',
}
const BTN_PRIMARY = {
  background: ds.teal, color: '#fff', border: 'none',
  borderRadius: 9, padding: '10px 22px', fontSize: 13,
  fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
}
const BTN_OUTLINE = {
  background: '#fff', color: '#0a1a24', border: '1.5px solid #D4E6EC',
  borderRadius: 9, padding: '10px 18px', fontSize: 13,
  fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit',
}

function Badge({ text, colours }) {
  return (
    <span style={{
      background: colours?.bg || '#F1F5F9',
      color: colours?.text || '#64748B',
      borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 600,
    }}>
      {text?.replace(/_/g, ' ')}
    </span>
  )
}

function fmtDate(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return iso }
}

// ── Issue Detail Drawer ───────────────────────────────────────────────────────
function IssueDrawer({ issue, teamMembers, onUpdate, onDelete, isManager, onClose }) {
  const [form, setForm] = useState({
    status:           issue.status,
    assigned_to:      issue.assigned_to || '',
    resolution_notes: issue.resolution_notes || '',
    priority:         issue.priority,
  })
  const [saving, setSaving]   = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const [err, setErr]         = useState(null)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSave = async () => {
    setSaving(true); setErr(null)
    try {
      const payload = {}
      if (form.status           !== issue.status)                payload.status           = form.status
      if (form.priority         !== issue.priority)              payload.priority         = form.priority
      if (form.assigned_to      !== (issue.assigned_to || ''))   payload.assigned_to      = form.assigned_to || null
      if (form.resolution_notes !== (issue.resolution_notes || '')) payload.resolution_notes = form.resolution_notes || null
      if (Object.keys(payload).length === 0) { onClose(); return }
      await onUpdate(issue.id, payload)
      onClose()
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Save failed.')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try { await onDelete(issue.id); onClose() }
    catch (e) { setErr(e?.response?.data?.detail?.message ?? 'Delete failed.'); setDeleting(false) }
  }

  const teamFiltered = teamMembers.filter(u => !issue.team || u.team === issue.team)

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={{ ...MODAL, maxWidth: 600 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
          <div>
            <span style={{ fontSize: 12, color: '#7A9BAD', fontWeight: 600 }}>{issue.reference}</span>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '4px 0 0' }}>
              {issue.title}
            </h3>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD' }}>×</button>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0 16px' }}>
          <Badge text={issue.team} colours={{ bg: '#F0F9FF', text: '#0369A1' }} />
          <Badge text={issue.category} colours={{ bg: '#F5F3FF', text: '#6D28D9' }} />
          <Badge text={issue.priority} colours={PRIORITY_COLOURS[issue.priority]} />
          <Badge text={issue.status} colours={STATUS_COLOURS[issue.status]} />
        </div>

        {issue.description && (
          <p style={{ fontSize: 13.5, color: '#4a7a8a', lineHeight: 1.6, margin: '0 0 16px' }}>
            {issue.description}
          </p>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 12, color: '#7A9BAD', marginBottom: 20 }}>
          <div>Reported by: <strong style={{ color: '#0a1a24' }}>{issue.reporter?.full_name || '—'}</strong></div>
          <div>Reported: <strong style={{ color: '#0a1a24' }}>{fmtDate(issue.created_at)}</strong></div>
          {issue.resolved_at && <div>Resolved: <strong style={{ color: '#0a1a24' }}>{fmtDate(issue.resolved_at)}</strong></div>}
        </div>

        <div style={{ borderTop: '1px solid #E4EEF2', paddingTop: 18 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <label style={LBL}>Status</label>
              <select value={form.status} onChange={e => set('status', e.target.value)} style={INP}>
                {STATUSES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
            <div>
              <label style={LBL}>Priority</label>
              <select value={form.priority} onChange={e => set('priority', e.target.value)} style={INP}>
                {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
          </div>

          <label style={LBL}>Assigned To</label>
          <select value={form.assigned_to} onChange={e => set('assigned_to', e.target.value)} style={INP}>
            <option value="">— Unassigned —</option>
            {teamFiltered.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </select>

          <label style={LBL}>Resolution Notes</label>
          <textarea
            value={form.resolution_notes}
            onChange={e => set('resolution_notes', e.target.value)}
            placeholder="Describe how this was resolved…"
            rows={3}
            style={{ ...INP, resize: 'vertical' }}
          />
        </div>

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}>⚠ {err}</p>}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 20 }}>
          <div>
            {isManager && !confirmDel && (
              <button onClick={() => setConfirmDel(true)} style={{ ...BTN_OUTLINE, color: '#DC2626', borderColor: '#FECACA' }}>
                Delete
              </button>
            )}
            {confirmDel && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: '#DC2626' }}>Confirm delete?</span>
                <button onClick={handleDelete} disabled={deleting} style={{ ...BTN_OUTLINE, color: '#DC2626', borderColor: '#FECACA' }}>
                  {deleting ? 'Deleting…' : 'Yes, delete'}
                </button>
                <button onClick={() => setConfirmDel(false)} style={BTN_OUTLINE}>Cancel</button>
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={onClose} style={BTN_OUTLINE}>Cancel</button>
            <button onClick={handleSave} disabled={saving} style={{ ...BTN_PRIMARY, background: saving ? '#aaa' : ds.teal }}>
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── New Issue Modal ───────────────────────────────────────────────────────────
function NewIssueModal({ teams, categories, teamMembers, onCreate, onClose }) {
  const [form, setForm] = useState({ title: '', description: '', team: '', category: '', priority: 'medium', assigned_to: '' })
  const [saving, setSaving] = useState(false)
  const [err, setErr]       = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const filteredMembers = teamMembers.filter(u => !form.team || u.team === form.team)

  const handleSubmit = async () => {
    if (!form.title.trim())    { setErr('Title is required.'); return }
    if (!form.team)            { setErr('Team is required.'); return }
    if (!form.category)        { setErr('Category is required.'); return }
    setSaving(true); setErr(null)
    try {
      await onCreate({
        title:       form.title.trim(),
        description: form.description.trim() || null,
        team:        form.team,
        category:    form.category,
        priority:    form.priority,
        assigned_to: form.assigned_to || null,
      })
      onClose()
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Failed to create issue.')
      setSaving(false)
    }
  }

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={MODAL} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>
            New Issue
          </h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD' }}>×</button>
        </div>

        <label style={LBL}>Title *</label>
        <input value={form.title} onChange={e => set('title', e.target.value)} placeholder="Brief description of the issue" style={INP} />

        <label style={LBL}>Description</label>
        <textarea value={form.description} onChange={e => set('description', e.target.value)} placeholder="More detail (optional)" rows={3} style={{ ...INP, resize: 'vertical' }} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div>
            <label style={LBL}>Team *</label>
            <select value={form.team} onChange={e => { set('team', e.target.value); set('assigned_to', '') }} style={INP}>
              <option value="">Select team</option>
              {teams.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label style={LBL}>Category *</label>
            <select value={form.category} onChange={e => set('category', e.target.value)} style={INP}>
              <option value="">Select category</option>
              {categories.filter(c => c.enabled !== false).map(c => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div>
            <label style={LBL}>Priority</label>
            <select value={form.priority} onChange={e => set('priority', e.target.value)} style={INP}>
              {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label style={LBL}>Assign To</label>
            <select value={form.assigned_to} onChange={e => set('assigned_to', e.target.value)} style={INP} disabled={!form.team}>
              <option value="">— Unassigned —</option>
              {filteredMembers.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
            </select>
          </div>
        </div>

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}>⚠ {err}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={BTN_OUTLINE}>Cancel</button>
          <button onClick={handleSubmit} disabled={saving} style={{ ...BTN_PRIMARY, background: saving ? '#aaa' : ds.teal }}>
            {saving ? 'Creating…' : 'Create Issue'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Log Activity Modal ────────────────────────────────────────────────────────
function LogActivityModal({ logType, existingLog, onSubmit, onClose }) {
  const today = new Date().toISOString().split('T')[0]
  // For weekly logs use Monday of current week
  const getMonday = () => {
    const d = new Date(); const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    return new Date(d.setDate(diff)).toISOString().split('T')[0]
  }

  const [form, setForm] = useState({
    activities: existingLog?.activities || '',
    blockers:   existingLog?.blockers   || '',
    plan:       existingLog?.plan       || '',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr]       = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const isUpdate = !!existingLog

  const handleSubmit = async () => {
    if (!form.activities.trim()) { setErr('Activities field is required.'); return }
    setSaving(true); setErr(null)
    try {
      const logDate = logType === 'weekly' ? getMonday() : today
      if (isUpdate) {
        await onSubmit(existingLog.id, {
          activities: form.activities.trim(),
          blockers:   form.blockers.trim() || null,
          plan:       form.plan.trim()     || null,
        }, true)
      } else {
        await onSubmit({
          log_date:   logDate,
          log_type:   logType,
          activities: form.activities.trim(),
          blockers:   form.blockers.trim() || null,
          plan:       form.plan.trim()     || null,
        }, false)
      }
      onClose()
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Failed to save log.')
      setSaving(false)
    }
  }

  const actLabel  = logType === 'weekly' ? 'What I did this week *'       : 'What I did today *'
  const planLabel = logType === 'weekly' ? 'Plan for next week'            : 'Plan for tomorrow'
  const title     = isUpdate
    ? (logType === 'weekly' ? 'Update Weekly Log' : 'Update Today\'s Log')
    : (logType === 'weekly' ? 'Log This Week'     : 'Log Today')

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={MODAL} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>{title}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD' }}>×</button>
        </div>

        <label style={LBL}>{actLabel}</label>
        <textarea value={form.activities} onChange={e => set('activities', e.target.value)} placeholder="Describe what you worked on…" rows={4} style={{ ...INP, resize: 'vertical' }} />

        <label style={LBL}>Any blockers?</label>
        <textarea value={form.blockers} onChange={e => set('blockers', e.target.value)} placeholder="Anything blocking progress? (optional)" rows={2} style={{ ...INP, resize: 'vertical' }} />

        <label style={LBL}>{planLabel}</label>
        <textarea value={form.plan} onChange={e => set('plan', e.target.value)} placeholder="What are you planning next? (optional)" rows={2} style={{ ...INP, resize: 'vertical' }} />

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}>⚠ {err}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={BTN_OUTLINE}>Cancel</button>
          <button onClick={handleSubmit} disabled={saving} style={{ ...BTN_PRIMARY, background: saving ? '#aaa' : ds.teal }}>
            {saving ? 'Saving…' : (isUpdate ? 'Update Log' : 'Submit Log')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Issues Tab ────────────────────────────────────────────────────────────────
function IssuesTab({ user }) {
  const isManager = ['owner', 'ops_manager'].includes(user?.roles?.template)
  const [issues, setIssues]           = useState([])
  const [teams, setTeams]             = useState([])
  const [categories, setCategories]   = useState([])
  const [teamMembers, setTeamMembers] = useState([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)
  const [filterTeam, setFilterTeam]   = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [showNew, setShowNew]           = useState(false)
  const [selected, setSelected]         = useState(null)
  const [showDownload, setShowDownload] = useState(false)
  const [downloading, setDownloading]   = useState(false)
  const [dlError, setDlError]           = useState(null)
  const [dlPreset,  setDlPreset]        = useState('this_month')
  const [dlFilters, setDlFilters]       = useState({
    date_from: '', date_to: '', team: '', category: '',
    status_filter: '', priority: '',
  })

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = {}
      if (filterTeam)   params.team          = filterTeam
      if (filterStatus) params.status_filter = filterStatus
      const [issData, teamsData, catsData, usersData] = await Promise.all([
        listIssues(params),
        getTeams(),
        getInternalIssueCategories(),
        listUsers(),
      ])
      setIssues(issData?.items ?? [])
      setTeams(teamsData?.teams ?? [])
      setCategories(catsData?.categories ?? [])
      setTeamMembers(usersData ?? [])
    } catch {
      setError('Failed to load issues.')
    } finally { setLoading(false) }
  }, [filterTeam, filterStatus])

  useEffect(() => { load() }, [load])

  const handleCreate = async (payload) => { await createIssue(payload); load() }
  const handleUpdate = async (id, payload) => { await updateIssue(id, payload); load() }
  const handleDelete = async (id) => { await deleteIssue(id); load() }

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading issues…</div>
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}>⚠ {error} <button onClick={load} style={{ ...BTN_OUTLINE, marginLeft: 10, padding: '5px 12px', fontSize: 12 }}>Retry</button></div>

  return (
    <div style={{ padding: 28 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Issues</h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>{issues.length} issue{issues.length !== 1 ? 's' : ''}</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {isManager && (
            <button onClick={() => { setDlError(null); setShowDownload(true) }}
              style={{ ...BTN_OUTLINE, padding: '8px 16px', fontSize: 13 }}>
              ⬇ Download Report
            </button>
          )}
          <button onClick={() => setShowNew(true)} style={BTN_PRIMARY}>+ New Issue</button>
        </div>
      </div>

      {showDownload && (
        <div style={OVERLAY} onClick={() => { setShowDownload(false); setDlPreset('this_month') }}>
          <div style={{ ...MODAL, maxWidth: 480 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', marginBottom: 20 }}>
              <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700,
                fontSize: 17, color: '#0a1a24', margin: 0 }}>
                Download Issues Report
              </h3>
              <button onClick={() => { setShowDownload(false); setDlPreset('this_month') }}
                style={{ background: 'none', border: 'none',
                  fontSize: 22, cursor: 'pointer', color: '#7A9BAD' }}>×</button>
            </div>

            {/* Period presets */}
            <label style={LBL}>Period</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
              {[
                { id: 'this_month',  label: 'This Month'  },
                { id: 'last_month',  label: 'Last Month'  },
                { id: 'last_7d',     label: 'Last 7d'     },
                { id: 'last_30d',    label: 'Last 30d'    },
                { id: 'last_90d',    label: 'Last 90d'    },
                { id: 'this_year',   label: 'This Year'   },
                { id: 'custom',      label: 'Custom'      },
              ].map(p => (
                <button
                  key={p.id}
                  onClick={() => {
                    setDlPreset(p.id)
                    if (p.id !== 'custom') {
                      const today = new Date()
                      const fmt   = d => d.toISOString().slice(0, 10)
                      let from, to = fmt(today)
                      if (p.id === 'this_month') {
                        from = fmt(new Date(today.getFullYear(), today.getMonth(), 1))
                      } else if (p.id === 'last_month') {
                        const f = new Date(today.getFullYear(), today.getMonth() - 1, 1)
                        const t = new Date(today.getFullYear(), today.getMonth(), 0)
                        from = fmt(f); to = fmt(t)
                      } else if (p.id === 'last_7d') {
                        const f = new Date(today); f.setDate(today.getDate() - 6)
                        from = fmt(f)
                      } else if (p.id === 'last_30d') {
                        const f = new Date(today); f.setDate(today.getDate() - 29)
                        from = fmt(f)
                      } else if (p.id === 'last_90d') {
                        const f = new Date(today); f.setDate(today.getDate() - 89)
                        from = fmt(f)
                      } else if (p.id === 'this_year') {
                        from = fmt(new Date(today.getFullYear(), 0, 1))
                      }
                      setDlFilters(f => ({ ...f, date_from: from, date_to: to }))
                    }
                  }}
                  style={{
                    padding: '5px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600,
                    fontFamily: ds.fontSyne, cursor: 'pointer', border: 'none',
                    background: dlPreset === p.id ? ds.teal : '#E4EEF2',
                    color:      dlPreset === p.id ? 'white'  : '#3A5A6A',
                    transition: 'all 0.15s',
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Custom date pickers — only shown when Custom is selected */}
            {dlPreset === 'custom' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 4 }}>
                <div>
                  <label style={LBL}>Date From</label>
                  <input type='date' value={dlFilters.date_from}
                    onChange={e => setDlFilters(f => ({ ...f, date_from: e.target.value }))}
                    style={INP} />
                </div>
                <div>
                  <label style={LBL}>Date To</label>
                  <input type='date' value={dlFilters.date_to}
                    onChange={e => setDlFilters(f => ({ ...f, date_to: e.target.value }))}
                    style={INP} />
                </div>
              </div>
            )}

            <label style={LBL}>Team</label>
            <select value={dlFilters.team}
              onChange={e => setDlFilters(f => ({ ...f, team: e.target.value }))}
              style={INP}>
              <option value=''>All Teams</option>
              {teams.map(t => <option key={t} value={t}>{t}</option>)}
            </select>

            <label style={LBL}>Category</label>
            <select value={dlFilters.category}
              onChange={e => setDlFilters(f => ({ ...f, category: e.target.value }))}
              style={INP}>
              <option value=''>All Categories</option>
              {categories.filter(c => c.enabled !== false).map(c => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </select>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={LBL}>Status</label>
                <select value={dlFilters.status_filter}
                  onChange={e => setDlFilters(f => ({ ...f, status_filter: e.target.value }))}
                  style={INP}>
                  <option value=''>All Statuses</option>
                  {STATUSES.map(s => (
                    <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={LBL}>Priority</label>
                <select value={dlFilters.priority}
                  onChange={e => setDlFilters(f => ({ ...f, priority: e.target.value }))}
                  style={INP}>
                  <option value=''>All Priorities</option>
                  {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>

            {dlError && (
              <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}>⚠ {dlError}</p>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end',
              gap: 10, marginTop: 24 }}>
              <button onClick={() => { setShowDownload(false); setDlPreset('this_month') }} style={BTN_OUTLINE}>
                Cancel
              </button>
              <button
                disabled={downloading}
                style={{ ...BTN_PRIMARY, background: downloading ? '#aaa' : ds.teal }}
                onClick={async () => {
                  setDownloading(true)
                  setDlError(null)
                  try {
                    const params = {}
                    if (dlFilters.date_from)     params.date_from     = dlFilters.date_from
                    if (dlFilters.date_to)       params.date_to       = dlFilters.date_to
                    if (dlFilters.team)          params.team          = dlFilters.team
                    if (dlFilters.category)      params.category      = dlFilters.category
                    if (dlFilters.status_filter) params.status_filter = dlFilters.status_filter
                    if (dlFilters.priority)      params.priority      = dlFilters.priority
                    const blob = await downloadInternalOpsReport(params)
                    const url  = URL.createObjectURL(blob)
                    const a    = document.createElement('a')
                    const from = dlFilters.date_from || 'all'
                    const to   = dlFilters.date_to   || 'today'
                    a.href     = url
                    a.download = `Internal_Ops_Report_${from}_to_${to}.pdf`
                    a.click()
                    URL.revokeObjectURL(url)
                    setShowDownload(false)
                    setDlPreset('this_month')
                  } catch (e) {
                    const msg = e?.response?.status === 429
                      ? 'You can download up to 10 reports per hour.'
                      : (e?.response?.data?.detail?.message ?? 'Download failed. Please try again.')
                    setDlError(msg)
                  } finally {
                    setDownloading(false)
                  }
                }}
              >
                {downloading ? 'Generating PDF…' : '⬇ Download PDF'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        {isManager && (
          <select value={filterTeam} onChange={e => setFilterTeam(e.target.value)}
            style={{ ...INP, width: 'auto', padding: '7px 12px', fontSize: 13 }}>
            <option value="">All Teams</option>
            {teams.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          style={{ ...INP, width: 'auto', padding: '7px 12px', fontSize: 13 }}>
          <option value="">All Statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
      </div>

      {/* Table */}
      {issues.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 32px', color: '#7A9BAD' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🏗️</div>
          <p style={{ fontSize: 14 }}>No issues found. Create one to get started.</p>
        </div>
      ) : (
        <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#F5F9FA' }}>
                {['Ref', 'Title', 'Team', 'Priority', 'Status', 'Assigned To', 'Reported'].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.7px', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {issues.map((iss, i) => (
                <tr
                  key={iss.id}
                  onClick={() => setSelected(iss)}
                  style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none', cursor: 'pointer', transition: 'background 0.1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#F8FCFD'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}
                >
                  <td style={{ padding: '12px 14px', fontSize: 12, color: '#7A9BAD', fontWeight: 600 }}>{iss.reference}</td>
                  <td style={{ padding: '12px 14px', fontSize: 13.5, color: '#0a1a24', fontWeight: 500, maxWidth: 260 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{iss.title}</div>
                  </td>
                  <td style={{ padding: '12px 14px' }}><Badge text={iss.team} colours={{ bg: '#F0F9FF', text: '#0369A1' }} /></td>
                  <td style={{ padding: '12px 14px' }}><Badge text={iss.priority} colours={PRIORITY_COLOURS[iss.priority]} /></td>
                  <td style={{ padding: '12px 14px' }}><Badge text={iss.status} colours={STATUS_COLOURS[iss.status]} /></td>
                  <td style={{ padding: '12px 14px', fontSize: 13, color: '#4a7a8a' }}>{iss.assignee?.full_name || '—'}</td>
                  <td style={{ padding: '12px 14px', fontSize: 12, color: '#7A9BAD' }}>{fmtDate(iss.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew && (
        <NewIssueModal
          teams={teams}
          categories={categories}
          teamMembers={teamMembers}
          onCreate={handleCreate}
          onClose={() => setShowNew(false)}
        />
      )}

      {selected && (
        <IssueDrawer
          issue={selected}
          teamMembers={teamMembers}
          isManager={isManager}
          onUpdate={async (id, payload) => { await handleUpdate(id, payload); setSelected(null) }}
          onDelete={async (id) => { await handleDelete(id); setSelected(null) }}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}

// ── Activity Log Tab ──────────────────────────────────────────────────────────
function ActivityLogTab({ user }) {
  const isManager = ['owner', 'ops_manager'].includes(user?.roles?.template)
  const [logs, setLogs]               = useState([])
  const [users, setUsers]             = useState([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)
  const [filterUser, setFilterUser]   = useState('')
  const [filterType, setFilterType]   = useState('')
  const [expanded, setExpanded]       = useState(null)
  const [logModal, setLogModal]       = useState(null)  // null | 'daily' | 'weekly'

  // Check for existing log today/this week for upsert UI
  const today = new Date().toISOString().split('T')[0]
  const getMonday = () => {
    const d = new Date(); const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    return new Date(new Date().setDate(diff)).toISOString().split('T')[0]
  }

  const todayLog  = logs.find(l => l.user_id === user?.id && l.log_type === 'daily'  && l.log_date === today)
  const weekLog   = logs.find(l => l.user_id === user?.id && l.log_type === 'weekly' && l.log_date === getMonday())

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = {}
      if (filterUser) params.user_id_filter = filterUser
      if (filterType) params.log_type       = filterType
      const [logsData, usersData] = await Promise.all([
        listActivityLogs(params),
        isManager ? listUsers() : Promise.resolve([]),
      ])
      setLogs(logsData?.items ?? [])
      setUsers(usersData ?? [])
    } catch {
      setError('Failed to load activity logs.')
    } finally { setLoading(false) }
  }, [filterUser, filterType, isManager])

  useEffect(() => { load() }, [load])

  const handleSubmit = async (payloadOrId, updatePayload, isUpdate) => {
    if (isUpdate) {
      await updateActivityLog(payloadOrId, updatePayload)
    } else {
      await submitActivityLog(payloadOrId)
    }
    load()
  }

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading activity logs…</div>
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}>⚠ {error} <button onClick={load} style={{ ...BTN_OUTLINE, marginLeft: 10, padding: '5px 12px', fontSize: 12 }}>Retry</button></div>

  return (
    <div style={{ padding: 28 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Activity Log</h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>Record what you worked on each day or week</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setLogModal('daily')} style={{ ...BTN_OUTLINE, padding: '8px 16px', fontSize: 13 }}>
            {todayLog ? '✏️ Update Today' : '+ Log Today'}
          </button>
          <button onClick={() => setLogModal('weekly')} style={{ ...BTN_PRIMARY, padding: '8px 16px', fontSize: 13 }}>
            {weekLog ? '✏️ Update Week' : '+ Log This Week'}
          </button>
        </div>
      </div>

      {/* Manager filters */}
      {isManager && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
          <select value={filterUser} onChange={e => setFilterUser(e.target.value)}
            style={{ ...INP, width: 'auto', padding: '7px 12px', fontSize: 13 }}>
            <option value="">All Staff</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </select>
          <select value={filterType} onChange={e => setFilterType(e.target.value)}
            style={{ ...INP, width: 'auto', padding: '7px 12px', fontSize: 13 }}>
            <option value="">Daily + Weekly</option>
            <option value="daily">Daily only</option>
            <option value="weekly">Weekly only</option>
          </select>
        </div>
      )}

      {/* Log list */}
      {logs.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 32px', color: '#7A9BAD' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📅</div>
          <p style={{ fontSize: 14 }}>No activity logs yet. Start by logging today's activities.</p>
        </div>
      ) : (
        <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
          {logs.map((log, i) => {
            const isOpen = expanded === log.id
            return (
              <div key={log.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none' }}>
                <div
                  onClick={() => setExpanded(isOpen ? null : log.id)}
                  style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '13px 18px', cursor: 'pointer', transition: 'background 0.1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#F8FCFD'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#0a1a24' }}>
                        {log.user?.full_name || 'You'}
                      </span>
                      <Badge text={log.team || '—'} colours={{ bg: '#F0F9FF', text: '#0369A1' }} />
                      <Badge text={log.log_type} colours={{ bg: '#F5F3FF', text: '#6D28D9' }} />
                      {log.blockers && <span style={{ fontSize: 11, background: '#FEE2E2', color: '#991B1B', borderRadius: 20, padding: '2px 8px', fontWeight: 600 }}>🚧 Blocker</span>}
                    </div>
                    <div style={{ fontSize: 12, color: '#7A9BAD', marginTop: 3 }}>
                      {fmtDate(log.log_date)} · {log.activities?.substring(0, 80)}{log.activities?.length > 80 ? '…' : ''}
                    </div>
                  </div>
                  <span style={{ color: '#7A9BAD', fontSize: 16, flexShrink: 0 }}>{isOpen ? '▲' : '▼'}</span>
                </div>

                {isOpen && (
                  <div style={{ padding: '4px 18px 18px', background: '#F8FAFC', borderTop: '1px solid #F0F7FA' }}>
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ ...LBL, marginTop: 12 }}>Activities</div>
                      <p style={{ fontSize: 13.5, color: '#0a1a24', lineHeight: 1.7, margin: 0, whiteSpace: 'pre-wrap' }}>{log.activities}</p>
                    </div>
                    {log.blockers && (
                      <div style={{ marginBottom: 12 }}>
                        <div style={LBL}>Blockers</div>
                        <p style={{ fontSize: 13.5, color: '#0a1a24', lineHeight: 1.7, margin: 0, whiteSpace: 'pre-wrap' }}>{log.blockers}</p>
                      </div>
                    )}
                    {log.plan && (
                      <div>
                        <div style={LBL}>Plan</div>
                        <p style={{ fontSize: 13.5, color: '#0a1a24', lineHeight: 1.7, margin: 0, whiteSpace: 'pre-wrap' }}>{log.plan}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {logModal && (
        <LogActivityModal
          logType={logModal}
          existingLog={logModal === 'daily' ? todayLog : weekLog}
          onSubmit={handleSubmit}
          onClose={() => setLogModal(null)}
        />
      )}
    </div>
  )
}

// ── Main Module ───────────────────────────────────────────────────────────────
const ALL_TABS = [
  { id: 'issues',   label: 'Issues',       icon: '🏗️' },
  { id: 'activity', label: 'Activity Log', icon: '📅' },
]

export default function InternalOpsModule({ user }) {
  const role = user?.roles?.template || ''
  const isSalesAgent = role === 'sales_agent'

  // Sales agents see Activity Log only — Issues tab hidden
  const TABS = isSalesAgent
    ? ALL_TABS.filter(t => t.id === 'activity')
    : ALL_TABS

  // Sales agents land on activity; everyone else on issues
  const [activeTab, setActiveTab] = useState(isSalesAgent ? 'activity' : 'issues')

  return (
    <div>
      {/* Tab bar */}
      <div style={{
        display: 'flex', gap: 4,
        borderBottom: '1px solid #E4EEF2',
        padding: '0 28px',
        background: 'white',
      }}>
        {TABS.map(tab => {
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '13px 16px 11px',
                background: 'none', border: 'none',
                borderBottom: active ? `2px solid ${ds.teal}` : '2px solid transparent',
                cursor: 'pointer', fontSize: 13.5,
                fontWeight: active ? 600 : 400,
                fontFamily: ds.fontDm,
                color: active ? ds.teal : '#7A9BAD',
                transition: 'all 0.15s', whiteSpace: 'nowrap',
                marginBottom: -1,
              }}
            >
              <span>{tab.icon}</span> {tab.label}
            </button>
          )
        })}
      </div>

      {/* Pattern 26: mount-and-hide */}
      <div style={{ display: activeTab === 'issues'   ? 'block' : 'none' }}>
        <IssuesTab user={user} />
      </div>
      <div style={{ display: activeTab === 'activity' ? 'block' : 'none' }}>
        <ActivityLogTab user={user} />
      </div>
    </div>
  )
}
