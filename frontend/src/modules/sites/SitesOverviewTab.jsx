/**
 * frontend/src/modules/sites/SitesOverviewTab.jsx
 * SITE-1A part 2 — Overview: totals by status, previews shared, builders count.
 * Basic only — revenue/conversion/renewal KPIs land with SITE-3 (payments don't exist yet).
 */
import { useCallback, useEffect, useState } from 'react'
import { Globe, Layers, Users, Eye } from 'lucide-react'
import { getSitesOverview, errorMessage } from '../../services/sites.service'
import { Card, Kpi, SectionTitle, Notice, Spinner, Badge } from './sitesUi'
import { T, num, SITE_STATUS } from './sitesKit'

export default function SitesOverviewTab({ isActive, enabled, onGoSettings }) {
  const [ov, setOv] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setOv(await getSitesOverview())
    } catch (e) {
      setError(errorMessage(e, 'Could not load the numbers.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isActive && enabled) load() }, [isActive, enabled, load])

  if (!enabled) {
    return (
      <Card>
        <SectionTitle title="Site engine is off"
          hint="Turn it on in Settings to start building and previewing sites by hand. Presets and builders can be set up either way." />
        <Badge tone="neutral" icon={Globe}>Disabled for this org</Badge>
        {onGoSettings && <div style={{ marginTop: 14 }}><a href="#" onClick={(e) => { e.preventDefault(); onGoSettings() }}
          style={{ fontSize: 13, fontWeight: 600, color: T.teal, textDecoration: 'none' }}>Go to Settings →</a></div>}
      </Card>
    )
  }

  if (loading) return <Spinner />
  if (error) return <Notice tone="bad">{error}</Notice>
  if (!ov) return null

  const kpiGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(165px, 1fr))', gap: 12 }
  const byStatus = ov.sites_by_status || {}
  const statusEntries = Object.entries(byStatus)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={kpiGrid}>
        <Kpi label="Sites total" icon={Globe} value={num(ov.sites_total)} />
        <Kpi label="Previews shared" icon={Eye} value={num(ov.previews_shared)} sub="preview ready or revising" />
        <Kpi label="Builders" icon={Users} value={num(ov.builders_total)} />
        <Kpi label="Statuses in use" icon={Layers} value={num(statusEntries.length)} />
      </div>

      <Card>
        <SectionTitle title="Sites by status" hint="Where every site currently sits in the pipeline." />
        {statusEntries.length ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {statusEntries.map(([key, count]) => {
              const st = SITE_STATUS[key] || { tone: 'neutral', label: key }
              return (
                <Badge key={key} tone={st.tone}>{st.label} · <span className="tnum">{count}</span></Badge>
              )
            })}
          </div>
        ) : <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No sites yet — build one from the Sites tab.</p>}
      </Card>
    </div>
  )
}
