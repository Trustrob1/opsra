/**
 * CustomerProfile.jsx — Module 02 customer detail panel.
 *
 * Tabs: Profile | Messages | Tasks | NPS History | Interaction Log | Tickets
 *
 * Profile badges update:
 *   - Fetches getCustomerAttentionSummary() on mount — one call, three signals:
 *     unread_messages, open_tickets, pending_tasks
 *   - Each relevant tab shows an inline badge pill when its signal > 0
 *   - Badge hidden when that tab is currently active
 *   - Tab renames: "Log Interaction" → "Interaction Log"
 *                  "Create Ticket"   → "Tickets"
 *
 * Tasks tab fix (post M01-9):
 *   - Removed incorrect `completed: true` param that was filtering to show
 *     only completed tasks instead of all tasks.
 *   - Replaced inline read-only task cards with real TaskCard component so
 *     reps and managers can complete tasks directly from the customer profile.
 *   - Completion updates local state immediately (optimistic update).
 *   - Completed tasks shown in a collapsible section at the bottom.
 *
 * Props:
 *   customerId — UUID
 *   onBack     — callback to return to CustomerList
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  getCustomer,
  updateCustomer,
  getCustomerMessages,
  getCustomerNps,
  listTemplates,
} from '../../services/whatsapp.service'
import { getCustomerAttentionSummary } from '../../services/customers.service'
import {
  getCustomerContacts,
  addCustomerContact,
  approveContact,
  removeContact,
} from '../../services/customers.service'
import useAuthStore from '../../store/authStore'
import { listTasks } from '../../services/tasks.service'
import MessageComposer from './MessageComposer'
import LogInteractionPanel from '../../shared/LogInteractionPanel'
import LinkedTicketsPanel  from '../../shared/LinkedTicketsPanel'
import TaskCard from '../tasks/TaskCard'

// ── Churn risk badge ──────────────────────────────────────────────────────────
const RISK_STYLE = {
  low:      { bg: '#E8F8EE', color: '#27AE60' },
  medium:   { bg: '#FFF9E0', color: '#D4AC0D' },
  high:     { bg: '#FFF3E0', color: '#E07B3A' },
  critical: { bg: '#FFE8E8', color: '#C0392B' },
}
function RiskBadge({ risk }) {
  const s = RISK_STYLE[risk] || RISK_STYLE.low
  return (
    <span style={{
      background: s.bg, color: s.color, borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 700, fontFamily: ds.fontHead, textTransform: 'capitalize',
    }}>
      {risk || 'low'}
    </span>
  )
}

// ── Field display ─────────────────────────────────────────────────────────────
function ProfileField({ label, value, fallback = '—' }) {
  return (
    <div style={{ background: '#F5FAFB', borderRadius: 8, padding: '10px 14px' }}>
      <div style={{ fontSize: 11, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 500, marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontSize: 13.5, color: ds.dark, fontWeight: 500 }}>
        {value || fallback}
      </div>
    </div>
  )
}

// ── NPS star display ──────────────────────────────────────────────────────────
function NpsStars({ score }) {
  return (
    <span>
      {[1,2,3,4,5].map(n => (
        <span key={n} style={{ color: n <= score ? '#F4A261' : '#D6E8EC', fontSize: 16 }}>★</span>
      ))}
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function CustomerProfile({ customerId, onBack }) {
  const [tab, setTab]           = useState('profile')
  const [customer, setCustomer] = useState(null)
  const [messages, setMessages] = useState([])
  const [tasks, setTasks]       = useState([])
  const [nps, setNps]           = useState([])
  const [templates, setTemplates] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [editing, setEditing]   = useState(false)
  const [editForm, setEditForm] = useState({})
  const [saving, setSaving]     = useState(false)
  const [saveErr, setSaveErr]   = useState(null)
  const [taskActionError, setTaskActionError] = useState(null)
  const [showCompletedTasks, setShowCompletedTasks] = useState(false)

  // Contacts state (WH-0) — managers only
  const isManager = useAuthStore.getState().isManager()
  const [contacts, setContacts]         = useState([])
  const [contactsLoading, setContactsLoading] = useState(false)
  const [contactForm, setContactForm]   = useState({ phone_number: '', name: '', contact_role: '' })
  const [contactSaving, setContactSaving] = useState(false)
  const [contactErr, setContactErr]     = useState(null)

  // Attention signals
  const [attention, setAttention] = useState({
    unread_messages: 0,
    open_tickets:    0,
    pending_tasks:   0,
  })

  const loadCustomer = useCallback(() => {
    setLoading(true)
    setError(null)
    getCustomer(customerId)
      .then(res => setCustomer(res.data?.data))
      .catch(() => setError('Failed to load customer.'))
      .finally(() => setLoading(false))
  }, [customerId])

  useEffect(() => { loadCustomer() }, [loadCustomer])

  // Fetch attention summary on mount
  useEffect(() => {
    if (!customerId) return
    getCustomerAttentionSummary()
      .then(res => {
        if (res.success) {
          const signals = (res.data ?? {})[customerId] ?? {}
          setAttention({
            unread_messages: signals.unread_messages ?? 0,
            open_tickets:    signals.open_tickets    ?? 0,
            pending_tasks:   signals.pending_tasks   ?? 0,
          })
        }
      })
      .catch(() => {})
  }, [customerId])

  // Load tab-specific data when tab changes
  const loadTasks = useCallback(() => {
    // FIX: removed `completed: true` param — was incorrectly filtering to
    // show only completed tasks. Fetch all tasks for this customer instead.
    listTasks({ source_record_id: customerId, page_size: 50 })
      .then(res => setTasks(res?.items ?? []))
      .catch(() => setTasks([]))
  }, [customerId])

  useEffect(() => {
    if (tab === 'messages') {
      getCustomerMessages(customerId).then(res => setMessages(res.data?.data?.items ?? []))
    }
    if (tab === 'tasks') {
      loadTasks()
    }
    if (tab === 'nps') {
      getCustomerNps(customerId).then(res => setNps(res.data?.data ?? []))
    }
    if (tab === 'contacts' && isManager) {
      setContactsLoading(true)
      getCustomerContacts(customerId)
        .then(res => setContacts(res.data ?? []))
        .catch(() => setContacts([]))
        .finally(() => setContactsLoading(false))
    }
  }, [tab, customerId, loadTasks])

  useEffect(() => {
    listTemplates().then(res => setTemplates(res.data?.data ?? []))
  }, [])

  // Task action handlers
  const handleTaskComplete = (taskId) => {
    setTasks(prev => prev.map(t =>
      t.id === taskId
        ? { ...t, status: 'completed', completed_at: new Date().toISOString() }
        : t
    ))
    setTaskActionError(null)
    // Refresh attention badge count
    getCustomerAttentionSummary()
      .then(res => {
        if (res.success) {
          const signals = (res.data ?? {})[customerId] ?? {}
          setAttention(prev => ({ ...prev, pending_tasks: signals.pending_tasks ?? 0 }))
        }
      })
      .catch(() => {})
  }

  const handleTaskSnooze = () => { loadTasks() }
  const handleTaskReassigned = () => { loadTasks() }

  function startEdit() {
    setEditForm({
      full_name:            customer.full_name,
      business_name:        customer.business_name,
      business_type:        customer.business_type || '',
      phone:                customer.phone || '',
      email:                customer.email || '',
      location:             customer.location || '',
      branches:             customer.branches || '',
      onboarding_complete:  customer.onboarding_complete ?? false,
    })
    setEditing(true)
    setSaveErr(null)
  }

  async function handleSave() {
    setSaving(true)
    setSaveErr(null)
    try {
      const payload = {}
      Object.entries(editForm).forEach(([k, v]) => {
        if (v !== '') payload[k] = v
      })
      await updateCustomer(customerId, payload)
      setEditing(false)
      loadCustomer()
    } catch (err) {
      setSaveErr(err.response?.data?.error?.message || 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  // Tab definitions with badge signals
  const TABS = [
    { key: 'profile',         label: 'Profile'           },
    { key: 'messages',        label: 'Messages',          badge: attention.unread_messages, color: 'red'   },
    { key: 'tasks',           label: 'Tasks',             badge: attention.pending_tasks,   color: 'amber' },
    { key: 'nps',             label: 'NPS History'        },
    { key: 'log-interaction', label: '📞 Interaction Log' },
    { key: 'create-ticket',   label: '🎫 Tickets',        badge: attention.open_tickets,    color: 'red'   },
    ...(isManager ? [{ key: 'contacts', label: '👥 Contacts' }] : []),
  ]

  const BADGE_STYLE = {
    red:   { background: '#E53E3E', color: 'white' },
    amber: { background: '#D97706', color: 'white' },
  }

  const S = {
    wrap: { padding: 28 },
    backBtn: {
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: 'none', border: 'none', cursor: 'pointer',
      color: ds.teal, fontSize: 13, fontWeight: 600, marginBottom: 18,
      fontFamily: ds.fontHead, padding: 0,
    },
    header: {
      background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 14,
      padding: '20px 24px', marginBottom: 20,
      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
    },
    name: { fontFamily: ds.fontHead, fontWeight: 700, fontSize: 20, color: ds.dark },
    biz: { fontSize: 13, color: ds.gray, marginTop: 3 },
    waNum: { fontSize: 13, color: '#25D366', fontWeight: 600, marginTop: 6 },
    tabBar: {
      display: 'flex', gap: 4, background: '#F5FAFB',
      padding: 4, borderRadius: 10, marginBottom: 20,
      flexWrap: 'wrap',
    },
    tabBtn: (active) => ({
      padding: '8px 18px', borderRadius: 7, border: 'none', cursor: 'pointer',
      fontSize: 13, fontWeight: active ? 600 : 500, fontFamily: ds.fontBody,
      background: active ? '#fff' : 'none',
      color: active ? ds.teal : ds.gray,
      boxShadow: active ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
      display: 'inline-flex', alignItems: 'center', gap: 5,
      whiteSpace: 'nowrap',
    }),
    card: {
      background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 14,
      padding: '20px 24px', marginBottom: 16,
    },
    grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 },
    editInput: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 13px',
      fontSize: 13, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box',
    },
    editLabel: {
      fontSize: 11, color: ds.gray, textTransform: 'uppercase',
      letterSpacing: '0.5px', fontWeight: 500, marginBottom: 5, display: 'block',
    },
    saveBtn: {
      padding: '9px 20px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: saving ? 'not-allowed' : 'pointer',
      opacity: saving ? 0.6 : 1, marginRight: 8,
    },
    cancelBtn: {
      padding: '9px 16px', background: '#EAF0F2', color: ds.dark,
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    editBtn: {
      padding: '8px 16px', background: '#E0F4F6', color: ds.teal,
      border: 'none', borderRadius: 9, fontSize: 12.5, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    msgBubble: (dir) => ({
      background: dir === 'outbound' ? '#DCF8C6' : '#fff',
      borderRadius: dir === 'outbound' ? '10px 0 10px 10px' : '0 10px 10px 10px',
      padding: '10px 13px', fontSize: 13, lineHeight: 1.65, color: '#1a1a1a',
      maxWidth: '80%', boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
      marginLeft: dir === 'outbound' ? 'auto' : 0,
      marginBottom: 8,
    }),
    msgMeta: (dir) => ({
      fontSize: 10.5, color: ds.gray, marginBottom: 4,
      textAlign: dir === 'outbound' ? 'right' : 'left',
    }),
    empty: { padding: 32, textAlign: 'center', color: ds.gray, fontSize: 13 },
  }

  if (loading) return (
    <div style={S.wrap}>
      <button style={S.backBtn} onClick={onBack}>← Back</button>
      <div style={{ color: ds.teal, padding: 32 }}>Loading customer profile…</div>
    </div>
  )

  if (error) return (
    <div style={S.wrap}>
      <button style={S.backBtn} onClick={onBack}>← Back</button>
      <div style={{ color: '#C0392B', padding: 32 }}>{error}</div>
    </div>
  )

  const windowOpen = customer?.window_open ?? false

  const activeTasks    = tasks.filter(t => (t.status || '').toLowerCase() !== 'completed')
  const completedTasks = tasks.filter(t => (t.status || '').toLowerCase() === 'completed')

  return (
    <div style={S.wrap}>
      <button style={S.backBtn} onClick={onBack}>← All Customers</button>

      {/* Profile header */}
      <div style={S.header}>
        <div>
          <div style={S.name}>{customer.full_name}</div>
          <div style={S.biz}>{customer.business_name} · {customer.business_type || 'Business'}</div>
          <div style={S.waNum}>💬 {customer.whatsapp}</div>
          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <RiskBadge risk={customer.churn_risk} />
            {customer.onboarding_complete
              ? <span style={{ background: '#E8F8EE', color: '#27AE60', borderRadius: 20, padding: '3px 10px', fontSize: 11, fontWeight: 600 }}>✓ Onboarded</span>
              : <span style={{ background: '#EAF0F2', color: ds.gray, borderRadius: 20, padding: '3px 10px', fontSize: 11, fontWeight: 600 }}>Onboarding</span>
            }
            {customer.last_nps_score && (
              <span style={{ background: '#FFF9E0', color: '#D4AC0D', borderRadius: 20, padding: '3px 10px', fontSize: 11, fontWeight: 600 }}>
                NPS {customer.last_nps_score}/5
              </span>
            )}
          </div>
        </div>
        {!editing && (
          <button style={S.editBtn} onClick={startEdit}>✏ Edit</button>
        )}
      </div>

      {/* Tab bar */}
      <div style={S.tabBar}>
        {TABS.map(({ key, label, badge, color }) => (
          <button key={key} style={S.tabBtn(tab === key)} onClick={() => setTab(key)}>
            {label}
            {badge > 0 && tab !== key && (
              <span style={{
                ...BADGE_STYLE[color],
                borderRadius: 20,
                padding: '1px 5px',
                fontSize: 9,
                fontWeight: 700,
                lineHeight: '14px',
                fontFamily: ds.fontHead,
              }}>
                {badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Profile tab ────────────────────────────────────────────────── */}
      {tab === 'profile' && (
        <div>
          {editing ? (
            <div style={S.card}>
              <div style={{ fontFamily: ds.fontHead, fontWeight: 700, fontSize: 14, color: ds.dark, marginBottom: 16 }}>
                Edit Customer
              </div>
              <div style={S.grid2}>
                {[
                  ['full_name', 'Full Name'],
                  ['business_name', 'Business Name'],
                  ['business_type', 'Business Type'],
                  ['phone', 'Phone'],
                  ['email', 'Email'],
                  ['location', 'Location'],
                  ['branches', 'Branches'],
                ].map(([key, label]) => (
                  <div key={key}>
                    <label style={S.editLabel}>{label}</label>
                    <input
                      style={S.editInput}
                      value={editForm[key] || ''}
                      onChange={e => setEditForm(f => ({ ...f, [key]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>

              <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
                <input
                  type="checkbox"
                  id="onboarding_complete"
                  checked={editForm.onboarding_complete ?? customer.onboarding_complete ?? false}
                  onChange={e => setEditForm(f => ({ ...f, onboarding_complete: e.target.checked }))}
                  style={{ width: 16, height: 16, cursor: 'pointer' }}
                />
                <label htmlFor="onboarding_complete" style={{ fontSize: 13, color: ds.dark, cursor: 'pointer' }}>
                  Onboarding Complete
                </label>
              </div>

              {saveErr && <div style={{ color: '#C0392B', fontSize: 12, margin: '10px 0' }}>⚠ {saveErr}</div>}
              <div style={{ marginTop: 16 }}>
                <button style={S.saveBtn} onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving…' : 'Save Changes'}
                </button>
                <button style={S.cancelBtn} onClick={() => setEditing(false)}>Cancel</button>
              </div>
            </div>
          ) : (
            <div style={S.card}>
              <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
                Customer Details
              </div>
              <div style={S.grid2}>
                <ProfileField label="Phone" value={customer.phone} />
                <ProfileField label="Email" value={customer.email} />
                <ProfileField label="Location" value={customer.location} />
                <ProfileField label="Branches" value={customer.branches} />
                <ProfileField label="Business Type" value={customer.business_type} />
                <ProfileField label="Assigned To" value={customer.assigned_user?.full_name} />
                <ProfileField label="WhatsApp Opt-in" value={customer.whatsapp_opt_in ? 'Yes' : 'No'} />
                <ProfileField label="Opt-out Broadcasts" value={customer.whatsapp_opt_out_broadcasts ? 'Yes' : 'No'} />
                <ProfileField label="Last NPS Sent" value={customer.last_nps_sent_at ? new Date(customer.last_nps_sent_at).toLocaleDateString() : null} />
                <ProfileField label="Churn Score Updated" value={customer.churn_score_updated_at ? new Date(customer.churn_score_updated_at).toLocaleDateString() : null} />
              </div>
            </div>
          )}

          {/* Payment Details */}
          <div style={S.card}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark }}>
                Payment Details
              </div>
              <button
                onClick={loadCustomer}
                title="Refresh payment details"
                style={{
                  background: 'none', border: `1px solid ${ds.border}`,
                  borderRadius: 6, padding: '4px 10px', cursor: 'pointer',
                  fontSize: 12, color: ds.gray, fontFamily: ds.fontDm,
                  display: 'flex', alignItems: 'center', gap: 4,
                }}
              >
                ↻ Refresh
              </button>
            </div>
            {customer.subscription ? (
              <div style={S.grid2}>
                <ProfileField
                  label="Plan"
                  value={[customer.subscription.plan_name, customer.subscription.plan_tier]
                    .filter(Boolean).join(' — ') || null}
                />
                <ProfileField
                  label="Subscription Type"
                  value={
                    customer.subscription.status === 'trial' ? 'Trial'
                    : customer.subscription.billing_cycle === 'annual' ? 'Annual'
                    : customer.subscription.billing_cycle === 'monthly' ? 'Monthly'
                    : customer.subscription.billing_cycle ?? null
                  }
                />
                <ProfileField
                  label="Status"
                  value={customer.subscription.status
                    ? customer.subscription.status.charAt(0).toUpperCase()
                      + customer.subscription.status.slice(1)
                    : null}
                />
                <ProfileField
                  label="Amount"
                  value={customer.subscription.amount != null
                    ? `₦${Number(customer.subscription.amount).toLocaleString()}`
                    : null}
                />
                <ProfileField
                  label="Next Due"
                  value={customer.subscription.next_due
                    ? new Date(customer.subscription.next_due).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' })
                    : null}
                />
                <ProfileField
                  label="Last Paid Amount"
                  value={customer.subscription.last_paid_amount != null
                    ? `₦${Number(customer.subscription.last_paid_amount).toLocaleString()}`
                    : null}
                />
                <ProfileField
                  label="Date Paid"
                  value={customer.subscription.last_paid_date
                    ? new Date(customer.subscription.last_paid_date).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' })
                    : null}
                />
                <ProfileField
                  label="Payment Method"
                  value={customer.subscription.payment_channel
                    ? customer.subscription.payment_channel.charAt(0).toUpperCase()
                      + customer.subscription.payment_channel.slice(1).replace(/_/g, ' ')
                    : null}
                />
              </div>
            ) : (
              <p style={{ fontSize: 13, color: '#9CA3AF', margin: 0 }}>
                No active subscription found.
              </p>
            )}
          </div>

          {/* Message compose */}
          <div style={S.card}>
            <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
              Send Message
            </div>
            <MessageComposer
              customerId={customerId}
              windowOpen={windowOpen}
              templates={templates}
              onSent={() => setTab('messages')}
            />
          </div>
        </div>
      )}

      {/* ── Messages tab ───────────────────────────────────────────────── */}
      {tab === 'messages' && (
        <div style={S.card}>
          <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
            Message History
          </div>
          {messages.length === 0 ? (
            <div style={S.empty}>No messages yet.</div>
          ) : (
            <div style={{ background: '#ECE5DD', borderRadius: 12, padding: 14 }}>
              {messages.map(m => (
                <div key={m.id}>
                  <div style={S.msgMeta(m.direction)}>
                    {m.direction === 'outbound'
                      ? `Sent · ${new Date(m.created_at).toLocaleString()}`
                      : `Received · ${new Date(m.created_at).toLocaleString()}`}
                    {m.template_name && ` · Template: ${m.template_name}`}
                  </div>
                  <div style={S.msgBubble(m.direction)}>
                    {m.content || '(Media message)'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Tasks tab ──────────────────────────────────────────────────── */}
      {tab === 'tasks' && (
        <div style={S.card}>
          <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
            Tasks
          </div>

          {taskActionError && (
            <p style={{ color: ds.red, fontSize: 13, marginBottom: 10 }}>⚠ {taskActionError}</p>
          )}

          {tasks.length === 0 ? (
            <div style={S.empty}>No tasks linked to this customer.</div>
          ) : (
            <>
              {/* Active tasks */}
              {activeTasks.length === 0 ? (
                <p style={{ color: ds.gray, fontSize: 13, fontStyle: 'italic', marginBottom: 12 }}>
                  All tasks completed. ✅
                </p>
              ) : (
                <div>
                  {activeTasks.map(task => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      onComplete={handleTaskComplete}
                      onSnooze={handleTaskSnooze}
                      onReassigned={handleTaskReassigned}
                      onError={setTaskActionError}
                    />
                  ))}
                </div>
              )}

              {/* Completed tasks — collapsible */}
              {completedTasks.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <button
                    onClick={() => setShowCompletedTasks(prev => !prev)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: 6,
                      fontSize: 12, fontWeight: 600, color: ds.gray,
                      fontFamily: ds.fontSyne, padding: '4px 0', marginBottom: 8,
                    }}
                  >
                    <span style={{
                      background: '#E8F8EE', color: '#276749',
                      borderRadius: 20, padding: '2px 8px', fontSize: 11,
                    }}>
                      ✓ {completedTasks.length} completed
                    </span>
                    <span style={{ fontSize: 10 }}>{showCompletedTasks ? '▲ Hide' : '▼ Show'}</span>
                  </button>

                  {showCompletedTasks && (
                    <div style={{ opacity: 0.8 }}>
                      {completedTasks.map(task => (
                        <TaskCard
                          key={task.id}
                          task={task}
                          onComplete={handleTaskComplete}
                          onSnooze={handleTaskSnooze}
                          onReassigned={handleTaskReassigned}
                          onError={setTaskActionError}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── NPS tab ────────────────────────────────────────────────────── */}
      {tab === 'nps' && (
        <div style={S.card}>
          <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
            NPS History
          </div>
          {nps.length === 0 ? (
            <div style={S.empty}>No NPS responses yet. NPS is collected quarterly and post-support.</div>
          ) : nps.map(n => (
            <div key={n.id} style={{
              background: '#F5FAFB', borderRadius: 10, padding: '12px 16px', marginBottom: 10,
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <NpsStars score={n.score} />
                <div style={{ fontSize: 12, color: ds.gray, marginTop: 4 }}>
                  Trigger: {n.trigger_type.replace(/_/g, ' ')}
                </div>
              </div>
              <div style={{ fontSize: 12, color: ds.gray }}>
                {new Date(n.responded_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Interaction Log tab ─────────────────────────────────────────── */}
      {tab === 'log-interaction' && (
        <LogInteractionPanel
          linkedTo={{ type: 'customer', id: customerId }}
          contextName={customer?.full_name ?? 'this customer'}
        />
      )}

      {/* ── Tickets tab ─────────────────────────────────────────────────── */}
      {tab === 'create-ticket' && (
        <LinkedTicketsPanel
          linkedTo={{ type: 'customer', id: customerId }}
          contextName={customer?.full_name ?? 'this customer'}
        />
      )}

      {/* ── Contacts tab (managers only) — WH-0 ─────────────────────────── */}
      {tab === 'contacts' && isManager && (
        <div style={S.card}>
          <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 14, color: ds.dark, marginBottom: 14 }}>
            Linked Contacts
          </div>
          <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '0 0 14px', lineHeight: 1.6 }}>
            B2B employees who have identified themselves as contacts for this customer via WhatsApp.
            Approve a contact to allow their phone number to be recognised as this customer&apos;s account.
          </p>

          {contactErr && (
            <p style={{ color: '#C0392B', fontSize: 13, marginBottom: 10 }}>⚠ {contactErr}</p>
          )}

          {contactsLoading ? (
            <div style={S.empty}>Loading contacts…</div>
          ) : contacts.length === 0 ? (
            <div style={S.empty}>No contacts linked to this customer yet.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 20 }}>
              <thead>
                <tr style={{ background: '#F5FAFB' }}>
                  {['Name', 'Phone', 'Role', 'Status', 'Actions'].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, color: '#7A9BAD', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.4px', borderBottom: '1px solid #E2EFF4' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {contacts.map(c => (
                  <tr key={c.id} style={{ borderBottom: '1px solid #F0F6F8' }}>
                    <td style={{ padding: '10px 12px', color: ds.dark }}>{c.name || '—'}</td>
                    <td style={{ padding: '10px 12px', color: ds.dark }}>{c.phone_number}</td>
                    <td style={{ padding: '10px 12px', color: ds.gray }}>{c.contact_role || '—'}</td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{
                        padding: '2px 9px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                        background: c.status === 'active' ? '#E8F8EE' : '#FFF9E0',
                        color:      c.status === 'active' ? '#27AE60' : '#D4AC0D',
                      }}>
                        {c.status === 'active' ? 'Active' : 'Pending'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', display: 'flex', gap: 6 }}>
                      {c.status === 'pending' && (
                        <button
                          onClick={() => {
                            setContactErr(null)
                            approveContact(c.id)
                              .then(() => setContacts(prev => prev.map(x => x.id === c.id ? { ...x, status: 'active' } : x)))
                              .catch(() => setContactErr('Failed to approve contact.'))
                          }}
                          style={{ padding: '4px 10px', background: '#E0F4F6', color: ds.teal, border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
                        >
                          Approve
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setContactErr(null)
                          removeContact(c.id)
                            .then(() => setContacts(prev => prev.filter(x => x.id !== c.id)))
                            .catch(() => setContactErr('Failed to remove contact.'))
                        }}
                        style={{ padding: '4px 10px', background: '#FFE8E8', color: '#C0392B', border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Add contact form */}
          <div style={{ borderTop: '1px solid #E2EFF4', paddingTop: 16 }}>
            <div style={{ fontFamily: ds.fontHead, fontWeight: 600, fontSize: 13, color: ds.dark, marginBottom: 12 }}>
              Add Contact Manually
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
              {[
                ['phone_number', 'Phone number *'],
                ['name',         'Name'],
                ['contact_role', 'Role'],
              ].map(([field, label]) => (
                <div key={field}>
                  <label style={{ display: 'block', fontSize: 11, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.4px', fontWeight: 500, marginBottom: 4 }}>
                    {label}
                  </label>
                  <input
                    style={{ border: '1.5px solid #D6E8EC', borderRadius: 8, padding: '8px 11px', fontSize: 13, fontFamily: 'inherit', outline: 'none', width: '100%', boxSizing: 'border-box' }}
                    value={contactForm[field]}
                    onChange={e => setContactForm(f => ({ ...f, [field]: e.target.value }))}
                    placeholder={label.replace(' *', '')}
                  />
                </div>
              ))}
            </div>
            <button
              disabled={contactSaving || !contactForm.phone_number.trim()}
              onClick={() => {
                if (!contactForm.phone_number.trim()) return
                setContactSaving(true)
                setContactErr(null)
                addCustomerContact(customerId, {
                  phone_number: contactForm.phone_number.trim(),
                  name:         contactForm.name.trim() || undefined,
                  contact_role: contactForm.contact_role.trim() || undefined,
                })
                  .then(res => {
                    setContacts(prev => [...prev, res.data])
                    setContactForm({ phone_number: '', name: '', contact_role: '' })
                  })
                  .catch(() => setContactErr('Failed to add contact.'))
                  .finally(() => setContactSaving(false))
              }}
              style={{
                padding: '8px 20px', background: ds.teal, color: 'white',
                border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600,
                fontFamily: ds.fontHead, cursor: contactSaving || !contactForm.phone_number.trim() ? 'not-allowed' : 'pointer',
                opacity: contactSaving || !contactForm.phone_number.trim() ? 0.55 : 1,
              }}
            >
              {contactSaving ? 'Adding…' : 'Add Contact'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
