/**
 * frontend/src/modules/admin/GrowthDashboardConfig.jsx
 * GROWTH-DASH-CONFIG — Admin settings panel for configurable Growth Dashboard.
 *
 * Lists all 8 sections with name, description, and visible/hidden toggle.
 * overview and pipeline_at_risk: always-on, toggle disabled + tooltip.
 * channels: contextual warning about CAC/spend data requirement.
 * Save → PATCH /api/v1/admin/growth-dashboard-config.
 *
 * Pattern 50: axios + _h() + ${BASE} prefix.
 * Pattern 51: full rewrite only.
 * Mobile-first: stacks to single column below 768px (Section 13.3).
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getGrowthDashboardConfig, updateGrowthDashboardConfig } from '../../services/admin.service'

const SECTION_META = [
  {
    key:         'overview',
    title:       '📊 Executive Overview',
    description: 'KPI cards showing total revenue, leads, conversion rate, CAC, and avg close time. Always shown.',
    alwaysOn:    true,
  },
  {
    key:         'team_performance',
    title:       '👥 Team Performance',
    description: 'Leads, conversion rate, and revenue per growth team. Hide for single-team or rep-only orgs.',
    alwaysOn:    false,
  },
  {
    key:         'funnel',
    title:       '🔽 Funnel Breakdown',
    description: 'Stage-by-stage conversion rates from New Lead to Closed. Useful for all pipeline orgs.',
    alwaysOn:    false,
  },
  {
    key:         'velocity',
    title:       '📈 Lead Velocity',
    description: 'Week-by-week lead volume trend chart. Shows momentum over the selected period.',
    alwaysOn:    false,
  },
  {
    key:         'pipeline_at_risk',
    title:       '⚠️ Pipeline at Risk',
    description: 'Leads that have gone silent or are overdue for follow-up. Always shown.',
    alwaysOn:    true,
  },
  {
    key:         'sales_reps',
    title:       '🏆 Sales Rep Leaderboard',
    description: 'Per-rep conversion rates and deal values. Hide for single-rep organisations.',
    alwaysOn:    false,
  },
  {
    key:         'channels',
    title:       '📡 Channel Performance',
    description: 'Lead volume, conversion, and CAC by acquisition channel. Hide if no ad spend is tracked.',
    alwaysOn:    false,
    warning:     'CAC and spend data only appear if campaign spend is logged in Growth Config. Without spend entries, these columns will always be empty.',
  },
  {
    key:         'win_loss',
    title:       '🎯 Win / Loss Analysis',
    description: 'Lost lead reasons and win rate breakdown. Relevant for all orgs with any pipeline activity.',
    alwaysOn:    false,
  },
]

const DEFAULT_SECTIONS = SECTION_META.map(s => ({ key: s.key, visible: true }))

export default function GrowthDashboardConfig() {
  const [sections, setSections] = useState(DEFAULT_SECTIONS)
  const [loading,  setLoading]  = useState(true)
  const [saving,   setSaving]   = useState(false)
  const [saved,    setSaved]    = useState(false)
  const [error,    setError]    = useState(null)

  useEffect(() => {
    getGrowthDashboardConfig()
      .then(data => {
        if (data?.sections?.length) setSections(data.sections)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const toggleSection = useCallback((key) => {
    setSections(prev => prev.map(s =>
      s.key === key ? { ...s, visible: !s.visible } : s
    ))
    setSaved(false)
  }, [])

  const resetToDefaults = () => {
    setSections(DEFAULT_SECTIONS)
    setSaved(false)
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      await updateGrowthDashboardConfig({ sections })
      setSaved(true)
    } catch (err) {
      const msg = err?.response?.data?.detail?.message
        || err?.response?.data?.detail
        || 'Failed to save. Please try again.'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setSaving(false)
    }
  }

  // Build visibility lookup
  const visibilityMap = Object.fromEntries(sections.map(s => [s.key, s.visible]))

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: ds.gray, fontSize: 14 }}>
        Loading dashboard configuration…
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: '0 0 6px' }}>
          📊 Growth Dashboard Configuration
        </h2>
        <p style={{ fontSize: 13.5, color: ds.gray, margin: 0, lineHeight: 1.5 }}>
          Control which sections appear on the Growth Dashboard for your organisation.
          Hidden sections are not fetched — no wasted compute.
        </p>
      </div>

      {/* Main layout: config + preview */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) minmax(0,320px)',
        gap: 24,
        alignItems: 'start',
      }}
        className="growth-dash-config-grid"
      >
        {/* ── Left: section list ── */}
        <div>
          <div style={sectionCard}>
            <div style={sectionTitle}>Dashboard Sections</div>
            <p style={sectionDesc}>Toggle sections on or off. Greyed rows cannot be hidden.</p>

            {SECTION_META.map(meta => {
              const isVisible = visibilityMap[meta.key] !== false
              return (
                <div key={meta.key} style={{
                  ...rowStyle,
                  opacity: meta.alwaysOn ? 0.7 : 1,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: ds.fontDm, fontWeight: 600, fontSize: 13.5, color: ds.dark, marginBottom: 3 }}>
                      {meta.title}
                      {meta.alwaysOn && (
                        <span style={{ marginLeft: 8, fontSize: 11, color: ds.teal, fontWeight: 400 }}>
                          Always on
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 12.5, color: ds.gray, lineHeight: 1.5 }}>
                      {meta.description}
                    </div>
                    {meta.warning && isVisible && (
                      <div style={{
                        marginTop: 6,
                        fontSize: 12,
                        color: '#92400e',
                        background: '#fffbeb',
                        border: '1px solid #fcd34d',
                        borderRadius: 6,
                        padding: '6px 10px',
                        lineHeight: 1.5,
                      }}>
                        ⚠ {meta.warning}
                      </div>
                    )}
                  </div>
                  <div style={{ flexShrink: 0, marginLeft: 16 }}>
                    {meta.alwaysOn ? (
                      <span
                        title="This section cannot be hidden."
                        style={{
                          padding: '4px 12px',
                          borderRadius: 20,
                          fontSize: 12,
                          background: '#e8f5e9',
                          color: '#2e7d32',
                          fontFamily: ds.fontDm,
                          fontWeight: 600,
                          cursor: 'default',
                          border: '1.5px solid #a5d6a7',
                        }}
                      >
                        Visible
                      </span>
                    ) : (
                      <button
                        onClick={() => toggleSection(meta.key)}
                        style={{
                          padding: '4px 14px',
                          borderRadius: 20,
                          fontSize: 12,
                          fontFamily: ds.fontDm,
                          fontWeight: 600,
                          cursor: 'pointer',
                          minWidth: 72,
                          transition: 'all 0.15s',
                          border: `1.5px solid ${isVisible ? ds.teal : ds.border}`,
                          background: isVisible ? ds.teal + '18' : '#f1f5f9',
                          color: isVisible ? ds.teal : ds.gray,
                          minHeight: 44,
                        }}
                      >
                        {isVisible ? 'Visible' : 'Hidden'}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {error && (
            <div style={{ background: '#fff5f5', border: '1px solid #fed7d7', borderRadius: 8, padding: '10px 14px', marginBottom: 14, fontSize: 13, color: ds.red }}>
              ⚠ {error}
            </div>
          )}
          {saved && (
            <div style={{ background: '#f0fff4', border: '1px solid #9ae6b4', borderRadius: 8, padding: '10px 14px', marginBottom: 14, fontSize: 13, color: '#276749' }}>
              ✓ Configuration saved successfully
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button onClick={resetToDefaults} style={secondaryBtn}>Reset to Defaults</button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{ ...primaryBtn, opacity: saving ? 0.6 : 1, cursor: saving ? 'not-allowed' : 'pointer' }}
            >
              {saving ? 'Saving…' : 'Save Configuration'}
            </button>
          </div>
        </div>

        {/* ── Right: summary panel ── */}
        <div style={{ position: 'sticky', top: 20 }}>
          <div style={sectionCard}>
            <div style={sectionTitle}>Summary</div>
            <p style={sectionDesc}>Sections currently shown on the dashboard.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {SECTION_META.map(meta => {
                const isVisible = meta.alwaysOn || visibilityMap[meta.key] !== false
                return (
                  <div key={meta.key} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 10px',
                    borderRadius: 7,
                    background: isVisible ? '#f0fdf4' : '#f8fafc',
                    fontSize: 12.5,
                    fontFamily: ds.fontDm,
                    color: isVisible ? '#166534' : ds.gray,
                  }}>
                    <span style={{ fontSize: 13 }}>{isVisible ? '✓' : '○'}</span>
                    {meta.title}
                  </div>
                )
              })}
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: ds.gray, borderTop: `1px solid ${ds.border}`, paddingTop: 10 }}>
              {SECTION_META.filter(m => m.alwaysOn || visibilityMap[m.key] !== false).length} of {SECTION_META.length} sections visible
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .growth-dash-config-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────

const sectionCard = {
  background: 'white',
  border: `1px solid ${ds.border}`,
  borderRadius: 12,
  padding: '18px 20px',
  marginBottom: 16,
}

const sectionTitle = {
  fontFamily: ds.fontSyne,
  fontWeight: 700,
  fontSize: 13,
  color: ds.dark,
  marginBottom: 4,
}

const sectionDesc = {
  fontSize: 12.5,
  color: ds.gray,
  marginBottom: 16,
  lineHeight: 1.5,
}

const rowStyle = {
  display: 'flex',
  alignItems: 'flex-start',
  padding: '12px 0',
  borderBottom: `1px solid ${ds.border}`,
}

const primaryBtn = {
  padding: '10px 22px',
  background: ds.teal,
  color: 'white',
  border: 'none',
  borderRadius: 8,
  fontFamily: ds.fontSyne,
  fontWeight: 600,
  fontSize: 13.5,
  cursor: 'pointer',
  minHeight: 44,
}

const secondaryBtn = {
  ...primaryBtn,
  background: 'white',
  color: ds.gray,
  border: `1.5px solid ${ds.border}`,
}
