/**
 * frontend/src/modules/sites/LookStudio.jsx
 * SITE-1C-1b — the template "Look studio" (mockup option B): start from a ready-made look, then
 * fine-tune colours, fonts and shape. Every option tile draws what it does, and a live preview
 * on the right follows the pointer.
 *
 * value = { default_palettes, allowed_fonts, token_options } — the same three fields the template
 * form saves. A ticked item is one new sites may use; an empty group means "everything allowed".
 * default_palettes holds palette keys and/or the template's own custom hex colours.
 */
import { useEffect, useMemo, useState } from 'react'
import { Check, Shuffle } from 'lucide-react'
import { Button } from './sitesUi'
import { T, PALETTES, FONT_PAIRINGS, FONT_GROUP_LABELS, TOKENS, THEME_TOKEN_EXCLUSIONS } from './sitesKit'
import { LOOKS, DEFAULT_TOKENS, coloursOf, tokenGlyph, previewStyles, ensureLookFonts, isHex, contrast } from './lookKit'
import LookPreview from './LookPreview'

const TEAL = '#0d7f8a'
const MAX_COLOURS = 30
const LABEL = { fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: T.muted, marginBottom: 8 }

function Tick() {
  return (
    <span style={{ position: 'absolute', top: -7, right: -7, width: 20, height: 20, borderRadius: '50%', background: TEAL, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Check size={13} strokeWidth={3.5} aria-hidden="true" />
    </span>
  )
}

const tileStyle = (on) => ({
  position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8,
  minWidth: 88, padding: '12px 10px', borderRadius: 10, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: T.ink, fontFamily: 'inherit',
  background: on ? '#e6f4f5' : '#fff', border: `1.5px solid ${on ? TEAL : '#d5dbe3'}`,
})

export default function LookStudio({ value, onChange, nicheKey, isMobile }) {
  const palettes = value.default_palettes || []
  const fonts = value.allowed_fonts || []
  const tokenOpts = value.token_options || {}

  const [tab, setTab] = useState('colours')
  const [looksOn, setLooksOn] = useState({})
  const [pickHex, setPickHex] = useState('#0E6B8A')
  const [customPool, setCustomPool] = useState(() => palettes.filter(isHex).map((h) => h.toUpperCase()))
  const [cur, setCur] = useState(() => ({ entry: palettes[0] || 'berry', font: fonts[0] || 'bodoni_jost', tok: { ...DEFAULT_TOKENS, ...Object.fromEntries(Object.entries(tokenOpts).filter(([, v]) => v?.length).map(([k, v]) => [k, v[0]])) } }))

  useEffect(() => { ensureLookFonts() }, [])

  const peek = (patch) => setCur((c) => ({ ...c, ...patch }))
  const peekTok = (k, v) => setCur((c) => ({ ...c, tok: { ...c.tok, [k]: v } }))
  const accent = coloursOf(cur.entry).accent

  const set = (patch) => onChange({ default_palettes: palettes, allowed_fonts: fonts, token_options: tokenOpts, ...patch })

  const togglePalette = (entry) => {
    const on = palettes.includes(entry)
    set({ default_palettes: on ? palettes.filter((x) => x !== entry) : [...palettes, entry] })
    if (!on) peek({ entry })
  }
  const toggleFont = (key) => {
    const on = fonts.includes(key)
    set({ allowed_fonts: on ? fonts.filter((x) => x !== key) : [...fonts, key] })
    if (!on) peek({ font: key })
  }
  const toggleToken = (tk, opt) => {
    const list = tokenOpts[tk] || []
    const on = list.includes(opt)
    set({ token_options: { ...tokenOpts, [tk]: on ? list.filter((x) => x !== opt) : [...list, opt] } })
    if (!on) peekTok(tk, opt)
  }
  const applyLook = (look) => {
    const on = !looksOn[look.key]
    setLooksOn((s) => ({ ...s, [look.key]: on }))
    if (!on) return
    const tok = { ...tokenOpts }
    Object.entries(look.tok).forEach(([k, v]) => { tok[k] = (tok[k] || []).includes(v) ? tok[k] : [...(tok[k] || []), v] })
    set({
      default_palettes: palettes.includes(look.pal) ? palettes : [...palettes, look.pal],
      allowed_fonts: fonts.includes(look.font) ? fonts : [...fonts, look.font],
      token_options: tok,
    })
    setCur({ entry: look.pal, font: look.font, tok: { ...DEFAULT_TOKENS, ...look.tok } })
  }
  const addColour = () => {
    const h = pickHex.toUpperCase()
    if (!isHex(h) || palettes.length >= MAX_COLOURS) return
    if (!customPool.includes(h)) setCustomPool((p) => [...p, h])
    if (!palettes.includes(h)) set({ default_palettes: [...palettes, h] })
    peek({ entry: h })
  }
  const onHexText = (e) => {
    let v = e.target.value.toUpperCase()
    if (v && v[0] !== '#') v = '#' + v
    setPickHex(v)
    if (isHex(v)) peek({ entry: v })
  }
  const shuffle = () => {
    const rnd = (a) => a[Math.floor(Math.random() * a.length)]
    const pool = palettes.length ? palettes : PALETTES.map((p) => p.value)
    const fpool = fonts.length ? fonts : FONT_PAIRINGS.map((f) => f.value)
    const tok = {}
    TOKENS.forEach((t) => {
      const excl = THEME_TOKEN_EXCLUSIONS.atelier?.[t.key] || []
      const all = t.options.map((o) => o.value)
      const allowed = (tokenOpts[t.key] || []).length ? tokenOpts[t.key] : all
      tok[t.key] = rnd(allowed.filter((v) => !excl.includes(v)).length ? allowed.filter((v) => !excl.includes(v)) : allowed)
    })
    setCur({ entry: rnd(pool), font: rnd(fpool), tok })
  }
  const suggested = PALETTES.filter((p) => p.niches.includes(nicheKey)).map((p) => p.value)

  const count = palettes.length + fonts.length + Object.values(tokenOpts).reduce((n, l) => n + (l?.length || 0), 0)
  const st = useMemo(() => previewStyles(cur), [cur])

  const swatch = (entry, name, on) => {
    const c = coloursOf(entry)
    return (
      <button key={entry} type="button" aria-pressed={on} aria-label={name} title={name}
        onClick={() => togglePalette(entry)} onMouseEnter={() => peek({ entry })}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, width: 70, padding: '6px 2px', background: 'none', border: 0, cursor: 'pointer', fontSize: 11, fontWeight: 600, color: T.soft, fontFamily: 'inherit' }}>
        <span style={{ width: 34, height: 34, borderRadius: '50%', background: c.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', color: contrast(c.accent, '#fff') >= 3 ? '#fff' : '#1a1a1a',
          boxShadow: `0 0 0 3px ${c.ground}, 0 0 0 ${on ? `5px ${TEAL}` : '4px #cfd5dd'}` }}>
          {on && <Check size={15} strokeWidth={3.5} aria-hidden="true" />}
        </span>
        <span>{name}</span>
      </button>
    )
  }

  const tabBtn = (key, label) => (
    <button key={key} type="button" onClick={() => setTab(key)}
      style={{ padding: '9px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 700, fontFamily: 'inherit', background: 'none', border: 0, borderBottom: `3px solid ${tab === key ? TEAL : 'transparent'}`, color: tab === key ? '#0b5f68' : T.soft }}>
      {label}
    </button>
  )

  return (
    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 0, height: isMobile ? 'auto' : '68vh', minHeight: 0 }}>
      <div style={{ flex: isMobile ? 'none' : '0 0 56%', overflowY: isMobile ? 'visible' : 'auto', padding: '0 20px 20px 0', boxSizing: 'border-box' }}>
        <h3 style={{ margin: '0 0 4px', fontSize: 15, fontWeight: 800, color: T.ink }}>Start from a look</h3>
        <p style={{ margin: '0 0 12px', fontSize: 12.5, color: T.muted, lineHeight: 1.45 }}>
          A look is a ready-made mix of colour, fonts and shape. Tick the ones this template can use, then fine-tune below.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
          {LOOKS.map((look) => {
            const s = previewStyles({ entry: look.pal, font: look.font, tok: look.tok })
            const on = !!looksOn[look.key]
            return (
              <button key={look.key} type="button" aria-pressed={on} onClick={() => applyLook(look)}
                onMouseEnter={() => setCur({ entry: look.pal, font: look.font, tok: { ...DEFAULT_TOKENS, ...look.tok } })}
                style={{ ...tileStyle(on), alignItems: 'stretch', textAlign: 'left', gap: 6, padding: 10 }}>
                <span style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: 96, padding: 11, boxSizing: 'border-box', borderRadius: 8, border: '1px solid #d7dce3', background: s.bg }}>
                  <span style={{ ...s.brand, fontSize: 15 }}>Adaeze Styles</span>
                  <span style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
                    <span style={{ ...s.btn, padding: '5px 11px', fontSize: 10 }}>Order</span>
                    <span style={{ ...s.tile, width: 50, height: 34 }} />
                  </span>
                </span>
                <span style={{ fontSize: 13, fontWeight: 800 }}>{look.name}</span>
                <span style={{ fontSize: 11.5, color: T.muted, fontWeight: 500 }}>{look.blurb}</span>
                {on && <Tick />}
              </button>
            )
          })}
        </div>

        <h3 style={{ margin: '26px 0 6px', fontSize: 15, fontWeight: 800, color: T.ink }}>Fine-tune</h3>
        <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${T.line}`, marginBottom: 14 }}>
          {tabBtn('colours', 'Colours')}{tabBtn('fonts', 'Fonts')}{tabBtn('shape', 'Shape and details')}
        </div>

        {tab === 'colours' && (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 2px' }}>
              {PALETTES.map((p) => swatch(p.value, p.label, palettes.includes(p.value)))}
              {customPool.map((h) => swatch(h, h, palettes.includes(h)))}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0 12px' }}>
              {suggested.length > 0 && <Button size="sm" variant="secondary" onClick={() => set({ default_palettes: [...suggested, ...palettes.filter(isHex)] })}>Use the {suggested.length} suggested for this niche</Button>}
              <Button size="sm" variant="ghost" onClick={() => set({ default_palettes: [...PALETTES.map((p) => p.value), ...palettes.filter(isHex)] })}>Tick all</Button>
              <Button size="sm" variant="ghost" onClick={() => set({ default_palettes: [] })}>Clear</Button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', padding: '12px 14px', border: '1.5px dashed #b9c2ce', borderRadius: 12, background: '#fafbfc' }}>
              <input type="color" value={isHex(pickHex) ? pickHex : '#0E6B8A'} aria-label="Pick a colour"
                onChange={(e) => { const v = e.target.value.toUpperCase(); setPickHex(v); peek({ entry: v }) }}
                style={{ width: 48, height: 48, padding: 0, border: 0, background: 'none', cursor: 'pointer' }} />
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, fontWeight: 700, color: T.soft }}>
                Hex code
                <input value={pickHex} onChange={onHexText} maxLength={7}
                  style={{ width: 104, padding: '8px 10px', border: `1px solid ${T.lineStrong}`, borderRadius: 8, fontSize: 13, fontWeight: 600, color: T.ink, fontFamily: 'inherit' }} />
              </label>
              {isHex(pickHex) && (
                <span style={{ fontSize: 12, fontWeight: 600, padding: '5px 10px', borderRadius: 999, background: contrast(pickHex, '#FFFFFF') >= 4.5 ? T.goodBg : T.warnBg, color: contrast(pickHex, '#FFFFFF') >= 4.5 ? T.good : T.warn }}>
                  {contrast(pickHex, '#FFFFFF') >= 4.5 ? 'Good contrast on white' : 'Light colour: small text in it may be hard to read'}
                </span>
              )}
              <Button size="sm" variant="primary" disabled={!isHex(pickHex)} onClick={addColour} style={{ marginLeft: 'auto' }}>Add this colour</Button>
            </div>
          </div>
        )}

        {tab === 'fonts' && (
          <div>
            {Object.keys(FONT_GROUP_LABELS).map((g) => (
              <div key={g} style={{ marginBottom: 14 }}>
                <div style={LABEL}>{FONT_GROUP_LABELS[g]}</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
                  {FONT_PAIRINGS.filter((f) => f.group === g).map((f) => {
                    const on = fonts.includes(f.value)
                    return (
                      <button key={f.value} type="button" aria-pressed={on} onClick={() => toggleFont(f.value)} onMouseEnter={() => peek({ font: f.value })}
                        style={{ ...tileStyle(on), alignItems: 'flex-start', textAlign: 'left', gap: 5, padding: '13px 14px' }}>
                        <span style={{ fontFamily: `'${f.heading}', serif`, fontSize: 21, lineHeight: 1.1, color: T.ink, fontWeight: 600 }}>Adaeze Styles</span>
                        <span style={{ fontFamily: `'${f.body}', sans-serif`, fontSize: 12.5, color: T.soft, fontWeight: 400 }}>Ankara and corporate wear, made to order.</span>
                        <span style={{ fontSize: 11, color: T.muted, fontWeight: 600 }}>{f.label}</span>
                        {on && <Tick />}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'shape' && (
          <div>
            {TOKENS.map((t) => (
              <div key={t.key} style={{ marginBottom: 16 }}>
                <div style={LABEL}>{t.label}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                  {t.options.map((o) => {
                    const on = (tokenOpts[t.key] || []).includes(o.value)
                    const gl = tokenGlyph(t.key, o.value, accent, cur.font)
                    return (
                      <button key={o.value} type="button" aria-pressed={on} onClick={() => toggleToken(t.key, o.value)} onMouseEnter={() => peekTok(t.key, o.value)} style={tileStyle(on)}>
                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 34 }}><span style={gl.style}>{gl.text}</span></span>
                        <span>{o.label}</span>
                        {on && <Tick />}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
        <p style={{ margin: '10px 0 0', fontSize: 11.5, color: T.muted }}>{count === 0 ? 'Nothing ticked: new sites may use every option.' : 'Leave a group empty to allow every option in it.'}</p>
      </div>

      <div style={{ flex: 1, minWidth: 0, background: '#f3f5f8', border: `1px solid ${T.line}`, borderRadius: 12, padding: 14, display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 800, color: T.ink }}>Live preview</div>
            <div style={{ fontSize: 11.5, color: T.muted, marginTop: 2 }}>
              {coloursOf(cur.entry).label} &middot; {FONT_PAIRINGS.find((f) => f.value === cur.font)?.label} &middot; {cur.tok.cards} cards &middot; {cur.tok.background === 'match' ? 'match background' : `${cur.tok.background} background`}
            </div>
          </div>
          <Button size="sm" variant="secondary" icon={Shuffle} onClick={shuffle}>Shuffle look</Button>
        </div>
        {!st.readable && <span style={{ fontSize: 11.5, fontWeight: 600, color: T.warn }}>This colour is light on the page: small text in it may be hard to read.</span>}
        <div style={{ overflowY: 'auto', flex: 1, minHeight: isMobile ? 420 : 0, borderRadius: 10, border: '1px solid #d7dce3', background: '#fff' }}><LookPreview cur={cur} /></div>
        <span style={{ fontSize: 11.5, color: T.muted }}>Hover an option to preview it. Click to tick it for new sites.</span>
      </div>
    </div>
  )
}
