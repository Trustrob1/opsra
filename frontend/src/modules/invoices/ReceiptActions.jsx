/**
 * frontend/src/modules/invoices/ReceiptActions.jsx
 * INV-4 — what you can do with one receipt: download the PDF, send it to the customer (WhatsApp, web chat or email,
 * greyed out with the reason when a way can't be used), and (admin) void it with a reason.
 */
import { useState } from 'react'
import { Download, Send, Ban, Mail, MessageCircle, MessagesSquare } from 'lucide-react'
import { ds } from '../../utils/ds'
import { downloadReceiptPdf, getReceiptSendOptions, sendReceipt, voidReceipt, apiError } from '../../services/invoices.service'
import { inp, btnG, btnDanger, disabled } from './invoiceUi'
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1

const NAMES = { whatsapp: 'WhatsApp', webchat: 'web chat', email: 'email' }
const small = { ...btnG, minHeight: 36, padding: '0 10px', fontSize: 13 }

export default function ReceiptActions({ receipt, isAdmin, onChanged }) {
  const [mode, setMode] = useState('')          // '' | 'send' | 'void'
  const [opts, setOpts] = useState(null)
  const [email, setEmail] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)
  const voided = !!receipt.voided_at

  const openSend = () => {
    setMode('send'); setMsg(null); setOpts(null)
    getReceiptSendOptions(receipt.id).then((o) => { setOpts(o); setEmail(o?.channels?.email?.to || '') })
      .catch((e) => setMsg({ ok: false, text: apiError(e) }))
  }
  const send = async (channel) => {
    setBusy(channel); setMsg(null)
    try {
      await sendReceipt(receipt.id, channel, channel === 'email' ? email.trim() : undefined)
      setMsg({ ok: true, text: `Receipt sent by ${NAMES[channel]}.` }); setMode('')
    } catch (e) { setMsg({ ok: false, text: apiError(e, `Could not send by ${NAMES[channel]}.`) }) } finally { setBusy('') }
  }
  const doVoid = async () => {
    setBusy('void'); setMsg(null)
    try { await voidReceipt(receipt.id, reason.trim()); setMode(''); setReason(''); onChanged?.() }
    catch (e) { setMsg({ ok: false, text: apiError(e) }) } finally { setBusy('') }
  }
  const pdf = async () => {
    setBusy('pdf'); setMsg(null)
    try { await downloadReceiptPdf(receipt.id) } catch (e) { setMsg({ ok: false, text: apiError(e, 'Could not make the PDF.') }) } finally { setBusy('') }
  }

  const ch = opts?.channels || {}
  const chButton = (key, Icon, label) => {
    const c = ch[key] || {}
    const off = !c.ok || !!busy
    return (
      <div key={key} style={{ display: 'grid', gap: 3 }}>
        <button type="button" style={disabled(small, off)} disabled={off} onClick={() => send(key)}><Icon size={14} />{busy === key ? 'Sending…' : label}</button>
        {!c.ok && c.reason && <small style={{ color: ds.gray, maxWidth: 220 }}>{c.reason}</small>}
      </div>
    )
  }
  const emailOk = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email.trim())

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button type="button" style={disabled(small, !!busy)} disabled={!!busy} onClick={pdf}><Download size={14} />{busy === 'pdf' ? 'Preparing…' : 'PDF'}</button>
        {!voided && <button type="button" style={disabled(small, !!busy)} disabled={!!busy} onClick={() => (mode === 'send' ? setMode('') : openSend())}><Send size={14} />Send</button>}
        {!voided && isAdmin && <button type="button" style={{ ...btnDanger, minHeight: 36, padding: '0 10px', fontSize: 13 }} onClick={() => setMode(mode === 'void' ? '' : 'void')}><Ban size={14} />Void</button>}
      </div>
      {mode === 'send' && (opts ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            {chButton('whatsapp', MessageCircle, 'WhatsApp')}
            {chButton('webchat', MessagesSquare, 'Web chat')}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input type="email" aria-label="Customer's email" style={{ ...inp, minHeight: 36, flex: '1 1 200px' }} maxLength={254}
              placeholder="customer@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            <button type="button" style={disabled(small, !emailOk || !!busy)} disabled={!emailOk || !!busy} onClick={() => send('email')}><Mail size={14} />{busy === 'email' ? 'Sending…' : 'Email'}</button>
          </div>
          <WhyDisabled reason={!emailOk && !busy ? email.trim() ? "That email address doesn't look right." : 'Type the customer\'s email to send it.' : ''} style={{ margin: 0 }} />
        </div>
      ) : !msg && <small style={{ color: ds.gray }}>Loading…</small>)}
      {mode === 'void' && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input autoFocus aria-label="Reason for voiding the receipt" style={{ ...inp, minHeight: 36, flex: '1 1 200px' }} maxLength={500}
            placeholder="Why? e.g. the transfer bounced" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button type="button" style={disabled({ ...small, color: '#fff', background: ds.red, borderColor: ds.red }, reason.trim().length < 3 || !!busy)}
            disabled={reason.trim().length < 3 || !!busy} onClick={doVoid}>{busy === 'void' ? 'Voiding…' : 'Void receipt'}</button>
          <WhyDisabled reason={!busy && reason.trim().length < 3 ? 'Write the reason (at least 3 letters).' : ''} style={{ flexBasis: '100%', margin: 0 }} />
        </div>
      )}
      {msg && <div role="status" style={{ color: msg.ok ? ds.green : ds.red, fontSize: 13 }}>{msg.text}</div>}
    </div>
  )
}
