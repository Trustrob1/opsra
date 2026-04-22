/**
 * frontend/src/modules/support/TicketDetail.jsx
 * Full ticket view — header, thread, reply composer, action buttons.
 *
 * Message types rendered differently:
 *   customer       → left-aligned, mint bg
 *   agent_reply    → right-aligned, teal bg, white text
 *   internal_note  → amber bg, lock icon, staff-only label
 *   ai_draft       → dashed border, distinct styling, "Send Draft" button
 *   system         → centred, small, gray
 *
 * State transitions available per status:
 *   open / in_progress / awaiting_customer → Resolve | Escalate
 *   resolved  → Close | Escalate
 *   closed    → Reopen
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  getTicket, addMessage, resolveTicket,
  closeTicket, reopenTicket, escalateTicket,
  updateTicket, suggestKBArticle, createKBArticle,
} from '../../services/support.service'
import { listTasks, completeTask } from '../../services/tasks.service'
import { getTicketCategories } from '../../services/admin.service'

// ---------------------------------------------------------------------------
// Badge helpers (duplicated locally — no shared component layer yet)
// ---------------------------------------------------------------------------
const URGENCY_STYLE = {
  critical: { background: '#FFE8E8', color: '#C0392B' },
  high:     { background: '#FFF3E0', color: '#E07B3A' },
  medium:   { background: '#FFF9E0', color: '#D4AC0D' },
  low:      { background: '#EAF0F2', color: ds.gray   },
}
const STATUS_MAP = {
  open:              { bg: '#EAF0F2', color: ds.gray,   label: 'Open' },
  in_progress:       { bg: '#E8F0FF', color: '#3450A4', label: 'In Progress' },
  awaiting_customer: { bg: '#FFF9E0', color: '#D4AC0D', label: 'Awaiting Customer' },
  resolved:          { bg: '#E8F8EE', color: ds.green,  label: 'Resolved' },
  closed:            { bg: '#F0F0F0', color: '#888',    label: 'Closed' },
}

function UBadge({ urgency }) {
  const s = URGENCY_STYLE[urgency] || URGENCY_STYLE.low
  return <span style={{ ...s, padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 700, textTransform: 'capitalize' }}>{urgency}</span>
}
function SBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP.open
  return <span style={{ background: s.bg, color: s.color, padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 600 }}>{s.label}</span>
}

// ---------------------------------------------------------------------------
// Resolve modal (resolution_notes required)
// ---------------------------------------------------------------------------
function ResolveModal({ onConfirm, onClose, saving }) {
  const [notes, setNotes] = useState('')
  const overlay = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000 }
  const modal   = { background: 'white', borderRadius: '14px', width: '460px', maxWidth: '95vw', padding: '26px', boxShadow: '0 20px 60px rgba(0,0,0,0.2)' }
  return (
    <div style={overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={modal}>
        <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '16px', color: ds.dark, marginBottom: '6px' }}>Resolve Ticket</div>
        <div style={{ fontSize: '13px', color: ds.gray, marginBottom: '16px' }}>Resolution notes are required before marking a ticket resolved.</div>
        <textarea
          autoFocus
          style={{ width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: '9px', padding: '10px 13px', fontSize: '13px', color: ds.dark, fontFamily: 'inherit', outline: 'none', minHeight: '90px', resize: 'vertical', boxSizing: 'border-box' }}
          placeholder="Describe how the issue was resolved…"
          value={notes}
          onChange={e => setNotes(e.target.value)}
        />
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '16px' }}>
          <button onClick={onClose} style={{ padding: '9px 18px', borderRadius: '8px', border: `1px solid ${ds.border}`, background: 'white', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}>Cancel</button>
          <button onClick={() => onConfirm(notes)} disabled={saving || !notes.trim()} style={{ padding: '9px 18px', borderRadius: '8px', border: 'none', background: ds.green, color: 'white', fontSize: '13px', fontWeight: 600, cursor: saving || !notes.trim() ? 'not-allowed' : 'pointer', opacity: saving || !notes.trim() ? 0.65 : 1 }}>
            {saving ? 'Resolving…' : '✓ Mark Resolved'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------
function MessageBubble({ msg, onSendDraft }) {
  const t = msg.message_type
  const timeStr = msg.created_at ? new Date(msg.created_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''

  if (t === 'system') {
    return (
      <div style={{ textAlign: 'center', margin: '10px 0' }}>
        <span style={{ fontSize: '11px', color: ds.gray, background: '#F5F5F5', padding: '4px 12px', borderRadius: '20px' }}>{msg.content}</span>
      </div>
    )
  }

  if (t === 'ai_draft') {
    return (
      <div style={{ margin: '10px 0', padding: '14px 16px', border: '2px dashed #B0DDD9', borderRadius: '12px', background: '#F8FDFD' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
          <span style={{ fontSize: '11px', fontWeight: 700, color: ds.teal, textTransform: 'uppercase', letterSpacing: '0.5px' }}>🤖 AI Draft</span>
          <span style={{ fontSize: '11px', color: ds.gray }}>{timeStr}</span>
          <span style={{ fontSize: '11px', background: '#FFF3E0', color: '#E07B3A', padding: '2px 8px', borderRadius: '10px', fontWeight: 600 }}>Pending review</span>
        </div>
        <div style={{ fontSize: '13.5px', color: ds.dark, lineHeight: 1.6, marginBottom: '12px' }}>{msg.content}</div>
        <button
          onClick={() => onSendDraft(msg)}
          style={{ padding: '7px 16px', borderRadius: '7px', border: 'none', background: ds.teal, color: 'white', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}
        >
          Send This Reply
        </button>
      </div>
    )
  }

  if (t === 'internal_note') {
    return (
      <div style={{ margin: '10px 0', padding: '12px 16px', background: '#FFF8F0', border: '1px solid #FFD0B0', borderRadius: '12px' }}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: '#8B4513', marginBottom: '6px' }}>🔒 Internal Note · {timeStr}</div>
        <div style={{ fontSize: '13.5px', color: ds.dark, lineHeight: 1.6 }}>{msg.content}</div>
      </div>
    )
  }

  const isAgent = t === 'agent_reply'
  return (
    <div style={{ display: 'flex', justifyContent: isAgent ? 'flex-end' : 'flex-start', margin: '8px 0' }}>
      <div style={{ maxWidth: '72%' }}>
        <div style={{ fontSize: '11px', color: ds.gray, marginBottom: '4px', textAlign: isAgent ? 'right' : 'left' }}>
          {isAgent ? 'Agent' : 'Customer'} · {timeStr}
        </div>
        <div style={{
          padding: '11px 15px', borderRadius: '12px', fontSize: '13.5px', lineHeight: 1.6,
          background: isAgent ? ds.teal : ds.mint,
          color: isAgent ? 'white' : ds.dark,
          borderBottomRightRadius: isAgent ? '3px' : '12px',
          borderBottomLeftRadius:  isAgent ? '12px' : '3px',
        }}>
          {msg.content}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function TicketDetail({ ticketId, onBack, onUpdated, onKBArticlePublished }) {
  const [ticket, setTicket]             = useState(null)
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState(null)
  const [actionError, setActionError]   = useState(null)
  const [acting, setActing]             = useState(false)
  const [showResolve, setShowResolve]   = useState(false)

  // CONFIG-1: org-configured categories for label display
  const [categories, setCategories] = useState([])
  useEffect(() => {
    getTicketCategories()
      .then(data => { if (data?.categories) setCategories(data.categories) })
      .catch(() => {})
  }, [])

  // KB gap suggestion state
  const [kbSuggestion, setKbSuggestion]   = useState(null)   // null | suggestion dict
  const [kbSugLoading, setKbSugLoading]   = useState(false)
  const [kbSugError, setKbSugError]       = useState(null)
  const [kbForm, setKbForm]               = useState(null)    // null | form being edited
  const [kbSaving, setKbSaving]           = useState(false)
  const [kbSaved, setKbSaved]             = useState(false)

  // Reply composer state
  const [replyContent, setReplyContent] = useState('')
  const [replyType, setReplyType]       = useState('agent_reply')
  const [sending, setSending]           = useState(false)

  // Linked tasks state
  const [tasks,        setTasks]        = useState([])
  const [tasksLoading, setTasksLoading] = useState(true)
  const [tasksOpen,    setTasksOpen]    = useState(true)  // collapsed state

  const loadTicket = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTicket(ticketId)
      setTicket(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [ticketId])

  const loadTasks = useCallback(async () => {
    setTasksLoading(true)
    try {
      const data = await listTasks({ source_record_id: ticketId, completed: true, page_size: 50 })
      setTasks(data?.items ?? [])
    } catch {
      // Non-critical — task widget failure must not break ticket view
    } finally {
      setTasksLoading(false)
    }
  }, [ticketId])

  useEffect(() => { loadTicket() }, [loadTicket])
  useEffect(() => { loadTasks()  }, [loadTasks])

  async function handleSendReply() {
    if (!replyContent.trim()) return
    setSending(true)
    setActionError(null)
    try {
      await addMessage(ticketId, { message_type: replyType, content: replyContent.trim() })
      setReplyContent('')
      await loadTicket()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setSending(false)
    }
  }

  async function handleSendDraft(msg) {
    // Convert ai_draft to sent agent_reply
    setActing(true)
    setActionError(null)
    try {
      await addMessage(ticketId, { message_type: 'agent_reply', content: msg.content })
      await loadTicket()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setActing(false)
    }
  }

  async function handleFetchKBSuggestion() {
    setKbSugLoading(true)
    setKbSugError(null)
    try {
      const suggestion = await suggestKBArticle(ticketId)
      setKbSuggestion(suggestion)
      setKbForm({ ...suggestion, tags: (suggestion.tags || []).join(', ') })
    } catch (e) {
      setKbSugError(e.message)
    } finally {
      setKbSugLoading(false)
    }
  }

  async function handleSaveKBArticle() {
    if (!kbForm) return
    setKbSaving(true)
    setKbSugError(null)
    try {
      await createKBArticle({
        category:     kbForm.category,
        title:        kbForm.title,
        content:      kbForm.content,
        tags:         kbForm.tags ? kbForm.tags.split(',').map(t => t.trim()).filter(Boolean) : [],
        is_published: true,
      })
      setKbSaved(true)
      setKbForm(null)
      setKbSuggestion(null)
      onKBArticlePublished?.()
    } catch (e) {
      setKbSugError(e.message)
    } finally {
      setKbSaving(false)
    }
  }

  async function handleAction(action, ...args) {
    setActing(true)
    setActionError(null)
    try {
      if (action === 'resolve') {
        await resolveTicket(ticketId, args[0])
        setShowResolve(false)
      } else if (action === 'close')    await closeTicket(ticketId)
      else if (action === 'reopen')     await reopenTicket(ticketId)
      else if (action === 'escalate')   await escalateTicket(ticketId)
      await loadTicket()
      onUpdated?.()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setActing(false)
    }
  }

  if (loading) return <div style={{ padding: '48px', textAlign: 'center', color: ds.gray }}>Loading ticket…</div>
  if (error)   return <div style={{ padding: '24px', color: '#C0392B' }}>{error}</div>
  if (!ticket) return null

  const status = ticket.status
  const canResolve   = ['open', 'in_progress', 'awaiting_customer'].includes(status)
  const canClose     = status === 'resolved'
  const canReopen    = status === 'closed'
  const canEscalate  = !['resolved', 'closed'].includes(status)

  const btnBase = { padding: '8px 16px', borderRadius: '8px', border: 'none', fontSize: '13px', fontWeight: 600, cursor: acting ? 'not-allowed' : 'pointer', opacity: acting ? 0.65 : 1 }

  return (
    <div>
      {/* Back link */}
      <button onClick={onBack} style={{ background: 'none', border: 'none', color: ds.teal, fontSize: '13px', fontWeight: 600, cursor: 'pointer', padding: '0 0 14px', display: 'flex', alignItems: 'center', gap: '5px' }}>
        ← Back to Tickets
      </button>

      {/* Header card */}
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', padding: '22px 26px', marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '13px', color: ds.teal }}>{ticket.reference}</span>
              <SBadge status={ticket.status} />
              <UBadge urgency={ticket.urgency} />
              {ticket.sla_breached && <span style={{ background: '#FFE8E8', color: '#C0392B', padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 700 }}>⚠ SLA Breached</span>}
              {ticket.knowledge_gap_flagged && <span style={{ background: '#FFF3E0', color: '#8B4513', padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 600 }}>Knowledge Gap Flagged</span>}
            </div>
            <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '18px', color: ds.dark, marginBottom: '8px' }}>{ticket.title || ticket.reference}</div>
            <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', fontSize: '12px', color: ds.gray }}>
              {ticket.category && <span>Category: <strong style={{ color: ds.dark, textTransform: 'capitalize' }}>{categories.find(c => c.key === ticket.category)?.label ?? ticket.category.replace(/_/g, ' ')}</strong></span>}
              {ticket.ai_handling_mode && <span>AI Mode: <strong style={{ color: ds.dark }}>{ticket.ai_handling_mode.replace(/_/g, ' ')}</strong></span>}
              {ticket.assigned_user?.full_name && <span>Assigned: <strong style={{ color: ds.dark }}>{ticket.assigned_user.full_name}</strong></span>}
              <span>Opened: <strong style={{ color: ds.dark }}>{new Date(ticket.created_at).toLocaleDateString('en-GB')}</strong></span>
            </div>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            {canResolve  && <button style={{ ...btnBase, background: ds.green, color: 'white' }} onClick={() => setShowResolve(true)} disabled={acting}>✓ Resolve</button>}
            {canClose    && <button style={{ ...btnBase, background: '#F0F0F0', color: ds.dark }} onClick={() => handleAction('close')} disabled={acting}>Close</button>}
            {canReopen   && <button style={{ ...btnBase, background: ds.mint, color: ds.teal }} onClick={() => handleAction('reopen')} disabled={acting}>Reopen</button>}
            {canEscalate && <button style={{ ...btnBase, background: '#FFE8E8', color: '#C0392B' }} onClick={() => handleAction('escalate')} disabled={acting}>⚠ Escalate</button>}
          </div>
        </div>

        {ticket.resolution_notes && (
          <div style={{ marginTop: '14px', padding: '12px 16px', background: '#E8F8EE', border: '1px solid #B0DDB8', borderRadius: '10px', fontSize: '13px', color: ds.dark }}>
            <strong style={{ color: ds.green }}>Resolution: </strong>{ticket.resolution_notes}
          </div>
        )}

        {actionError && (
          <div style={{ marginTop: '12px', padding: '10px 14px', background: '#FFF0F0', border: '1px solid #FFD0D0', borderRadius: '8px', fontSize: '13px', color: '#C0392B' }}>
            {actionError}
          </div>
        )}
      </div>

      {/* ── Linked Tasks ─────────────────────────────────────────────────── */}
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', padding: '18px 24px', marginBottom: '20px' }}>
        <div
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
          onClick={() => setTasksOpen(o => !o)}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontFamily: 'Syne, sans-serif', fontWeight: 600, fontSize: '14px', color: ds.dark }}>
              ✅ Tasks
            </span>
            {tasks.length > 0 && (
              <span style={{ background: ds.teal, color: 'white', fontSize: '10px', fontWeight: 700, padding: '1px 7px', borderRadius: '10px' }}>
                {tasks.length}
              </span>
            )}
          </div>
          <span style={{ fontSize: '12px', color: ds.gray }}>{tasksOpen ? '▲ collapse' : '▼ expand'}</span>
        </div>

        {tasksOpen && (
          <div style={{ marginTop: '14px' }}>
            {tasksLoading && (
              <div style={{ fontSize: '13px', color: ds.gray, padding: '8px 0' }}>Loading tasks…</div>
            )}
            {!tasksLoading && tasks.length === 0 && (
              <div style={{ fontSize: '13px', color: ds.gray, padding: '8px 0' }}>
                No tasks linked to this ticket yet.
              </div>
            )}
            {!tasksLoading && tasks.map(task => {
              const overdue = task.due_at && new Date(task.due_at) < new Date() && task.status !== 'completed'
              const isComplete = task.status === 'completed'
              return (
                <div key={task.id} style={{
                  display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px',
                  padding: '10px 12px', borderRadius: '8px', marginBottom: '8px',
                  background: isComplete ? '#F8FFF8' : overdue ? '#FFFAFA' : ds.light,
                  border: `1px solid ${isComplete ? '#B0DDB8' : overdue ? '#FFD0D0' : ds.border}`,
                  borderLeft: `3px solid ${isComplete ? ds.green : overdue ? '#C0392B' : ds.teal}`,
                  opacity: isComplete ? 0.7 : 1,
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: ds.dark, textDecoration: isComplete ? 'line-through' : 'none', marginBottom: '4px' }}>
                      {task.title}
                    </div>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '11px', color: ds.gray, background: '#EAF0F2', borderRadius: '8px', padding: '1px 7px', textTransform: 'capitalize' }}>
                        {task.status}
                      </span>
                      {task.priority && (
                        <span style={{ fontSize: '11px', fontWeight: 600, padding: '1px 7px', borderRadius: '8px', textTransform: 'capitalize',
                          background: task.priority === 'critical' ? '#FFE8E8' : task.priority === 'high' ? '#FFF3E0' : '#EAF0F2',
                          color:      task.priority === 'critical' ? '#C0392B' : task.priority === 'high' ? '#E07B3A' : ds.gray,
                        }}>
                          {task.priority}
                        </span>
                      )}
                      {overdue && (
                        <span style={{ fontSize: '11px', fontWeight: 700, color: '#C0392B' }}>Overdue</span>
                      )}
                      {task.due_at && !overdue && (
                        <span style={{ fontSize: '11px', color: ds.gray }}>
                          Due {new Date(task.due_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
                        </span>
                      )}
                    </div>
                  </div>
                  {!isComplete && (
                    <button
                      onClick={async () => {
                        try {
                          await completeTask(task.id)
                          loadTasks()
                        } catch { /* non-critical */ }
                      }}
                      style={{ fontSize: '11px', fontWeight: 600, background: ds.mint, color: ds.teal, border: 'none', borderRadius: '6px', padding: '4px 10px', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
                    >
                      ✓ Done
                    </button>
                  )}
                </div>
              )
            })}
            <p style={{ fontSize: '11px', color: '#9ca3af', margin: '10px 0 0', textAlign: 'center' }}>
              Create tasks from the Task Board — link to this ticket using source record.
            </p>
          </div>
        )}
      </div>

      {/* KB gap prompt — shown when ticket is resolved and knowledge_gap_flagged=true */}
      {['resolved', 'closed'].includes(status) && ticket.knowledge_gap_flagged && !kbSaved && (
        <div style={{ background: '#FFF8F0', border: '2px solid #FFD0B0', borderRadius: '14px', padding: '20px 24px', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
            <span style={{ fontSize: '22px' }}>📚</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '14px', color: ds.dark, marginBottom: '4px' }}>
                Knowledge Gap Detected
              </div>
              <div style={{ fontSize: '13px', color: ds.gray, marginBottom: '14px' }}>
                This ticket was resolved without a matching KB article. Would you like to create one so future agents can answer similar questions faster?
              </div>

              {kbSugError && (
                <div style={{ background: '#FFF0F0', border: '1px solid #FFD0D0', borderRadius: '8px', padding: '8px 12px', fontSize: '12px', color: '#C0392B', marginBottom: '10px' }}>
                  {kbSugError}
                </div>
              )}

              {!kbSuggestion && !kbForm && (
                <button
                  onClick={handleFetchKBSuggestion}
                  disabled={kbSugLoading}
                  style={{ padding: '9px 18px', borderRadius: '8px', border: 'none', background: '#E07B3A', color: 'white', fontSize: '13px', fontWeight: 600, cursor: kbSugLoading ? 'not-allowed' : 'pointer', opacity: kbSugLoading ? 0.7 : 1 }}
                >
                  {kbSugLoading ? 'Generating draft…' : '✨ Generate KB Article Draft'}
                </button>
              )}

              {kbForm && (
                <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '10px', padding: '16px 18px', marginTop: '8px' }}>
                  <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 600, fontSize: '13px', color: ds.dark, marginBottom: '12px' }}>
                    Review and edit before publishing
                  </div>

                  {[
                    { label: 'Title', field: 'title', type: 'input' },
                    { label: 'Content', field: 'content', type: 'textarea' },
                    { label: 'Tags (comma-separated)', field: 'tags', type: 'input' },
                  ].map(({ label, field, type }) => (
                    <div key={field} style={{ marginBottom: '12px' }}>
                      <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '4px' }}>{label}</label>
                      {type === 'textarea' ? (
                        <textarea
                          value={kbForm[field] || ''}
                          onChange={e => setKbForm(f => ({ ...f, [field]: e.target.value }))}
                          style={{ width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: '8px', padding: '9px 12px', fontSize: '13px', color: ds.dark, fontFamily: 'inherit', outline: 'none', minHeight: '120px', resize: 'vertical', boxSizing: 'border-box' }}
                        />
                      ) : (
                        <input
                          value={kbForm[field] || ''}
                          onChange={e => setKbForm(f => ({ ...f, [field]: e.target.value }))}
                          style={{ width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: '8px', padding: '9px 12px', fontSize: '13px', color: ds.dark, fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }}
                        />
                      )}
                    </div>
                  ))}

                  <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '4px' }}>
                    <button onClick={() => { setKbForm(null); setKbSuggestion(null) }} style={{ padding: '8px 16px', borderRadius: '7px', border: `1px solid ${ds.border}`, background: 'white', fontSize: '12px', fontWeight: 600, cursor: 'pointer', color: ds.gray }}>
                      Dismiss
                    </button>
                    <button
                      onClick={handleSaveKBArticle}
                      disabled={kbSaving || !kbForm.title?.trim() || !kbForm.content?.trim()}
                      style={{ padding: '8px 16px', borderRadius: '7px', border: 'none', background: ds.teal, color: 'white', fontSize: '12px', fontWeight: 600, cursor: kbSaving ? 'not-allowed' : 'pointer', opacity: kbSaving || !kbForm.title?.trim() || !kbForm.content?.trim() ? 0.65 : 1 }}
                    >
                      {kbSaving ? 'Publishing…' : '✓ Publish Article'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* KB article published confirmation */}
      {kbSaved && (
        <div style={{ background: '#E8F8EE', border: '1px solid #B0DDB8', borderRadius: '14px', padding: '16px 22px', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '18px' }}>✓</span>
          <div style={{ fontSize: '13px', color: ds.green, fontWeight: 600 }}>
            KB article published. Future tickets on this topic will be answered from your knowledge base.
          </div>
        </div>
      )}

      {/* Thread */}
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', padding: '22px 26px', marginBottom: '20px' }}>
        <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 600, fontSize: '14px', color: ds.dark, marginBottom: '18px' }}>Thread</div>

        {(!ticket.messages || ticket.messages.length === 0) ? (
          <div style={{ textAlign: 'center', padding: '24px', color: ds.gray, fontSize: '13px' }}>No messages yet.</div>
        ) : (
          <div>
            {ticket.messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} onSendDraft={handleSendDraft} />
            ))}
          </div>
        )}
      </div>

      {/* Reply composer — not shown for closed tickets */}
      {status !== 'closed' && (
        <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', padding: '22px 26px' }}>
          <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 600, fontSize: '14px', color: ds.dark, marginBottom: '14px' }}>Add Reply</div>

          <div style={{ display: 'flex', gap: '10px', marginBottom: '12px' }}>
            {['agent_reply', 'internal_note'].map(t => (
              <button
                key={t}
                onClick={() => setReplyType(t)}
                style={{
                  padding: '7px 14px', borderRadius: '7px', fontSize: '12px', fontWeight: 600, cursor: 'pointer', border: 'none',
                  background: replyType === t ? (t === 'agent_reply' ? ds.teal : '#FFD0B0') : '#F0F0F0',
                  color: replyType === t ? (t === 'agent_reply' ? 'white' : '#8B4513') : ds.gray,
                }}
              >
                {t === 'agent_reply' ? '💬 Agent Reply' : '🔒 Internal Note'}
              </button>
            ))}
          </div>

          <textarea
            style={{ width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: '9px', padding: '11px 14px', fontSize: '13.5px', color: ds.dark, fontFamily: 'inherit', outline: 'none', minHeight: '90px', resize: 'vertical', boxSizing: 'border-box' }}
            placeholder={replyType === 'agent_reply' ? 'Write a reply to the customer…' : 'Add an internal note (visible to staff only)…'}
            value={replyContent}
            onChange={e => setReplyContent(e.target.value)}
          />

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '12px' }}>
            <button
              onClick={handleSendReply}
              disabled={sending || !replyContent.trim()}
              style={{ padding: '9px 20px', borderRadius: '8px', border: 'none', background: replyType === 'agent_reply' ? ds.teal : '#E07B3A', color: 'white', fontSize: '13px', fontWeight: 600, cursor: sending || !replyContent.trim() ? 'not-allowed' : 'pointer', opacity: sending || !replyContent.trim() ? 0.65 : 1 }}
            >
              {sending ? 'Sending…' : replyType === 'agent_reply' ? 'Send Reply' : 'Add Note'}
            </button>
          </div>
        </div>
      )}

      {/* Resolve modal */}
      {showResolve && (
        <ResolveModal
          saving={acting}
          onConfirm={notes => handleAction('resolve', notes)}
          onClose={() => setShowResolve(false)}
        />
      )}
    </div>
  )
}
