/**
 * frontend/src/modules/assistant/AriaButton.jsx
 * -----------------------------------------------
 * Aria FAB (floating action button) — always visible in bottom-right corner.
 * Shows a badge dot when a new briefing is available.
 *
 * Props:
 *   onClick     {function}   Toggle the Aria panel
 *   hasBadge    {boolean}    Whether to show the unread badge
 *   panelOpen   {boolean}    Whether panel is currently open (affects icon)
 */

import { ds } from '../../utils/ds'

export default function AriaButton({ onClick, hasBadge, panelOpen }) {
  // Hide the FAB when the panel is open — the panel header already has a close
  // button, and the FAB would overlap the suggestions tray at the panel bottom.
  if (panelOpen) return null

  return (
    <button
      onClick={onClick}
      title="Open Aria — AI Assistant"
      style={{
        position:       'fixed',
        bottom:         28,
        right:          28,
        width:          52,
        height:         52,
        borderRadius:   '50%',
        background:     `linear-gradient(135deg, ${ds.teal}, #0097a7)`,
        border:         'none',
        boxShadow:      '0 4px 20px rgba(0,188,212,0.4)',
        cursor:         'pointer',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        zIndex:         (ds.z.modal ?? 1100) + 1,
        transition:     'box-shadow 0.2s',
        flexShrink:     0,
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 6px 28px rgba(0,188,212,0.6)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,188,212,0.4)'}
    >
      {/* Icon */}
      <span style={{ fontSize: 22, color: 'white', lineHeight: 1 }}>✦</span>

      {/* Badge dot — shown when a new briefing is available */}
      {hasBadge && (
        <span style={{
          position:     'absolute',
          top:          4,
          right:        4,
          width:        11,
          height:       11,
          borderRadius: '50%',
          background:   '#ef4444',
          border:       '2px solid #0a1a24',
          animation:    'pulse-badge 2s ease-in-out infinite',
        }} />
      )}
    </button>
  )
}
