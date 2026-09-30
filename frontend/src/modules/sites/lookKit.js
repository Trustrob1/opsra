/**
 * frontend/src/modules/sites/lookKit.js
 * SITE-1C-1b — the data and style maths behind the template "Look studio": ready-made looks,
 * what each option tile draws, and the styles of the live mini-preview.
 *
 * The mini-preview is an approximation of the real page (site_renderer.py is the truth); it exists
 * so staff can SEE what a setting does before saving. The server still validates every value.
 */
import { PALETTES, FONT_PAIRINGS } from './sitesKit'

export const GOOGLE_FONTS_URL = 'https://fonts.googleapis.com/css2?family=Anton&family=Archivo+Black&family=Bodoni+Moda:wght@500;600&family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@400;500;700&family=DM+Serif+Display&family=Fraunces:wght@500;600&family=Inter:wght@400;500&family=Jost:wght@400;500;600&family=Karla:wght@400;600&family=Lato:wght@400;700&family=Lora:wght@500;600&family=Manrope:wght@500;600;700&family=Nunito:wght@400;600&family=Playfair+Display:wght@500;600&family=Plus+Jakarta+Sans:wght@500;700&family=Poppins:wght@500;600&family=Sora:wght@500;600&family=Syne:wght@600;700&family=Work+Sans:wght@400;500&display=swap'

/** Loads the pairing fonts once so the font cards and preview show real type. */
export function ensureLookFonts() {
  if (typeof document === 'undefined' || document.getElementById('look-fonts')) return
  const link = document.createElement('link')
  link.id = 'look-fonts'
  link.rel = 'stylesheet'
  link.href = GOOGLE_FONTS_URL
  document.head.appendChild(link)
}

export const BACKGROUNDS = { white: '#FFFFFF', grey: '#F3F4F6', ivory: '#FAF7F0' } // mirrors site_renderer.BACKGROUND_VALUES
const SERIF_HEADINGS = new Set(['Bodoni Moda', 'Fraunces', 'Playfair Display', 'Cormorant Garamond', 'DM Serif Display', 'Lora'])
const HEADING_WEIGHT = { 'Bodoni Moda': 500, Anton: 400, Fraunces: 600, 'Playfair Display': 600, 'Cormorant Garamond': 600, 'DM Serif Display': 400, 'Archivo Black': 400, Syne: 700, Poppins: 600, Lora: 600, 'Plus Jakarta Sans': 700, Sora: 600 }

const isHex = (v) => typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v)
export { isHex }

const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const toHex = (c) => '#' + c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('').toUpperCase()
export function mixHex(a, b, amount) {
  const x = rgb(a), y = rgb(b)
  return toHex(x.map((v, i) => v + (y[i] - v) * amount))
}
const lum = (h) => {
  const [r, g, b] = rgb(h).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
export const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) }
const onColour = (a) => (contrast(a, '#FFFFFF') >= contrast(a, '#1A1A1A') ? '#FFFFFF' : '#1A1A1A')

export function washColour(accent) {
  for (const step of [0.92, 0.93, 0.94, 0.95, 0.96, 0.97]) {
    const w = mixHex(accent, '#FFFFFF', step)
    if (contrast(accent, w) >= 4.5) return w
  }
  return mixHex(accent, '#FFFFFF', 0.97)
}

/** Resolves a palette entry (a palette key or a custom hex) to the colours the preview needs. */
export function coloursOf(entry) {
  if (isHex(entry)) return { accent: entry.toUpperCase(), ground: mixHex(entry, '#FFFFFF', 0.96), label: entry.toUpperCase(), custom: true }
  const p = PALETTES.find((x) => x.value === entry) || PALETTES[0]
  return { accent: p.accent, ground: p.ground, label: p.label, custom: false }
}

export const DEFAULT_TOKENS = { radius: 'sharp', density: 'regular', button: 'solid', heading_case: 'normal', image_style: 'square', divider: 'line', background: 'match', bands: 'plain', cards: 'flat', finish: 'standard' }

export const LOOKS = [
  { key: 'elegant', name: 'Elegant boutique', blurb: 'Fine lines, arches, airy', pal: 'berry', font: 'bodoni_jost', tok: { radius: 'sharp', density: 'airy', button: 'outline', heading_case: 'spaced_upper', image_style: 'arch', divider: 'ornament', background: 'ivory', bands: 'wash', cards: 'bordered' } },
  { key: 'bold', name: 'Bold market', blurb: 'Loud, compact, punchy', pal: 'coral', font: 'anton_manrope', tok: { radius: 'pill', density: 'compact', button: 'solid', heading_case: 'upper', image_style: 'square', divider: 'none', background: 'white', bands: 'plain', cards: 'flat' } },
  { key: 'friendly', name: 'Soft and friendly', blurb: 'Round, warm, easy', pal: 'blush', font: 'poppins_nunito', tok: { radius: 'pill', density: 'regular', button: 'solid', heading_case: 'normal', image_style: 'rounded', divider: 'dot', background: 'white', bands: 'wash', cards: 'lifted' } },
  { key: 'minimal', name: 'Clean minimal', blurb: 'Quiet, lots of space', pal: 'charcoal', font: 'jakarta_inter', tok: { radius: 'soft', density: 'airy', button: 'underline', heading_case: 'normal', image_style: 'square', divider: 'line', background: 'white', bands: 'plain', cards: 'bordered' } },
  { key: 'kitchen', name: 'Warm kitchen', blurb: 'Earthy, framed photos', pal: 'terracotta', font: 'fraunces_karla', tok: { radius: 'soft', density: 'regular', button: 'solid', heading_case: 'normal', image_style: 'framed', divider: 'line', background: 'ivory', bands: 'wash', cards: 'flat' } },
  { key: 'natural', name: 'Fresh and natural', blurb: 'Green, soft, outlined', pal: 'sage', font: 'lora_nunito', tok: { radius: 'soft', density: 'airy', button: 'outline', heading_case: 'normal', image_style: 'rounded', divider: 'dot', background: 'grey', bands: 'plain', cards: 'lifted' } },
  { key: 'corporate', name: 'Corporate calm', blurb: 'Navy, sharp, upper', pal: 'midnight', font: 'dmserif_dmsans', tok: { radius: 'sharp', density: 'regular', button: 'solid', heading_case: 'upper', image_style: 'square', divider: 'line', background: 'grey', bands: 'wash', cards: 'bordered' } },
  { key: 'pop', name: 'Playful pop', blurb: 'Bright, round, compact', pal: 'sunset', font: 'syne_dmsans', tok: { radius: 'pill', density: 'compact', button: 'solid', heading_case: 'normal', image_style: 'rounded', divider: 'none', background: 'white', bands: 'wash', cards: 'lifted' } },
]

/** What an option tile draws. Returns { style, text } for the little glyph above the label. */
export function tokenGlyph(tokenKey, opt, accent, fontKey) {
  const ink = '#3b4452'
  const font = FONT_PAIRINGS.find((f) => f.value === fontKey) || FONT_PAIRINGS[0]
  const on = onColour(accent)
  if (tokenKey === 'radius') return { style: { width: 40, height: 26, border: `2px solid ${ink}`, background: '#eef1f5', borderRadius: { sharp: 0, soft: 7, pill: 14 }[opt] }, text: '' }
  if (tokenKey === 'density') {
    const gap = { airy: 8, regular: 5, compact: 2 }[opt]
    return { style: { width: 40, height: 28, background: `repeating-linear-gradient(to bottom, ${ink} 0 3px, transparent 3px ${3 + gap}px)` }, text: '' }
  }
  if (tokenKey === 'button') {
    const base = { font: '700 11px sans-serif', padding: '5px 13px', borderRadius: 7 }
    if (opt === 'solid') return { style: { ...base, background: accent, color: on, border: `1.5px solid ${accent}` }, text: 'Buy' }
    if (opt === 'outline') return { style: { ...base, color: accent, border: `1.5px solid ${accent}` }, text: 'Buy' }
    return { style: { ...base, color: accent, borderBottom: `2px solid ${accent}`, borderRadius: 0, padding: '5px 1px' }, text: 'Buy' }
  }
  if (tokenKey === 'heading_case') {
    return { style: { fontFamily: `'${font.heading}', serif`, fontSize: 17, fontWeight: 600, color: ink, textTransform: opt === 'normal' ? 'none' : 'uppercase', letterSpacing: opt === 'spaced_upper' ? '.16em' : 0 }, text: 'Abc' }
  }
  if (tokenKey === 'image_style') {
    const base = { width: 32, height: 32, background: `${accent}66` }
    if (opt === 'rounded') return { style: { ...base, borderRadius: 10 }, text: '' }
    if (opt === 'arch') return { style: { ...base, borderRadius: '16px 16px 0 0' }, text: '' }
    if (opt === 'framed') return { style: { ...base, border: '3px solid #fff', boxShadow: `0 0 0 1px ${ink}` }, text: '' }
    return { style: base, text: '' }
  }
  if (tokenKey === 'background') {
    const fill = opt === 'match' ? mixHex(accent, '#FFFFFF', 0.9) : BACKGROUNDS[opt]
    return { style: { width: 40, height: 28, borderRadius: 5, border: '1px solid #b9c2ce', background: fill }, text: '' }
  }
  if (tokenKey === 'finish') {
    const fine = opt === 'refined'
    return { style: { fontFamily: `'${font.heading}', serif`, fontSize: 20, fontWeight: fine ? 400 : 700, letterSpacing: fine ? '-.03em' : 0, color: ink }, text: 'Aa' }
  }
  if (tokenKey === 'bands') {
    const wash = washColour(accent)
    return { style: { width: 40, height: 28, borderRadius: 5, border: '1px solid #b9c2ce', background: opt === 'wash' ? `linear-gradient(to bottom, #fff 0 33%, ${wash} 33% 66%, #fff 66%)` : '#fff' }, text: '' }
  }
  if (tokenKey === 'cards') {
    if (opt === 'bordered') return { style: { width: 34, height: 26, borderRadius: 5, border: '1.5px solid #8c97a6', background: '#fff' }, text: '' }
    if (opt === 'lifted') return { style: { width: 34, height: 26, borderRadius: 5, background: '#fff', boxShadow: '0 7px 10px -3px rgba(20,30,50,.4), 0 1px 2px rgba(20,30,50,.15)' }, text: '' }
    return { style: { width: 34, height: 26, borderRadius: 5, background: '#e3e8ee' }, text: '' }
  }
  return { style: { font: '700 14px sans-serif', color: ink }, text: { none: 'none', line: '━━', dot: '•', ornament: '◆' }[opt] || '' }
}

/** Styles for the mini-preview. `cur` = { entry (palette key or hex), font, tok }. */
export function previewStyles(cur) {
  const { accent, ground } = coloursOf(cur.entry)
  const t = { ...DEFAULT_TOKENS, ...(cur.tok || {}) }
  const font = FONT_PAIRINGS.find((f) => f.value === cur.font) || FONT_PAIRINGS[0]
  const bg = BACKGROUNDS[t.background] || ground
  const ink = '#211d1d', muted = '#6a6262'
  const onA = onColour(accent)
  const r = { sharp: 0, soft: 9, pill: 999 }[t.radius]
  const cr = { sharp: 0, soft: 12, pill: 22 }[t.radius]
  const pad = { airy: 30, regular: 22, compact: 13 }[t.density]
  const hf = `'${font.heading}', ${SERIF_HEADINGS.has(font.heading) ? 'serif' : 'sans-serif'}`
  const bf = `'${font.body}', sans-serif`
  const refined = t.finish === 'refined' && !['bold', 'friendly'].includes(font.group)  // SITE-1C-3d: light, tight headings
  const head = { fontFamily: hf, fontWeight: refined ? 400 : (HEADING_WEIGHT[font.heading] || 600), textTransform: t.heading_case === 'normal' ? 'none' : 'uppercase', letterSpacing: t.heading_case === 'spaced_upper' ? '.16em' : (refined && t.heading_case === 'normal' ? '-.02em' : 0), margin: 0 }
  const btnBase = { font: `600 11px ${bf}`, padding: '8px 16px', borderRadius: r, display: 'inline-block' }
  const btn = t.button === 'solid' ? { ...btnBase, background: accent, color: onA, border: `1.5px solid ${accent}` }
    : t.button === 'outline' ? { ...btnBase, background: 'transparent', color: accent, border: `1.5px solid ${accent}` }
      : { ...btnBase, background: 'transparent', color: accent, borderBottom: `2px solid ${accent}`, borderRadius: 0, padding: '8px 2px' }
  const shape = t.image_style === 'square' ? { borderRadius: 0 } : t.image_style === 'rounded' ? { borderRadius: 14 }
    : t.image_style === 'arch' ? { borderRadius: '999px 999px 0 0' } : { border: '6px solid #fff', boxShadow: `0 0 0 1px ${accent}66` }
  const fill = { background: `linear-gradient(155deg, ${accent}30, ${accent}99)` }
  const wash = washColour(accent)
  const line = mixHex(accent, '#FFFFFF', 0.78)
  const card = t.cards === 'bordered' ? { background: '#fff', border: `1px solid ${line}`, borderRadius: cr, padding: 10 }
    : t.cards === 'lifted' ? { background: '#fff', borderRadius: cr, padding: 10, boxShadow: '0 14px 30px -16px rgba(20,20,30,.35), 0 2px 6px rgba(20,20,30,.06)' }
      : { padding: 0 }
  const washed = t.bands === 'wash'
  return {
    accent, bg, wash, washed, t, hf, bf,
    root: { background: bg, color: ink, fontFamily: bf, width: '100%', boxSizing: 'border-box' },
    nav: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: `13px ${pad}px`, borderBottom: `1px solid ${accent}22` },
    brand: { ...head, fontSize: 16, color: accent },
    links: { font: `500 11px ${bf}`, color: muted },
    btn,
    hero: { padding: `${Math.round(pad * 1.7)}px ${pad}px`, color: '#fff', display: 'flex', flexDirection: 'column', gap: 11, background: `linear-gradient(180deg, rgba(0,0,0,.08), rgba(0,0,0,.66)), linear-gradient(135deg, ${accent}, ${accent}77)` },
    eyebrow: { font: `600 10px ${bf}`, letterSpacing: '.14em', textTransform: 'uppercase', opacity: 0.9 },
    h1: { ...head, fontSize: t.finish === 'refined' ? 34 : 28, lineHeight: t.finish === 'refined' ? 1 : 1.12, color: '#fff' },
    sub: { margin: 0, font: `400 12.5px ${bf}`, opacity: 0.92, maxWidth: 340 },
    btn1: { ...btnBase, background: accent, color: onA, border: `1.5px solid ${accent}` },
    btn2: t.button === 'underline' ? { ...btnBase, color: '#fff', borderBottom: '2px solid #fff', borderRadius: 0, padding: '8px 2px' } : { ...btnBase, color: '#fff', border: '1.5px solid #ffffffd0' },
    divRow: t.divider === 'none' ? { display: 'none' } : { display: 'flex', alignItems: 'center', gap: 12, padding: `${Math.round(pad * 0.7)}px ${pad}px 0`, color: accent },
    divSeg: { flex: 1, height: 1, background: `${accent}77` },
    divMark: t.divider === 'dot' ? '•' : t.divider === 'ornament' ? '◆' : '',
    divMarkSt: { font: `600 12px ${bf}`, color: accent },
    sec: (even) => ({ padding: `${pad}px`, background: washed && even ? wash : 'transparent' }),
    h2: { ...head, fontSize: 18, color: ink, marginBottom: 12 },
    tile: { width: 96, height: 106, flex: 'none', ...fill, ...shape },
    cap: { font: `600 11px ${bf}`, color: muted },
    card,
    cardImg: { height: 70, ...fill, ...shape },
    name: { font: `600 12px ${bf}`, color: ink },
    price: { font: `500 11.5px ${bf}`, color: muted },
    foot: { padding: `13px ${pad}px`, background: '#211d1d', color: bg, font: `600 11.5px ${bf}`, textAlign: 'center' },
    readable: contrast(accent, bg) >= 4.5,
  }
}

/** Short text for the summary line in the template form. */
export function lookSummary(value) {
  const p = (value.default_palettes || []).length
  const f = (value.allowed_fonts || []).length
  const o = Object.values(value.token_options || {}).reduce((n, l) => n + (l?.length || 0), 0)
  if (!p && !f && !o) return 'Nothing narrowed: new sites may use every colour, font and option.'
  return `${p} colour${p === 1 ? '' : 's'} \u00b7 ${f} font pairing${f === 1 ? '' : 's'} \u00b7 ${o} look option${o === 1 ? '' : 's'} ticked`
}

// ---- shared look-picker pieces (used by LookStudio and LookPicker) ----
export const TEAL = '#0d7f8a'
export const LABEL_STYLE = { fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: '#7A9BAD', marginBottom: 8 }
export const tileStyle = (on) => ({
  position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8,
  minWidth: 88, padding: '12px 10px', borderRadius: 10, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#0a1a24', fontFamily: 'inherit',
  background: on ? '#e6f4f5' : '#fff', border: `1.5px solid ${on ? TEAL : '#d5dbe3'}`,
})

// Mirrors site_design_registry.THEME_META (a parity test keeps them in step).
export const THEME_FONT_GROUPS = { atelier: ['elegant', 'editorial'], market: ['bold', 'friendly'], studio: ['minimal', 'friendly', 'editorial'] }
export const THEME_DEFAULT_FONT = { atelier: 'bodoni_jost', market: 'anton_manrope', studio: 'fraunces_karla' }
// What a theme looks like when a site sets no design option (approximate, for the preview only).
export const THEME_DEFAULT_TOKENS = { atelier: { radius: 'sharp' }, market: { radius: 'pill', heading_case: 'upper' }, studio: { radius: 'soft' } }

/** The `cur` the mini-preview needs, from a saved recipe. */
export function curFromRecipe(recipe) {
  const theme = recipe.theme || 'atelier'
  const tok = { ...DEFAULT_TOKENS, ...(THEME_DEFAULT_TOKENS[theme] || {}) }
  Object.entries(recipe.tokens || {}).forEach(([k, v]) => { if (v) tok[k] = v })
  return { entry: recipe.custom_colour || recipe.palette || 'berry', font: recipe.fonts || THEME_DEFAULT_FONT[theme] || 'bodoni_jost', tok }
}
