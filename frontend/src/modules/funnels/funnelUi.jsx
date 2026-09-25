/**
 * frontend/src/modules/funnels/funnelUi.jsx
 * FUNNEL-1B — shared UI components for the Event Funnels module.
 *
 * Matches Opsra's existing look (ds.js tokens, Poppins, white cards on #F5FAFB,
 * #E4EEF2 borders, #0a1a24 ink, #7A9BAD muted) — same family as SalesRecordTab / Business Activities.
 * Finish rules: tabular numbers wherever figures line up, visible :focus-visible
 * rings, 44px tap targets on mobile, Lucide icons only (no emoji in UI chrome),
 * text in ink/muted tokens (never in a series colour).
 * Tokens, formatters and hooks: funnelKit.js.
 */
import { useEffect, useRef, useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import { ds } from '../../utils/ds'
import { T } from './funnelKit'

export function Card({ children, style, pad = 18, ...rest }) {
  return (
    <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 12, padding: pad,
      boxShadow: ds.cardShadow, ...style }} {...rest}>{children}</div>
  )
}

export function SectionTitle({ title, hint, right }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
      <div>
        <h3 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: T.ink }}>{title}</h3>
        {hint && <p style={{ margin: '3px 0 0', fontSize: 12.5, color: T.muted, maxWidth: 640 }}>{hint}</p>}
      </div>
      {right}
    </div>
  )
}

export function Eyebrow({ children, style }) {
  return <p style={{ fontSize: 10.5, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '0.9px', margin: 0, ...style }}>{children}</p>
}

export function Kpi({ label, value, sub, tone, icon: Icon }) {
  const color = tone === 'bad' ? T.bad : tone === 'warn' ? T.warn : T.ink
  return (
    <Card pad={16} style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {Icon && <Icon size={13} color={T.muted} strokeWidth={2} aria-hidden="true" />}
        <Eyebrow>{label}</Eyebrow>
      </div>
      <p className="tnum" style={{ margin: '8px 0 0', fontSize: 24, fontWeight: 700, color, lineHeight: 1.1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</p>
      {sub && <p className="tnum" style={{ margin: '4px 0 0', fontSize: 11.5, color: T.muted }}>{sub}</p>}
    </Card>
  )
}

const BTN = {
  primary:   { bg: T.teal, fg: '#fff', bd: T.teal, hover: T.tealDark },
  secondary: { bg: '#fff', fg: T.ink, bd: T.lineStrong, hover: '#F5FAFB' },
  ghost:     { bg: 'transparent', fg: T.teal, bd: 'transparent', hover: T.mint },
  danger:    { bg: '#fff', fg: T.bad, bd: '#F2C4BF', hover: T.badBg },
}

export function Button({ children, variant = 'secondary', size = 'md', icon: Icon, loading, disabled, style, ...rest }) {
  const v = BTN[variant]
  const [hover, setHover] = useState(false)
  const h = size === 'sm' ? 32 : 38
  return (
    <button type="button" disabled={disabled || loading}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7, minHeight: h,
        padding: size === 'sm' ? '0 11px' : '0 15px', borderRadius: 9, border: `1px solid ${v.bd}`,
        background: hover && !disabled ? v.hover : v.bg, color: v.fg, fontSize: size === 'sm' ? 12.5 : 13.5,
        fontWeight: 600, fontFamily: 'inherit', cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.55 : 1, whiteSpace: 'nowrap', transition: 'background .15s', ...style }} {...rest}>
      {loading ? <Loader2 size={15} className="spin" aria-hidden="true" /> : Icon && <Icon size={15} strokeWidth={2} aria-hidden="true" />}
      {children}
    </button>
  )
}

/** `group` renders a <div> instead of <label> — use it around Segmented/Toggle/button groups,
 *  otherwise a click on the label text would activate the first button inside. */
export function Field({ label, hint, children, error, count, max, style, group }) {
  const Tag = group ? 'div' : 'label'
  return (
    <Tag style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0, ...style }}>
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: T.ink }}>{label}</span>
        {max && <span className="tnum" style={{ fontSize: 11.5, color: count > max ? T.bad : T.muted }}>{count ?? 0}/{max}</span>}
      </span>
      {children}
      {hint && !error && <span style={{ fontSize: 11.5, color: T.muted, lineHeight: 1.45 }}>{hint}</span>}
      {error && <span role="alert" style={{ fontSize: 11.5, color: T.bad }}>{error}</span>}
    </Tag>
  )
}

export function Segmented({ value, onChange, options, ariaLabel }) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} style={{ display: 'inline-flex', alignSelf: 'flex-start', maxWidth: '100%', padding: 3, background: '#EEF4F6', borderRadius: 10, gap: 3, flexWrap: 'wrap' }}>
      {options.map((o) => {
        const on = o.value === value
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} onClick={() => onChange(o.value)}
            style={{ minHeight: 34, padding: '0 14px', borderRadius: 8, border: 'none', fontFamily: 'inherit', fontSize: 13,
              fontWeight: 600, cursor: 'pointer', background: on ? '#fff' : 'transparent', color: on ? T.ink : T.soft,
              boxShadow: on ? '0 1px 3px rgba(10,26,36,.12)' : 'none' }}>{o.label}</button>
        )
      })}
    </div>
  )
}

export function Toggle({ checked, onChange, label, disabled }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 9, cursor: disabled ? 'not-allowed' : 'pointer', minHeight: 32 }}>
      <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        style={{ width: 36, height: 20, borderRadius: 20, border: 'none', padding: 2, cursor: 'inherit', flexShrink: 0,
          background: checked ? T.teal : '#C9D6DD', transition: 'background .15s' }}>
        <span style={{ display: 'block', width: 16, height: 16, borderRadius: '50%', background: '#fff',
          transform: `translateX(${checked ? 16 : 0}px)`, transition: 'transform .15s' }} />
      </button>
      {label && <span style={{ fontSize: 13, color: T.ink }}>{label}</span>}
    </label>
  )
}

const BADGE = {
  good: [T.goodBg, T.good], warn: [T.warnBg, T.warn], bad: [T.badBg, T.bad],
  info: [T.infoBg, T.info], neutral: [T.neutralBg, T.neutral],
}

export function Badge({ tone = 'neutral', icon: Icon, children, title }) {
  const [bg, fg] = BADGE[tone]
  return (
    <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: bg, color: fg, fontSize: 11.5,
      fontWeight: 600, padding: '3px 9px', borderRadius: 20, whiteSpace: 'nowrap', lineHeight: 1.4 }}>
      {Icon && <Icon size={12} strokeWidth={2.2} aria-hidden="true" />}{children}
    </span>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div role="status" style={{ display: 'flex', alignItems: 'center', gap: 8, color: T.muted, fontSize: 13, padding: 24, justifyContent: 'center' }}>
      <Loader2 size={16} className="spin" aria-hidden="true" /> {label}
    </div>
  )
}

export function Empty({ icon: Icon, title, text, action }) {
  return (
    <div style={{ textAlign: 'center', padding: '36px 16px', color: T.muted }}>
      {Icon && <Icon size={28} strokeWidth={1.6} color={T.muted} aria-hidden="true" />}
      <p style={{ margin: '10px 0 4px', fontSize: 14, fontWeight: 600, color: T.ink }}>{title}</p>
      {text && <p style={{ margin: '0 auto', fontSize: 12.5, maxWidth: 420 }}>{text}</p>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  )
}

export function Notice({ tone = 'info', icon: Icon, children, style }) {
  const [bg, fg] = BADGE[tone]
  return (
    <div role={tone === 'bad' ? 'alert' : 'note'} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', background: bg, color: fg,
      borderRadius: 10, padding: '10px 12px', fontSize: 12.5, lineHeight: 1.5, ...style }}>
      {Icon && <Icon size={15} strokeWidth={2} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden="true" />}
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  )
}

/** Right-side drawer on desktop, bottom sheet on mobile. Esc + backdrop close it. */
export function Drawer({ open, onClose, title, subtitle, children, isMobile, width = 460 }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: ds.z.modal, display: 'flex', justifyContent: isMobile ? 'stretch' : 'flex-end', alignItems: isMobile ? 'flex-end' : 'stretch' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(10,26,36,.38)' }} />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        style={{ position: 'relative', background: '#fff', width: isMobile ? '100%' : width, maxWidth: '100%',
          height: isMobile ? '88vh' : '100%', borderRadius: isMobile ? '16px 16px 0 0' : 0, display: 'flex', flexDirection: 'column',
          boxShadow: ds.modalShadow, animation: isMobile ? 'fadeIn .2s ease' : 'slideInRight .22s ease', outline: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '16px 18px', borderBottom: `1px solid ${T.line}` }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.ink, overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</h2>
            {subtitle && <p style={{ margin: '3px 0 0', fontSize: 12.5, color: T.muted }}>{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ width: 36, height: 36, borderRadius: 9, border: 'none', background: '#F1F6F8', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <X size={17} color={T.ink} aria-hidden="true" />
          </button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>{children}</div>
      </div>
    </div>
  )
}

/** Centered modal (used for confirmations and the create wizard). */
export function Modal({ open, onClose, title, children, footer, width = 560 }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: ds.z.modal, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(10,26,36,.42)' }} />
      <div role="dialog" aria-modal="true" aria-label={title}
        style={{ position: 'relative', background: '#fff', borderRadius: 14, width, maxWidth: '100%', maxHeight: '92vh',
          display: 'flex', flexDirection: 'column', boxShadow: ds.modalShadow, animation: 'fadeIn .2s ease' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '16px 18px', borderBottom: `1px solid ${T.line}` }}>
          <h2 style={{ margin: 0, flex: 1, fontSize: 16, fontWeight: 700, color: T.ink }}>{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" style={{ width: 36, height: 36, borderRadius: 9, border: 'none', background: '#F1F6F8', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <X size={17} color={T.ink} aria-hidden="true" />
          </button>
        </div>
        <div style={{ overflowY: 'auto', padding: 18 }}>{children}</div>
        {footer && <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 18px', borderTop: `1px solid ${T.line}`, flexWrap: 'wrap' }}>{footer}</div>}
      </div>
    </div>
  )
}

/** Renders the toast from useToast(). */
export function Toast({ t }) {
  if (!t) return null
  return (
    <div role="status" aria-live="polite" style={{ position: 'fixed', left: '50%', bottom: 24, transform: 'translateX(-50%)', zIndex: ds.z.modal + 10,
      background: t.tone === 'bad' ? T.bad : T.ink, color: '#fff', padding: '11px 16px', borderRadius: 10, fontSize: 13,
      boxShadow: ds.modalShadow, maxWidth: 'calc(100vw - 32px)', animation: 'fadeIn .2s ease' }}>{t.text}</div>
  )
}
