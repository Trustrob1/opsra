/**
 * frontend/src/modules/invoices/SendPanel.jsx
 * INV-3 — send an issued quote / invoice to the customer: WhatsApp, web chat or email (the PDF plus a link to their page),
 * or copy the link to share any other way. A channel that can't be used right now is greyed out with the reason.
 */
import { useEffect, useState } from 'react'
import { Send, Copy, Check, Mail, MessageCircle, MessagesSquare } from 'lucide-react'
import { ds } from '../../utils/ds'
import { getSendOptions, sendDoc, apiError } from '../../services/invoices.service'
import { niceDate, lab, inp, btnG, disabled } from './invoiceUi'

const NAMES = { whatsapp: 'WhatsApp', webchat: 'web chat', email: 'email' }

export default function SendPanel({ doc, onSent }) {
  const [opts, setOpts] = useState(null)
  const [email, setEmail] = useState(doc.customer_email || '')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)       // { ok, text }
  const [copied, setCopied] = useState(false)
  const [sentAt, setSentAt] = useState(doc.sent_at || null)

  useEffect(() => {
    let live = true
    getSendOptions(doc.id).then((o) => { if (live) setOpts(o) }).catch((e) => { if (live) setMsg({ ok: false, text: apiError(e) }) })
    return () => { live = false }
  }, [doc.id])

  const send = async (channel) => {
    setBusy(channel); setMsg(null)
    try {
      const r = await sendDoc(doc.id, channel, channel === 'email' ? email.trim() : undefined)
      setSentAt(r?.sent_at || new Date().toISOString())
      setMsg({ ok: true, text: `Sent by ${NAMES[channel]}.` })
      onSent?.()
    } catch (e) {
      setMsg({ ok: false, text: apiError(e, `Could not send by ${NAMES[channel]}. Please try again.`) })
    } finally { setBusy('') }
  }
  const copy = async () => {
    if (!opts?.link) return
    try { await navigator.clipboard.writeText(opts.link); setCopied(true); setTimeout(() => setCopied(false), 2000) }
    catch { setMsg({ ok: false, text: 'Could not copy. Select the link and copy it yourself.' }) }
  }

  if (!opts) return <div style={{ color: msg ? ds.red : ds.gray, fontSize: 13.5 }}>{msg?.text || 'Loading sending options…'}</div>
  const ch = opts.channels || {}
  const chButton = (key, Icon, label) => {
    const c = ch[key] || {}
    const off = !c.ok || !!busy
    return (
      <div key={key} style={{ display: 'grid', gap: 4 }}>
        <button type="button" style={disabled(btnG, off)} disabled={off} onClick={() => send(key)}>
          <Icon size={16} />{busy === key ? 'Sending…' : label}
        </button>
        {!c.ok && c.reason && <small style={{ color: ds.gray, maxWidth: 260 }}>{c.reason}</small>}
      </div>
    )
  }
  const emailOk = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email.trim())

  return (
    <section style={{ border: `1px solid ${ds.border}`, borderRadius: 12, padding: 14, display: 'grid', gap: 12, background: ds.light }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Send size={16} color={ds.tealDark} />
        <b style={{ color: ds.dark }}>Send to the customer</b>
        {sentAt && <span style={{ color: ds.gray, fontSize: 13 }}>· first sent {niceDate(sentAt)}</span>}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {chButton('whatsapp', MessageCircle, 'WhatsApp')}
        {chButton('webchat', MessagesSquare, 'Web chat')}
      </div>
      <div>
        <label style={lab} htmlFor="send-email">Email</label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input id="send-email" type="email" style={{ ...inp, flex: '1 1 220px' }} maxLength={254} placeholder="customer@example.com"
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <button type="button" style={disabled(btnG, !emailOk || !!busy)} disabled={!emailOk || !!busy} onClick={() => send('email')}>
            <Mail size={16} />{busy === 'email' ? 'Sending…' : 'Send email'}
          </button>
        </div>
      </div>
      {opts.link && (
        <div>
          <span style={lab}>Customer's link</span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input readOnly aria-label="Customer's link" style={{ ...inp, flex: '1 1 220px', color: ds.gray }} value={opts.link} onFocus={(e) => e.target.select()} />
            <button type="button" style={btnG} onClick={copy}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? 'Copied' : 'Copy link'}</button>
          </div>
          <small style={{ color: ds.gray }}>Anyone with this link can see this {doc.doc_type === 'quote' ? 'quote and accept it' : 'invoice'}.</small>
        </div>
      )}
      {msg && <div role="status" style={{ color: msg.ok ? ds.green : ds.red, fontSize: 14 }}>{msg.text}</div>}
    </section>
  )
}
