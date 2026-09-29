/**
 * frontend/src/modules/sites/sitesOpsUi.jsx
 * SITE-3 part 3 — small shared pieces for the Orders / Hosting queue / Domains tabs
 * (table cells, key–value rows, a labelled amount line). Same tokens as sitesUi.jsx.
 */
import { T, money } from './sitesKit'

export function Th({ children, align = 'left' }) {
  return (
    <th style={{ textAlign: align, fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase',
      letterSpacing: '.6px', padding: '10px 12px', whiteSpace: 'nowrap' }}>{children}</th>
  )
}

export function Td({ children, className, align = 'left', style }) {
  return (
    <td className={className} style={{ padding: '11px 12px', color: T.ink, verticalAlign: 'middle', textAlign: align, ...style }}>{children}</td>
  )
}

/** A label above a value — used in drawers and cards. */
export function Fact({ label, children }) {
  return (
    <div style={{ minWidth: 0 }}>
      <p style={{ margin: 0, fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px' }}>{label}</p>
      <div style={{ margin: '3px 0 0', fontSize: 13.5, color: T.ink, overflowWrap: 'anywhere' }}>{children ?? '—'}</div>
    </div>
  )
}

/** One line of a price breakdown: label on the left, tabular amount on the right. */
export function AmountLine({ label, value, strong, muted, sign }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '5px 0', fontSize: 13,
      fontWeight: strong ? 700 : 400, color: muted ? T.muted : T.ink, borderTop: strong ? `1px solid ${T.line}` : 'none', marginTop: strong ? 4 : 0 }}>
      <span>{label}</span>
      <span className="tnum">{sign}{money(value)}</span>
    </div>
  )
}

/** Count pill shown on a tab. tone: 'warn' | 'bad'. */
export function CountPill({ n, tone = 'warn', label }) {
  if (!n) return null
  const bg = tone === 'bad' ? T.bad : T.warn
  return (
    <span className="tnum" title={label} aria-label={label ? `${n} ${label}` : String(n)}
      style={{ minWidth: 18, height: 18, padding: '0 5px', borderRadius: 9, background: bg, color: '#fff', fontSize: 11,
        fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>{n}</span>
  )
}
