/**
 * frontend/src/modules/inventory/StockModal.jsx
 * STOCK-1 — the pop-up panel used by Receive stock, Adjust and the product panel. Esc or the backdrop closes it
 * (not while saving). Full screen on phones.
 */
import { useEffect } from 'react'
import { X } from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { btnG } from './stockUi'

export default function StockModal({ title, icon: Icon, onClose, busy = false, footer, width = 640, children }) {
  const isMobile = useIsMobile()
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])
  const shell = {
    position: 'fixed', inset: 0, background: 'rgba(15,20,30,0.45)', zIndex: ds.z.modal,
    display: 'flex', alignItems: isMobile ? 'stretch' : 'center', justifyContent: 'center', padding: isMobile ? 0 : 20,
  }
  const panel = {
    background: '#fff', width: '100%', maxWidth: width, maxHeight: isMobile ? '100%' : '92vh', height: isMobile ? '100%' : 'auto',
    borderRadius: isMobile ? 0 : ds.radius.xxl, boxShadow: ds.modalShadow, display: 'flex', flexDirection: 'column', fontFamily: ds.fontDm,
  }
  return (
    <div style={shell} onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div style={panel} role="dialog" aria-modal="true" aria-label={title}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 20px', borderBottom: `1px solid ${ds.border}` }}>
          {Icon && <Icon size={20} color={ds.teal} />}
          <div style={{ flex: 1, minWidth: 0, fontWeight: 700, fontSize: 17, color: ds.dark }}>{title}</div>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close" style={{ ...btnG, minHeight: 40, padding: '0 10px' }}><X size={18} /></button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? 16 : 22 }}>{children}</div>
        {footer && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '12px 20px', borderTop: `1px solid ${ds.border}`, justifyContent: 'flex-end', alignItems: 'center' }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
