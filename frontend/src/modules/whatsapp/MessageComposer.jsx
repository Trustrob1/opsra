/**
 * MessageComposer.jsx — WhatsApp message compose panel.
 *
 * Enforces Meta's 24-hour conversation window rules:
 *   - If window open: free-form text OR template
 *   - If window closed: template ONLY (shown as info hint)
 *
 * Props:
 *   customerId  — UUID (required)
 *   windowOpen  — bool (from CustomerProfile state)
 *   templates   — array of approved templates
 *   onSent      — callback after successful send
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import { sendMessage } from '../../services/whatsapp.service'

export default function MessageComposer({ customerId, windowOpen, templates = [], onSent }) {
  const [mode, setMode]               = useState(windowOpen ? 'free' : 'template')
  const [content, setContent]         = useState('')
  const [templateName, setTemplateName] = useState('')
  const [sending, setSending]         = useState(false)
  const [error, setError]             = useState(null)
  const [sent, setSent]               = useState(false)

  const approvedTemplates = templates.filter(t => t.meta_status === 'approved')

  async function handleSend() {
    setError(null)
    setSending(true)
    try {
      const payload = { customer_id: customerId }
      if (mode === 'free') {
        if (!content.trim()) { setError('Message cannot be empty.'); return }
        payload.content = content.trim()
      } else {
        if (!templateName) { setError('Please select a template.'); return }
        payload.template_name = templateName
      }
      await sendMessage(payload)
      setSent(true)
      setContent('')
      setTemplateName('')
      onSent?.()
    } catch (err) {
      const msg = err.response?.data?.error?.message
      setError(msg || 'Failed to send message.')
    } finally {
      setSending(false)
    }
  }

  const S = {
    wrap: {
      background: '#ECE5DD', borderRadius: 14, padding: 16,
    },
    header: {
      display: 'flex', alignItems: 'center', gap: 10,
      marginBottom: 12, borderBottom: '1px solid #d4cfc8', paddingBottom: 10,
    },
    avatar: {
      width: 36, height: 36, background: ds.teal, borderRadius: '50%',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontWeight: 700, color: '#fff', fontSize: 15, flexShrink: 0,
    },
    name: { fontWeight: 600, fontSize: 13, color: '#1a1a1a' },
    status: { fontSize: 11, color: ds.gray },
    windowBanner: (open) => ({
      background: open ? '#DCF8C6' : '#FFF3CD',
      border: `1px solid ${open ? '#B0DDB8' : '#FFD97D'}`,
      borderRadius: 8, padding: '8px 12px', marginBottom: 12,
      fontSize: 12, color: open ? '#27AE60' : '#856404',
      display: 'flex', alignItems: 'center', gap: 6,
    }),
    modeToggle: {
      display: 'flex', gap: 6, marginBottom: 12,
    },
    modeBtn: (active) => ({
      padding: '6px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
      fontSize: 12, fontWeight: 600, fontFamily: ds.fontHead,
      background: active ? ds.teal : '#fff',
      color: active ? '#fff' : ds.gray,
      opacity: !windowOpen && 'template' !== 'free' ? 1 : 1,
    }),
    textarea: {
      width: '100%', border: `1.5px solid #d4cfc8`, borderRadius: 10,
      padding: '12px 14px', fontSize: 13, fontFamily: ds.fontBody,
      resize: 'vertical', minHeight: 80, outline: 'none', boxSizing: 'border-box',
    },
    select: {
      width: '100%', border: `1.5px solid #d4cfc8`, borderRadius: 10,
      padding: '11px 14px', fontSize: 13, fontFamily: ds.fontBody,
      outline: 'none', background: '#fff',
    },
    sendBtn: {
      marginTop: 10, padding: '10px 22px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: sending ? 'not-allowed' : 'pointer',
      opacity: sending ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: 8,
    },
    errBox: {
      marginTop: 8, fontSize: 12, color: '#C0392B',
      background: '#FFE8E8', borderRadius: 7, padding: '8px 12px',
    },
    sentBox: {
      marginTop: 8, fontSize: 12, color: '#27AE60',
      background: '#E8F8EE', borderRadius: 7, padding: '8px 12px',
    },
  }

  return (
    <div style={S.wrap}>
      {/* WhatsApp-style header */}
      <div style={S.header}>
        <div style={S.avatar}>💬</div>
        <div>
          <div style={S.name}>Send WhatsApp</div>
          <div style={S.status}>via Meta Cloud API</div>
        </div>
      </div>

      {/* Window status */}
      <div style={S.windowBanner(windowOpen)}>
        {windowOpen
          ? '✓ Conversation window open — free-form or template'
          : '⚠ Window closed — templates only (Meta 24hr rule)'}
      </div>

      {/* Mode toggle — disable free-form when window closed */}
      <div style={S.modeToggle}>
        <button
          style={S.modeBtn(mode === 'free')}
          onClick={() => setMode('free')}
          disabled={!windowOpen}
          title={!windowOpen ? 'Window closed — use a template' : ''}
        >
          ✏ Free-form
        </button>
        <button style={S.modeBtn(mode === 'template')} onClick={() => setMode('template')}>
          📋 Template
        </button>
      </div>

      {/* Input */}
      {mode === 'free' ? (
        <textarea
          style={S.textarea}
          placeholder="Type your message…"
          value={content}
          onChange={e => { setContent(e.target.value); setSent(false) }}
        />
      ) : (
        approvedTemplates.length === 0 ? (
          <div style={{ fontSize: 13, color: ds.gray, background: '#fff', borderRadius: 9, padding: 12 }}>
            No approved templates yet. Create and submit templates in Template Manager.
          </div>
        ) : (
          <select
            style={S.select}
            value={templateName}
            onChange={e => { setTemplateName(e.target.value); setSent(false) }}
          >
            <option value="">— Select a template —</option>
            {approvedTemplates.map(t => (
              <option key={t.id} value={t.name}>{t.name}</option>
            ))}
          </select>
        )
      )}

      {/* Send button */}
      <button style={S.sendBtn} onClick={handleSend} disabled={sending}>
        {sending
          ? <><span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.4)', borderTopColor: '#fff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} /> Sending…</>
          : '💬 Send Message'
        }
      </button>

      {error && <div style={S.errBox}>⚠ {error}</div>}
      {sent && <div style={S.sentBox}>✓ Message sent successfully</div>}
    </div>
  )
}
