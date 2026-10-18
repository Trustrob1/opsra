/**
 * frontend/src/pages/WebChatPage.jsx
 * WEBCHAT-1 — Opsra's own chat page: /c/:key
 *
 * A visitor taps a menu option or types; the answers are the business's own (scripted, no AI yet).
 * After the first answer the page asks for contact (name + WhatsApp number and/or email + consent).
 * Visitors who came from WhatsApp (?h= hand-off link) already have a proven number, so only an optional
 * email is asked. A rep's reply from the Opsra inbox appears here within a few seconds (polling).
 *
 * The session token is kept in localStorage when the browser allows it (Instagram's in-app browser may not),
 * and the page works without it for the current visit.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { startChat, resumeChat, pollChat, sendChat, sendContact, sendBooking, chatErrorMessage } from '../services/webchat.service'

const POLL_MS = 4000
const URL_RE = /(https?:\/\/[^\s<>"']+)/g

function readStore(key) { try { return window.localStorage.getItem(key) } catch { return null } }
function writeStore(key, v) { try { v ? window.localStorage.setItem(key, v) : window.localStorage.removeItem(key) } catch { /* private mode */ } }

function Linkified({ text }) {
  const parts = String(text || '').split(URL_RE)
  return parts.map((p, i) => (/^https?:\/\//.test(p)
    ? <a key={i} href={p} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline', wordBreak: 'break-all' }}>{p}</a>
    : <span key={i}>{p}</span>))
}

export default function WebChatPage({ chatKey }) {
  const [state, setState] = useState('loading')           // loading | ready | closed | error
  const [cfg, setCfg] = useState(null)
  const [messages, setMessages] = useState([])
  const [hasContact, setHasContact] = useState(false)
  const [verified, setVerified] = useState(false)
  const [human, setHuman] = useState(false)
  const [panel, setPanel] = useState(null)                // null | 'contact' | 'email' | 'booking'
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [contact, setContact] = useState({ name: '', phone: '', email: '', consent: false, website: '' })
  const [booking, setBooking] = useState({})
  const token = useRef(null)
  const listRef = useRef(null)
  const tokenKey = `wc_token_${chatKey}`

  const brand = cfg?.brand_color || '#028090'

  const merge = useCallback((incoming) => {
    if (!incoming?.length) return
    setMessages((cur) => {
      const seen = new Set(cur.map((m) => m.id))
      const add = incoming.filter((m) => !seen.has(m.id))
      return add.length ? [...cur, ...add].sort((a, b) => String(a.at).localeCompare(String(b.at))) : cur
    })
  }, [])

  const apply = useCallback((snap) => {
    setCfg(snap.config)
    setMessages(snap.messages || [])
    setHasContact(!!snap.has_contact)
    setVerified(!!snap.verified_phone)
    setHuman(!!snap.human)
    setState('ready')
  }, [])

  // noindex, plus a sensible title
  useEffect(() => {
    const m = document.createElement('meta')
    m.name = 'robots'; m.content = 'noindex, nofollow'
    document.head.appendChild(m)
    return () => { document.head.removeChild(m) }
  }, [])
  useEffect(() => { if (cfg?.business_name) document.title = `Chat with ${cfg.business_name}` }, [cfg])

  // open: hand-off link → resume stored session → new session
  useEffect(() => {
    let dead = false
    const params = new URLSearchParams(window.location.search)
    const handoff = params.get('h')
    const source = params.get('s') || (handoff ? 'whatsapp' : undefined)
    const fresh = async () => {
      const snap = await startChat(chatKey, { source, handoff: handoff || undefined })
      token.current = snap.token
      writeStore(tokenKey, snap.token)
      return snap
    }
    ;(async () => {
      try {
        let snap
        const stored = handoff ? null : readStore(tokenKey)
        if (stored) {
          try { token.current = stored; snap = await resumeChat(chatKey, stored) }
          catch (e) { if (e?.response?.status === 401) snap = await fresh(); else throw e }
        } else {
          snap = await fresh()
        }
        if (dead) return
        if (handoff) window.history.replaceState({}, '', window.location.pathname)   // the one-time token is spent
        apply(snap)
        if (snap.needs_email && snap.messages.length > 2) setPanel('email')
      } catch (e) {
        if (!dead) setState(e?.response?.status === 404 ? 'closed' : 'error')
      }
    })()
    return () => { dead = true }
  }, [chatKey, tokenKey, apply])

  // poll for rep replies while the tab is visible
  useEffect(() => {
    if (state !== 'ready') return undefined
    const id = setInterval(async () => {
      if (document.hidden || !token.current) return
      try {
        const last = messages.length ? messages[messages.length - 1].at : undefined
        const res = await pollChat(chatKey, token.current, last)
        merge(res.messages)
        setHuman(!!res.human)
      } catch (e) {
        if (e?.response?.status === 401) { writeStore(tokenKey, null); setState('error') }
      }
    }, POLL_MS)
    return () => clearInterval(id)
  }, [state, messages, chatKey, tokenKey, merge])

  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight }, [messages, panel])

  const handleReply = (res) => {
    merge(res.messages)
    if (typeof res.human === 'boolean') setHuman(res.human)
    if (res.form === 'booking') setPanel('booking')
    else if (res.ask_contact) setPanel('contact')
    else if (res.ask_email) setPanel('email')
  }

  const act = async (fn) => {
    if (busy) return
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(chatErrorMessage(e)) } finally { setBusy(false) }
  }

  const sendMenu = (id) => act(async () => handleReply(await sendChat(chatKey, token.current, { kind: 'menu', menu_id: id })))
  const sendText = (e) => {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    setText('')
    act(async () => handleReply(await sendChat(chatKey, token.current, { kind: 'text', text: t })))
  }
  const submitContact = (e) => {
    e.preventDefault()
    act(async () => {
      const res = await sendContact(chatKey, token.current, { ...contact, name: verified ? undefined : contact.name })
      merge(res.messages)
      setHasContact(true)
      setPanel(res.form === 'booking' ? 'booking' : null)
    })
  }
  const submitBooking = (e) => {
    e.preventDefault()
    act(async () => {
      const res = await sendBooking(chatKey, token.current, booking)
      merge(res.messages)
      setBooking({})
      setPanel(null)
    })
  }

  const S = {
    page: { height: '100dvh', display: 'flex', justifyContent: 'center', background: '#eef2f4', fontFamily: "'DM Sans', system-ui, sans-serif" },
    shell: { width: '100%', maxWidth: 520, display: 'flex', flexDirection: 'column', background: '#fff', height: '100%', boxShadow: '0 0 24px rgba(0,0,0,0.06)' },
    head: { background: brand, color: '#fff', padding: '14px 16px', fontWeight: 700, fontSize: 17 },
    list: { flex: 1, overflowY: 'auto', padding: '14px 12px', background: '#f6f8f9' },
    bubble: (role) => ({
      maxWidth: '82%', margin: role === 'visitor' ? '6px 0 6px auto' : '6px auto 6px 0', padding: '9px 12px', borderRadius: 14,
      fontSize: 15, lineHeight: 1.45, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
      background: role === 'visitor' ? brand : '#fff', color: role === 'visitor' ? '#fff' : '#1c2b36',
      border: role === 'visitor' ? 'none' : '1px solid #dfe6ea',
    }),
    who: { fontSize: 11, color: '#6b7f8d', margin: '8px 4px 0', fontWeight: 600 },
    menu: { display: 'flex', flexWrap: 'wrap', gap: 8, padding: '8px 12px', background: '#fff', borderTop: '1px solid #e6ecef' },
    chip: { minHeight: 40, padding: '8px 14px', borderRadius: 20, border: `1.5px solid ${brand}`, background: '#fff', color: brand, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' },
    form: { display: 'flex', gap: 8, padding: '8px 12px 12px', background: '#fff' },
    input: { flex: 1, minWidth: 0, minHeight: 44, padding: '10px 12px', border: '1px solid #c9d6de', borderRadius: 10, fontSize: 16, fontFamily: 'inherit', boxSizing: 'border-box' },
    send: { minHeight: 44, minWidth: 64, border: 0, borderRadius: 10, background: brand, color: '#fff', fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' },
    card: { background: '#fff', border: '1px solid #dfe6ea', borderRadius: 12, padding: 14, margin: '10px 0' },
    lab: { display: 'block', fontSize: 13, fontWeight: 600, color: '#2c4152', margin: '8px 0 4px' },
    full: { width: '100%', minHeight: 44, padding: '10px 12px', border: '1px solid #c9d6de', borderRadius: 8, fontSize: 16, fontFamily: 'inherit', boxSizing: 'border-box' },
    primary: { width: '100%', minHeight: 46, marginTop: 12, border: 0, borderRadius: 8, background: brand, color: '#fff', fontSize: 16, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' },
    err: { color: '#b3261e', fontSize: 13, padding: '0 12px 6px', minHeight: 4 },
    center: { margin: 'auto', padding: 24, textAlign: 'center', color: '#4a6375', fontSize: 15 },
  }

  if (state === 'loading') return <div style={S.page}><div style={S.shell}><div style={S.center}>Opening chat…</div></div></div>
  if (state === 'closed') return <div style={S.page}><div style={S.shell}><div style={S.center}>This chat is not available right now.</div></div></div>
  if (state === 'error') return (
    <div style={S.page}><div style={S.shell}><div style={S.center}>
      We could not open the chat. <button style={{ ...S.chip, marginTop: 12 }} onClick={() => { writeStore(tokenKey, null); window.location.reload() }}>Try again</button>
    </div></div></div>
  )

  return (
    <div style={S.page}>
      <div style={S.shell}>
        <div style={S.head}>{cfg.business_name}</div>

        <div style={S.list} ref={listRef} role="log" aria-live="polite" aria-label="Chat messages">
          {messages.map((m, i) => (
            <div key={m.id}>
              {m.role === 'rep' && (i === 0 || messages[i - 1].role !== 'rep') && <div style={S.who}>{cfg.business_name} team</div>}
              <div style={S.bubble(m.role)}><Linkified text={m.text} /></div>
            </div>
          ))}

          {panel === 'contact' && (
            <form style={S.card} onSubmit={submitContact}>
              <div style={{ fontSize: 14, color: '#2c4152', marginBottom: 4 }}>{cfg.contact_prompt}</div>
              <label style={S.lab} htmlFor="wc-name">Your name</label>
              <input id="wc-name" style={S.full} value={contact.name} maxLength={80} autoComplete="name" required
                onChange={(e) => setContact({ ...contact, name: e.target.value })} />
              <label style={S.lab} htmlFor="wc-phone">WhatsApp number</label>
              <input id="wc-phone" style={S.full} value={contact.phone} maxLength={30} inputMode="tel" autoComplete="tel"
                onChange={(e) => setContact({ ...contact, phone: e.target.value })} />
              <label style={S.lab} htmlFor="wc-email">Email (optional if you gave a number)</label>
              <input id="wc-email" style={S.full} value={contact.email} maxLength={200} inputMode="email" autoComplete="email"
                onChange={(e) => setContact({ ...contact, email: e.target.value })} />
              <input aria-hidden="true" tabIndex={-1} autoComplete="off" value={contact.website} name="website"
                onChange={(e) => setContact({ ...contact, website: e.target.value })}
                style={{ position: 'absolute', left: '-9999px', width: 1, height: 1, opacity: 0 }} />
              <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, color: '#4a6375', margin: '10px 0 0' }}>
                <input type="checkbox" checked={contact.consent} style={{ marginTop: 3 }}
                  onChange={(e) => setContact({ ...contact, consent: e.target.checked })} />
                <span>{cfg.consent_text}</span>
              </label>
              <button type="submit" style={S.primary} disabled={busy}>Continue</button>
            </form>
          )}

          {panel === 'email' && (
            <form style={S.card} onSubmit={submitContact}>
              <div style={{ fontSize: 14, color: '#2c4152' }}>Want a copy of this chat by email? Add your email (optional).</div>
              <label style={S.lab} htmlFor="wc-email2">Email</label>
              <input id="wc-email2" style={S.full} value={contact.email} maxLength={200} inputMode="email" autoComplete="email"
                onChange={(e) => setContact({ ...contact, email: e.target.value, consent: !!e.target.value })} />
              <button type="submit" style={S.primary} disabled={busy || !contact.email}>Save email</button>
              <button type="button" style={{ ...S.chip, width: '100%', marginTop: 8 }} onClick={() => setPanel(null)}>No thanks</button>
            </form>
          )}

          {panel === 'booking' && (
            <form style={S.card} onSubmit={submitBooking}>
              {cfg.booking_fields.map((f) => (
                <div key={f.key}>
                  <label style={S.lab} htmlFor={`wc-b-${f.key}`}>{f.label}</label>
                  <input id={`wc-b-${f.key}`} style={S.full} value={booking[f.key] || ''} maxLength={300} required={f.required}
                    onChange={(e) => setBooking({ ...booking, [f.key]: e.target.value })} />
                </div>
              ))}
              <button type="submit" style={S.primary} disabled={busy}>Send booking request</button>
            </form>
          )}
          {human && <div style={{ ...S.who, textAlign: 'center', margin: '12px 0' }}>A team member will reply here.</div>}
        </div>

        {error && <div style={S.err} role="alert">{error}</div>}

        {!human && cfg.menu.length > 0 && (
          <div style={S.menu}>
            {cfg.menu.map((m) => <button key={m.id} type="button" style={S.chip} disabled={busy} onClick={() => sendMenu(m.id)}>{m.label}</button>)}
          </div>
        )}

        <form style={S.form} onSubmit={sendText}>
          <label htmlFor="wc-text" style={{ position: 'absolute', left: '-9999px' }}>Type a message</label>
          <input id="wc-text" style={S.input} value={text} maxLength={1000} placeholder="Type a message" autoComplete="off"
            onChange={(e) => setText(e.target.value)} />
          <button type="submit" style={S.send} disabled={busy || !text.trim()}>Send</button>
        </form>
      </div>
    </div>
  )
}
