/**
 * frontend/src/modules/admin/WASalesModeConfig.jsx
 * COMM-2 — WhatsApp Sales Mode selector.
 *
 * PWA compliance (Section 13.3 / 13.7):
 *   - useIsMobile() used for responsive layout
 *   - All interactive elements ≥ 44px tap target height
 *   - Fixed save bar has paddingBottom offset on mobile to clear bottom tab bar
 *   - Scrollable form — no fixed-height containers
 *
 * Pattern 50: admin.service.js calls only (axios + _h()).
 * Pattern 51: full rewrite only — never sed.
 * No react-router-dom — parent handles navigation (Pattern 13).
 * org_id never in payload — derived from JWT server-side (Pattern 12).
 */
import { useState, useEffect, useCallback } from 'react'
import { getWASalesMode, updateWASalesMode } from '../../services/admin.service'
import { useIsMobile } from '../../hooks/useIsMobile'

// ─── Icons ────────────────────────────────────────────────────────────────────

function IconHuman() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}
      style={{ width: 22, height: 22, flexShrink: 0 }}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
    </svg>
  )
}

function IconBot() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}
      style={{ width: 22, height: 22, flexShrink: 0 }}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21M6.75 8.25h10.5a2.25 2.25 0 012.25 2.25v5.25a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 15.75V10.5a2.25 2.25 0 012.25-2.25z" />
    </svg>
  )
}

function IconAgent() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}
      style={{ width: 22, height: 22, flexShrink: 0 }}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
    </svg>
  )
}

function IconCheck() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
      style={{ width: 16, height: 16, flexShrink: 0 }}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  )
}

function IconWarning() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}
      style={{ width: 20, height: 20, flexShrink: 0 }}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  )
}

// ─── Mode definitions ─────────────────────────────────────────────────────────

const MODES = [
  {
    key: 'human',
    label: 'Human',
    tagline: 'Rep-led conversations',
    icon: <IconHuman />,
    color: '#0e6c7e',
    bgLight: '#f0f9fa',
    borderActive: '#0e6c7e',
    description:
      'The bot handles triage and lead qualification only. All sales conversations ' +
      'are picked up and managed by your sales reps manually. Best for high-value, ' +
      'consultative sales cycles.',
    bullets: [
      'Bot qualifies the lead, then hands off to rep',
      'Rep responds directly in WhatsApp',
      'Full conversation visible in lead profile',
    ],
    available: true,
  },
  {
    key: 'bot',
    label: 'Bot',
    tagline: 'Automated product & checkout flow',
    icon: <IconBot />,
    color: '#7c3aed',
    bgLight: '#f5f3ff',
    borderActive: '#7c3aed',
    description:
      'Contacts browse products via an interactive WhatsApp menu, add items to cart, ' +
      'and receive a Shopify checkout link — all without rep involvement. Requires ' +
      'Shopify connected and Commerce enabled.',
    bullets: [
      'Interactive product list sent on sales intent',
      'Button-driven add-to-cart and checkout flow',
      'Rep notified on completed or abandoned cart',
    ],
    available: true,
    requiresCommerce: true,
  },
  {
    key: 'ai_agent',
    label: 'AI Agent',
    tagline: 'Conversational AI-driven sales',
    icon: <IconAgent />,
    color: '#d97706',
    bgLight: '#fffbeb',
    borderActive: '#d97706',
    description:
      'An AI agent handles natural-language product discovery, variant selection, ' +
      'and guided cart building — escalating to a rep when it hits its boundary. ' +
      'Currently in A/B test phase on a second WhatsApp number.',
    bullets: [
      'Natural language product discovery & matching',
      'KB-grounded answers to product questions',
      'Automatic escalation when AI reaches its limit',
    ],
    available: false,
    comingSoon: true,
  },
]

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ toast, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 3500)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '12px 16px', borderRadius: 10,
      boxShadow: '0 4px 20px rgba(0,0,0,0.13)',
      fontSize: 13, fontWeight: 500,
      background: toast.type === 'success' ? '#0e6c7e' : '#dc2626',
      color: 'white',
      animation: 'slideUp 0.2s ease-out',
    }}>
      {toast.type === 'success' ? <IconCheck /> : <IconWarning />}
      {toast.message}
    </div>
  )
}

// ─── Mode card ────────────────────────────────────────────────────────────────

function ModeCard({ mode, selected, onSelect, saving, isMobile }) {
  const isSelected = selected === mode.key
  const disabled   = !mode.available || saving

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => !disabled && onSelect(mode.key)}
      style={{
        display: 'block', width: '100%', textAlign: 'left',
        background: isSelected ? mode.bgLight : 'white',
        border: `2px solid ${isSelected ? mode.borderActive : '#e2e8f0'}`,
        borderRadius: 14,
        padding: isMobile ? '14px' : '20px 22px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: mode.comingSoon ? 0.55 : 1,
        transition: 'border-color 0.15s, background 0.15s, box-shadow 0.15s',
        boxShadow: isSelected ? `0 0 0 3px ${mode.borderActive}22` : '0 1px 3px rgba(0,0,0,0.06)',
        position: 'relative',
        minHeight: 44,                          // Section 13.3 — 44px tap target minimum
        WebkitTapHighlightColor: 'transparent', // clean tap on iOS
      }}
    >
      {/* Coming soon badge */}
      {mode.comingSoon && (
        <span style={{
          position: 'absolute', top: 12, right: 12,
          background: '#fef3c7', color: '#92400e',
          fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
          textTransform: 'uppercase', padding: '3px 8px', borderRadius: 20,
          border: '1px solid #fde68a',
        }}>
          Coming soon
        </span>
      )}

      {/* Header row */}
      <div style={{
        display: 'flex', alignItems: 'flex-start',
        gap: isMobile ? 10 : 14, marginBottom: 10,
      }}>
        <div style={{
          width: 42, height: 42, borderRadius: 10, flexShrink: 0,
          background: isSelected ? mode.color : '#f1f5f9',
          color: isSelected ? 'white' : '#64748b',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'background 0.15s, color 0.15s',
        }}>
          {mode.icon}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{
              fontFamily: "'DM Sans', sans-serif", fontWeight: 700,
              fontSize: isMobile ? 14 : 15,
              color: isSelected ? mode.color : '#0f172a',
            }}>
              {mode.label}
            </span>
            {isSelected && (
              <span style={{
                background: mode.color, color: 'white',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
                textTransform: 'uppercase', padding: '2px 8px', borderRadius: 20,
              }}>
                Active
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            {mode.tagline}
          </div>
        </div>
      </div>

      {/* Description — collapsed on mobile when not selected to reduce scroll */}
      {(!isMobile || isSelected) && (
        <p style={{
          fontSize: 13, color: '#475569', lineHeight: 1.6,
          margin: '0 0 10px',
          paddingLeft: isMobile ? 0 : 52,
        }}>
          {mode.description}
        </p>
      )}

      {/* Bullets */}
      <ul style={{
        margin: 0,
        padding: `0 0 0 ${isMobile ? 0 : 52}px`,
        listStyle: 'none',
      }}>
        {mode.bullets.map((b, i) => (
          <li key={i} style={{
            display: 'flex', alignItems: 'flex-start', gap: 8,
            fontSize: isMobile ? 12 : 12.5,
            color: isSelected ? mode.color : '#64748b',
            marginBottom: i < mode.bullets.length - 1 ? 5 : 0,
          }}>
            <span style={{
              width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
              background: isSelected ? mode.color : '#94a3b8',
              marginTop: 6,
            }} />
            {b}
          </li>
        ))}
      </ul>

      {mode.requiresCommerce && !isSelected && (
        <p style={{
          fontSize: 11.5, color: '#7c3aed',
          marginTop: 10,
          paddingLeft: isMobile ? 0 : 52,
          fontStyle: 'italic',
        }}>
          Requires Shopify connected + Commerce enabled
        </p>
      )}
    </button>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function WASalesModeConfig() {
  const isMobile = useIsMobile()   // Section 13.3 — mandatory hook

  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [toast, setToast]     = useState(null)

  const [savedMode, setSavedMode] = useState('human')
  const [selected, setSelected]   = useState('human')

  const isDirty = selected !== savedMode

  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type })
  }, [])

  // ── Load ───────────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getWASalesMode()
      .then(data => {
        if (cancelled) return
        const m = data?.mode ?? 'human'
        setSavedMode(m)
        setSelected(m)
      })
      .catch(() => {
        if (!cancelled) showToast('Failed to load WhatsApp sales mode', 'error')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [showToast])

  // ── Save ───────────────────────────────────────────────────────────────────

  async function handleSave() {
    if (!isDirty || saving) return
    setSaving(true)
    try {
      await updateWASalesMode(selected)
      setSavedMode(selected)
      showToast('WhatsApp sales mode saved')
    } catch (err) {
      setSelected(savedMode)
      const detail = err?.response?.data?.detail
      const msg =
        (typeof detail === 'object' ? detail?.message : detail)
        ?? 'Failed to save. Please try again.'
      showToast(msg, 'error')
    } finally {
      setSaving(false)
    }
  }

  function handleDiscard() {
    setSelected(savedMode)
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          border: '4px solid #0e6c7e', borderTopColor: 'transparent',
          animation: 'spin 0.7s linear infinite',
        }} />
      </div>
    )
  }

  // Bottom padding must clear: save bar height + PWA bottom tab bar on mobile.
  // Save bar: ~72px desktop, ~130px mobile (stacked buttons).
  // PWA tab bar: ~56px on mobile — covered by env(safe-area-inset-bottom) in the bar itself.
  const contentPaddingBottom = isDirty ? (isMobile ? 148 : 88) : (isMobile ? 24 : 32)

  return (
    <div style={{ maxWidth: 680, margin: '0 auto', paddingBottom: contentPaddingBottom }}>

      {/* Toast — positioned above save bar */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: isDirty ? (isMobile ? 156 : 88) : 24,
          right: 16, zIndex: 50,
          maxWidth: 'calc(100vw - 32px)',
        }}>
          <Toast toast={toast} onDismiss={() => setToast(null)} />
        </div>
      )}

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center',
        gap: isMobile ? 10 : 14,
        marginBottom: isMobile ? 16 : 24,
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 10, flexShrink: 0,
          background: '#f0f9fa', color: '#0e6c7e',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}
            style={{ width: 22, height: 22 }}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
          </svg>
        </div>
        <div>
          <h2 style={{
            fontFamily: "'Syne', sans-serif", fontWeight: 700,
            fontSize: isMobile ? 15 : 17, color: '#0f172a', margin: 0,
          }}>
            WhatsApp Sales Mode
          </h2>
          <p style={{ fontSize: isMobile ? 12 : 13, color: '#64748b', margin: '3px 0 0' }}>
            Choose how sales conversations are handled when a contact expresses purchase intent
          </p>
        </div>
      </div>

      {/* Mode cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
        {MODES.map(mode => (
          <ModeCard
            key={mode.key}
            mode={mode}
            selected={selected}
            onSelect={setSelected}
            saving={saving}
            isMobile={isMobile}
          />
        ))}
      </div>

      {/* Behaviour summary */}
      {!isDirty && (
        <div style={{
          background: '#f8fafc', border: '1px solid #e2e8f0',
          borderRadius: 12, padding: isMobile ? '14px' : '16px 20px',
          fontSize: 13, color: '#475569', lineHeight: 1.6,
        }}>
          <span style={{ fontWeight: 600, color: '#0f172a' }}>Current behaviour: </span>
          {savedMode === 'human' &&
            'When a lead or customer expresses purchase intent, the triage bot hands off to a sales rep. The rep manages the conversation manually in WhatsApp.'}
          {savedMode === 'bot' &&
            'When purchase intent is detected, the bot sends an interactive product list. The contact adds to cart and receives a Shopify checkout link automatically.'}
          {savedMode === 'ai_agent' &&
            'The AI agent handles the sales conversation end-to-end — discovering needs, matching products, and building the cart — escalating to a rep when it reaches its limit.'}
        </div>
      )}

      {/* ── Save bar ─────────────────────────────────────────────────────── */}
      {isDirty && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 40,
          display: 'flex',
          // Mobile: stack buttons vertically so each is full-width ≥ 44px
          flexDirection: isMobile ? 'column' : 'row',
          alignItems: isMobile ? 'stretch' : 'center',
          justifyContent: isMobile ? 'flex-end' : 'space-between',
          gap: isMobile ? 8 : 16,
          padding: isMobile ? '12px 16px' : '14px 24px',
          // env(safe-area-inset-bottom) clears the PWA home indicator on iOS
          // and the bottom tab bar on Android in standalone mode (Section 13.3)
          paddingBottom: isMobile
            ? 'calc(12px + env(safe-area-inset-bottom, 56px))'
            : '14px',
          background: 'white',
          borderTop: '1px solid #e2e8f0',
          boxShadow: '0 -4px 20px rgba(0,0,0,0.07)',
        }}>
          {!isMobile && (
            <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
              You have unsaved changes
            </p>
          )}
          <div style={{
            display: 'flex',
            flexDirection: isMobile ? 'column' : 'row',
            gap: isMobile ? 8 : 10,
          }}>
            {/* Discard — 44px min height (Section 13.3) */}
            <button
              type="button"
              onClick={handleDiscard}
              disabled={saving}
              style={{
                minHeight: 44, padding: isMobile ? '0 18px' : '9px 18px',
                borderRadius: 8, border: 'none',
                background: '#f1f5f9', color: '#475569',
                fontSize: 13, fontWeight: 500, cursor: 'pointer',
                opacity: saving ? 0.5 : 1,
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              Discard
            </button>

            {/* Save — 44px min height (Section 13.3) */}
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                minHeight: 44, padding: isMobile ? '0 20px' : '9px 20px',
                borderRadius: 8, border: 'none',
                background: '#0e6c7e', color: 'white',
                fontSize: 13, fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
                opacity: saving ? 0.7 : 1,
                boxShadow: '0 1px 4px rgba(14,108,126,0.3)',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              {saving ? (
                <>
                  <span style={{
                    width: 14, height: 14, borderRadius: '50%',
                    border: '2px solid white', borderTopColor: 'transparent',
                    animation: 'spin 0.7s linear infinite',
                    display: 'inline-block', flexShrink: 0,
                  }} />
                  Saving…
                </>
              ) : (
                <>
                  <IconCheck />
                  Save changes
                </>
              )}
            </button>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin    { to { transform: rotate(360deg); } }
        @keyframes slideUp { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
      `}</style>
    </div>
  )
}
