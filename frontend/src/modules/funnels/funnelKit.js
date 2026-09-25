/**
 * frontend/src/modules/funnels/funnelKit.js
 * FUNNEL-1B — non-component helpers for the Event Funnels module: design tokens,
 * formatters (all Africa/Lagos time), status maps, style injection, toast state, clipboard.
 * Components live in funnelUi.jsx (kept separate so React Fast Refresh works).
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
  // chart series (validated with the dataviz palette validator: CVD ΔE 17.3, normal ΔE 27.2, both ≥ 3:1 on white)
  seriesLeads: '#0092A6',
  seriesPaid: '#D9621F',
  // status (reserved — always shipped with an icon or label)
  good: '#1E8E4F', goodBg: '#E8F6EE',
  warn: '#9A6200', warnBg: '#FDF4E3',
  bad: '#C0392B', badBg: '#FDECEA',
  info: '#0E6E7C', infoBg: '#E6F4F6',
  neutral: '#5B6B78', neutralBg: '#F1F4F6',
}

export const SPACE = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }

// One-time style block: focus rings, tabular numbers, spinner, reduced motion.

export function useFunnelStyles() {
  useEffect(() => {
    if (document.getElementById('fnl-styles')) return
    const s = document.createElement('style')
    s.id = 'fnl-styles'
    s.textContent = `
      .fnl :is(button,a,input,select,textarea,[tabindex]):focus-visible{outline:2px solid ${ds.teal};outline-offset:2px;border-radius:8px}
      .fnl .tnum{font-variant-numeric:tabular-nums}
      .fnl .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
      .fnl h1,.fnl h2,.fnl h3{text-wrap:balance}
      .fnl p{text-wrap:pretty}
      .fnl .spin{animation:spin 1s linear infinite}
      .fnl .fnl-row:hover{background:#F7FBFC}
      .fnl input[type=range]{accent-color:${ds.teal}}
      .fnl ::selection{background:${ds.mint}}
      @media (prefers-reduced-motion: reduce){.fnl *{animation:none !important;transition:none !important}}
    `
    document.head.appendChild(s)
  }, [])
}

/** Normalise list responses: some services return the array, others the axios response. */
export const asList = (r) => (Array.isArray(r) ? r : Array.isArray(r?.data?.data) ? r.data.data : Array.isArray(r?.data) ? r.data : [])

const TZ = 'Africa/Lagos'

export const money = (n, cur = 'NGN') => {
  if (n === null || n === undefined || n === '' || Number.isNaN(Number(n))) return '—'
  const s = Math.round(Number(n)).toLocaleString('en-NG')  // whole naira everywhere
  return cur === 'NGN' ? `₦${s}` : `${cur} ${s}`
}

export const num = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('en-NG'))

export const pct = (x) => (x === null || x === undefined ? '—' : `${(Number(x) * 100).toFixed(1)}%`)

export const dateTime = (iso) => {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso))
}

export const dateOnly = (iso) => {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(iso))
}

export const ago = (iso) => {
  if (!iso) return '—'
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}

/** ISO → value for <input type="datetime-local">, in Lagos time. */
export const toLocalInput = (iso) => {
  if (!iso) return ''
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: TZ, year: 'numeric', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}T${p.hour === '24' ? '00' : p.hour}:${p.minute}`
}

/** <input type="datetime-local"> value (Lagos wall time) → ISO with +01:00. */
export const fromLocalInput = (v) => (v ? `${v}:00+01:00` : null)

export const todayLagos = () => toLocalInput(new Date().toISOString()).slice(0, 10)

export const INPUT = {
  width: '100%', boxSizing: 'border-box', padding: '9px 11px', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
  fontSize: 13.5, fontFamily: 'inherit', color: T.ink, background: '#fff', minHeight: 40,
}

export const FUNNEL_STATUS = {
  draft: { tone: 'neutral', label: 'Draft' },
  active: { tone: 'good', label: 'Live' },
  closed: { tone: 'warn', label: 'Closed' },
}

export const REG_STATUS = {
  new: { tone: 'info', label: 'Not paid' },
  paid: { tone: 'good', label: 'Paid' },
  closed_unpaid: { tone: 'neutral', label: 'Closed' },
  opted_out: { tone: 'bad', label: 'Opted out' },
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

/** Copy text; falls back to a hidden textarea when the Clipboard API is blocked. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    ta.remove()
    return ok
  }
}
