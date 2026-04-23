/**
 * frontend/src/modules/onboarding/OnboardingChecklist.jsx
 *
 * Collapsible setup checklist panel — fixed right edge.
 * Visible only when:  !org.is_live  AND  role is owner or ops_manager.
 *
 * Collapsed: floating tab on right edge — progress ring + "X/17" count.
 * Expanded:  320px panel slides in from right.
 *
 * Patterns:
 *   Pattern 11 — JWT in Zustand memory only
 *   Pattern 13 — setView/setActiveNav for navigation (props injected from AppShell)
 *   Pattern 26 — mount-and-hide, not conditional render (panel stays mounted)
 *   Pattern 50 — axios + _h() via service layer
 *   Pattern 56 — isManager() is a function; user id at user?.id
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import useAuthStore from '../../store/authStore'
import { getChecklist, activateOrg } from '../../services/onboarding.service'
import { ds } from '../../utils/ds'

// ── Navigation targets per checklist item ─────────────────────────────────────
const NAV_TARGETS = {
  team_user:           { view: 'admin', tab: 'users' },
  routing_rule:        { view: 'admin', tab: 'routing' },
  scoring_rubric:      { view: 'admin', tab: 'scoring' },
  qualification_flow:  { view: 'admin', tab: 'qualification' },
  pipeline_confirmed:  { view: 'admin', tab: 'pipeline' },
  whatsapp_connected:  { view: 'admin', tab: 'integrations' },
  wa_template_approved:{ view: 'admin', tab: 'templates' },
  triage_menu:         { view: 'admin', tab: 'whatsapp-menu' },
  ticket_routing:      { view: 'support', tab: null },
  ticket_categories:   { view: 'support', tab: null },
  kb_minimum:          { view: 'support', tab: null },
  drip_sequence:       { view: 'whatsapp', tab: null },
  sla_targets:         { view: 'admin', tab: 'sla' },
  business_hours:      { view: 'admin', tab: 'sla-hours' },
  business_types:      { view: 'admin', tab: 'biz-types' },
  nurture_reviewed:    { view: 'admin', tab: 'nurture' },
  staff_whatsapp:      { view: 'admin', tab: 'users' },
}

const GROUP_ORDER = [
  'Team & Access',
  'Lead Pipeline',
  'WhatsApp',
  'Support',
  'Customer Engagement',
  'Notifications',
]

// ── Small SVG progress ring ───────────────────────────────────────────────────
function ProgressRing({ percent, size = 44, stroke = 4 }) {
  const r = (size - stroke * 2) / 2
  const circ = 2 * Math.PI * r
  const offset = circ - (percent / 100) * circ
  return (
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth={stroke} />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none"
        stroke={percent === 100 ? ds.green : ds.teal}
        strokeWidth={stroke}
        strokeDasharray={circ}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 0.5s ease' }}
      />
    </svg>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function OnboardingChecklist({ setView, setActiveNav }) {
  const { user } = useAuthStore()
  const template = user?.roles?.template ?? ''

  // Only owner or ops_manager can see this
  const canSee = (template === 'owner' || template === 'ops_manager')
  const isLive = user?.is_live === true   // if we ever store it on the user obj

  const [expanded,        setExpanded]        = useState(false)
  const [checklist,       setChecklist]       = useState(null)   // null = loading
  const [loadError,       setLoadError]       = useState(false)
  const [activating,      setActivating]      = useState(false)
  const [confirmModal,    setConfirmModal]     = useState(false)
  const [liveSuccess,     setLiveSuccess]      = useState(false)
  const [orgIsLive,       setOrgIsLive]        = useState(false)
  const pollingRef = useRef(null)

  const fetchChecklist = useCallback(async () => {
    try {
      const data = await getChecklist()
      setChecklist(data)
      setLoadError(false)
      if (data.is_live) setOrgIsLive(true)
    } catch {
      setLoadError(true)
    }
  }, [])

  // Fetch on open, poll every 60s while expanded
  useEffect(() => {
    if (!canSee || orgIsLive) return
    if (expanded) {
      fetchChecklist()
      pollingRef.current = setInterval(fetchChecklist, 60_000)
    } else {
      clearInterval(pollingRef.current)
    }
    return () => clearInterval(pollingRef.current)
  }, [expanded, canSee, orgIsLive, fetchChecklist])

  // Initial silent fetch to know percent for collapsed ring
  useEffect(() => {
    if (canSee && !orgIsLive) fetchChecklist()
  }, [canSee, orgIsLive, fetchChecklist])

  const handleActivate = async () => {
    setActivating(true)
    try {
      await activateOrg()
      setLiveSuccess(true)
      setOrgIsLive(true)
      setConfirmModal(false)
      clearInterval(pollingRef.current)
      // Hide panel after 3s celebration
      setTimeout(() => {
        setExpanded(false)
      }, 3000)
    } catch (err) {
      alert(err?.response?.data?.detail?.message ?? 'Activation failed. Please try again.')
    } finally {
      setActivating(false)
    }
  }

  const handleGoTo = (itemId) => {
    const target = NAV_TARGETS[itemId]
    if (!target) return
    setView(target.view)
    setActiveNav(target.view)
    setExpanded(false)
  }

  // ── Derived state ────────────────────────────────────────────────────────
  const percent      = checklist?.percent_complete ?? 0
  const goLiveReady  = checklist?.go_live_ready    ?? false
  const totalItems   = checklist?.items?.length    ?? 17
  const doneCount    = checklist?.items?.filter(i => i.complete).length ?? 0

  // Don't render if user can't see it or org is already live (and no success msg)
  if (!canSee) return null
  if (orgIsLive && !liveSuccess) return null

  // ── Styles ───────────────────────────────────────────────────────────────
  const panelZ = 1100   // above modules, below Aria (which is typically ~1200)

  return (
    <>
      {/* ── Inject slide-in keyframe once ──────────────────────────────── */}
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);   opacity: 1; }
        }
        @keyframes celebrationPop {
          0%   { transform: scale(0.8); opacity: 0; }
          60%  { transform: scale(1.1); }
          100% { transform: scale(1);   opacity: 1; }
        }
        .ocl-go-btn:hover { background: rgba(0,188,212,0.18) !important; }
        .ocl-tab:hover    { background: #015F6B !important; }
        .ocl-item:hover   { background: rgba(255,255,255,0.04) !important; }
      `}</style>

      {/* ── Collapsed tab ──────────────────────────────────────────────── */}
      {!expanded && !liveSuccess && (
        <div
          className="ocl-tab"
          onClick={() => setExpanded(true)}
          title="Setup Checklist"
          style={{
            position:   'fixed',
            top:        '50%',
            right:      0,
            transform:  'translateY(-50%)',
            zIndex:     panelZ,
            background: ds.dark2,
            border:     '1px solid #1a3a4a',
            borderRight:'none',
            borderRadius: '12px 0 0 12px',
            padding:    '14px 10px',
            cursor:     'pointer',
            display:    'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap:        6,
            transition: 'background 0.18s',
            boxShadow:  '-4px 0 20px rgba(0,0,0,0.3)',
          }}
        >
          <div style={{ position: 'relative', width: 44, height: 44 }}>
            <ProgressRing percent={percent} />
            <div style={{
              position:  'absolute', inset: 0,
              display:   'flex', alignItems: 'center', justifyContent: 'center',
              fontSize:  10, fontWeight: 700, color: 'white',
              fontFamily: ds.fontSyne,
            }}>
              {doneCount}/{totalItems}
            </div>
          </div>
          <span style={{
            fontSize: 9, fontWeight: 600, color: '#7A9BAD',
            textTransform: 'uppercase', letterSpacing: '0.8px',
            writingMode: 'vertical-rl', textOrientation: 'mixed',
          }}>
            Setup
          </span>
        </div>
      )}

      {/* ── Expanded panel — Pattern 26: always mounted ─────────────────── */}
      <div style={{
        position:   'fixed',
        top:        60,   // below topbar
        right:      0,
        bottom:     0,
        width:      320,
        zIndex:     panelZ,
        display:    expanded ? 'flex' : 'none',
        flexDirection: 'column',
        background: ds.dark2,
        borderLeft: '1px solid #1a3a4a',
        boxShadow:  '-8px 0 32px rgba(0,0,0,0.35)',
        animation:  expanded ? 'slideInRight 0.22s ease' : 'none',
      }}>

        {/* ── Live success overlay ─────────────────────────────────────── */}
        {liveSuccess && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 10,
            background: ds.dark2,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            gap: 16, padding: 32,
            animation: 'celebrationPop 0.4s ease',
          }}>
            <div style={{ fontSize: 56 }}>🎉</div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: 'white', margin: 0, textAlign: 'center' }}>
              You're live!
            </p>
            <p style={{ fontSize: 13, color: '#7A9BAD', margin: 0, textAlign: 'center', lineHeight: 1.6 }}>
              Your organisation is now fully activated. Welcome to Opsra.
            </p>
          </div>
        )}

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div style={{
          padding:    '18px 20px 14px',
          borderBottom: '1px solid #1a3a4a',
          display:    'flex', alignItems: 'center', justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: 'white', margin: 0 }}>
              Setup Checklist
            </p>
            <p style={{ fontSize: 12, color: '#7A9BAD', margin: '2px 0 0' }}>
              {doneCount} of {totalItems} complete
            </p>
          </div>
          <button
            onClick={() => setExpanded(false)}
            style={{ background: 'none', border: 'none', color: '#7A9BAD', fontSize: 18, cursor: 'pointer', lineHeight: 1, padding: 4 }}
          >
            ×
          </button>
        </div>

        {/* ── Progress bar ─────────────────────────────────────────────── */}
        <div style={{ padding: '10px 20px 0', flexShrink: 0 }}>
          <div style={{ height: 5, background: 'rgba(255,255,255,0.08)', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${percent}%`,
              background: percent === 100 ? ds.green : ds.teal,
              borderRadius: 4,
              transition: 'width 0.5s ease',
            }} />
          </div>
          <p style={{ fontSize: 11, color: '#3a5a6a', margin: '6px 0 0', textAlign: 'right' }}>
            {percent}%
          </p>
        </div>

        {/* ── Item list ────────────────────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {loadError && (
            <div style={{ padding: '20px', textAlign: 'center' }}>
              <p style={{ fontSize: 13, color: '#FF9A9A' }}>Failed to load checklist.</p>
              <button onClick={fetchChecklist} style={{ fontSize: 12, color: ds.teal, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
                Retry
              </button>
            </div>
          )}

          {!checklist && !loadError && (
            <div style={{ padding: 20, textAlign: 'center' }}>
              <div style={{ width: 20, height: 20, border: `2px solid ${ds.teal}`, borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto' }} />
            </div>
          )}

          {checklist && GROUP_ORDER.map(group => {
            const items = checklist.items.filter(i => i.group === group)
            if (!items.length) return null
            return (
              <div key={group}>
                {/* Group header */}
                <div style={{
                  padding: '12px 20px 4px',
                  fontSize: 10, fontWeight: 600, color: '#3a5a6a',
                  textTransform: 'uppercase', letterSpacing: '1px',
                }}>
                  {group}
                </div>

                {items.map(item => (
                  <div
                    key={item.id}
                    className="ocl-item"
                    style={{
                      display:    'flex',
                      alignItems: 'center',
                      gap:        10,
                      padding:    '8px 20px',
                      transition: 'background 0.15s',
                      borderRadius: 6,
                      margin:     '0 4px',
                    }}
                  >
                    {/* Status icon */}
                    <div style={{ flexShrink: 0, fontSize: 14 }}>
                      {item.complete
                        ? '✅'
                        : item.is_gate
                          ? '⛔'
                          : '⏳'}
                    </div>

                    {/* Label + gate badge */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{
                        fontSize:  12.5,
                        color:     item.complete ? '#7A9BAD' : 'white',
                        margin:    0,
                        lineHeight: 1.4,
                        textDecoration: item.complete ? 'line-through' : 'none',
                        opacity:   item.complete ? 0.6 : 1,
                      }}>
                        {item.label}
                      </p>
                      {item.is_gate && !item.complete && (
                        <p style={{ fontSize: 10, color: '#EF4444', margin: '2px 0 0', fontWeight: 500 }}>
                          🔒 Required before activation
                        </p>
                      )}
                    </div>

                    {/* Go → button for incomplete items */}
                    {!item.complete && (
                      <button
                        className="ocl-go-btn"
                        onClick={() => handleGoTo(item.id)}
                        title={`Go to ${item.label}`}
                        style={{
                          flexShrink:   0,
                          background:   'rgba(0,188,212,0.1)',
                          border:       `1px solid rgba(0,188,212,0.25)`,
                          borderRadius: 6,
                          padding:      '4px 10px',
                          fontSize:     11,
                          fontWeight:   600,
                          color:        ds.teal,
                          cursor:       'pointer',
                          fontFamily:   ds.fontSyne,
                          transition:   'background 0.15s',
                          whiteSpace:   'nowrap',
                        }}
                      >
                        Go →
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )
          })}
        </div>

        {/* ── Activate button ──────────────────────────────────────────── */}
        <div style={{
          padding:      '14px 20px 20px',
          borderTop:    '1px solid #1a3a4a',
          flexShrink:   0,
        }}>
          {!goLiveReady && checklist && (
            <p style={{ fontSize: 11, color: '#7A9BAD', margin: '0 0 10px', textAlign: 'center', lineHeight: 1.5 }}>
              Complete all required (⛔) items to activate
            </p>
          )}
          <button
            onClick={() => goLiveReady && setConfirmModal(true)}
            disabled={!goLiveReady || activating}
            title={!goLiveReady ? 'Complete all required setup steps first' : 'Activate your organisation'}
            style={{
              width:        '100%',
              background:   goLiveReady ? ds.teal : 'rgba(255,255,255,0.07)',
              color:        goLiveReady ? 'white' : '#3a5a6a',
              border:       'none',
              borderRadius: 10,
              padding:      '13px 0',
              fontSize:     14,
              fontWeight:   700,
              fontFamily:   ds.fontSyne,
              cursor:       goLiveReady ? 'pointer' : 'not-allowed',
              transition:   'all 0.2s',
              letterSpacing:'0.3px',
            }}
          >
            {activating ? 'Activating…' : '🚀 Activate Organisation'}
          </button>
        </div>
      </div>

      {/* ── Confirm modal ────────────────────────────────────────────────── */}
      {confirmModal && (
        <div style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.7)',
          zIndex: panelZ + 100,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background:   ds.dark2,
            border:       '1px solid #1e3a4f',
            borderRadius: 16,
            padding:      '32px 28px',
            width:        380,
            boxShadow:    '0 24px 60px rgba(0,0,0,0.5)',
            animation:    'celebrationPop 0.25s ease',
          }}>
            <div style={{ fontSize: 36, marginBottom: 12, textAlign: 'center' }}>🚀</div>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: 'white', margin: '0 0 10px', textAlign: 'center' }}>
              Ready to go live?
            </h3>
            <p style={{ fontSize: 13, color: '#7A9BAD', lineHeight: 1.65, margin: '0 0 24px', textAlign: 'center' }}>
              This will activate your organisation on Opsra. Your WhatsApp integration, lead pipeline, and support system will all go live immediately.
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => setConfirmModal(false)}
                style={{
                  flex: 1, background: 'none', border: '1px solid #2a4a5a',
                  borderRadius: 9, padding: '11px 0', fontSize: 13,
                  color: '#7A9BAD', cursor: 'pointer', fontFamily: ds.fontDm,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleActivate}
                disabled={activating}
                style={{
                  flex: 1, background: ds.teal, border: 'none',
                  borderRadius: 9, padding: '11px 0', fontSize: 13,
                  fontWeight: 700, color: 'white', cursor: activating ? 'not-allowed' : 'pointer',
                  fontFamily: ds.fontSyne, transition: 'background 0.2s',
                  opacity: activating ? 0.7 : 1,
                }}
              >
                {activating ? 'Activating…' : 'Yes, go live'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
