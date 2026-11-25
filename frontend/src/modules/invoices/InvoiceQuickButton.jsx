/**
 * frontend/src/modules/invoices/InvoiceQuickButton.jsx
 * INV-2 — "Invoice" button in a Conversations thread: starts a draft invoice (or quote) for the person in the chat.
 * Works for every product mode, so WhatsApp-only and web-chat-only businesses can bill from the inbox.
 */
import { useEffect, useRef, useState } from 'react'
import { Receipt } from 'lucide-react'
import { ds } from '../../utils/ds'
import InvoiceEditor from './InvoiceEditor'

export default function InvoiceQuickButton({ leadId, compact = false }) {
  const [menu, setMenu] = useState(false)
  const [editor, setEditor] = useState(null)
  const box = useRef(null)
  useEffect(() => {
    if (!menu) return undefined
    const off = (e) => { if (box.current && !box.current.contains(e.target)) setMenu(false) }
    document.addEventListener('mousedown', off)
    return () => document.removeEventListener('mousedown', off)
  }, [menu])
  const start = (doc_type) => { setMenu(false); setEditor({ doc_type, lead_id: leadId }) }
  const item = { display: 'block', width: '100%', textAlign: 'left', border: 'none', background: 'none', padding: '10px 14px', minHeight: 44, cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 14, color: ds.dark }
  return (
    <div ref={box} style={{ position: 'relative', flexShrink: 0 }}>
      <button type="button" onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu} title="Make an invoice or quote for this customer" aria-label="Invoice"
        style={{ minHeight: 40, minWidth: 40, padding: compact ? 0 : '0 14px', borderRadius: 999, border: `1px solid ${ds.border}`, background: '#fff', color: ds.tealDark, fontWeight: 600, fontSize: 13.5, cursor: 'pointer', fontFamily: ds.fontDm, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
        <Receipt size={16} />{!compact && 'Invoice'}
      </button>
      {menu && (
        <div role="menu" style={{ position: 'absolute', right: 0, top: 46, zIndex: 20, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 10, boxShadow: ds.hoverShadow, minWidth: 180, overflow: 'hidden' }}>
          <button type="button" role="menuitem" style={item} onClick={() => start('invoice')}>New invoice</button>
          <button type="button" role="menuitem" style={item} onClick={() => start('quote')}>New quote</button>
        </div>
      )}
      {editor && <InvoiceEditor initial={editor} onClose={() => setEditor(null)} />}
    </div>
  )
}
