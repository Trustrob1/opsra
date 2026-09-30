/**
 * frontend/src/modules/sites/sitesKit.js
 * SITE-1A part 2 — non-component helpers for the Sites module: design tokens,
 * formatters, status maps, style injection, toast state.
 * Mirrors modules/funnels/funnelKit.js's conventions (same ds.js tokens, same
 * Africa/Lagos formatting) so Sites reads like the same app as Event Funnels.
 * Components live in sitesUi.jsx (kept separate so React Fast Refresh works).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ds } from '../../utils/ds'

export const T = {
  ink: '#0a1a24',
  muted: '#7A9BAD',
  soft: '#4A6272',
  line: '#E4EEF2',
  lineStrong: '#D1D5DB',
  page: ds.light,
  card: ds.white,
  teal: ds.teal,
  tealDark: ds.tealDark,
  mint: ds.mint,
  good: '#1E8E4F', goodBg: '#E8F6EE',
  warn: '#9A6200', warnBg: '#FDF4E3',
  bad: '#C0392B', badBg: '#FDECEA',
  info: '#0E6E7C', infoBg: '#E6F4F6',
  neutral: '#5B6B78', neutralBg: '#F1F4F6',
}

export const SPACE = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }

export function useSitesStyles() {
  useEffect(() => {
    if (document.getElementById('sts-styles')) return
    const s = document.createElement('style')
    s.id = 'sts-styles'
    s.textContent = `
      .sts :is(button,a,input,select,textarea,[tabindex]):focus-visible{outline:2px solid ${ds.teal};outline-offset:2px;border-radius:8px}
      .sts .tnum{font-variant-numeric:tabular-nums}
      .sts .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
      .sts h1,.sts h2,.sts h3{text-wrap:balance}
      .sts p{text-wrap:pretty}
      .sts .spin{animation:spin 1s linear infinite}
      .sts .sts-row:hover{background:#F7FBFC}
      .sts ::selection{background:${ds.mint}}
      @media (prefers-reduced-motion: reduce){.sts *{animation:none !important;transition:none !important}}
    `
    document.head.appendChild(s)
  }, [])
}

const TZ = 'Africa/Lagos'

export const money = (n, cur = 'NGN') => {
  if (n === null || n === undefined || n === '' || Number.isNaN(Number(n))) return '—'
  const s = Math.round(Number(n)).toLocaleString('en-NG')
  return cur === 'NGN' ? `₦${s}` : `${cur} ${s}`
}

export const num = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('en-NG'))

export const dateTime = (iso) => {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso))
}

export const dateOnly = (iso) => {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso))
}

export const INPUT = {
  width: '100%', boxSizing: 'border-box', padding: '9px 11px', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
  fontSize: 13.5, fontFamily: 'inherit', color: T.ink, background: '#fff', minHeight: 40,
}

export const TEXTAREA = { ...INPUT, minHeight: 88, resize: 'vertical', lineHeight: 1.5 }

// site_renderer.py's registries, mirrored here for the picker UIs (Templates + Sites design tab).
export const THEMES = [
  { value: 'atelier', label: 'Atelier', hint: 'Elegant — serif display, fine borders' },
  { value: 'market', label: 'Market', hint: 'Bold — heavy display, rounded buttons' },
  { value: 'studio', label: 'Studio', hint: 'Minimal — clean sans, generous space' },
]

// site_design_registry.py's palettes, mirrored (tests/unit/test_site_design.py checks they stay in step).
export const PALETTES = [
  { value: 'berry', label: 'Berry', accent: '#7A2E4A', ground: '#F4F0EE', niches: ['boutique', 'salon'], personality: ['elegant', 'warm'] },
  { value: 'cobalt', label: 'Cobalt', accent: '#1F3FD1', ground: '#FFFFFF', niches: ['services', 'restaurant', 'boutique'], personality: ['bold', 'minimal'] },
  { value: 'sage', label: 'Sage', accent: '#35664A', ground: '#F2F4EF', niches: ['salon', 'services', 'boutique'], personality: ['minimal', 'warm'] },
  { value: 'terracotta', label: 'Terracotta', accent: '#B4441F', ground: '#FAF3EC', niches: ['restaurant', 'boutique', 'salon'], personality: ['warm', 'playful'] },
  { value: 'midnight', label: 'Midnight', accent: '#1E3A5F', ground: '#F7F5F0', niches: ['services', 'boutique', 'salon'], personality: ['elegant', 'minimal'] },
  { value: 'emerald', label: 'Emerald', accent: '#0F6B4F', ground: '#F1F7F4', niches: ['restaurant', 'services', 'salon'], personality: ['warm', 'elegant'] },
  { value: 'gold', label: 'Gold', accent: '#8A6414', ground: '#FBF8F1', niches: ['boutique', 'salon', 'restaurant'], personality: ['elegant'] },
  { value: 'blush', label: 'Blush', accent: '#B03A5B', ground: '#FDF3F3', niches: ['salon', 'boutique', 'restaurant'], personality: ['playful', 'elegant', 'warm'] },
  { value: 'plum', label: 'Plum', accent: '#5B2A86', ground: '#F6F1F7', niches: ['boutique', 'salon', 'services'], personality: ['elegant', 'bold'] },
  { value: 'coral', label: 'Coral', accent: '#C03434', ground: '#FFF7F3', niches: ['restaurant', 'boutique', 'salon'], personality: ['playful', 'bold'] },
  { value: 'teal', label: 'Teal', accent: '#0E6B78', ground: '#F0F7F7', niches: ['services', 'salon', 'restaurant'], personality: ['minimal', 'playful'] },
  { value: 'mustard', label: 'Mustard', accent: '#8A5A00', ground: '#FFFBF0', niches: ['restaurant', 'boutique', 'services'], personality: ['warm', 'bold'] },
  { value: 'charcoal', label: 'Charcoal', accent: '#222222', ground: '#F5F5F3', niches: ['boutique', 'services', 'salon'], personality: ['minimal', 'elegant'] },
  { value: 'royal', label: 'Royal', accent: '#B3122A', ground: '#FFFFFF', niches: ['services', 'restaurant', 'boutique'], personality: ['bold', 'elegant'] },
  { value: 'forest', label: 'Forest', accent: '#2F5D1F', ground: '#F3F5EE', niches: ['restaurant', 'services', 'salon'], personality: ['warm', 'minimal'] },
  { value: 'sky', label: 'Sky', accent: '#1D6FB8', ground: '#F4F9FD', niches: ['services', 'salon', 'boutique'], personality: ['minimal', 'playful'] },
  { value: 'rose_gold', label: 'Rose Gold', accent: '#A2544B', ground: '#FBF4F1', niches: ['salon', 'boutique', 'restaurant'], personality: ['elegant', 'warm'] },
  { value: 'sunset', label: 'Sunset', accent: '#C2410C', ground: '#FFF9F2', niches: ['restaurant', 'boutique', 'salon'], personality: ['bold', 'playful'] },
  { value: 'olive', label: 'Olive', accent: '#5F6B1B', ground: '#F6F5EC', niches: ['restaurant', 'services', 'salon'], personality: ['warm', 'minimal'] },
  { value: 'mist', label: 'Mist', accent: '#4B4BA8', ground: '#F5F5F9', niches: ['services', 'salon', 'boutique'], personality: ['minimal', 'elegant'] },
  { value: 'cocoa', label: 'Cocoa', accent: '#6B3E26', ground: '#F8F2EC', niches: ['restaurant', 'boutique', 'salon'], personality: ['warm', 'elegant'] },
]

// SITE-1C-1: font pairings, grouped by personality (mirrors site_design_registry.FONT_PAIRINGS).
export const FONT_GROUP_LABELS = { elegant: 'Elegant', editorial: 'Editorial', bold: 'Bold', friendly: 'Friendly', minimal: 'Minimal' }
export const FONT_PAIRINGS = [
  { value: 'bodoni_jost', label: 'Bodoni + Jost', group: 'elegant', heading: 'Bodoni Moda', body: 'Jost' },
  { value: 'anton_manrope', label: 'Anton + Manrope', group: 'bold', heading: 'Anton', body: 'Manrope' },
  { value: 'fraunces_karla', label: 'Fraunces + Karla', group: 'editorial', heading: 'Fraunces', body: 'Karla' },
  { value: 'playfair_lato', label: 'Playfair + Lato', group: 'elegant', heading: 'Playfair Display', body: 'Lato' },
  { value: 'cormorant_jost', label: 'Cormorant + Jost', group: 'elegant', heading: 'Cormorant Garamond', body: 'Jost' },
  { value: 'cormorant_dmsans', label: 'Cormorant + DM Sans', group: 'elegant', heading: 'Cormorant Garamond', body: 'DM Sans' },
  { value: 'dmserif_dmsans', label: 'DM Serif + DM Sans', group: 'editorial', heading: 'DM Serif Display', body: 'DM Sans' },
  { value: 'archivo_worksans', label: 'Archivo Black + Work Sans', group: 'bold', heading: 'Archivo Black', body: 'Work Sans' },
  { value: 'syne_dmsans', label: 'Syne + DM Sans', group: 'bold', heading: 'Syne', body: 'DM Sans' },
  { value: 'poppins_nunito', label: 'Poppins + Nunito', group: 'friendly', heading: 'Poppins', body: 'Nunito' },
  { value: 'lora_nunito', label: 'Lora + Nunito', group: 'friendly', heading: 'Lora', body: 'Nunito' },
  { value: 'jakarta_inter', label: 'Plus Jakarta + Inter', group: 'minimal', heading: 'Plus Jakarta Sans', body: 'Inter' },
  { value: 'sora_karla', label: 'Sora + Karla', group: 'minimal', heading: 'Sora', body: 'Karla' },
]

// SITE-1C-1: design tokens (mirrors site_design_registry.TOKENS) and the options a theme does not support.
export const TOKENS = [
  { key: 'radius', label: 'Corners', options: [{ value: 'sharp', label: 'Sharp' }, { value: 'soft', label: 'Soft' }, { value: 'pill', label: 'Pill' }] },
  { key: 'density', label: 'Spacing', options: [{ value: 'airy', label: 'Airy' }, { value: 'regular', label: 'Regular' }, { value: 'compact', label: 'Compact' }] },
  { key: 'button', label: 'Buttons', options: [{ value: 'solid', label: 'Solid' }, { value: 'outline', label: 'Outline' }, { value: 'underline', label: 'Underline' }] },
  { key: 'heading_case', label: 'Headings', options: [{ value: 'normal', label: 'Normal' }, { value: 'upper', label: 'UPPERCASE' }, { value: 'spaced_upper', label: 'SPACED UPPERCASE' }] },
  { key: 'image_style', label: 'Photos', options: [{ value: 'square', label: 'Square' }, { value: 'rounded', label: 'Rounded' }, { value: 'arch', label: 'Arch' }, { value: 'framed', label: 'Framed' }] },
  { key: 'divider', label: 'Section divider', options: [{ value: 'none', label: 'None' }, { value: 'line', label: 'Line' }, { value: 'dot', label: 'Dot' }, { value: 'ornament', label: 'Ornament' }] },
  // SITE-1C-1b: page background, alternating section bands, card style (first option = no change).
  { key: 'background', label: 'Page background', options: [{ value: 'match', label: 'Match colour' }, { value: 'white', label: 'White' }, { value: 'grey', label: 'Soft grey' }, { value: 'ivory', label: 'Warm ivory' }] },
  { key: 'bands', label: 'Section bands', options: [{ value: 'plain', label: 'Plain' }, { value: 'wash', label: 'Tinted bands' }] },
  { key: 'cards', label: 'Cards', options: [{ value: 'flat', label: 'Flat' }, { value: 'bordered', label: 'Bordered' }, { value: 'lifted', label: 'Lifted' }, { value: 'tile', label: 'Tile' }] },
  // SITE-1C-3d: big light headings, roomier spacing, floating header, photo hover, dark story band, floating WhatsApp button.
  // SITE-1C-3e: how tall a Full photo hero is (only affects the Full photo layout).
  { key: 'hero_height', label: 'Hero height', options: [{ value: 'standard', label: 'Standard' }, { value: 'tall', label: 'Nearly full screen' }] },
  { key: 'finish', label: 'Refined look', options: [{ value: 'standard', label: 'Standard' }, { value: 'refined', label: 'Refined' }] },
]
export const THEME_TOKEN_EXCLUSIONS = { atelier: { radius: ['pill'] } }

// SITE-1C-3: the list is also the natural page order (announcement bar first, hours & location last).
export const SECTION_KEYS = ['announcement', 'hero', 'about', 'process', 'items', 'menu', 'categories', 'gallery', 'team', 'reviews', 'faq', 'order', 'visit']
export const SECTION_LABELS = {
  hero: 'Hero', about: 'About', items: 'Items / Shop', categories: 'Categories', reviews: 'Reviews', order: 'How to order',
  announcement: 'Announcement bar', faq: 'FAQ', menu: 'Price list', visit: 'Hours & location', process: 'How we work', team: 'Team', gallery: 'Gallery',
}
/** Add a section to a template's list at its natural place, without reordering what is already there
 *  (a template keeps whatever order it was saved with; new tiles slot in after the closest earlier section). */
export function insertSection(list, key) {
  if (list.includes(key)) return list
  const at = SECTION_KEYS.indexOf(key)
  let pos = 0
  list.forEach((k, i) => { if (SECTION_KEYS.indexOf(k) < at) pos = i + 1 })
  return [...list.slice(0, pos), key, ...list.slice(pos)]
}
export const SECTION_HINTS = {
  hero: 'The big opening banner with your headline and button.',
  about: 'Your story, in a few lines.',
  items: 'Your products or services, with prices and an order button.',
  categories: 'Browse by type, so people jump straight to what they want.',
  reviews: 'What happy customers say about you.',
  order: 'How to order, in simple numbered steps.',
  announcement: 'One short line in a bar above the menu: a promo or delivery cut-off.',
  faq: 'Questions customers keep asking, with your answers.',
  menu: 'A price list or menu: groups of priced lines.',
  visit: 'Opening hours, address and an ask-for-directions button.',
  process: 'How a job goes from first message to done, step by step.',
  team: 'The people behind the business, with photos.',
  gallery: 'A grid of photos of your work.',
}
// site_renderer.SECTION_VARIANTS, mirrored (the first layout of each section is the default).
// tests/unit/test_site_design_frontend_parity.py keeps this in step with the server.
export const SECTION_LAYOUTS = {
  hero: [{ value: 'fullbleed', label: 'Full photo' }, { value: 'collage', label: 'Collage' }, { value: 'centered', label: 'Centred' }],
  items: [{ value: 'grid', label: 'Grid' }, { value: 'rows', label: 'Rows' }, { value: 'featured', label: 'Featured' }],
  about: [{ value: 'left', label: 'Photo left' }, { value: 'right', label: 'Photo right' }, { value: 'quote', label: 'Quote' }],
  reviews: [{ value: 'cards', label: 'Cards' }, { value: 'spotlight', label: 'Spotlight' }, { value: 'list', label: 'List' }],
  categories: [{ value: 'tiles', label: 'Tiles' }, { value: 'chips', label: 'Chips' }],
  order: [{ value: 'steps', label: 'Steps' }],
  announcement: [{ value: 'bar', label: 'Bar' }],
  faq: [{ value: 'list', label: 'Accordion' }, { value: 'columns', label: 'Columns' }],
  menu: [{ value: 'list', label: 'List' }, { value: 'columns', label: 'Columns' }],
  visit: [{ value: 'split', label: 'Split' }, { value: 'card', label: 'Card' }],
  process: [{ value: 'numbered', label: 'Numbered' }, { value: 'timeline', label: 'Timeline' }],
  team: [{ value: 'cards', label: 'Cards' }, { value: 'list', label: 'List' }],
  gallery: [{ value: 'grid', label: 'Grid' }, { value: 'masonry', label: 'Masonry' }],
}

export const SITE_STATUS = {
  brief_in_progress: { tone: 'neutral', label: 'Brief in progress' },
  brief_complete: { tone: 'info', label: 'Brief complete' },
  generating: { tone: 'info', label: 'Generating' },
  preview_ready: { tone: 'good', label: 'Preview ready' },
  revising: { tone: 'warn', label: 'Revising' },
  hosting_checkout: { tone: 'warn', label: 'Checkout' },
  awaiting_payment: { tone: 'warn', label: 'Awaiting payment' },
  paid: { tone: 'good', label: 'Paid' },
  publishing: { tone: 'info', label: 'Publishing' },
  live: { tone: 'good', label: 'Live' },
  renewal_due: { tone: 'warn', label: 'Renewal due' },
  lapsed: { tone: 'bad', label: 'Lapsed' },
  cancelled: { tone: 'neutral', label: 'Cancelled' },
}

export const BUILDER_STATUS = {
  active: { tone: 'good', label: 'Active' },
  inactive: { tone: 'neutral', label: 'Inactive' },
  suspended: { tone: 'bad', label: 'Suspended' },
}

export const ORDER_STATUS = {
  pending_payment: { tone: 'neutral', label: 'Awaiting payment' },
  awaiting_approval: { tone: 'warn', label: 'Needs approval' },
  fulfilling: { tone: 'info', label: 'Being set up' },
  live: { tone: 'good', label: 'Live' },
  rejected: { tone: 'bad', label: 'Rejected' },
  refund_pending: { tone: 'warn', label: 'Refund due' },
  refunded: { tone: 'neutral', label: 'Refunded' },
  needs_builder_choice: { tone: 'warn', label: 'Needs a new domain' },
  expired: { tone: 'neutral', label: 'Expired' },
}

export const JOB_STATUS = {
  queued: { tone: 'neutral', label: 'Queued' },
  in_progress: { tone: 'info', label: 'In progress' },
  blocked: { tone: 'warn', label: 'Blocked' },
  done: { tone: 'good', label: 'Done' },
}

/** Hosting-job clock: green → amber 12 h before due → red once overdue (spec §11.4). */
export const SLA = {
  green: { tone: 'good', label: 'On track' },
  amber: { tone: 'warn', label: 'Due soon' },
  red: { tone: 'bad', label: 'Overdue' },
  done: { tone: 'neutral', label: 'Done' },
  none: { tone: 'neutral', label: 'No deadline' },
}

export const DOMAIN_STATUS = {
  active: { tone: 'good', label: 'Active' },
  expiring: { tone: 'warn', label: 'Expiring' },
  lapsed: { tone: 'bad', label: 'Lapsed' },
  transferred: { tone: 'neutral', label: 'Transferred' },
}

/** 84_300 → "23h 25m left" · -7_500 → "2h 05m overdue". */
export function formatCountdown(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const overdue = seconds < 0
  const total = Math.abs(Math.floor(seconds))
  const d = Math.floor(total / 86400)
  const h = Math.floor((total % 86400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const text = d > 0 ? `${d}d ${h}h` : `${h}h ${String(m).padStart(2, '0')}m`
  return overdue ? `${text} overdue` : `${text} left`
}

/** Re-renders on an interval while `active` — drives the live SLA countdowns. */
export function useNow(active, everyMs = 30000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return undefined
    const kick = setTimeout(() => setNow(Date.now()), 0) // refresh straight away when the tab is opened
    const t = setInterval(() => setNow(Date.now()), everyMs)
    return () => { clearTimeout(kick); clearInterval(t) }
  }, [active, everyMs])
  return now
}

/** Toast state. const [toast, show] = useToast(); show('Saved') / show('Failed', 'bad'); render <Toast t={toast} /> */
export function useToast() {
  const [t, setT] = useState(null)
  const timer = useRef(null)
  const show = useCallback((text, tone = 'good') => {
    setT({ text, tone })
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setT(null), tone === 'bad' ? 6000 : 3200)
  }, [])
  useEffect(() => () => clearTimeout(timer.current), [])
  return [t, show]
}
