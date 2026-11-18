import assert from 'node:assert/strict'
import { themeTokens, normaliseTheme, accentFor, THEME_IDS, THEME_LABELS, THEME_HINTS, OPSRA_BLUE } from './webchatTheme.js'

// unknown or missing theme = classic, which keeps today's exact colours
assert.equal(normaliseTheme(undefined), 'classic'); assert.equal(normaliseTheme('neon'), 'classic'); assert.equal(normaliseTheme('midnight'), 'midnight')
const c = themeTokens(undefined, '#028090')
assert.equal(c.id, 'classic'); assert.equal(c.brand, '#028090'); assert.equal(c.ink, '#14222B'); assert.equal(c.muted, '#566770')
assert.equal(c.line, '#DCE4E8'); assert.equal(c.bg, '#F4F7F8'); assert.equal(c.surface, '#FFFFFF'); assert.equal(c.meBg, '#028090'); assert.equal(c.dark, false)
assert.ok(c.font.startsWith("'DM Sans'"))
// the new looks turn the untouched old default colour into Opsra blue, but never override a colour the owner chose
for (const id of ['blue', 'midnight', 'ink']) {
  assert.equal(themeTokens(id, '#028090').brand, OPSRA_BLUE, id)
  assert.equal(themeTokens(id, '#028090').font.startsWith("'Hanken Grotesk'"), true, id)
  assert.equal(themeTokens(id, '#E8590C').brand, '#E8590C', id)
}
assert.equal(themeTokens('classic', '#028090').brand, '#028090')
assert.equal(accentFor('blue', 'not a colour'), OPSRA_BLUE)             // bad value falls back to the old default, then to blue
assert.equal(accentFor('classic', 'not a colour'), '#028090')
// midnight is dark: light text, dark surfaces
const m = themeTokens('midnight', '#028090')
assert.equal(m.dark, true); assert.equal(m.surface, '#1B2029'); assert.equal(m.bg, '#14181F'); assert.equal(m.ink, '#F2F4F8')
// ink look: dark visitor bubble, grey borderless bot bubble
const k = themeTokens('ink', '#028090')
assert.equal(k.meBg, '#1B1F28'); assert.equal(k.botBorder, false); assert.equal(k.botBg, '#F1F3F7'); assert.equal(k.bg, '#FFFFFF')
// every theme has a label and a hint; text/background pairs are readable (contrast >= 4.5)
const lum = (hex) => { const n = parseInt(hex.slice(1), 16); const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }; return 0.2126 * f(n >> 16) + 0.7152 * f((n >> 8) & 255) + 0.0722 * f(n & 255) }
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
for (const id of THEME_IDS) {
  assert.ok(THEME_LABELS[id] && THEME_HINTS[id], id)
  const t = themeTokens(id, '#028090')
  assert.ok(ratio(t.ink, t.bg) >= 4.5, `${id} ink on bg`)
  assert.ok(ratio(t.ink, t.surface) >= 4.5, `${id} ink on surface`)
  assert.ok(ratio(t.muted, t.bg) >= 4.5, `${id} muted on bg`)
  assert.ok(ratio(t.muted, t.surface) >= 4.5, `${id} muted on surface`)
  assert.ok(ratio(t.meInk, t.meBg) >= 4.5, `${id} text on the visitor bubble`)
  assert.ok(ratio(t.ink, t.botBg) >= 4.5, `${id} text on the bot bubble`)
}
console.log('webchatTheme: all tests passed')
