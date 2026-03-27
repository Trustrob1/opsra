/**
 * LeadScoreButton
 *
 * Calls POST /api/v1/leads/{id}/score (Claude AI scoring).
 * Shows spinner while pending, then displays score + reason.
 * On graceful degradation (AI unavailable), backend returns score='unscored'
 * with a reason explaining the degradation — this component renders it faithfully.
 */
import { useState } from 'react'
import { scoreLead } from '../../services/leads.service'
import { ds, SCORE_STYLE } from '../../utils/ds'

export default function LeadScoreButton({ leadId, currentScore, currentReason, onScored }) {
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [result, setResult]     = useState(null)

  const scoreStyle = SCORE_STYLE[result?.score ?? currentScore] ?? SCORE_STYLE.unscored

  const handleScore = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await scoreLead(leadId)
      if (res.success) {
        setResult(res.data)
        onScored?.(res.data)
      } else {
        setError(res.error ?? 'Scoring failed')
      }
    } catch (err) {
      setError(err?.response?.data?.error ?? 'Scoring temporarily unavailable')
    } finally {
      setLoading(false)
    }
  }

  const displayScore  = result?.score       ?? currentScore  ?? 'unscored'
  const displayReason = result?.score_reason ?? currentReason ?? null

  return (
    <div>
      {/* Current badge + trigger button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {/* Score badge */}
        <span style={{
          background: scoreStyle.bg,
          color:      scoreStyle.color,
          padding:    '4px 12px',
          borderRadius: 20,
          fontSize:   12,
          fontWeight: 700,
          fontFamily: ds.fontSyne,
        }}>
          {scoreStyle.label}
        </span>

        {/* Trigger / regenerate button */}
        <button
          onClick={handleScore}
          disabled={loading}
          style={{
            display:      'inline-flex',
            alignItems:   'center',
            gap:          6,
            padding:      '7px 14px',
            borderRadius: 9,
            border:       `1.5px solid ${ds.teal}`,
            background:   loading ? '#f0f0f0' : 'white',
            color:        ds.teal,
            fontSize:     12,
            fontWeight:   600,
            fontFamily:   ds.fontSyne,
            cursor:       loading ? 'not-allowed' : 'pointer',
            transition:   'all 0.15s',
          }}
        >
          {loading ? (
            <>
              <Spinner />
              Scoring…
            </>
          ) : (
            <>
              🤖 {displayScore === 'unscored' ? 'Score with AI' : 'Regenerate Score'}
            </>
          )}
        </button>
      </div>

      {/* Score reason — shown after scoring or if one already exists */}
      {displayReason && (
        <div style={{
          marginTop:    10,
          background:   '#F0FAF9',
          border:       `1.5px solid #B0DDD9`,
          borderRadius: 10,
          padding:      '12px 14px',
          fontSize:     13,
          color:        ds.dark,
          lineHeight:   1.6,
          position:     'relative',
        }}>
          {/* AI badge */}
          <span style={{
            position:     'absolute',
            top:          -10,
            left:         12,
            background:   ds.teal,
            color:        'white',
            fontSize:     10,
            fontWeight:   600,
            padding:      '2px 10px',
            borderRadius: 20,
            fontFamily:   ds.fontSyne,
            letterSpacing: '0.5px',
          }}>
            AI Reasoning
          </span>
          {displayReason}
        </div>
      )}

      {/* Error state */}
      {error && (
        <p style={{ marginTop: 8, fontSize: 12, color: ds.red }}>
          ⚠ {error}
        </p>
      )}
    </div>
  )
}

function Spinner() {
  return (
    <span style={{
      display:      'inline-block',
      width:        14,
      height:       14,
      border:       `2px solid rgba(2,128,144,0.2)`,
      borderTop:    `2px solid ${ds.teal}`,
      borderRadius: '50%',
      animation:    'spin 0.7s linear infinite',
      flexShrink:   0,
    }} />
  )
}
