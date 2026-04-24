/**
 * LeadProfile
 *
 * Fetches GET /api/v1/leads/{id} and renders the full lead record.
 * Tab 1 — Profile:          all fields from the leads table schema
 * Tab 2 — Messages:         WhatsApp message history
 * Tab 3 — Timeline:         LeadTimeline component
 * Tab 4 — Tasks:            LeadTasks component
 * Tab 5 — Demos:            DemoScheduler component  (M01-7)
 * Tab 6 — Interaction Log:  LogInteractionPanel
 * Tab 7 — Tickets:          LinkedTicketsPanel
 *
 * GPM-1B: Deal Value modal on convert.
 *   When rep clicks "✓ Convert", a modal asks for deal value before confirming.
 *   Rep can skip (converts without deal_value) or enter amount.
 *   After conversion, deal_value is saved via PATCH /leads/{id}.
 *
 * SECURITY: org_id never sent in any payload — derived from JWT server-side.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  getLead, moveStage, convertLead, reactivateLead, reactivateFromNurture,
  updateLead, overrideLeadScore, getLeadAttentionSummary,
} from '../../services/leads.service'
import useAuthStore from '../../store/authStore'
import UserSelect   from '../../shared/UserSelect'
import { ds, SCORE_STYLE, STAGE_STYLE, STAGES, SOURCE_LABELS, LOST_REASON_LABELS, BRANCHES_OPTIONS } from '../../utils/ds'
import { getPipelineStages } from '../../services/admin.service'
import LeadScoreButton from './LeadScoreButton'
import LeadTimeline    from './LeadTimeline'
import LeadTasks       from './LeadTasks'
import LeadMessages    from './LeadMessages'
import MarkLostModal   from './MarkLostModal'
import DemoScheduler   from './DemoScheduler'
import LogInteractionPanel from '../../shared/LogInteractionPanel'
import LinkedTicketsPanel  from '../../shared/LinkedTicketsPanel'

// Fallback movable stages (used before org config loads)
const _DEFAULT_MOVABLE = ['new', 'contacted', 'meeting_done', 'proposal_sent']

// ─── Deal Value Modal ─────────────────────────────────────────────────────────

function DealValueModal({ leadName, onConfirm, onSkip, loading }) {
  const [value, setValue] = useState('')

  function handleConfirm() {
    const num = parseFloat(value.replace(/,/g, ''))
    onConfirm(isNaN(num) || num <= 0 ? null : num)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: 'white', borderRadius: ds.radius.xl,
        padding: '28px 28px 24px', width: 420, maxWidth: '90vw',
        boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
      }}>
        <div style={{ fontSize: 32, marginBottom: 8, textAlign: 'center' }}>🎉</div>
        <h3 style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17,
          color: ds.dark, margin: '0 0 6px', textAlign: 'center',
        }}>
          Deal Closed!
        </h3>
        <p style={{
          fontSize: 13.5, color: ds.gray, margin: '0 0 20px',
          lineHeight: 1.5, textAlign: 'center',
        }}>
          Converting <strong>{leadName}</strong> to a customer.
          What was the deal value?
        </p>

        <div style={{ marginBottom: 20 }}>
          <label style={{
            fontSize: 11, fontWeight: 600, color: ds.gray,
            textTransform: 'uppercase', letterSpacing: '0.5px',
            display: 'block', marginBottom: 6,
          }}>
            Deal Value (optional)
          </label>
          <div style={{ position: 'relative' }}>
            <span style={{
              position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
              fontSize: 13.5, color: ds.gray, fontFamily: ds.fontDm, pointerEvents: 'none',
            }}>₦</span>
            <input
              type="text"
              value={value}
              onChange={e => setValue(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleConfirm()}
              placeholder="0.00"
              autoFocus
              style={{
                width: '100%', boxSizing: 'border-box',
                border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
                padding: '10px 12px 10px 28px', fontSize: 15,
                fontFamily: ds.fontDm, color: ds.dark,
              }}
            />
          </div>
          <p style={{ fontSize: 11.5, color: '#94a3b8', margin: '6px 0 0', fontFamily: ds.fontDm }}>
            Leave blank to skip — you can update this later from the lead profile.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onSkip}
            disabled={loading}
            style={{
              padding: '9px 18px', borderRadius: ds.radius.md,
              border: `1.5px solid ${ds.border}`, background: 'white',
              color: ds.gray, fontSize: 13, fontWeight: 600,
              fontFamily: ds.fontSyne, cursor: 'pointer',
            }}
          >
            Skip
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading}
            style={{
              padding: '9px 20px', borderRadius: ds.radius.md,
              border: 'none', background: ds.teal,
              color: 'white', fontSize: 13, fontWeight: 600,
              fontFamily: ds.fontSyne, cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? '…' : '✓ Convert'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function LeadProfile({ leadId, onBack }) {
  const [lead, setLead]           = useState(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [tab, setTab]             = useState('profile')
  const [actionError, setActionError] = useState(null)
  const [actionLoading, setActionLoading] = useState(null)
  const [showMarkLost, setShowMarkLost]   = useState(false)
  const [assignedTo,   setAssignedTo]     = useState('')
  const [assignSaving, setAssignSaving]   = useState(false)
  const [overrideLoading, setOverrideLoading] = useState(false)

  // GPM-1B: deal value modal state
  const [showDealValueModal, setShowDealValueModal] = useState(false)
  const [dealValueLoading,   setDealValueLoading]   = useState(false)

  // CONFIG-6: org pipeline stages
  const [pipelineStages,   setPipelineStages]   = useState(STAGES)
  const [movableStageKeys, setMovableStageKeys] = useState(_DEFAULT_MOVABLE)
  useEffect(() => {
    getPipelineStages()
      .then(data => {
        const cfg = data?.stages
        if (Array.isArray(cfg) && cfg.length > 0) {
          const DOT = {
            new: '#7A9BAD', contacted: '#3b82f6', meeting_done: '#8b5cf6',
            proposal_sent: '#f59e0b', converted: '#10b981',
            lost: '#ef4444', not_ready: '#6b7280',
          }
          const mapped = cfg.map(s => ({ key: s.key, label: s.label, dot: DOT[s.key] || '#7A9BAD' }))
          setPipelineStages(mapped)
          const nonTerminal = new Set(['converted', 'lost', 'not_ready'])
          setMovableStageKeys(
            cfg.filter(s => s.enabled !== false && !nonTerminal.has(s.key)).map(s => s.key)
          )
        }
      })
      .catch(() => {})
  }, [])

  // Attention signals
  const [attention, setAttention] = useState({
    unread_messages: 0,
    pending_demos:   0,
    open_tickets:    0,
    pending_tasks:   0,
  })

  const [showNurtureReactivate, setShowNurtureReactivate] = useState(false)
  const [nurtureReason, setNurtureReason]                 = useState('')
  const [nurtureReactivating, setNurtureReactivating]     = useState(false)

  const fetchLead = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getLead(leadId)
      if (res.success) {
        setLead(res.data)
        setAssignedTo(res.data?.assigned_to ?? '')
      } else {
        setError(res.error ?? 'Failed to load lead')
      }
    } catch (err) {
      setError(err?.response?.data?.error ?? 'Failed to load lead')
    } finally {
      setLoading(false)
    }
  }, [leadId])

  useEffect(() => { fetchLead() }, [fetchLead])

  useEffect(() => {
    if (!leadId) return
    getLeadAttentionSummary()
      .then(res => {
        if (res.success) {
          const signals = (res.data ?? {})[leadId] ?? {}
          setAttention({
            unread_messages: signals.unread_messages ?? 0,
            pending_demos:   signals.pending_demos   ?? 0,
            open_tickets:    signals.open_tickets    ?? 0,
            pending_tasks:   signals.pending_tasks   ?? 0,
          })
        }
      })
      .catch(() => {})
  }, [leadId])

  const runAction = async (key, fn) => {
    setActionError(null)
    setActionLoading(key)
    try {
      const res = await fn()
      if (res?.success) setLead(res.data?.lead ?? res.data)
    } catch (err) {
      setActionError(err?.response?.data?.error ?? 'Action failed')
    } finally {
      setActionLoading(null)
    }
  }

  const handleMoveStage = (newStage) => {
    if (!newStage || newStage === lead.stage) return
    runAction('move', () => moveStage(leadId, newStage))
  }

  // GPM-1B: Convert button now opens deal value modal instead of window.confirm
  const handleConvertClick = () => {
    setShowDealValueModal(true)
  }

  const handleDealValueConfirm = async (dealValue) => {
    setDealValueLoading(true)
    setActionError(null)
    try {
      // Step 1: convert the lead
      const res = await convertLead(leadId)
      if (!res?.success) {
        setActionError(res?.error ?? 'Conversion failed')
        setShowDealValueModal(false)
        setDealValueLoading(false)
        return
      }
      setLead(res.data?.lead ?? res.data)

      // Step 2: save deal_value if provided
      if (dealValue != null) {
        await updateLead(leadId, { deal_value: dealValue })
        setLead(prev => ({ ...prev, deal_value: dealValue }))
      }

      setShowDealValueModal(false)
    } catch (err) {
      setActionError(err?.response?.data?.error ?? 'Conversion failed')
      setShowDealValueModal(false)
    } finally {
      setDealValueLoading(false)
    }
  }

  const handleDealValueSkip = async () => {
    // Convert without deal value
    await handleDealValueConfirm(null)
  }

  const handleReactivate = () => {
    if (!window.confirm(`Reactivate ${lead.full_name}? A new lead will be created linked to this record.`)) return
    runAction('reactivate', () => reactivateLead(leadId))
  }

  const handleReactivateFromNurture = async () => {
    setActionError(null)
    setNurtureReactivating(true)
    try {
      const res = await reactivateFromNurture(leadId, nurtureReason.trim() || null)
      if (res?.success) {
        setLead(res.data?.lead ?? res.data)
        setShowNurtureReactivate(false)
        setNurtureReason('')
      } else {
        setActionError(res.error ?? 'Reactivation failed')
      }
    } catch (err) {
      setActionError(err?.response?.data?.error ?? 'Reactivation failed')
    } finally {
      setNurtureReactivating(false)
    }
  }

  const handleOverrideScore = async (score) => {
    setOverrideLoading(true)
    setActionError(null)
    try {
      const res = await overrideLeadScore(leadId, score)
      if (res?.success) setLead(prev => ({ ...prev, ...res.data }))
    } catch (err) {
      setActionError(err?.response?.data?.error ?? 'Score override failed')
    } finally {
      setOverrideLoading(false)
    }
  }

  if (loading) return <ProfileSkeleton onBack={onBack} />
  if (error) return (
    <div style={{ padding: 28 }}>
      <BackButton onBack={onBack} />
      <p style={{ color: ds.red, marginTop: 16 }}>⚠ {error}</p>
    </div>
  )
  if (!lead) return null

  const scoreStyle = SCORE_STYLE[lead.score] ?? SCORE_STYLE.unscored
  const stageStyle = STAGE_STYLE[lead.stage] ?? {}
  const stageLabel = pipelineStages.find(s => s.key === lead.stage)?.label ?? lead.stage?.replace(/_/g, ' ')
  const isTerminal  = ['converted', 'lost', 'not_ready'].includes(lead.stage)
  const isLostStage = lead.stage === 'lost'
  const isNurture   = lead.nurture_track === true
  const isAffiliate = useAuthStore.getState().getRoleTemplate() === 'affiliate_partner'
  const isManager   = useAuthStore.getState().isManager()

  const TABS = [
    { key: 'profile',         label: '👤 Profile'         },
    { key: 'messages',        label: '💬 Messages',        badge: attention.unread_messages, color: 'red'   },
    { key: 'timeline',        label: '📋 Timeline'         },
    { key: 'tasks',           label: '✅ Tasks',           badge: attention.pending_tasks,   color: 'amber' },
    { key: 'demos',           label: '📅 Demos',           badge: attention.pending_demos,   color: 'amber' },
    { key: 'log-interaction', label: '📞 Interaction Log'  },
    { key: 'create-ticket',   label: '🎫 Tickets',         badge: attention.open_tickets,    color: 'red'   },
  ]

  const BADGE_STYLE = {
    red:   { background: '#E53E3E', color: 'white' },
    amber: { background: '#D97706', color: 'white' },
  }

  return (
    <div style={{ padding: 28 }}>
      {/* Back */}
      <BackButton onBack={onBack} />

      {/* ── Profile header ──────────────────────────────────────────── */}
      <div style={{
        background:   'white',
        border:       `1px solid ${ds.border}`,
        borderRadius: ds.radius.xl,
        padding:      '22px 24px',
        marginBottom: 20,
        boxShadow:    ds.cardShadow,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          {/* Avatar */}
          <div style={{
            width: 52, height: 52, borderRadius: '50%',
            background: ds.teal, color: 'white', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20,
          }}>
            {lead.full_name?.[0]?.toUpperCase() ?? '?'}
          </div>

          {/* Name + badges */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: ds.dark, margin: '0 0 6px' }}>
              {lead.full_name}
            </h2>
            {lead.business_name && (
              <p style={{ fontSize: 14, color: ds.gray, margin: '0 0 8px' }}>{lead.business_name}</p>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ background: scoreStyle.bg, color: scoreStyle.color, padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700, fontFamily: ds.fontSyne }}>
                {scoreStyle.label}
              </span>
              {lead.score && lead.score !== 'unscored' && (
                <span style={{
                  background: lead.score_source === 'human' ? '#FFF3E0' : '#E0F7FA',
                  color:      lead.score_source === 'human' ? '#92400E' : '#006064',
                  padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 600,
                }}>
                  {lead.score_source === 'human' ? '👤 Human' : '🤖 AI'}
                </span>
              )}
              <span style={{ background: stageStyle.bg, color: stageStyle.color, padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700, fontFamily: ds.fontSyne }}>
                {stageLabel}
              </span>
              {lead.source && (
                <span style={{ background: ds.mint, color: ds.tealDark, padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600 }}>
                  {SOURCE_LABELS[lead.source] ?? lead.source}
                </span>
              )}
              {/* GPM-1B: show deal value badge if set */}
              {lead.deal_value != null && (
                <span style={{ background: '#f0fdf4', color: '#16a34a', padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700, fontFamily: ds.fontSyne }}>
                  💰 ₦{Number(lead.deal_value).toLocaleString()}
                </span>
              )}
            </div>
          </div>

          {/* Action buttons */}
          {!isAffiliate && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
              {!isTerminal && (
                <select
                  value={lead.stage}
                  onChange={(e) => handleMoveStage(e.target.value)}
                  disabled={actionLoading === 'move'}
                  style={{
                    border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
                    padding: '8px 12px', fontSize: 12.5, color: ds.dark,
                    fontFamily: ds.fontDm, background: 'white', cursor: 'pointer',
                  }}
                >
                  {pipelineStages.filter(s => movableStageKeys.includes(s.key)).map(s => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              )}

              <LeadScoreButton
                leadId={leadId}
                onScored={(updated) => setLead(prev => ({ ...prev, ...updated }))}
              />

              {isManager && lead.score && lead.score !== 'unscored' && (
                <div style={{ display: 'flex', gap: 4 }}>
                  {['hot', 'warm', 'cold'].map(s => (
                    <button
                      key={s}
                      disabled={overrideLoading || lead.score === s}
                      onClick={() => handleOverrideScore(s)}
                      style={{
                        padding: '6px 10px', borderRadius: ds.radius.sm,
                        border: `1.5px solid ${SCORE_STYLE[s]?.color ?? ds.border}`,
                        background: lead.score === s ? SCORE_STYLE[s]?.bg : 'white',
                        color: SCORE_STYLE[s]?.color ?? ds.dark,
                        fontSize: 11, fontWeight: 700, fontFamily: ds.fontSyne,
                        cursor: (overrideLoading || lead.score === s) ? 'not-allowed' : 'pointer',
                        opacity: (overrideLoading || lead.score === s) ? 0.6 : 1,
                      }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}

              {/* GPM-1B: Convert button now triggers deal value modal */}
              {!isTerminal && lead.stage === 'proposal_sent' && (
                <ActionBtn onClick={handleConvertClick} loading={actionLoading === 'convert'} color={ds.teal}>
                  ✓ Convert
                </ActionBtn>
              )}

              {!isTerminal && (
                <ActionBtn onClick={() => setShowMarkLost(true)} loading={false} color={ds.red}>
                  ✗ Mark Lost
                </ActionBtn>
              )}

              {isLostStage && (
                <ActionBtn onClick={handleReactivate} loading={actionLoading === 'reactivate'} color={ds.teal}>
                  ↺ Reactivate
                </ActionBtn>
              )}

              {isNurture && (
                <ActionBtn onClick={() => setShowNurtureReactivate(true)} loading={false} color="#7C3AED">
                  ↺ Reactivate from Nurture
                </ActionBtn>
              )}
            </div>
          )}
        </div>

        {actionError && (
          <p style={{ color: ds.red, fontSize: 13, marginTop: 10 }}>⚠ {actionError}</p>
        )}

        {/* Assign rep */}
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${ds.border}` }}>
          <p style={{ fontSize: 11, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.5px', margin: '0 0 8px' }}>
            Assigned Rep
          </p>
          {isManager ? (
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', maxWidth: 380 }}>
              <div style={{ flex: 1 }}>
                <UserSelect value={assignedTo} onChange={setAssignedTo} placeholder="— Unassigned —" />
              </div>
              <button
                disabled={assignSaving || assignedTo === (lead.assigned_to ?? '')}
                onClick={async () => {
                  setAssignSaving(true)
                  try {
                    await updateLead(leadId, { assigned_to: assignedTo || null })
                    await fetchLead()
                  } catch {
                    setActionError('Failed to reassign lead.')
                  } finally {
                    setAssignSaving(false)
                  }
                }}
                style={{
                  background: (assignSaving || assignedTo === (lead.assigned_to ?? '')) ? '#9ca3af' : ds.teal,
                  color: 'white', border: 'none', borderRadius: 8,
                  padding: '9px 16px', fontSize: 13, fontWeight: 600,
                  cursor: (assignSaving || assignedTo === (lead.assigned_to ?? '')) ? 'not-allowed' : 'pointer',
                  fontFamily: ds.fontSyne, whiteSpace: 'nowrap',
                }}
              >
                {assignSaving ? 'Saving…' : 'Save'}
              </button>
            </div>
          ) : (
            <p style={{ fontSize: 13.5, color: lead.assigned_to ? ds.dark : ds.gray, margin: 0 }}>
              {lead.assigned_user?.full_name ?? (lead.assigned_to ? lead.assigned_to.slice(0, 8) + '…' : 'Unassigned')}
            </p>
          )}
        </div>
      </div>

      {/* ── Tabs ──────────────────────────────────────────────────── */}
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: ds.radius.xl, boxShadow: ds.cardShadow, overflow: 'hidden' }}>
        <div style={{ display: 'flex', gap: 4, padding: '10px 16px', borderBottom: `1px solid ${ds.border}`, background: ds.light, overflowX: 'auto' }}>
          {TABS.map(({ key, label, badge, color }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                padding:      '8px 16px',
                borderRadius: 7,
                border:       'none',
                background:   tab === key ? 'white' : 'none',
                color:        tab === key ? ds.teal : ds.gray,
                fontWeight:   tab === key ? 600 : 500,
                fontSize:     13,
                cursor:       'pointer',
                fontFamily:   ds.fontDm,
                boxShadow:    tab === key ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
                transition:   'all 0.15s',
                position:     'relative',
                display:      'inline-flex',
                alignItems:   'center',
                gap:          5,
                whiteSpace:   'nowrap',
                flexShrink:   0,
              }}
            >
              {label}
              {badge > 0 && tab !== key && (
                <span style={{
                  ...BADGE_STYLE[color],
                  borderRadius: 20, padding: '1px 5px',
                  fontSize: 9, fontWeight: 700,
                  lineHeight: '14px', fontFamily: ds.fontSyne,
                }}>
                  {badge}
                </span>
              )}
            </button>
          ))}
        </div>

        <div style={{ padding: '24px' }}>
          {tab === 'profile'  && <ProfileTab lead={lead} pipelineStages={pipelineStages} />}
          {tab === 'messages' && <LeadMessages leadId={leadId} leadName={lead.full_name} />}
          {tab === 'timeline' && <LeadTimeline leadId={leadId} />}
          {tab === 'tasks'    && <LeadTasks    leadId={leadId} />}
          {tab === 'demos'    && <DemoScheduler leadId={leadId} leadName={lead.full_name} />}
          {tab === 'log-interaction' && (
            <LogInteractionPanel linkedTo={{ type: 'lead', id: leadId }} contextName={lead.full_name} />
          )}
          {tab === 'create-ticket' && (
            <LinkedTicketsPanel linkedTo={{ type: 'lead', id: leadId }} contextName={lead.full_name} />
          )}
        </div>
      </div>

      {/* Nurture reactivation modal */}
      {showNurtureReactivate && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            background: 'white', borderRadius: ds.radius.xl,
            padding: '28px 28px 24px', width: 420, maxWidth: '90vw',
            boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
          }}>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: '0 0 6px' }}>
              Reactivate from Nurture
            </h3>
            <p style={{ fontSize: 13.5, color: ds.gray, margin: '0 0 18px', lineHeight: 1.5 }}>
              This will move <strong>{lead.full_name}</strong> back to the active pipeline (stage: New).
              Optionally add a note about why you're reactivating this lead.
            </p>
            <textarea
              value={nurtureReason}
              onChange={e => setNurtureReason(e.target.value)}
              placeholder="e.g. Spoke on the phone — they're ready to proceed"
              maxLength={500}
              rows={3}
              style={{
                width: '100%', boxSizing: 'border-box',
                border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
                padding: '10px 12px', fontSize: 13.5, fontFamily: ds.fontDm,
                color: ds.dark, resize: 'vertical', marginBottom: 18,
              }}
            />
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <ActionBtn onClick={() => { setShowNurtureReactivate(false); setNurtureReason('') }} loading={false} color={ds.gray}>
                Cancel
              </ActionBtn>
              <ActionBtn onClick={handleReactivateFromNurture} loading={nurtureReactivating} color="#7C3AED">
                ↺ Reactivate
              </ActionBtn>
            </div>
          </div>
        </div>
      )}

      {/* Mark lost modal */}
      {showMarkLost && (
        <MarkLostModal
          leadId={leadId}
          leadName={lead.full_name}
          onClose={() => setShowMarkLost(false)}
          onMarked={(updated) => { setLead(updated); setShowMarkLost(false) }}
        />
      )}

      {/* GPM-1B: Deal value modal */}
      {showDealValueModal && (
        <DealValueModal
          leadName={lead.full_name}
          onConfirm={handleDealValueConfirm}
          onSkip={handleDealValueSkip}
          loading={dealValueLoading}
        />
      )}
    </div>
  )
}

// ─── Profile fields tab ───────────────────────────────────────────────────────

function ProfileTab({ lead, pipelineStages }) {
  const groups = [
    {
      title: 'Contact Details',
      fields: [
        { label: 'Phone',          value: lead.phone },
        { label: 'WhatsApp',       value: lead.whatsapp },
        { label: 'Email',          value: lead.email },
        { label: 'Assigned To',    value: lead.assigned_user?.full_name ?? null },
      ],
    },
    {
      title: 'Business Details',
      fields: [
        { label: 'Business Name',  value: lead.business_name },
        { label: 'Business Type',  value: lead.business_type },
        { label: 'Location',       value: lead.location },
        { label: 'Branches',       value: lead.branches },
      ],
    },
    {
      title: 'Source & Attribution',
      fields: [
        { label: 'Source',         value: SOURCE_LABELS[lead.source] ?? lead.source },
        { label: 'Referrer',       value: lead.referrer },
        { label: 'UTM Source',     value: lead.utm_source },
        { label: 'UTM Campaign',   value: lead.utm_campaign },
        { label: 'UTM Ad',         value: lead.utm_ad },
        { label: 'Ad ID',          value: lead.ad_id },
        { label: 'Entry Path',     value: lead.entry_path },
        { label: 'Source Team',    value: lead.source_team },
      ],
    },
    {
      title: 'Pipeline Status',
      fields: [
        { label: 'Stage',              value: pipelineStages.find(s => s.key === lead.stage)?.label ?? lead.stage?.replace(/_/g, ' ') },
        { label: 'Deal Value',         value: lead.deal_value != null ? `₦${Number(lead.deal_value).toLocaleString()}` : null },
        { label: 'Lost Reason',        value: LOST_REASON_LABELS[lead.lost_reason] ?? lead.lost_reason },
        { label: 'Re-engagement Date', value: lead.reengagement_date },
        { label: 'Converted At',       value: lead.converted_at ? fmtDate(lead.converted_at) : null },
        { label: 'Last Activity',      value: lead.last_activity_at ? fmtDate(lead.last_activity_at) : null },
        { label: 'Created At',         value: lead.created_at ? fmtDate(lead.created_at) : null },
      ],
    },
  ]

  return (
    <>
      {lead.problem_stated && (
        <div style={{ marginBottom: 20 }}>
          <p style={groupLabelStyle}>Problem / Need Stated</p>
          <p style={{ fontSize: 13.5, color: ds.dark, lineHeight: 1.7, background: ds.light, borderRadius: ds.radius.md, padding: '12px 14px' }}>
            {lead.problem_stated}
          </p>
        </div>
      )}

      {lead.previous_lead_id && (
        <div style={{ marginBottom: 20, background: '#FFF9E0', border: `1px solid #FFE066`, borderRadius: ds.radius.md, padding: '10px 14px', fontSize: 13, color: '#8B6800' }}>
          ℹ️ This lead was reactivated from a previous record (ID: {lead.previous_lead_id})
        </div>
      )}

      {groups.map((g) => {
        const visible = g.fields.filter(f => f.value != null && f.value !== '')
        if (!visible.length) return null
        return (
          <div key={g.title} style={{ marginBottom: 20 }}>
            <p style={groupLabelStyle}>{g.title}</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {visible.map((f) => (
                <div key={f.label} style={{ background: ds.light, borderRadius: ds.radius.sm, padding: '10px 14px' }}>
                  <p style={{ fontSize: 11, color: ds.gray, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px', margin: '0 0 3px' }}>{f.label}</p>
                  <p style={{ fontSize: 13.5, color: ds.dark, fontWeight: 500, margin: 0 }}>{f.value}</p>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </>
  )
}

// ─── Shared helpers ───────────────────────────────────────────────────────────

function BackButton({ onBack }) {
  return (
    <button
      onClick={onBack}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: 'none', border: 'none', color: ds.teal,
        fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
        fontFamily: ds.fontSyne, marginBottom: 18, padding: 0,
      }}
    >
      ← Back to Pipeline
    </button>
  )
}

function ActionBtn({ onClick, loading, color, children }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '8px 14px', borderRadius: ds.radius.md,
        border: `1.5px solid ${color}`, background: 'white',
        color, fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne,
        cursor: loading ? 'not-allowed' : 'pointer', transition: 'all 0.15s',
        opacity: loading ? 0.5 : 1,
      }}
    >
      {loading ? '…' : children}
    </button>
  )
}

function ProfileSkeleton({ onBack }) {
  const bar = (w, h = 14) => (
    <div style={{ height: h, background: ds.border, borderRadius: 4, width: w, marginBottom: 6 }} />
  )
  return (
    <div style={{ padding: 28 }}>
      <BackButton onBack={onBack} />
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: ds.radius.xl, padding: '22px 24px', marginBottom: 20 }}>
        {bar('40%', 22)}
        {bar('25%', 14)}
        {bar('60%', 11)}
      </div>
    </div>
  )
}

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

const groupLabelStyle = {
  fontSize: 11, fontWeight: 600, color: ds.teal,
  textTransform: 'uppercase', letterSpacing: '0.8px',
  marginBottom: 10, margin: '0 0 10px',
}
