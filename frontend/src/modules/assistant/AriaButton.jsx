/**
 * frontend/src/modules/assistant/AriaButton.jsx
 * -----------------------------------------------
 * Aria FAB (floating action button).
 *
 * CONV-UI additions:
 *   - view prop: hides the FAB when in Conversations (thread header has its own trigger)
 *   - minimised / onMinimise props: FAB can be collapsed to a compact dark button so it
 *     never blocks the send button or other UI elements.
 *
 * Props:
 *   onClick      {function}  Toggle the Aria panel open/closed
 *   hasBadge     {boolean}   Show the unread briefing badge dot
 *   panelOpen    {boolean}   Panel is currently open (FAB hides when open)
 *   view         {string}    Current app view — FAB hidden when 'conversations'
 *   minimised    {boolean}   Compact mode — smaller, darker, non-blocking
 *   onMinimise   {function}  Toggle minimised state (persisted in App via localStorage)
 */

import { ds } from '../../utils/ds'

export default function AriaButton({ onClick, hasBadge, panelOpen, view, minimised, onMinimise }) {
  // Hide when panel is open — panel header has its own close button
  if (panelOpen) return null

  // Hide in Conversations — the thread header has a dedicated "✦ Ask Aria" trigger
  if (view === 'conversations') return null

  // ── Minimised state — compact dark button, non-blocking ────────────────
  if (minimised) {
    return (
      <div style={{ position: 'fixed', bottom: 24, right: 24, zIndex: (ds.z?.modal ?? 1100) + 1 }}>
        <button
          onClick={onClick}
          title="Open Aria — AI Assistant"
          style={{
            width:          36,
            height:         36,
            borderRadius:   '50%',
            background:     '#0e2030',
            border:         '1px solid #2a4a5a',
            cursor:         'pointer',
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            transition:     'border-color 0.15s',
            flexShrink:     0,
          }}
          onMouseEnter={e => e.currentTarget.style.borderColor = ds.teal}
          onMouseLeave={e => e.currentTarget.style.borderColor = '#2a4a5a'}
        >
          <span style={{ fontSize: 15, color: '#7A9BAD', lineHeight: 1 }}>✦</span>

          {hasBadge && (
            <span style={{
              position: 'absolute', top: 2, right: 2,
              width: 9, height: 9, borderRadius: '50%',
              background: '#ef4444', border: '2px solid #0a1a24',
              animation: 'pulse-badge 2s ease-in-out infinite',
            }} />
          )}
        </button>

        {/* Restore to full FAB */}
        <button
          onClick={(e) => { e.stopPropagation(); onMinimise?.() }}
          title="Restore Aria button"
          style={{
            position: 'absolute', top: -6, right: -6,
            width: 16, height: 16, borderRadius: '50%',
            background: '#1a3040', border: '1px solid #2a4a5a',
            cursor: 'pointer', display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: 10, color: '#7A9BAD', lineHeight: 1, padding: 0,
          }}
          onMouseEnter={e => { e.currentTarget.style.background = ds.teal; e.currentTarget.style.color = 'white' }}
          onMouseLeave={e => { e.currentTarget.style.background = '#1a3040'; e.currentTarget.style.color = '#7A9BAD' }}
        >
          +
        </button>
      </div>
    )
  }

  // ── Full FAB ───────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'fixed', bottom: 28, right: 28, zIndex: (ds.z?.modal ?? 1100) + 1 }}>
      <button
        onClick={onClick}
        title="Open Aria — AI Assistant"
        style={{
          width: 52, height: 52, borderRadius: '50%',
          background: `linear-gradient(135deg, ${ds.teal}, #0097a7)`,
          border: 'none', boxShadow: '0 4px 20px rgba(0,188,212,0.4)',
          cursor: 'pointer', display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          transition: 'box-shadow 0.2s', flexShrink: 0,
        }}
        onMouseEnter={e => e.currentTarget.style.boxShadow = '0 6px 28px rgba(0,188,212,0.6)'}
        onMouseLeave={e => e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,188,212,0.4)'}
      >
        <span style={{ fontSize: 22, color: 'white', lineHeight: 1 }}>✦</span>

        {hasBadge && (
          <span style={{
            position: 'absolute', top: 4, right: 4,
            width: 11, height: 11, borderRadius: '50%',
            background: '#ef4444', border: '2px solid #0a1a24',
            animation: 'pulse-badge 2s ease-in-out infinite',
          }} />
        )}
      </button>

      {/* Minimise — collapses FAB to compact form */}
      <button
        onClick={(e) => { e.stopPropagation(); onMinimise?.() }}
        title="Minimise Aria button"
        style={{
          position: 'absolute', top: -4, right: -4,
          width: 18, height: 18, borderRadius: '50%',
          background: '#1a3040', border: '1px solid #2a4a5a',
          cursor: 'pointer', display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          fontSize: 11, color: '#7A9BAD', lineHeight: 1, padding: 0,
        }}
        onMouseEnter={e => { e.currentTarget.style.background = '#2a4a5a'; e.currentTarget.style.color = 'white' }}
        onMouseLeave={e => { e.currentTarget.style.background = '#1a3040'; e.currentTarget.style.color = '#7A9BAD' }}
      >
        −
      </button>
    </div>
  )
}
