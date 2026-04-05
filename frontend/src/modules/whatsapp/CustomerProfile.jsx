/**
 * CustomerProfile.jsx — Module 02 customer detail panel.
 *
 * Tabs: Profile | Messages | Tasks | NPS
 * Includes inline MessageComposer, edit mode for basic fields.
 * Mirrors the LeadProfile pattern (tabs, sticky header, back button).
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
  getCustomerTasks,
  getCustomerNps,
} from '../../services/whatsapp.service'
import { listTemplates } from '../../services/whatsapp.service'
import MessageComposer from './MessageComposer'
import LogInteractionPanel from '../../shared/LogInteractionPanel'
import LinkedTicketsPanel  from '../../shared/LinkedTicketsPanel'

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

  const loadCustomer = useCallback(() => {
    setLoading(true)
    setError(null)
    getCustomer(customerId)
      .then(res => setCustomer(res.data?.data))
      .catch(() => setError('Failed to load customer.'))
      .finally(() => setLoading(false))
  }, [customerId])

  useEffect(() => { loadCustomer() }, [loadCustomer])

  useEffect(() => {
    if (tab === 'messages') {
      getCustomerMessages(customerId).then(res => setMessages(res.data?.data?.items ?? []))
    }
    if (tab === 'tasks') {
      getCustomerTasks(customerId).then(res => setTasks(res.data?.data ?? []))
    }
    if (tab === 'nps') {
      getCustomerNps(customerId).then(res => setNps(res.data?.data ?? []))
    }
  }, [tab, customerId])

  useEffect(() => {
    listTemplates().then(res => setTemplates(res.data?.data ?? []))
  }, [])

  function startEdit() {
    setEditForm({
      full_name:     customer.full_name,
      business_name: customer.business_name,
      business_type: customer.business_type || '',
      phone:         customer.phone || '',
      email:         customer.email || '',
      location:      customer.location || '',
      branches:      customer.branches || '',
      onboarding_complete:  customer.onboarding_complete ?? false,
    })
    setEditing(true)
    setSaveErr(null)
  }

  async function handleSave() {
    setSaving(true)
    setSaveErr(null)
    try {
      // strip empty strings → backend ignores null
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

  const TABS = ['profile', 'messages', 'tasks', 'nps', 'log-interaction', 'create-ticket']
  const TAB_LABELS = {
    profile:          'Profile',
    messages:         'Messages',
    tasks:            'Tasks',
    nps:              'NPS History',
    'log-interaction':'📞 Log Interaction',
    'create-ticket':  '🎫 Create Ticket',
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
      padding: 4, borderRadius: 10, marginBottom: 20, width: 'fit-content',
    },
    tabBtn: (active) => ({
      padding: '8px 18px', borderRadius: 7, border: 'none', cursor: 'pointer',
      fontSize: 13, fontWeight: active ? 600 : 500, fontFamily: ds.fontBody,
      background: active ? '#fff' : 'none',
      color: active ? ds.teal : ds.gray,
      boxShadow: active ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
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
    taskCard: {
      background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 10,
      padding: '12px 16px', marginBottom: 10,
    },
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

  // Window status requires an active Meta integration and inbound messages.
  // Default to true for development — production will check whatsapp_messages table.
  const windowOpen = customer?.last_window_open ?? true

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

      {/* Tabs */}
      <div style={S.tabBar}>
        {TABS.map(t => (
          <button key={t} style={S.tabBtn(tab === t)} onClick={() => setTab(t)}>
            {TAB_LABELS[t]}
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

              {/* Onboarding toggle — separate from text fields */}
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
                    {m.direction === 'outbound' ? `Sent · ${new Date(m.created_at).toLocaleString()}` : `Received · ${new Date(m.created_at).toLocaleString()}`}
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
          {tasks.length === 0 ? (
            <div style={S.empty}>No tasks linked to this customer.</div>
          ) : tasks.map(t => {
            const overdue = t.due_at && new Date(t.due_at) < new Date() && t.status !== 'completed'
            return (
              <div key={t.id} style={{
                ...S.taskCard,
                borderLeft: overdue ? `3px solid #E05252` : `3px solid ${ds.teal}`,
                background: overdue ? '#FFFAFA' : '#fff',
              }}>
                <div style={{ fontWeight: 600, fontSize: 13.5, color: ds.dark, marginBottom: 4 }}>
                  {t.title}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: ds.gray, flexWrap: 'wrap' }}>
                  {t.status && (
                    <span style={{ background: '#EAF0F2', color: ds.dark, borderRadius: 10, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                      {t.status}
                    </span>
                  )}
                  {overdue && (
                    <span style={{ background: '#FFE8E8', color: '#C0392B', borderRadius: 10, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                      Overdue
                    </span>
                  )}
                  {t.due_at && <span>Due: {new Date(t.due_at).toLocaleDateString()}</span>}
                  {t.ai_recommended && (
                    <span style={{ background: '#FFF3E0', color: '#8B4513', borderRadius: 10, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                      🤖 AI Recommended
                    </span>
                  )}
                </div>
              </div>
            )
          })}
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

      {/* ── Log Interaction tab ─────────────────────────────────────────── */}
      {tab === 'log-interaction' && (
        <LogInteractionPanel
          linkedTo={{ type: 'customer', id: customerId }}
          contextName={customer?.full_name ?? 'this customer'}
        />
      )}

      {/* ── Create Ticket tab ───────────────────────────────────────────── */}
      {tab === 'create-ticket' && (
        <LinkedTicketsPanel
          linkedTo={{ type: 'customer', id: customerId }}
          contextName={customer?.full_name ?? 'this customer'}
        />
      )}
    </div>
  )
}
