/**
 * frontend/src/modules/assistant/BriefingCard.jsx
 * -------------------------------------------------
 * Morning briefing formatted card displayed as the first Aria message.
 *
 * Rendered inside AriaPanel when a new day's briefing is available.
 * Shows structured briefing text with a greeting, bullet points, and
 * action buttons ("Let's go" / "Skip").
 *
 * Props:
 *   content  {string}    Raw briefing text from Haiku
 *   onAccept {function}  Called when "Let's go" clicked
 *   onDismiss {function} Called when "Skip" clicked
 */

import { ds } from '../../utils/ds'

export default function BriefingCard({ content, onAccept, onDismiss }) {
  // Split content into lines for structured rendering
  const lines = (content || '').split('\n').filter(l => l.trim())

  return (
    <div style={{
      background:   'linear-gradient(135deg, rgba(0,188,212,0.12) 0%, rgba(0,188,212,0.04) 100%)',
      border:       `1px solid ${ds.teal}44`,
      borderRadius: 12,
      padding:      '16px 18px',
      marginBottom: 4,
    }}>
      {/* Aria badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%',
          background: ds.teal,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14,
        }}>
          ✦
        </div>
        <span style={{
          fontFamily: ds.fontSyne,
          fontWeight: 700,
          fontSize:   13,
          color:      ds.teal,
          letterSpacing: '0.5px',
        }}>
          Morning Briefing
        </span>
        <span style={{ fontSize: 10, color: '#3a5a6a', marginLeft: 'auto' }}>
          Today
        </span>
      </div>

      {/* Content lines */}
      <div style={{ fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.65, color: '#c8dde8' }}>
        {lines.map((line, i) => {
          const isBullet = line.trim().startsWith('•') || line.trim().startsWith('-') || /^\d+\./.test(line.trim())

          return (
            <div
              key={i}
              style={{
                display:      isBullet ? 'flex' : 'block',
                gap:          isBullet ? 8 : 0,
                alignItems:   'flex-start',
                marginBottom: 6,
                paddingLeft:  isBullet ? 0 : 0,
              }}
            >
              {isBullet && (
                <span style={{ color: ds.teal, flexShrink: 0, marginTop: 1 }}>▸</span>
              )}
              <span style={{ fontWeight: i === 0 ? 500 : 400 }}>
                {line.replace(/^[-•]\s*/, '').replace(/^\d+\.\s*/, '')}
              </span>
            </div>
          )
        })}
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <button
          onClick={onAccept}
          style={{
            flex:         1,
            background:   ds.teal,
            border:       'none',
            borderRadius: 8,
            padding:      '9px 0',
            fontSize:     13,
            fontWeight:   600,
            color:        'white',
            fontFamily:   ds.fontDm,
            cursor:       'pointer',
            transition:   'opacity 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
          onMouseLeave={e => e.currentTarget.style.opacity = '1'}
        >
          Let's go ✦
        </button>
        <button
          onClick={onDismiss}
          style={{
            background:   'transparent',
            border:       '1px solid #2a4a5a',
            borderRadius: 8,
            padding:      '9px 16px',
            fontSize:     13,
            color:        '#7A9BAD',
            fontFamily:   ds.fontDm,
            cursor:       'pointer',
            transition:   'border-color 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.borderColor = ds.teal}
          onMouseLeave={e => e.currentTarget.style.borderColor = '#2a4a5a'}
        >
          Skip
        </button>
      </div>
    </div>
  )
}
