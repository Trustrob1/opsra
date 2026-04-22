/**
 * frontend/src/modules/admin/PipelineConfig.jsx
 * CONFIG-6 — Org-configurable pipeline stage labels and visibility.
 *
 * - Lists 5 configurable stages (new + converted locked always-enabled)
 * - Per stage: editable label, enabled toggle, locked indicator
 * - Up/down reorder buttons — order determines Kanban column order
 * - Live preview of what the Kanban pipeline will look like
 * - Reset to defaults button
 *
 * Pattern 50: axios + _h() via admin.service.js only.
 * Pattern 51: full rewrite only, never sed.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getPipelineStages, updatePipelineStages } from '../../services/admin.service'

const LOCKED_KEYS = new Set(['new', 'converted'])

const DEFAULT_STAGES = [
  { key: 'new',           label: 'New Lead',      enabled: true  },
  { key: 'contacted',     label: 'Contacted',     enabled: true  },
  { key: 'meeting_done',  label: 'Demo Done',     enabled: true  },
  { key: 'proposal_sent', label: 'Proposal Sent', enabled: true  },
  { key: 'converted',     label: 'Converted',     enabled: true  },
]

// Dot colours matching the existing Kanban palette
const STAGE_DOT = {
  new:           '#7A9BAD',
  contacted:     '#3b82f6',
  meeting_done:  '#8b5cf6',
  proposal_sent: '#f59e0b',
  converted:     '#10b981',
  lost:          '#ef4444',
  not_ready:     '#6b7280',
}

export default function PipelineConfig() {
  const [stages,  setStages]  = useState(null)   // null = loading
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState(null)
  const [success, setSuccess] = useState(false)

  // ── Load ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    getPipelineStages()
      .then(data => setStages(data.stages ?? DEFAULT_STAGES))
      .catch(() => setStages([...DEFAULT_STAGES]))
  }, [])

  // ── Helpers ───────────────────────────────────────────────────────────────

  function updateLabel(idx, value) {
    setStages(prev => prev.map((s, i) => i === idx ? { ...s, label: value } : s))
    setSuccess(false)
  }

  function toggleEnabled(idx) {
    setStages(prev => prev.map((s, i) => {
      if (i !== idx) return s
      if (LOCKED_KEYS.has(s.key)) return s   // locked — ignore
      return { ...s, enabled: !s.enabled }
    }))
    setSuccess(false)
  }

  function moveUp(idx) {
    if (idx === 0) return
    setStages(prev => {
      const next = [...prev]
      ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
      return next
    })
    setSuccess(false)
  }

  function moveDown(idx) {
    if (!stages || idx === stages.length - 1) return
    setStages(prev => {
      const next = [...prev]
      ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
      return next
    })
    setSuccess(false)
  }

  function resetToDefaults() {
    setStages([...DEFAULT_STAGES])
    setSuccess(false)
    setError(null)
  }

  async function handleSave() {
    if (!stages) return
    // Validate: no empty labels
    const invalid = stages.find(s => !s.label || !s.label.trim())
    if (invalid) {
      setError('All stage labels are required.')
      return
    }
    const tooLong = stages.find(s => s.label.trim().length > 50)
    if (tooLong) {
      setError(`Label "${tooLong.label}" exceeds 50 characters.`)
      return
    }
    const enabledCount = stages.filter(s => s.enabled).length
    if (enabledCount < 2) {
      setError('At least 2 stages must be enabled.')
      return
    }

    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      await updatePipelineStages({ stages })
      setSuccess(true)
    } catch (e) {
      const msg = e?.response?.data?.detail?.message
        || e?.response?.data?.detail
        || 'Failed to save. Please try again.'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setSaving(false)
    }
  }

  // ── Loading ───────────────────────────────────────────────────────────────

  if (!stages) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
        <div style={{ fontSize: 22, marginBottom: 8 }}>🗂️</div>
        Loading pipeline config…
      </div>
    )
  }

  // ── Preview (enabled stages only) ────────────────────────────────────────

  const previewStages = stages.filter(s => s.enabled)

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ maxWidth: 780 }}>

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18,
          color: '#0a1a24', margin: '0 0 6px',
        }}>
          🗂️ Pipeline Stage Configuration
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0 }}>
          Customise stage labels and visibility for your organisation's lead pipeline.
          The order here determines the Kanban column order.
        </p>
      </div>

      {/* Stage editor */}
      <div style={{
        background: 'white',
        border: '1px solid #d4e5ee',
        borderRadius: 10,
        overflow: 'hidden',
        marginBottom: 24,
      }}>

        {/* Column headers */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '32px 1fr 160px 80px 64px',
          gap: 0,
          background: '#f0f6f9',
          borderBottom: '1px solid #d4e5ee',
          padding: '8px 16px',
          alignItems: 'center',
        }}>
          <span />
          <span style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Stage Label
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            System Key
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.06em', textAlign: 'center' }}>
            Enabled
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.06em', textAlign: 'center' }}>
            Order
          </span>
        </div>

        {stages.map((stage, idx) => {
          const isLocked = LOCKED_KEYS.has(stage.key)
          return (
            <div
              key={stage.key}
              style={{
                display: 'grid',
                gridTemplateColumns: '32px 1fr 160px 80px 64px',
                gap: 0,
                padding: '12px 16px',
                borderBottom: idx < stages.length - 1 ? '1px solid #edf3f7' : 'none',
                alignItems: 'center',
                background: stage.enabled ? 'white' : '#f9fbfc',
                transition: 'background 0.15s',
              }}
            >
              {/* Dot */}
              <div style={{
                width: 9, height: 9, borderRadius: '50%',
                background: stage.enabled ? (STAGE_DOT[stage.key] || ds.teal) : '#c8d8e4',
                flexShrink: 0,
              }} />

              {/* Label input */}
              <div style={{ paddingRight: 16 }}>
                <input
                  value={stage.label}
                  onChange={e => updateLabel(idx, e.target.value)}
                  maxLength={50}
                  disabled={!stage.enabled}
                  style={{
                    width: '100%',
                    border: '1px solid #d4e5ee',
                    borderRadius: 6,
                    padding: '6px 10px',
                    fontSize: 13,
                    fontFamily: ds.fontDm,
                    color: stage.enabled ? '#0a1a24' : '#9ab0bc',
                    background: stage.enabled ? 'white' : '#f0f6f9',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              {/* System key */}
              <div style={{ paddingRight: 16 }}>
                <span style={{
                  fontFamily: 'monospace',
                  fontSize: 11,
                  background: '#edf3f7',
                  color: '#4a7a8a',
                  padding: '3px 8px',
                  borderRadius: 4,
                  whiteSpace: 'nowrap',
                }}>
                  {stage.key}
                </span>
                {isLocked && (
                  <span style={{ marginLeft: 6, fontSize: 10, color: '#9ab0bc' }}>🔒</span>
                )}
              </div>

              {/* Enabled toggle */}
              <div style={{ textAlign: 'center' }}>
                <button
                  onClick={() => toggleEnabled(idx)}
                  disabled={isLocked}
                  title={isLocked ? 'This stage is always enabled' : (stage.enabled ? 'Disable stage' : 'Enable stage')}
                  style={{
                    width: 36, height: 20,
                    borderRadius: 10,
                    border: 'none',
                    cursor: isLocked ? 'not-allowed' : 'pointer',
                    background: stage.enabled ? ds.teal : '#c8d8e4',
                    position: 'relative',
                    transition: 'background 0.2s',
                    flexShrink: 0,
                    opacity: isLocked ? 0.5 : 1,
                  }}
                >
                  <span style={{
                    position: 'absolute',
                    top: 2, left: stage.enabled ? 18 : 2,
                    width: 16, height: 16,
                    borderRadius: '50%',
                    background: 'white',
                    transition: 'left 0.2s',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }} />
                </button>
              </div>

              {/* Order buttons */}
              <div style={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
                <button
                  onClick={() => moveUp(idx)}
                  disabled={idx === 0}
                  style={arrowBtnStyle(idx === 0)}
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  onClick={() => moveDown(idx)}
                  disabled={idx === stages.length - 1}
                  style={arrowBtnStyle(idx === stages.length - 1)}
                  title="Move down"
                >
                  ↓
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Live preview */}
      <div style={{ marginBottom: 24 }}>
        <p style={{ fontSize: 12, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Kanban Preview
        </p>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {previewStages.map((s, i) => (
            <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'white', border: '1px solid #d4e5ee',
                borderRadius: 8, padding: '6px 12px',
                fontSize: 12, fontFamily: ds.fontDm, color: '#0a1a24', fontWeight: 600,
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%',
                  background: STAGE_DOT[s.key] || ds.teal, flexShrink: 0,
                }} />
                {s.label || s.key}
              </div>
              {i < previewStages.length - 1 && (
                <span style={{ color: '#c8d8e4', fontSize: 14 }}>→</span>
              )}
            </div>
          ))}
          {/* lost + not_ready always present */}
          <span style={{ color: '#c8d8e4', fontSize: 14 }}>|</span>
          {[{ key: 'lost', label: 'Lost' }, { key: 'not_ready', label: 'Not Ready' }].map(s => (
            <div key={s.key} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: '#f9fbfc', border: '1px solid #e4edf2',
              borderRadius: 8, padding: '6px 12px',
              fontSize: 12, fontFamily: ds.fontDm, color: '#7A9BAD', fontStyle: 'italic',
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%',
                background: STAGE_DOT[s.key], flexShrink: 0,
              }} />
              {s.label}
            </div>
          ))}
        </div>
        <p style={{ fontSize: 11, color: '#9ab0bc', marginTop: 8 }}>
          Lost and Not Ready are system stages — always visible, cannot be disabled.
        </p>
      </div>

      {/* Feedback */}
      {error && (
        <div style={{
          marginBottom: 16, padding: '10px 14px',
          background: '#fef2f2', border: '1px solid #fca5a5',
          borderRadius: 8, fontSize: 13, color: '#b91c1c',
        }}>
          {error}
        </div>
      )}
      {success && (
        <div style={{
          marginBottom: 16, padding: '10px 14px',
          background: '#f0fdf4', border: '1px solid #86efac',
          borderRadius: 8, fontSize: 13, color: '#15803d',
        }}>
          ✅ Pipeline stages saved successfully.
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: saving ? '#7A9BAD' : ds.teal,
            color: 'white',
            border: 'none',
            borderRadius: 8,
            padding: '9px 22px',
            fontSize: 13,
            fontFamily: ds.fontDm,
            fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        <button
          onClick={resetToDefaults}
          disabled={saving}
          style={{
            background: 'none',
            color: '#4a7a8a',
            border: '1px solid #d4e5ee',
            borderRadius: 8,
            padding: '8px 18px',
            fontSize: 13,
            fontFamily: ds.fontDm,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          Reset to Defaults
        </button>
      </div>
    </div>
  )
}

function arrowBtnStyle(disabled) {
  return {
    background: 'none',
    border: '1px solid #d4e5ee',
    borderRadius: 4,
    width: 24, height: 24,
    fontSize: 12,
    cursor: disabled ? 'not-allowed' : 'pointer',
    color: disabled ? '#c8d8e4' : '#4a7a8a',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    lineHeight: 1,
  }
}
