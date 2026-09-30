/**
 * frontend/src/modules/sites/SectionTiles.jsx
 * SITE-1C-2a — sections as tiles with a wireframe of each layout.
 *   mode "select" — tick which sections a template offers (multi)
 *   mode "show"   — per site: show/hide each section and pick its layout (writes recipe.variants)
 */
import { T, SECTION_LABELS, SECTION_HINTS, SECTION_LAYOUTS } from './sitesKit'
import { TEAL } from './lookKit'
import SectionThumb from './SectionThumb'
import LookTick from './LookTick'

export default function SectionTiles({ mode, keys, selected, onToggle, variants, onVariant, disabled = false }) {
  const tile = (on) => ({
    position: 'relative', width: 214, padding: 10, boxSizing: 'border-box', borderRadius: 12, background: on ? '#f4fbfb' : '#fafbfc',
    border: `2px solid ${on ? TEAL : '#d5dbe3'}`, opacity: on ? 1 : 0.75, textAlign: 'left', fontFamily: 'inherit',
  })
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
      {keys.map((key) => {
        const layouts = SECTION_LAYOUTS[key] || []
        const on = selected.includes(key)
        const cur = variants?.[key] || layouts[0]?.value
        const head = (
          <>
            <SectionThumb section={key} variant={cur} width={192} active={on} />
            <div style={{ fontSize: 13.5, fontWeight: 800, color: T.ink, marginTop: 8 }}>{SECTION_LABELS[key] || key}</div>
            <div style={{ fontSize: 11.5, color: T.soft, marginTop: 2, lineHeight: 1.35, minHeight: 32 }}>{SECTION_HINTS[key]}</div>
          </>
        )
        return (
          <div key={key} style={tile(on)}>
            <button type="button" role="checkbox" aria-checked={on} aria-label={`${SECTION_LABELS[key] || key}: ${mode === 'show' ? (on ? 'shown' : 'hidden') : (on ? 'offered' : 'not offered')}`} disabled={disabled} onClick={() => onToggle(key)}
              style={{ display: 'block', width: '100%', padding: 0, border: 0, background: 'none', textAlign: 'left', cursor: disabled ? 'default' : 'pointer', fontFamily: 'inherit' }}>
              {head}
              <div style={{ fontSize: 11, fontWeight: 700, marginTop: 4, color: on ? '#0b5f68' : T.muted }}>
                {mode === 'show' ? (on ? 'Shown on the site' : 'Hidden (content kept)') : (on ? 'Offered' : 'Not offered')}
              </div>
            </button>
            {on && <LookTick />}
            {mode === 'show' && on && layouts.length > 1 && (
              <div role="radiogroup" aria-label={`${SECTION_LABELS[key]} layout`} style={{ display: 'flex', gap: 6, marginTop: 8, paddingTop: 8, borderTop: `1px solid ${T.line}` }}>
                {layouts.map((l) => (
                  <button key={l.value} type="button" role="radio" aria-checked={cur === l.value} disabled={disabled} onClick={() => onVariant(key, l.value)} title={l.label}
                    style={{ flex: 1, minWidth: 0, padding: 3, background: 'none', border: 0, cursor: disabled ? 'default' : 'pointer', fontFamily: 'inherit', fontSize: 10, fontWeight: 700, color: cur === l.value ? '#0b5f68' : T.muted }}>
                    <SectionThumb section={key} variant={l.value} width={54} active={cur === l.value} />
                    <div style={{ marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.label}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
