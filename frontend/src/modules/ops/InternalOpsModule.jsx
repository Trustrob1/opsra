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
import { AlertTriangle, Flag, Edit, CheckCircle, Construction, CalendarDays, X } from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  listIssues, createIssue, updateIssue, deleteIssue, getIssuesSummary,
  listActivityLogs, submitActivityLog, submitActivityLogBulk, updateActivityLog, getActivityLogsSummary,
  downloadInternalOpsReport, downloadActivityLogReport,
} from '../../services/internal_ops.service'
import { toggleOwnerAttention } from '../../services/performance.service'
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

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{err}</span></p>}

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

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{err}</span></p>}

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
const STAFF_ACTIVITY_TYPES = [
  'General', 'Content Creation', 'Research', 'Client Communication',
  'Design', 'Development', 'Strategy', 'Admin', 'Meeting', 'Sales', 'Other',
]

function LogActivityModal({ logType, existingLog, onSubmit, onClose }) {
  const today = new Date().toISOString().split('T')[0]
  const getMonday = () => {
    const d = new Date(); const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    return new Date(d.setDate(diff)).toISOString().split('T')[0]
  }

  const isUpdate = !!existingLog

  // Seed entries from existing log if updating
  const seedEntries = () => {
    if (!isUpdate) return [{ activity_description: '', activity_type: 'General', duration_minutes: '', has_blocker: false, blocker_note: '', plan: '' }]
    // If existing log has structured entries, restore them
    if (existingLog.entries?.length) {
      return existingLog.entries.map(e => ({
        activity_description: e.activity_description || '',
        activity_type:        e.activity_type || 'General',
        duration_minutes:     e.duration_minutes || '',
        has_blocker:          e.has_blocker || false,
        blocker_note:         e.blocker_note || '',
        plan:                 e.plan || '',
      }))
    }
    // Legacy single-entry format
    return [{ activity_description: existingLog.activities || '', activity_type: 'General', duration_minutes: '', has_blocker: !!(existingLog.blockers), blocker_note: existingLog.blockers || '', plan: existingLog.plan || '' }]
  }

  const [entries,  setEntries]  = useState(seedEntries)
  const [saving,   setSaving]   = useState(false)
  const [err,      setErr]      = useState(null)
  const [logDate,  setLogDate]  = useState(() => {
    if (existingLog?.log_date) return existingLog.log_date
    return logType === 'weekly' ? getMonday() : today
  })

  const addEntry    = () => setEntries(p => [...p, { activity_description: '', activity_type: 'General', duration_minutes: '', has_blocker: false, blocker_note: '', plan: '' }])
  const removeEntry = (i) => setEntries(p => p.filter((_, idx) => idx !== i))
  const updateEntry = (i, field, val) => setEntries(p => { const n = [...p]; n[i] = { ...n[i], [field]: val }; return n })

  const validEntries = entries.filter(e => e.activity_description.trim())

  const handleSubmit = async () => {
    if (validEntries.length === 0) { setErr('At least one activity description is required.'); return }
    setSaving(true); setErr(null)
    try {
      // Both new and update use bulk endpoint — upsert handles the rest
      await submitActivityLogBulk({
        log_date: logDate,
        log_type: logType,
        entries:  validEntries.map(e => ({
          activity_description: e.activity_description.trim(),
          activity_type:        e.activity_type || 'General',
          duration_minutes:     e.duration_minutes ? parseInt(e.duration_minutes) : null,
          has_blocker:          e.has_blocker,
          blocker_note:         e.has_blocker ? (e.blocker_note.trim() || null) : null,
          plan:                 e.plan.trim() || null,
        })),
      })
      onSubmit(null, null, false) // trigger list reload
      onClose()
    } catch (e) {
      setErr(e?.response?.data?.detail?.message ?? 'Failed to save log.')
      setSaving(false)
    }
  }

  const planLabel = logType === 'weekly' ? 'Plan for next week' : 'Plan for tomorrow'
  const title = isUpdate
    ? (logType === 'weekly' ? "Update Weekly Log" : "Update Today's Log")
    : (logType === 'weekly' ? 'Log This Week'     : 'Log Today')

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={{ ...MODAL, maxWidth: 600 }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>{title}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD' }}>×</button>
        </div>

        {/* Date picker — allows logging for any past date */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, padding: '8px 12px', background: '#f4f8fb', borderRadius: 8, border: '1px solid #dce8ef' }}>
          <span style={{ fontSize: 13, color: '#4a6274', fontWeight: 600, whiteSpace: 'nowrap' }}>Log date:</span>
          <input
            type="date"
            value={logDate}
            max={today}
            onChange={e => setLogDate(e.target.value || today)}
            style={{ fontSize: 13, border: '1.5px solid #b8d0dc', borderRadius: 6, padding: '4px 8px', color: '#0a1a24', background: '#fff', cursor: 'pointer', flex: 1 }}
          />
          {logDate !== today && (
            <span style={{ fontSize: 11, color: '#e67e22', fontWeight: 600, whiteSpace: 'nowrap' }}>Logging for past date</span>
          )}
        </div>

        {/* Entry count indicator */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: 0 }}>
            {validEntries.length > 0
              ? `${validEntries.length} activit${validEntries.length > 1 ? 'ies' : 'y'} to log`
              : 'Add your activities for today'}
          </p>
          <button onClick={addEntry}
            style={{ ...BTN_OUTLINE, padding: '6px 14px', fontSize: 12, color: ds.teal, borderColor: ds.teal }}>
            + Add activity
          </button>
        </div>

        {err && <p style={{ color: '#DC2626', fontSize: 13, marginBottom: 12 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{err}</span></p>}

        {/* Entry cards */}
        {entries.map((entry, i) => (
          <div key={i} style={{ background: '#f8fafc', border: '1.5px solid #D4E6EC', borderRadius: 10, padding: '14px 16px', marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#4a7a8a', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Activity {i + 1}
              </span>
              {entries.length > 1 && (
                <button onClick={() => removeEntry(i)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#DC2626', padding: 0, display:'flex', alignItems:'center' }}><X size={16} /></button>
              )}
            </div>

            <label style={LBL}>{logType === 'weekly' ? 'What I did this week *' : 'What I did today *'}</label>
            <textarea
              value={entry.activity_description}
              onChange={e => updateEntry(i, 'activity_description', e.target.value)}
              placeholder="Describe what you worked on…"
              rows={3}
              style={{ ...INP, resize: 'vertical', marginBottom: 10 }}
            />

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <div>
                <label style={LBL}>Activity type</label>
                <select value={entry.activity_type} onChange={e => updateEntry(i, 'activity_type', e.target.value)}
                  style={{ ...INP, background: 'white' }}>
                  {STAFF_ACTIVITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label style={LBL}>Hours worked</label>
                <input type="number" min="0" max="24" step="0.5"
                  value={entry.duration_minutes}
                  onChange={e => updateEntry(i, 'duration_minutes', e.target.value)}
                  placeholder="e.g. 2"
                  style={INP} />
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: entry.has_blocker ? 8 : 0 }}>
              <input type="checkbox" id={`blocker-staff-${i}`} checked={entry.has_blocker}
                onChange={e => updateEntry(i, 'has_blocker', e.target.checked)}
                style={{ accentColor: '#DC2626', width: 15, height: 15 }} />
              <label htmlFor={`blocker-staff-${i}`}
                style={{ fontSize: 13, color: entry.has_blocker ? '#DC2626' : '#4a7a8a', fontWeight: entry.has_blocker ? 600 : 400, cursor: 'pointer' }}>
                <span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} color="#DC2626" />This activity has a blocker</span>
              </label>
            </div>

            {entry.has_blocker && (
              <textarea
                value={entry.blocker_note}
                onChange={e => updateEntry(i, 'blocker_note', e.target.value)}
                placeholder="Describe the blocker…"
                rows={2}
                style={{ ...INP, resize: 'vertical', borderColor: '#FECACA', marginTop: 8 }}
              />
            )}

            {/* Plan on last entry only */}
            {i === entries.length - 1 && (
              <>
                <label style={LBL}>{planLabel}</label>
                <textarea
                  value={entry.plan}
                  onChange={e => updateEntry(i, 'plan', e.target.value)}
                  placeholder="What are you planning next? (optional)"
                  rows={2}
                  style={{ ...INP, resize: 'vertical' }}
                />
              </>
            )}
          </div>
        ))}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8 }}>
          <button onClick={onClose} style={BTN_OUTLINE}>Cancel</button>
          <button onClick={handleSubmit} disabled={saving || validEntries.length === 0}
            style={{ ...BTN_PRIMARY, background: saving || validEntries.length === 0 ? '#aaa' : ds.teal }}>
            {saving ? 'Saving…' : isUpdate ? 'Update Log' : `Submit ${validEntries.length > 1 ? `${validEntries.length} Activities` : 'Log'}`}
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
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{error}</span> <button onClick={load} style={{ ...BTN_OUTLINE, marginLeft: 10, padding: '5px 12px', fontSize: 12 }}>Retry</button></div>

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
              <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{dlError}</span></p>
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
          <div style={{ display:"flex",justifyContent:"center",marginBottom:12 }}><Construction size={40} color={ds.teal} strokeWidth={1.5} /></div>
          <p style={{ fontSize: 14 }}>No issues found. Create one to get started.</p>
        </div>
      ) : (
        <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#F5F9FA' }}>
                {['Ref', 'Title', 'Team', 'Priority', 'Status', 'Assigned To', 'Reported', ''].map(h => (
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
                  <td style={{ padding: '12px 14px' }} onClick={e => e.stopPropagation()}>
                    {isManager && (
                      <button
                        title={iss.needs_owner_attention ? 'Remove owner flag' : 'Flag for owner attention'}
                        onClick={async (e) => {
                          e.stopPropagation()
                          await toggleOwnerAttention(iss.id, !iss.needs_owner_attention)
                          load()
                        }}
                        style={{
                          background: iss.needs_owner_attention ? '#FCEBEB' : '#f9fafb',
                          border: `1px solid ${iss.needs_owner_attention ? '#fca5a5' : '#e5e7eb'}`,
                          borderRadius: 6, padding: '4px 8px', cursor: 'pointer',
                          fontSize: 11, fontWeight: 500,
                          color: iss.needs_owner_attention ? '#A32D2D' : '#9ca3af',
                          display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap',
                        }}
                      >
                        <span style={{display:"inline-flex",alignItems:"center",gap:4}}><Flag size={12} />{iss.needs_owner_attention ? "Flagged" : "Flag"}</span>
                      </button>
                    )}
                  </td>
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

  // logModal: null | { logType: 'daily'|'weekly', existingLog: obj|null }
  const [logModal, setLogModal]       = useState(null)

  // Download report state
  const [showDlModal, setShowDlModal]   = useState(false)
  const [dlDownloading, setDlDownloading] = useState(false)
  const [dlError, setDlError]           = useState(null)
  const [dlPreset, setDlPreset]         = useState('this_month')
  const [dlFilters, setDlFilters]       = useState({
    date_from: '', date_to: '', user_id_filter: '', team: '', include_contractors: true,
  })

  // Local date — avoids UTC-offset mismatch (e.g. WAT = UTC+1)
  const today = (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
  })()
  const getMonday = () => {
    const d = new Date(); const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    const m = new Date(d.setDate(diff))
    return `${m.getFullYear()}-${String(m.getMonth()+1).padStart(2,'0')}-${String(m.getDate()).padStart(2,'0')}`
  }

  // Date-aware: only true if current user has a daily log for TODAY specifically
  const todayLog = logs.find(
    l => l.user_id === user?.id && l.log_type === 'daily' && l.log_date === today
  )
  const weekLog = logs.find(
    l => l.user_id === user?.id && l.log_type === 'weekly' && l.log_date === getMonday()
  )

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

  // Re-fetch when tab becomes visible — Pattern 26 keeps component mounted,
  // so switching back to this tab won't trigger a mount re-fetch without this.
  useEffect(() => {
    const handleVisibility = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [load])

  const handleSubmit = async (payloadOrId, updatePayload, isUpdate) => {
    if (isUpdate) {
      await updateActivityLog(payloadOrId, updatePayload)
    } else if (payloadOrId !== null) {
      await submitActivityLog(payloadOrId)
    }
    load()
  }

  // Edit: open modal pre-populated with that row's entries (any date, any log)
  const openEdit = (log, e) => {
    e.stopPropagation()
    setLogModal({ logType: log.log_type, existingLog: log })
  }

  // Resolve preset → date_from / date_to
  const resolveDlPreset = (preset) => {
    const today = new Date()
    const pad   = n => String(n).padStart(2, '0')
    const fmt   = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
    if (preset === 'this_week') {
      const mon = new Date(today); mon.setDate(today.getDate() - today.getDay() + (today.getDay()===0?-6:1))
      return { date_from: fmt(mon), date_to: fmt(today) }
    }
    if (preset === 'this_month') {
      return { date_from: fmt(new Date(today.getFullYear(), today.getMonth(), 1)), date_to: fmt(today) }
    }
    if (preset === 'last_month') {
      const first = new Date(today.getFullYear(), today.getMonth()-1, 1)
      const last  = new Date(today.getFullYear(), today.getMonth(), 0)
      return { date_from: fmt(first), date_to: fmt(last) }
    }
    if (preset === 'last_3_months') {
      const from = new Date(today); from.setMonth(today.getMonth()-3)
      return { date_from: fmt(from), date_to: fmt(today) }
    }
    return { date_from: dlFilters.date_from, date_to: dlFilters.date_to }
  }

  const handleDlPreset = (preset) => {
    setDlPreset(preset)
    if (preset !== 'custom') {
      const { date_from, date_to } = resolveDlPreset(preset)
      setDlFilters(f => ({ ...f, date_from, date_to }))
    }
  }

  const handleDlDownload = async () => {
    setDlDownloading(true); setDlError(null)
    try {
      const { date_from, date_to } = dlPreset !== 'custom'
        ? resolveDlPreset(dlPreset)
        : { date_from: dlFilters.date_from, date_to: dlFilters.date_to }
      const params = {}
      if (date_from)               params.date_from            = date_from
      if (date_to)                 params.date_to              = date_to
      if (dlFilters.user_id_filter) params.user_id_filter      = dlFilters.user_id_filter
      if (dlFilters.team)          params.team                 = dlFilters.team
      params.include_contractors = dlFilters.include_contractors ? 'true' : 'false'
      const blob = await downloadActivityLogReport(params)
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      const from = date_from || 'all'
      const to   = date_to   || 'today'
      a.href     = url
      a.download = `Activity_Log_${from}_to_${to}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      setShowDlModal(false)
      setDlPreset('this_month')
    } catch (e) {
      const msg = e?.response?.status === 429
        ? 'Download limit reached (10/hr). Try again later.'
        : (e?.response?.data?.detail?.message ?? 'Download failed. Please try again.')
      setDlError(msg)
    } finally { setDlDownloading(false) }
  }


  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading activity logs…</div>
  if (error)   return <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{error}</span> <button onClick={load} style={{ ...BTN_OUTLINE, marginLeft: 10, padding: '5px 12px', fontSize: 12 }}>Retry</button></div>

  return (
    <div style={{ padding: 28 }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Activity Log</h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>Record what you worked on each day or week</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {isManager && (
            <button onClick={() => { setShowDlModal(true); handleDlPreset('this_month') }}
              style={{ ...BTN_OUTLINE, padding: '8px 16px', fontSize: 13 }}>
              ⬇ Download Report
            </button>
          )}
          <button onClick={() => setLogModal({ logType: 'daily', existingLog: null })}
            style={{ ...BTN_OUTLINE, padding: '8px 16px', fontSize: 13 }}>
            + Log Today
          </button>
          <button onClick={() => setLogModal({ logType: 'weekly', existingLog: null })}
            style={{ ...BTN_PRIMARY, padding: '8px 16px', fontSize: 13 }}>
            + Log This Week
          </button>
        </div>
      </div>

      {/* Activity Log Download Modal */}
      {showDlModal && (
        <div style={OVERLAY} onClick={() => { setShowDlModal(false); setDlPreset('this_month') }}>
          <div style={{ ...MODAL, maxWidth: 480 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
              <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: 0 }}>
                Download Activity Log Report
              </h3>
              <button onClick={() => { setShowDlModal(false); setDlPreset('this_month') }}
                style={{ background: 'none', border: 'none', fontSize: 22, cursor: 'pointer', color: '#7A9BAD' }}>×</button>
            </div>

            {/* Period presets */}
            <label style={LBL}>Period</label>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              {[
                { value: 'this_week',     label: 'This Week'     },
                { value: 'this_month',    label: 'This Month'    },
                { value: 'last_month',    label: 'Last Month'    },
                { value: 'last_3_months', label: 'Last 3 Months' },
                { value: 'custom',        label: 'Custom'        },
              ].map(p => (
                <button key={p.value}
                  onClick={() => handleDlPreset(p.value)}
                  style={{
                    padding: '5px 12px', fontSize: 12, borderRadius: 7, cursor: 'pointer',
                    border: `1.5px solid ${dlPreset === p.value ? ds.teal : '#D4E6EC'}`,
                    background: dlPreset === p.value ? '#EEF8FA' : '#fff',
                    color: dlPreset === p.value ? ds.teal : '#4a7a8a',
                    fontWeight: dlPreset === p.value ? 600 : 400,
                    fontFamily: 'inherit',
                  }}>
                  {p.label}
                </button>
              ))}
            </div>

            {dlPreset === 'custom' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                <div>
                  <label style={LBL}>From</label>
                  <input type='date' value={dlFilters.date_from}
                    onChange={e => setDlFilters(f => ({ ...f, date_from: e.target.value }))}
                    style={INP} />
                </div>
                <div>
                  <label style={LBL}>To</label>
                  <input type='date' value={dlFilters.date_to}
                    onChange={e => setDlFilters(f => ({ ...f, date_to: e.target.value }))}
                    style={INP} />
                </div>
              </div>
            )}

            {/* Staff filter — manager only */}
            <label style={LBL}>Staff</label>
            <select value={dlFilters.user_id_filter}
              onChange={e => setDlFilters(f => ({ ...f, user_id_filter: e.target.value }))}
              style={INP}>
              <option value=''>All staff</option>
              {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
            </select>

            {/* Team filter */}
            <label style={LBL}>Team</label>
            <select value={dlFilters.team}
              onChange={e => setDlFilters(f => ({ ...f, team: e.target.value }))}
              style={INP}
              disabled={!!dlFilters.user_id_filter}>
              <option value=''>All teams</option>
              {[...new Set(users.map(u => u.team).filter(Boolean))].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            {dlFilters.user_id_filter && (
              <p style={{ fontSize: 11, color: '#7A9BAD', marginTop: 4 }}>
                Team filter disabled when a specific staff member is selected.
              </p>
            )}

            {/* Include contractors toggle */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 16,
              padding: '10px 14px', background: '#fdf4ff', borderRadius: 9,
              border: '1.5px solid #e9d5ff' }}>
              <input
                type='checkbox'
                id='include-contractors-toggle'
                checked={dlFilters.include_contractors}
                onChange={e => setDlFilters(f => ({ ...f, include_contractors: e.target.checked }))}
                style={{ accentColor: '#7c3aed', width: 15, height: 15, cursor: 'pointer' }}
              />
              <label htmlFor='include-contractors-toggle'
                style={{ fontSize: 13, color: '#7c3aed', fontWeight: 600, cursor: 'pointer' }}>
                Include contractor daily activities
              </label>
              <span style={{ fontSize: 11, color: '#9ca3af', marginLeft: 'auto' }}>
                Appended as Part 2
              </span>
            </div>

            {dlError && (
              <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{dlError}</span></p>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24 }}>
              <button onClick={() => { setShowDlModal(false); setDlPreset('this_month') }} style={BTN_OUTLINE}>
                Cancel
              </button>
              <button
                disabled={dlDownloading}
                onClick={handleDlDownload}
                style={{ ...BTN_PRIMARY, background: dlDownloading ? '#aaa' : ds.teal }}>
                {dlDownloading ? 'Generating PDF…' : '⬇ Download PDF'}
              </button>
            </div>
          </div>
        </div>
      )}

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

      {/* intentionally empty — logging via header buttons above */}

      {/* Log list */}
      {logs.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 32px', color: '#7A9BAD' }}>
          <div style={{ display:"flex",justifyContent:"center",marginBottom:12 }}><CalendarDays size={40} color={ds.teal} strokeWidth={1.5} /></div>
          <p style={{ fontSize: 14 }}>No activity logs yet. Start by logging today's activities.</p>
        </div>
      ) : (
        <div style={{ background: 'white', borderRadius: 12, border: '1px solid #E4EEF2', overflow: 'hidden' }}>
          {logs.map((log, i) => {
            const isOpen   = expanded === log.id
            const isOwnLog = log.user_id === user?.id

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
                      {log.blockers && (
                        (log.entries || []).filter(e => e.has_blocker).length > 0 &&
                        (log.entries || []).filter(e => e.has_blocker).every(e => e.blocker_issue_status === 'resolved')
                          ? <span style={{ fontSize: 11, background: '#D1FAE5', color: '#065F46', borderRadius: 20, padding: '2px 8px', fontWeight: 600 }}> Blocker Resolved</span>
                          : <span style={{ fontSize: 11, background: '#FEE2E2', color: '#991B1B', borderRadius: 20, padding: '2px 8px', fontWeight: 600 }}>Blocker</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: '#7A9BAD', marginTop: 3 }}>
                      {fmtDate(log.log_date)} · {log.activities?.substring(0, 80)}{log.activities?.length > 80 ? '…' : ''}
                    </div>
                  </div>

                  {/* Edit — own logs only */}
                  {isOwnLog && (
                    <div style={{ flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                      <button
                        onClick={e => openEdit(log, e)}
                        title="Edit this log"
                        style={{ ...BTN_OUTLINE, padding: '5px 11px', fontSize: 11, fontWeight: 600 }}
                      >
                        <span style={{display:"inline-flex",alignItems:"center",gap:4}}><Edit size={12} />Edit</span>
                      </button>
                    </div>
                  )}

                  <span style={{ color: '#7A9BAD', fontSize: 16, flexShrink: 0 }}>{isOpen ? '▲' : '▼'}</span>
                </div>

                {isOpen && (
                  <div style={{ padding: '4px 18px 18px', background: '#F8FAFC', borderTop: '1px solid #F0F7FA' }}>

                    {/* Structured entries — rendered as cards when entries JSONB exists */}
                    {log.entries?.length > 0 ? (
                      <div style={{ marginTop: 14 }}>
                        {log.entries.map((entry, ei) => (
                          <div key={ei} style={{
                            background: '#fff', border: '1.5px solid #E4EEF2',
                            borderRadius: 10, padding: '12px 16px', marginBottom: 10,
                          }}>
                            {/* Type badge + hours */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                              <span style={{
                                fontSize: 11, fontWeight: 700, background: '#EEF8FA',
                                color: '#0D9488', borderRadius: 20, padding: '3px 10px',
                                textTransform: 'uppercase', letterSpacing: '0.5px',
                              }}>
                                {entry.activity_type || 'General'}
                              </span>
                              {entry.duration_minutes && (
                                <span style={{ fontSize: 12, color: '#7A9BAD', fontWeight: 600 }}>
                                  ⏱ {entry.duration_minutes}h
                                </span>
                              )}
                            </div>

                            {/* Description */}
                            <p style={{ fontSize: 13.5, color: '#0a1a24', lineHeight: 1.6, margin: 0, whiteSpace: 'pre-wrap' }}>
                              {entry.activity_description}
                            </p>

                            {/* Blocker */}
                            {entry.has_blocker && (
                              <div style={{
                                marginTop: 10,
                                background: entry.blocker_issue_status === 'resolved' ? '#F0FDF4' : '#FEF2F2',
                                border: `1px solid ${entry.blocker_issue_status === 'resolved' ? '#BBF7D0' : '#FECACA'}`,
                                borderRadius: 7,
                                padding: '8px 12px',
                              }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                  <span style={{ fontSize: 11, fontWeight: 700, color: entry.blocker_issue_status === 'resolved' ? '#065F46' : '#DC2626', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                    {entry.blocker_issue_status === 'resolved' ? <span style={{display:"inline-flex",alignItems:"center",gap:4}}><CheckCircle size={11} color="#065F46" />Blocker Resolved</span> : <span style={{display:"inline-flex",alignItems:"center",gap:4}}><AlertTriangle size={11} color="#92400E" />Blocker</span>}
                                  </span>
                                  {entry.blocker_issue_id && (
                                    <span style={{
                                      fontSize: 11, fontWeight: 600,
                                      color: entry.blocker_issue_status === 'resolved' ? '#065F46' : '#7A9BAD',
                                    }}>
                                      {entry.blocker_issue_status === 'in_progress'
                                        ? '→ Being resolved in Issues tab'
                                        : entry.blocker_issue_status === 'resolved'
                                        ? '→ Resolved in Issues tab'
                                        : '→ Logged as issue in Issues tab'}
                                    </span>
                                  )}
                                </div>
                                {entry.blocker_note && (
                                  <p style={{ fontSize: 13, color: entry.blocker_issue_status === 'resolved' ? '#065F46' : '#991B1B', margin: '4px 0 0', lineHeight: 1.5 }}>
                                    {entry.blocker_note}
                                  </p>
                                )}
                              </div>
                            )}

                            {/* Plan — last entry only */}
                            {entry.plan && (
                              <div style={{ marginTop: 10 }}>
                                <div style={{ ...LBL, marginTop: 0 }}>
                                  {log.log_type === 'weekly' ? 'Plan for next week' : 'Plan for tomorrow'}
                                </div>
                                <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0, lineHeight: 1.5 }}>
                                  {entry.plan}
                                </p>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      /* Legacy fallback — plain text blob for old logs without entries JSONB */
                      <div>
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
                )}
              </div>
            )
          })}
        </div>
      )}

      {logModal && (
        <LogActivityModal
          logType={logModal.logType}
          existingLog={logModal.existingLog}
          onSubmit={handleSubmit}
          onClose={() => setLogModal(null)}
        />
      )}
    </div>
  )
}
// ── Main Module ───────────────────────────────────────────────────────────────
const ALL_TABS = [
  { id: 'issues',   label: 'Issues',       Icon: Construction },
  { id: 'activity', label: 'Activity Log', Icon: CalendarDays },
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
          const TabIcon = tab.Icon || null
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
              {TabIcon && <TabIcon size={14} strokeWidth={active ? 2.5 : 1.8} />} {tab.label}
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
