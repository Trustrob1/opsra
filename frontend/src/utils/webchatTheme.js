/**
 * frontend/src/utils/webchatTheme.js
 * The look of the web chat page: classic (today's teal) plus three Opsra looks an owner can choose in Chat settings.
 * Pure data so it can be tested without a browser. The page reads every colour from the tokens returned here.
 *   classic  : the original look, unchanged (colour comes from the business's own colour setting)
 *   blue     : Opsra blue, light
 *   midnight : dark charcoal with blue
 *   ink      : white and near-black with blue used for actions only
 */
export const OLD_DEFAULT_COLOUR = '#028090'     // the colour every business had before the Opsra looks: treated as "not customised"
export const OPSRA_BLUE = '#2467E3'
export const THEME_IDS = ['classic', 'blue', 'midnight', 'ink']
export const THEME_LABELS = {
  classic: 'Classic (teal)',
  blue: 'Opsra blue',
  midnight: 'Midnight (dark)',
  ink: 'Ink and blue',
}
export const THEME_HINTS = {
  classic: 'The original look. Uses the colour you pick below.',
  blue: 'Light and friendly. Matches the Opsra business page.',
  midnight: 'Dark charcoal with blue. Best for dark websites.',
  ink: 'Clean white and black, with blue only on the buttons.',
}

const CLASSIC = { ink: '#14222B', muted: '#566770', line: '#DCE4E8', fieldLine: '#B9C6CC', bg: '#F4F7F8', surface: '#FFFFFF', quote: '#F0F4F5',
  botBg: '#FFFFFF', botBorder: true, font: "'DM Sans', system-ui, sans-serif", dark: false, scrim: 'rgba(20,34,43,0.55)', online: '#22C55E', error: '#B3261E', errorBg: '#FBE9E7' }
const HANKEN = "'Hanken Grotesk', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
const TOKENS = {
  classic: CLASSIC,
  blue: { ...CLASSIC, ink: '#1B1F28', muted: '#5B6270', line: '#E1E5EC', fieldLine: '#B4BBC8', bg: '#F4F6FB', quote: '#EEF2FA', font: HANKEN, online: '#2E9E5B', scrim: 'rgba(20,24,31,0.55)' },
  midnight: { ...CLASSIC, ink: '#F2F4F8', muted: '#A5ADBB', line: '#2A303B', fieldLine: '#3A4252', bg: '#14181F', surface: '#1B2029', quote: '#262D3A',
    botBg: '#1B2029', font: HANKEN, dark: true, scrim: 'rgba(0,0,0,0.6)', online: '#34D399', error: '#FFB4AB', errorBg: '#3A1F1F' },
  ink: { ...CLASSIC, ink: '#1B1F28', muted: '#5B6270', line: '#E9ECF2', fieldLine: '#B4BBC8', bg: '#FFFFFF', quote: '#E6E9F0', botBg: '#F1F3F7', botBorder: false, font: HANKEN, online: '#2E9E5B', scrim: 'rgba(20,24,31,0.55)' },
}

export function normaliseTheme(id) {
  return THEME_IDS.includes(id) ? id : 'classic'
}

/** Accent colour: the business's own colour, except that an untouched old default becomes Opsra blue in the new looks. */
export function accentFor(id, brand) {
  const b = /^#[0-9a-fA-F]{6}$/.test(brand || '') ? brand : OLD_DEFAULT_COLOUR
  const t = normaliseTheme(id)
  if (t !== 'classic' && b.toLowerCase() === OLD_DEFAULT_COLOUR) return OPSRA_BLUE
  return b
}

/** Everything the page needs to colour itself. */
export function themeTokens(id, brand) {
  const t = normaliseTheme(id)
  const base = TOKENS[t]
  const accent = accentFor(t, brand)
  // the visitor's bubble: the accent, except in the ink look where it is near-black
  const meBg = t === 'ink' ? '#1B1F28' : accent
  return { ...base, id: t, brand: accent, meBg, meInk: '#FFFFFF', onBrand: '#FFFFFF' }
}
