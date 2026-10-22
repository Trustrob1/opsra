/**
 * frontend/src/modules/admin/CatalogDialog.jsx
 * STORE-10/12: a centered window for the import and photo screens. Escape closes (unless `locked`), Tab stays inside,
 * focus returns to the button that opened it, the page behind does not scroll.
 */
import { useEffect, useRef } from 'react'
import { ds } from '../../utils/ds'

function focusables(root) {
  return [...root.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')]
}

export default function CatalogDialog({ title, onClose, locked = false, children, footer }) {
  const panel = useRef(null)
  const returnTo = useRef(null)

  useEffect(() => {
    returnTo.current = document.activeElement
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const t = setTimeout(() => { if (panel.current) panel.current.focus() }, 0)
    return () => {
      clearTimeout(t)
      document.body.style.overflow = prev
      if (returnTo.current && returnTo.current.focus) returnTo.current.focus()
    }
  }, [])

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.stopPropagation(); if (!locked) onClose(); return }
    if (e.key !== 'Tab' || !panel.current) return
    const f = focusables(panel.current)
    if (!f.length) return
    const first = f[0], last = f[f.length - 1]
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }} onKeyDown={onKeyDown}>
      <div onClick={locked ? undefined : onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)' }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} style={{
        position: 'relative', width: 'min(760px, 100%)', maxHeight: '100%', background: 'white', borderRadius: 16, display: 'flex', flexDirection: 'column',
        outline: 'none', boxShadow: '0 12px 48px rgba(0,0,0,0.25)',
      }}>
        <div style={{ minHeight: 64, padding: '0 8px 0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #E6E4DF', flexShrink: 0 }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24' }}>{title}</div>
          <button onClick={onClose} disabled={locked} aria-label="Close" style={{ width: 44, height: 44, border: 0, background: 'transparent', fontSize: 20, cursor: locked ? 'default' : 'pointer', color: '#7A9BAD', opacity: locked ? 0.4 : 1 }}>✕</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>{children}</div>
        {footer && <div style={{ flexShrink: 0, padding: '14px 24px 18px', borderTop: '1px solid #E6E4DF', display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap', alignItems: 'center' }}>{footer}</div>}
      </div>
    </div>
  )
}
