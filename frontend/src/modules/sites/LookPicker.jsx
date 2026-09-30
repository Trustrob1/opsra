/**
 * frontend/src/modules/sites/LookPicker.jsx
 * SITE-1C-1c — the visual look picker for ONE site (staff site editor and builder editor).
 * Same tiles and live preview as the template Look studio, but each group picks a single option
 * and writes straight into the recipe (palette / custom_colour / fonts / tokens).
 *
 * `preset` narrows the choices: { allowed_themes, allowed_fonts, token_options } (the template's
 * own settings; the server enforces the same rules on save). Empty = everything allowed.
 */
import { useEffect, useMemo, useState } from 'react'
import { Check, Palette } from 'lucide-react'
import { Button, Modal } from './sitesUi'
import { T, PALETTES, FONT_PAIRINGS, FONT_GROUP_LABELS, TOKENS, THEME_TOKEN_EXCLUSIONS } from './sitesKit'
import {
  TEAL, LABEL_STYLE, tileStyle, THEME_FONT_GROUPS, THEME_DEFAULT_FONT, curFromRecipe, tokenGlyph, ensureLookFonts, isHex, contrast, coloursOf,
} from './lookKit'
import LookPreview from './LookPreview'
import LookTick from './LookTick'

function fontChoices(recipe, preset) {
  const groups = THEME_FONT_GROUPS[recipe.theme] || Object.keys(FONT_GROUP_LABELS)
  const allowed = preset?.allowed_fonts || []
  return FONT_PAIRINGS.filter((f) => f.value === recipe.fonts || (groups.includes(f.group) && (!allowed.length || allowed.includes(f.value))))
}

function tokenChoices(token, recipe, preset) {
  const excluded = THEME_TOKEN_EXCLUSIONS[recipe.theme]?.[token.key] || []
  const narrowed = preset?.token_options?.[token.key] || []
  return token.options.filter((o) => o.value === recipe.tokens?.[token.key] || (!excluded.includes(o.value) && (!narrowed.length || narrowed.includes(o.value))))
}

function LookPickerBody({ recipe, setRecipe, preset, isMobile }) {
  const [tab, setTab] = useState('colour')
  const [hex, setHex] = useState(recipe.custom_colour || '#0E6B8A')
  const [peek, setPeek] = useState(null) // { entry?, font?, tok? } — hover preview
  useEffect(() => { ensureLookFonts() }, [])

  const base = useMemo(() => curFromRecipe(recipe), [recipe])
  const cur = peek ? { ...base, ...peek, tok: { ...base.tok, ...(peek.tok || {}) } } : base
  const accent = coloursOf(base.entry).accent
  const tokens = recipe.tokens || {}

  const setPalette = (value) => setRecipe((r) => ({ ...r, palette: value, custom_colour: null }))
  const setCustom = (v) => { setHex(v); if (isHex(v)) setRecipe((r) => ({ ...r, custom_colour: v.toUpperCase(), palette: r.palette || 'berry' })) }
  const setFonts = (value) => setRecipe((r) => ({ ...r, fonts: value }))
  const setToken = (key, value) => setRecipe((r) => ({ ...r, tokens: { ...(r.tokens || {}), [key]: value } }))
  const reset = () => setRecipe((r) => ({ ...r, fonts: null, tokens: {} }))

  const tabBtn = (key, label) => (
    <button key={key} type="button" onClick={() => setTab(key)}
      style={{ padding: '9px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 700, fontFamily: 'inherit', background: 'none', border: 0, borderBottom: `3px solid ${tab === key ? TEAL : 'transparent'}`, color: tab === key ? '#0b5f68' : T.soft }}>
      {label}
    </button>
  )
  const hovered = (patch) => ({ onMouseEnter: () => setPeek(patch), onMouseLeave: () => setPeek(null), onFocus: () => setPeek(patch), onBlur: () => setPeek(null) })
  const swatch = (entry, name, on, onClick) => {
    const c = coloursOf(entry)
    return (
      <button key={entry + name} type="button" aria-pressed={on} aria-label={name} title={name} onClick={onClick} {...hovered({ entry })}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, width: 70, padding: '6px 2px', background: 'none', border: 0, cursor: 'pointer', fontSize: 11, fontWeight: 600, color: T.soft, fontFamily: 'inherit' }}>
        <span style={{ width: 34, height: 34, borderRadius: '50%', background: c.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', color: contrast(c.accent, '#fff') >= 3 ? '#fff' : '#1a1a1a',
          boxShadow: `0 0 0 3px ${c.ground}, 0 0 0 ${on ? `5px ${TEAL}` : '4px #cfd5dd'}` }}>
          {on && <Check size={15} strokeWidth={3.5} aria-hidden="true" />}
        </span>
        <span>{name}</span>
      </button>
    )
  }

  const usingCustom = !!recipe.custom_colour
  const fonts = fontChoices(recipe, preset)
  const readable = contrast(accent, '#FFFFFF') >= 4.5

  return (
    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 0, height: isMobile ? 'auto' : '66vh', minHeight: 0 }}>
      <div style={{ flex: isMobile ? 'none' : '0 0 54%', overflowY: isMobile ? 'visible' : 'auto', padding: '0 20px 20px 0', boxSizing: 'border-box' }}>
        <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${T.line}`, marginBottom: 14 }}>
          {tabBtn('colour', 'Colour')}{tabBtn('fonts', 'Fonts')}{tabBtn('shape', 'Shape and details')}
        </div>

        {tab === 'colour' && (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 2px' }}>
              {PALETTES.map((p) => swatch(p.value, p.label, !usingCustom && recipe.palette === p.value, () => setPalette(p.value)))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', padding: '12px 14px', marginTop: 10, border: '1.5px dashed #b9c2ce', borderRadius: 12, background: '#fafbfc' }}>
              <input type="color" value={isHex(hex) ? hex : '#0E6B8A'} aria-label="Pick your own colour" onChange={(e) => setCustom(e.target.value.toUpperCase())}
                style={{ width: 48, height: 48, padding: 0, border: 0, background: 'none', cursor: 'pointer' }} />
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, fontWeight: 700, color: T.soft }}>
                Your own colour (hex)
                <input value={hex} maxLength={7} onChange={(e) => { let v = e.target.value.toUpperCase(); if (v && v[0] !== '#') v = '#' + v; setCustom(v) }}
                  style={{ width: 118, padding: '8px 10px', border: `1px solid ${T.lineStrong}`, borderRadius: 8, fontSize: 13, fontWeight: 600, color: T.ink, fontFamily: 'inherit' }} />
              </label>
              {usingCustom && <span style={{ fontSize: 12, fontWeight: 600, padding: '5px 10px', borderRadius: 999, background: readable ? T.goodBg : T.warnBg, color: readable ? T.good : T.warn }}>
                {readable ? 'Good contrast on white' : 'Light colour: small text in it may be hard to read'}
              </span>}
              {usingCustom && <Button size="sm" variant="ghost" onClick={() => setPalette(recipe.palette || 'berry')} style={{ marginLeft: 'auto' }}>Use a palette instead</Button>}
            </div>
          </div>
        )}

        {tab === 'fonts' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
            {(() => {
              const def = FONT_PAIRINGS.find((f) => f.value === THEME_DEFAULT_FONT[recipe.theme]) || FONT_PAIRINGS[0]
              const on = !recipe.fonts
              return (
                <button type="button" aria-pressed={on} onClick={() => setFonts(null)} {...hovered({ font: def.value })}
                  style={{ ...tileStyle(on), alignItems: 'flex-start', textAlign: 'left', gap: 5, padding: '13px 14px' }}>
                  <span style={{ fontFamily: `'${def.heading}', serif`, fontSize: 21, lineHeight: 1.1, color: T.ink, fontWeight: 600 }}>Adaeze Styles</span>
                  <span style={{ fontSize: 12.5, color: T.soft, fontWeight: 400 }}>The theme's own fonts.</span>
                  <span style={{ fontSize: 11, color: T.muted, fontWeight: 600 }}>Theme default</span>
                  {on && <LookTick />}
                </button>
              )
            })()}
            {fonts.map((f) => {
              const on = recipe.fonts === f.value
              return (
                <button key={f.value} type="button" aria-pressed={on} onClick={() => setFonts(f.value)} {...hovered({ font: f.value })}
                  style={{ ...tileStyle(on), alignItems: 'flex-start', textAlign: 'left', gap: 5, padding: '13px 14px' }}>
                  <span style={{ fontFamily: `'${f.heading}', serif`, fontSize: 21, lineHeight: 1.1, color: T.ink, fontWeight: 600 }}>Adaeze Styles</span>
                  <span style={{ fontFamily: `'${f.body}', sans-serif`, fontSize: 12.5, color: T.soft, fontWeight: 400 }}>Ankara and corporate wear, made to order.</span>
                  <span style={{ fontSize: 11, color: T.muted, fontWeight: 600 }}>{f.label}</span>
                  {on && <LookTick />}
                </button>
              )
            })}
          </div>
        )}

        {tab === 'shape' && (
          <div>
            {TOKENS.map((t) => (
              <div key={t.key} style={{ marginBottom: 16 }}>
                <div style={LABEL_STYLE}>{t.label}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                  <button type="button" aria-pressed={!tokens[t.key]} onClick={() => setToken(t.key, null)} style={tileStyle(!tokens[t.key])}>
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 34, fontSize: 12, color: T.muted }}>Auto</span>
                    <span>Theme default</span>
                    {!tokens[t.key] && <LookTick />}
                  </button>
                  {tokenChoices(t, recipe, preset).map((o) => {
                    const on = tokens[t.key] === o.value
                    const gl = tokenGlyph(t.key, o.value, accent, cur.font)
                    return (
                      <button key={o.value} type="button" aria-pressed={on} onClick={() => setToken(t.key, o.value)} {...hovered({ tok: { [t.key]: o.value } })} style={tileStyle(on)}>
                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 34 }}><span style={gl.style}>{gl.text}</span></span>
                        <span>{o.label}</span>
                        {on && <LookTick />}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
            <Button size="sm" variant="ghost" onClick={reset}>Reset fonts and style to the theme's defaults</Button>
          </div>
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0, background: '#f3f5f8', border: `1px solid ${T.line}`, borderRadius: 12, padding: 14, display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 800, color: T.ink }}>Live preview</div>
          <div style={{ fontSize: 11.5, color: T.muted, marginTop: 2 }}>A quick picture of this look. Use Render preview on the page for the real thing.</div>
        </div>
        <div style={{ overflowY: 'auto', flex: 1, minHeight: isMobile ? 420 : 0, borderRadius: 10, border: '1px solid #d7dce3', background: '#fff' }}><LookPreview cur={cur} /></div>
      </div>
    </div>
  )
}

/** The compact field for the Design card: a summary line and a button that opens the picker. */
export default function LookPickerField({ recipe, setRecipe, preset, canEdit = true, isMobile }) {
  const [open, setOpen] = useState(false)
  // Escape closes only the picker, not the page underneath it (capture phase runs first).
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open])

  const c = coloursOf(recipe.custom_colour || recipe.palette || 'berry')
  const font = FONT_PAIRINGS.find((f) => f.value === recipe.fonts)?.label || 'Theme fonts'
  const nStyle = Object.values(recipe.tokens || {}).filter(Boolean).length
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', padding: '10px 12px', border: `1px solid ${T.line}`, borderRadius: 10, background: '#FAFCFD' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, fontSize: 12.5, color: T.soft, flex: 1, minWidth: 180 }}>
          <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: '50%', background: c.accent, boxShadow: `0 0 0 3px ${c.ground}, 0 0 0 4px #cfd5dd`, flex: 'none' }} />
          {c.label} &middot; {font} &middot; {nStyle} style choice{nStyle === 1 ? '' : 's'} set
        </span>
        {canEdit && <Button size="sm" variant="secondary" icon={Palette} onClick={() => setOpen(true)}>Change look</Button>}
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Choose the look" width={1100}
        footer={<Button variant="primary" onClick={() => setOpen(false)}>Done</Button>}>
        <LookPickerBody recipe={recipe} setRecipe={setRecipe} preset={preset} isMobile={isMobile} />
      </Modal>
    </>
  )
}
