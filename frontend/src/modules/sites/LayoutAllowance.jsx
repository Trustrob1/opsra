/**
 * frontend/src/modules/sites/LayoutAllowance.jsx
 * SITE-1C-2 — which layouts new sites of a template may use, per section (template form).
 * Nothing ticked in a section = every layout allowed. Only sections the template offers are shown.
 */
import { T, SECTION_LABELS, SECTION_LAYOUTS } from './sitesKit'
import { TEAL } from './lookKit'
import SectionThumb from './SectionThumb'
import LookTick from './LookTick'

export default function LayoutAllowance({ sections, value, onChange }) {
  const shown = sections.filter((k) => (SECTION_LAYOUTS[k] || []).length > 1)
  const toggle = (key, layout) => {
    const cur = value[key] || []
    const next = cur.includes(layout) ? cur.filter((x) => x !== layout) : [...cur, layout]
    const out = { ...value }
    if (next.length) out[key] = next; else delete out[key]
    onChange(out)
  }
  if (!shown.length) return <span style={{ fontSize: 12.5, color: T.muted }}>The sections chosen have a single layout.</span>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {shown.map((key) => {
        const cur = value[key] || []
        return (
          <div key={key}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: T.ink, marginBottom: 6 }}>
              {SECTION_LABELS[key]} <span style={{ fontWeight: 500, color: T.muted }}>&middot; {cur.length ? `${cur.length} allowed` : 'all allowed'}</span>
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {SECTION_LAYOUTS[key].map((l) => {
                const on = cur.includes(l.value)
                return (
                  <button key={l.value} type="button" role="checkbox" aria-checked={on} aria-label={`${SECTION_LABELS[key]} layout ${l.label}`} onClick={() => toggle(key, l.value)}
                    style={{ position: 'relative', width: 96, padding: 6, background: on ? '#f4fbfb' : '#fff', border: `1.5px solid ${on ? TEAL : '#d5dbe3'}`, borderRadius: 10, cursor: 'pointer', fontFamily: 'inherit', fontSize: 11, fontWeight: 700, color: on ? '#0b5f68' : T.muted }}>
                    <SectionThumb section={key} variant={l.value} width={82} active={on} />
                    <div style={{ marginTop: 4 }}>{l.label}</div>
                    {on && <LookTick />}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
