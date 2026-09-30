/**
 * frontend/src/modules/sites/ThemePicker.jsx
 * SITE-1C-2a — themes as picture cards: each card is a live mini-site drawn in that theme (with
 * the site's own colour when there is one), so nobody has to guess what "Atelier" means.
 *   multi   — tick several (template form: which themes may a site use)
 *   single  — pick one (site editors)
 */
import { useEffect } from 'react'
import { T, THEMES } from './sitesKit'
import { TEAL, curFromRecipe, ensureLookFonts } from './lookKit'
import LookPreview from './LookPreview'
import LookTick from './LookTick'

const CARD_W = 214, PREVIEW_W = 570, PREVIEW_H = 640
const SCALE = (CARD_W - 2) / PREVIEW_W

export default function ThemePicker({ themes, value, onChange, multi = false, recipe, disabled = false }) {
  useEffect(() => { ensureLookFonts() }, [])
  const list = themes || THEMES
  const isOn = (v) => (multi ? (value || []).includes(v) : value === v)
  const pick = (v) => {
    if (disabled) return
    if (multi) onChange(isOn(v) ? value.filter((x) => x !== v) : [...(value || []), v])
    else onChange(v)
  }
  return (
    <div role={multi ? 'group' : 'radiogroup'} aria-label="Theme" style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
      {list.map((t) => {
        const on = isOn(t.value)
        const cur = curFromRecipe({ ...(recipe || {}), theme: t.value })
        return (
          <button key={t.value} type="button" role={multi ? 'checkbox' : 'radio'} aria-checked={on} disabled={disabled} onClick={() => pick(t.value)}
            style={{ position: 'relative', width: CARD_W, padding: 0, textAlign: 'left', cursor: disabled ? 'default' : 'pointer', fontFamily: 'inherit', background: '#fff', borderRadius: 12,
              border: `2px solid ${on ? TEAL : '#d5dbe3'}`, boxShadow: on ? '0 0 0 3px #0d7f8a22' : 'none', opacity: disabled && !on ? 0.6 : 1 }}>
            <div aria-hidden="true" style={{ height: 250, overflow: 'hidden', position: 'relative', pointerEvents: 'none', background: '#f3f5f8', borderRadius: '10px 10px 0 0' }}>
              <div style={{ width: PREVIEW_W, height: PREVIEW_H, transform: `scale(${SCALE})`, transformOrigin: 'top left' }}><LookPreview cur={cur} /></div>
            </div>
            <div style={{ padding: '10px 12px 12px', borderTop: `1px solid ${T.line}` }}>
              <div style={{ fontSize: 14, fontWeight: 800, color: T.ink }}>{t.label}</div>
              <div style={{ fontSize: 12, color: T.soft, marginTop: 2, lineHeight: 1.35 }}>{t.hint}</div>
            </div>
            {on && <LookTick />}
          </button>
        )
      })}
    </div>
  )
}
