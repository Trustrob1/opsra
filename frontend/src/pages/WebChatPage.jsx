/**
 * frontend/src/pages/WebChatPage.jsx
 * WEBCHAT-1 — Opsra's own chat page: /c/:key
 *
 * A visitor taps a menu option or types; the answers are the business's own (scripted, no AI yet).
 * After the first answer the page asks for contact (name + phone/WhatsApp number and/or email + consent).
 * Visitors who came from WhatsApp (?h= hand-off link) already have a proven number, so only an optional
 * email is asked. A rep's reply from the Opsra inbox appears here within a few seconds (polling).
 *
 * The session token is kept in localStorage when the browser allows it (Instagram's in-app browser may not),
 * and the page works without it for the current visit.
 *
 * WEBCHAT-UI (Nov 2026): redesigned. Same logic and API calls; new look. The brand colour (cfg.brand_color) drives
 * every accent; Shop, Cart and "Email me this chat" appear only when the business has them switched on, so the
 * page also works as a plain chat for a business that uses nothing else from Opsra.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { startChat, resumeChat, pollChat, sendChat, sendContact, sendBooking, getChatProducts, changeChatCart, chatCheckout, saveChatByEmail, stopChatEmails, tapChat, chatErrorMessage } from '../services/webchat.service'

const POLL_MS = 4000
const URL_RE = /(https?:\/\/[^\s<>"']+)/g
const FONT = "'DM Sans', system-ui, sans-serif"
const INK = '#14222B'
const MUTED = '#566770'
const LINE = '#DCE4E8'
const FIELD_LINE = '#B9C6CC'
const BG = '#F4F7F8'

function readStore(key) { try { return window.localStorage.getItem(key) } catch { return null } }
function writeStore(key, v) { try { v ? window.localStorage.setItem(key, v) : window.localStorage.removeItem(key) } catch { /* private mode */ } }

const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`

function Linkified({ text, onTap }) {
  const parts = String(text || '').split(URL_RE)
  return parts.map((p, i) => (/^https?:\/\//.test(p)
    ? <a key={i} href={p} target="_blank" rel="noopener noreferrer" onClick={onTap} style={{ color: 'inherit', textDecoration: 'underline', wordBreak: 'break-all' }}>{p}</a>
    : <span key={i}>{p}</span>))
}

function Icon({ name, size = 20 }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style: { flex: 'none' } }
  if (name === 'send') return <svg {...common}><path d="M4 12l16-8-6 16-3-7-7-1z" /></svg>
  if (name === 'back') return <svg {...common} strokeWidth="2.2"><path d="M15 5l-7 7 7 7" /></svg>
  if (name === 'close') return <svg {...common} strokeWidth="2.2"><path d="M6 6l12 12M18 6L6 18" /></svg>
  if (name === 'cart') return <svg {...common}><path d="M3 4h2.5l2.2 11h10.1l2-8H7" /><circle cx="9.5" cy="19" r="1.2" /><circle cx="17" cy="19" r="1.2" /></svg>
  if (name === 'bag') return <svg {...common}><path d="M5 8h14l-1 12H6L5 8z M9 8V6.5a3 3 0 016 0V8" /></svg>
  if (name === 'mail') return <svg {...common}><rect x="3.5" y="5.5" width="17" height="13" rx="2.5" /><path d="M4 7.5l8 6 8-6" /></svg>
  if (name === 'lock') return <svg {...common}><rect x="5" y="10.5" width="14" height="9.5" rx="2.2" /><path d="M8.5 10.5V8a3.5 3.5 0 017 0v2.5" /></svg>
  return null
}

function Thumb({ src, alt, size = 72, brand }) {
  if (src) return <img src={src} alt={alt} loading="lazy" style={{ width: size, height: size, objectFit: 'cover', borderRadius: 14, flexShrink: 0 }} />
  return (
    <div aria-hidden="true" style={{ width: size, height: size, flex: 'none', borderRadius: 14, background: `color-mix(in srgb, ${brand} 12%, white)`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: brand }}>
      <Icon name="bag" size={Math.round(size * 0.42)} />
    </div>
  )
}

function ProductCard({ p, S, brand, busy, picked, setPicked, onAdd }) {
  const vid = picked[p.id]
  const shown = p.variants.length ? (p.variants.find((v) => v.id === vid)?.price ?? p.variants[0].price) : p.price
  const from = p.variants.length > 1 && !vid
  return (
    <div style={S.card}>
      <div style={{ display: 'flex', gap: 12 }}>
        <Thumb src={p.image_url} alt={p.title} brand={brand} />
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.2px', overflowWrap: 'anywhere' }}>{p.title}</span>
          {p.description && <span style={{ fontSize: 14, lineHeight: 1.4, color: MUTED }}>{p.description}</span>}
          <span style={{ fontSize: 16, fontWeight: 700, color: S.brandDark, marginTop: 2 }}>{from ? 'From ' : ''}{naira(from ? Math.min(...p.variants.map((v) => v.price)) : shown)}</span>
        </div>
      </div>
      {p.variants.length > 1 && (
        <label style={{ display: 'block', marginTop: 10 }}>
          <span style={{ display: 'block', fontSize: 12, fontWeight: 600, color: MUTED, marginBottom: 4 }}>Option</span>
          <select aria-label={`Option for ${p.title}`} style={{ ...S.field, height: 44, padding: '0 12px', fontSize: 15 }} value={vid || ''}
            onChange={(e) => setPicked({ ...picked, [p.id]: e.target.value })}>
            <option value="">Choose an option</option>
            {p.variants.map((v) => <option key={v.id} value={v.id}>{v.label} - {naira(v.price)}</option>)}
          </select>
        </label>
      )}
      <button type="button" style={{ ...S.primary, marginTop: 12, minHeight: 44, fontSize: 15, fontWeight: 600 }} disabled={busy} onClick={() => onAdd(p)}>Add to cart</button>
    </div>
  )
}

export default function WebChatPage({ chatKey }) {
  const [state, setState] = useState('loading')           // loading | ready | closed | error
  const [cfg, setCfg] = useState(null)
  const [messages, setMessages] = useState([])
  const [hasContact, setHasContact] = useState(false)
  const [verified, setVerified] = useState(false)
  const [human, setHuman] = useState(false)
  const [panel, setPanel] = useState(null)                // null | 'contact' | 'email' | 'booking' | 'shop' | 'cart' | 'save'
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [contact, setContact] = useState({ name: '', phone: '', email: '', consent: false, website: '' })
  const [booking, setBooking] = useState({})
  const [saveForm, setSaveForm] = useState({ email: '', consent: false })
  const [cards, setCards] = useState([])                   // AI-suggested product cards
  const [products, setProducts] = useState([])
  const [cart, setCart] = useState({ items: [], total: 0, count: 0 })
  const [picked, setPicked] = useState({})                 // product id -> chosen variant id
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

  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight }, [messages, cards])

  const handleReply = (res) => {
    merge(res.messages)
    if (typeof res.human === 'boolean') setHuman(res.human)
    setCards(res.cards || [])
    if (res.form === 'booking') setPanel('booking')
    else if (res.ask_contact) setPanel('contact')
    else if (res.ask_email) setPanel('email')
  }

  const act = async (fn) => {
    if (busy) return
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(chatErrorMessage(e)) } finally { setBusy(false) }
  }

  const closePanel = () => { setPanel(null); setError('') }
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
  const submitSave = (e) => {
    e.preventDefault()
    act(async () => {
      const res = await saveChatByEmail(chatKey, token.current, saveForm)
      merge(res.messages); setPanel(null)
    })
  }
  const stopEmails = () => act(async () => { merge((await stopChatEmails(chatKey, token.current)).messages); setPanel(null) })
  const openShop = () => act(async () => {
    const r = await getChatProducts(chatKey, token.current)
    setProducts(r.products || []); setCart(r.cart || { items: [], total: 0, count: 0 }); setPanel('shop')
  })
  const addToCart = (p) => act(async () => {
    const vid = picked[p.id] || (p.variants.length === 1 ? p.variants[0].id : undefined)
    if (p.variants.length && !vid) { setError('Please choose an option first.'); return }
    setCart(await changeChatCart(chatKey, token.current, { action: 'add', product_id: p.id, variant_id: vid, qty: 1 }))
  })
  const removeLine = (line) => act(async () => {
    setCart(await changeChatCart(chatKey, token.current, { action: 'remove', product_id: line.pid, variant_id: line.vid || undefined }))
  })
  const checkout = () => act(async () => {
    if (!hasContact) { setPanel('contact'); setError('Please share your contact details first, then check out.'); return }
    try {
      const res = await chatCheckout(chatKey, token.current)
      merge(res.messages); setCart(res.cart || { items: [], total: 0, count: 0 }); setPanel(null)
      if (res.human) setHuman(true)
    } catch (e) {
      if (e?.response?.data?.detail?.ask_contact) { setPanel('contact'); setError('Please share your contact details first, then check out.') } else throw e
    }
  })
  const submitBooking = (e) => {
    e.preventDefault()
    act(async () => {
      const res = await sendBooking(chatKey, token.current, booking)
      merge(res.messages)
      setBooking({})
      setPanel(null)
    })
  }

  const brandDark = `color-mix(in srgb, ${brand} 78%, black)`
  const tint = `color-mix(in srgb, ${brand} 10%, white)`
  const tintLine = `color-mix(in srgb, ${brand} 28%, white)`

  const S = {
    brandDark,
    page: { height: '100dvh', display: 'flex', justifyContent: 'center', background: '#E4EAED', fontFamily: FONT, color: INK },
    shell: { width: '100%', maxWidth: 520, position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', background: BG, height: '100%', boxShadow: '0 0 24px rgba(0,0,0,0.06)' },
    head: { flex: 'none', display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: '#fff', borderBottom: `1px solid ${LINE}` },
    avatar: { width: 40, height: 40, flex: 'none', borderRadius: 999, background: brand, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 16 },
    list: { flex: 1, minHeight: 0, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 },
    row: (role) => ({ alignSelf: role === 'visitor' ? 'flex-end' : 'flex-start', maxWidth: '82%', display: 'flex', flexDirection: 'column', gap: 3, alignItems: role === 'visitor' ? 'flex-end' : 'flex-start' }),
    bubble: (role) => ({
      padding: '10px 14px', fontSize: 15, lineHeight: 1.45, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
      borderRadius: role === 'visitor' ? '18px 18px 6px 18px' : '18px 18px 18px 6px',
      background: role === 'visitor' ? brand : role === 'rep' ? tint : '#fff',
      color: role === 'visitor' ? '#fff' : INK,
      border: role === 'visitor' ? 'none' : `1px solid ${role === 'rep' ? tintLine : LINE}`,
    }),
    who: { fontSize: 12, fontWeight: 600, color: brandDark, marginLeft: 4 },
    chips: { display: 'flex', flexWrap: 'wrap', gap: 8 },
    chip: { minHeight: 44, padding: '0 16px', borderRadius: 999, border: `1.5px solid ${brand}`, background: '#fff', color: brandDark, fontSize: 15, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' },
    dock: { flex: 'none', background: '#fff', borderTop: `1px solid ${LINE}`, padding: '10px 16px 14px', display: 'flex', flexDirection: 'column', gap: 10 },
    action: { flex: 1, minHeight: 44, borderRadius: 12, border: `1px solid ${LINE}`, background: BG, color: INK, fontSize: 15, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 },
    input: { flex: 1, minWidth: 0, height: 48, padding: '0 18px', border: `1px solid ${LINE}`, borderRadius: 999, fontSize: 16, fontFamily: 'inherit', boxSizing: 'border-box', background: BG, color: INK },
    send: { width: 48, height: 48, flex: 'none', border: 0, borderRadius: 999, background: brand, color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' },
    linkBtn: { alignSelf: 'center', minHeight: 44, margin: '-4px 0 -8px', border: 0, background: 'transparent', color: brandDark, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 6 },
    card: { background: '#fff', border: `1px solid ${LINE}`, borderRadius: 18, padding: 14 },
    lab: { display: 'block', fontSize: 14, fontWeight: 600, margin: '0 0 6px' },
    field: { width: '100%', height: 48, padding: '0 14px', border: `1px solid ${FIELD_LINE}`, borderRadius: 12, fontSize: 16, fontFamily: 'inherit', boxSizing: 'border-box', background: '#fff', color: INK },
    primary: { width: '100%', minHeight: 50, border: 0, borderRadius: 12, background: brand, color: '#fff', fontSize: 16, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' },
    ghost: { width: '100%', minHeight: 44, border: 0, borderRadius: 12, background: 'transparent', color: brandDark, fontSize: 15, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' },
    outline: { width: '100%', minHeight: 44, border: `1px solid ${LINE}`, borderRadius: 12, background: '#fff', color: INK, fontSize: 15, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' },
    err: { flex: 'none', color: '#B3261E', background: '#FBE9E7', fontSize: 14, padding: '8px 16px' },
    center: { margin: 'auto', padding: 32, textAlign: 'center', color: MUTED, fontSize: 15, lineHeight: 1.5, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 },
    iconBtn: { width: 44, height: 44, flex: 'none', border: 0, borderRadius: 12, background: 'transparent', color: INK, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' },
    page2: { position: 'absolute', inset: 0, background: BG, display: 'flex', flexDirection: 'column', zIndex: 3 },
    scrim: { position: 'absolute', inset: 0, background: 'rgba(20,34,43,0.55)', zIndex: 4 },
    sheet: { position: 'absolute', left: 0, right: 0, bottom: 0, zIndex: 5, maxHeight: '92%', overflowY: 'auto', background: '#fff', borderRadius: '24px 24px 0 0', padding: '10px 20px 24px', display: 'flex', flexDirection: 'column', gap: 14 },
  }

  const css = (
    <style>{`
      .wc-root button:focus-visible, .wc-root input:focus-visible, .wc-root select:focus-visible { outline: 2px solid ${brand}; outline-offset: 2px; }
      .wc-root button:disabled { opacity: 0.55; cursor: default; }
      @keyframes wc-pulse { 0%,100% { opacity: .35; transform: scale(.92) } 50% { opacity: 1; transform: scale(1) } }
      @media (prefers-reduced-motion: reduce) { .wc-pulse { animation: none !important; } }
    `}</style>
  )

  if (state === 'loading') return (
    <div style={S.page} className="wc-root">{css}<div style={S.shell}><div style={S.center}>
      <div className="wc-pulse" aria-hidden="true" style={{ ...S.avatar, width: 64, height: 64, fontSize: 26, animation: 'wc-pulse 1.4s ease-in-out infinite' }}>·</div>
      <div role="status" style={{ fontSize: 16, fontWeight: 600, color: INK }}>Opening chat</div>
    </div></div></div>
  )
  if (state === 'closed') return (
    <div style={S.page} className="wc-root">{css}<div style={S.shell}><div style={S.center}>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: '-0.4px', color: INK }}>This chat is not available right now</h1>
      <p style={{ margin: 0, maxWidth: 280 }}>The business is not taking chat messages at the moment. Please check back later.</p>
    </div></div></div>
  )
  if (state === 'error') return (
    <div style={S.page} className="wc-root">{css}<div style={S.shell}><div style={S.center}>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: '-0.4px', color: INK }}>We could not open the chat</h1>
      <p style={{ margin: 0, maxWidth: 280 }}>Check your internet connection, then try again.</p>
      <button type="button" style={{ ...S.primary, width: 'auto', padding: '0 32px' }} onClick={() => { writeStore(tokenKey, null); window.location.reload() }}>Try again</button>
    </div></div></div>
  )

  const sheetOpen = ['contact', 'email', 'booking', 'save'].includes(panel)
  const sheetTitle = { contact: 'Where can we reach you?', email: 'Get the reply by email?', booking: 'Send a booking request', save: 'Keep this chat' }[panel]

  return (
    <div style={S.page} className="wc-root">
      {css}
      <div style={S.shell}>
        <header style={S.head}>
          <div style={S.avatar} aria-hidden="true">{(cfg.business_name || '?').trim().charAt(0).toUpperCase()}</div>
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700, letterSpacing: '-0.2px', lineHeight: 1.2 }}>{cfg.business_name}</h1>
        </header>

        <main style={S.list} ref={listRef} role="log" aria-live="polite" aria-label="Chat messages">
          {messages.map((m, i) => (
            <div key={m.id} style={S.row(m.role)}>
              {m.role === 'rep' && (i === 0 || messages[i - 1].role !== 'rep') && <span style={S.who}>{cfg.business_name} team</span>}
              <div style={S.bubble(m.role)}><Linkified text={m.text} onTap={m.role === 'visitor' ? undefined : () => tapChat(chatKey, token.current)} /></div>
            </div>
          ))}

          {cards.length > 0 && !panel && cards.map((p) => <ProductCard key={p.id} p={p} S={S} brand={brand} busy={busy} picked={picked} setPicked={setPicked} onAdd={addToCart} />)}

          {cfg.menu.length > 0 && (
            <div style={S.chips}>
              {cfg.menu.map((m) => <button key={m.id} type="button" style={S.chip} disabled={busy} onClick={() => sendMenu(m.id)}>{m.label}</button>)}
            </div>
          )}

          {human && (
            <p style={{ margin: '4px 0', textAlign: 'center', fontSize: 13, color: MUTED }}>A team member will reply here.</p>
          )}
        </main>

        {error && !sheetOpen && !panel && <div style={S.err} role="alert">{error}</div>}

        <div style={S.dock}>
          {cfg.shop_enabled && (
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" style={S.action} disabled={busy} onClick={openShop}><Icon name="bag" />Shop</button>
              <button type="button" style={{ ...S.action, flex: 1.6, background: brand, borderColor: brand, color: '#fff' }} disabled={busy}
                onClick={() => setPanel('cart')}><Icon name="cart" />Cart ({cart.count}){cart.count > 0 ? ` · ${naira(cart.total)}` : ''}</button>
            </div>
          )}
          <form onSubmit={sendText} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label htmlFor="wc-text" style={{ position: 'absolute', left: '-9999px' }}>Type your message</label>
            <input id="wc-text" style={S.input} value={text} maxLength={1000} placeholder="Type your message" autoComplete="off"
              onChange={(e) => setText(e.target.value)} />
            <button type="submit" aria-label="Send" style={S.send} disabled={busy || !text.trim()}><Icon name="send" size={22} /></button>
          </form>
          {hasContact && cfg.email_enabled && (
            <button type="button" style={S.linkBtn} onClick={() => setPanel('save')}><Icon name="mail" size={18} />Email me this chat</button>
          )}
        </div>

        {panel === 'shop' && (
          <div style={S.page2}>
            <header style={S.head}>
              <button type="button" aria-label="Back to chat" style={{ ...S.iconBtn, marginLeft: -8 }} onClick={closePanel}><Icon name="back" size={22} /></button>
              <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Shop</h2>
            </header>
            <div style={{ ...S.list, flex: 1 }}>
              {products.length === 0 && <p style={{ margin: 0, fontSize: 15, color: MUTED }}>No products to show right now.</p>}
              {products.map((p) => <ProductCard key={p.id} p={p} S={S} brand={brand} busy={busy} picked={picked} setPicked={setPicked} onAdd={addToCart} />)}
            </div>
            {error && <div style={S.err} role="alert">{error}</div>}
            <div style={S.dock}>
              <button type="button" style={{ ...S.primary, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }} onClick={() => setPanel('cart')}>
                <Icon name="cart" />View cart ({cart.count}){cart.count > 0 ? ` · ${naira(cart.total)}` : ''}
              </button>
            </div>
          </div>
        )}

        {panel === 'cart' && (
          <div style={S.page2}>
            <header style={S.head}>
              <button type="button" aria-label="Back to chat" style={{ ...S.iconBtn, marginLeft: -8 }} onClick={closePanel}><Icon name="back" size={22} /></button>
              <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Your cart</h2>
            </header>
            <div style={{ ...S.list, flex: 1 }}>
              <div style={{ ...S.card, padding: '4px 16px 0' }}>
                {cart.items.length === 0 && <p style={{ margin: 0, padding: '14px 0', fontSize: 15, color: MUTED }}>Your cart is empty.</p>}
                {cart.items.map((i, n) => (
                  <div key={`${i.pid}-${i.vid}`} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0', borderTop: n ? `1px solid ${LINE}` : 'none' }}>
                    <Thumb src={i.image_url} alt={i.name} size={56} brand={brand} />
                    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ fontSize: 15, fontWeight: 600, overflowWrap: 'anywhere' }}>{i.name}</span>
                      <span style={{ fontSize: 13, color: MUTED }}>Quantity {i.qty}</span>
                      <span style={{ fontSize: 15, fontWeight: 700, color: brandDark }}>{naira(i.price * i.qty)}</span>
                    </div>
                    <button type="button" aria-label={`Remove ${i.name}`} style={{ minHeight: 44, padding: '0 10px', border: 0, background: 'transparent', color: '#B3261E', fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }} disabled={busy} onClick={() => removeLine(i)}>Remove</button>
                  </div>
                ))}
                {cart.items.length > 0 && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '16px 0', borderTop: `1px solid ${LINE}` }}>
                    <span style={{ fontSize: 15, color: MUTED }}>Total</span>
                    <b style={{ fontSize: 22, letterSpacing: '-0.4px' }}>{naira(cart.total)}</b>
                  </div>
                )}
              </div>
              {cart.items.length > 0 && (
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: MUTED, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                  <Icon name="lock" size={18} /><span>You pay on a secure page.</span>
                </p>
              )}
            </div>
            {error && <div style={S.err} role="alert">{error}</div>}
            <div style={S.dock}>
              {cart.items.length > 0 && <button type="button" style={S.primary} disabled={busy} onClick={checkout}>Pay {naira(cart.total)}</button>}
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" style={{ ...S.outline, flex: 1 }} onClick={openShop} disabled={busy}>Keep shopping</button>
                <button type="button" style={{ ...S.ghost, flex: 1 }} onClick={closePanel}>Back to chat</button>
              </div>
            </div>
          </div>
        )}

        {sheetOpen && (
          <>
            <div style={S.scrim} onClick={closePanel} aria-hidden="true" />
            <section role="dialog" aria-modal="true" aria-label={sheetTitle} style={S.sheet}>
              <div aria-hidden="true" style={{ alignSelf: 'center', width: 40, height: 4, borderRadius: 999, background: LINE }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, letterSpacing: '-0.3px' }}>{sheetTitle}</h2>
                  <p style={{ margin: '4px 0 0', fontSize: 14, lineHeight: 1.45, color: MUTED }}>
                    {panel === 'contact' && cfg.contact_prompt}
                    {panel === 'email' && 'Add your email and we will write to you there. This is optional.'}
                    {panel === 'booking' && 'Fill in the details and the team will confirm.'}
                    {panel === 'save' && 'We will email you this chat, and tell you if the team replies after you have left.'}
                  </p>
                </div>
                <button type="button" aria-label="Close" style={{ ...S.iconBtn, margin: '-6px -10px 0 0' }} onClick={closePanel}><Icon name="close" size={22} /></button>
              </div>

              {panel === 'contact' && (
                <form onSubmit={submitContact} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <label><span style={S.lab}>Your name</span>
                    <input style={S.field} value={contact.name} maxLength={80} autoComplete="name" required
                      onChange={(e) => setContact({ ...contact, name: e.target.value })} /></label>
                  <label><span style={S.lab}>Phone or WhatsApp number</span>
                    <input style={S.field} value={contact.phone} maxLength={30} inputMode="tel" autoComplete="tel"
                      onChange={(e) => setContact({ ...contact, phone: e.target.value })} /></label>
                  <label><span style={S.lab}>Email <span style={{ fontWeight: 400, color: MUTED }}>(optional if you gave a number)</span></span>
                    <input style={S.field} value={contact.email} maxLength={200} inputMode="email" autoComplete="email"
                      onChange={(e) => setContact({ ...contact, email: e.target.value })} /></label>
                  {/* Spam trap. A textarea with an unrelated name, so Chrome autofill does not fill it (it filled a field named "website" and the server then silently dropped the contact form). */}
                  <textarea aria-hidden="true" tabIndex={-1} autoComplete="off" value={contact.website} name="hp_note_x7" rows={1}
                    onChange={(e) => setContact({ ...contact, website: e.target.value })}
                    style={{ position: 'absolute', left: '-9999px', width: 1, height: 1, opacity: 0, pointerEvents: 'none' }} />
                  <label style={{ display: 'flex', gap: 12, alignItems: 'flex-start', minHeight: 44, cursor: 'pointer' }}>
                    <input type="checkbox" checked={contact.consent} style={{ width: 22, height: 22, margin: '1px 0 0', accentColor: brand, flex: 'none' }}
                      onChange={(e) => setContact({ ...contact, consent: e.target.checked })} />
                    <span style={{ fontSize: 14, lineHeight: 1.45 }}>{cfg.consent_text}</span>
                  </label>
                  <button type="submit" style={S.primary} disabled={busy}>Continue to chat</button>
                </form>
              )}

              {panel === 'email' && (
                <form onSubmit={submitContact} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <label><span style={S.lab}>Email address</span>
                    <input style={S.field} value={contact.email} maxLength={200} inputMode="email" autoComplete="email"
                      onChange={(e) => setContact({ ...contact, email: e.target.value, consent: !!e.target.value })} /></label>
                  <button type="submit" style={S.primary} disabled={busy || !contact.email}>Save email</button>
                  <button type="button" style={S.ghost} onClick={closePanel}>No thanks</button>
                </form>
              )}

              {panel === 'booking' && (
                <form onSubmit={submitBooking} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {cfg.booking_fields.map((f) => (
                    <label key={f.key}><span style={S.lab}>{f.label}</span>
                      <input style={S.field} value={booking[f.key] || ''} maxLength={300} required={f.required}
                        onChange={(e) => setBooking({ ...booking, [f.key]: e.target.value })} /></label>
                  ))}
                  <button type="submit" style={S.primary} disabled={busy}>Send booking request</button>
                </form>
              )}

              {panel === 'save' && (
                <form onSubmit={submitSave} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <label><span style={S.lab}>Email address</span>
                    <input style={S.field} value={saveForm.email} maxLength={200} inputMode="email" autoComplete="email" required
                      onChange={(e) => setSaveForm({ ...saveForm, email: e.target.value })} /></label>
                  <label style={{ display: 'flex', gap: 12, alignItems: 'flex-start', minHeight: 44, cursor: 'pointer' }}>
                    <input type="checkbox" checked={saveForm.consent} style={{ width: 22, height: 22, margin: '1px 0 0', accentColor: brand, flex: 'none' }}
                      onChange={(e) => setSaveForm({ ...saveForm, consent: e.target.checked })} />
                    <span style={{ fontSize: 14, lineHeight: 1.45 }}>Email me this chat and any replies from {cfg.business_name}. I can stop these emails any time.</span>
                  </label>
                  <button type="submit" style={S.primary} disabled={busy}>Email me this chat</button>
                  <div style={{ borderTop: `1px solid ${LINE}`, paddingTop: 6 }}>
                    <button type="button" style={S.ghost} onClick={stopEmails} disabled={busy}>Stop follow-up emails</button>
                  </div>
                </form>
              )}

              {error && <div style={{ ...S.err, borderRadius: 8 }} role="alert">{error}</div>}
            </section>
          </>
        )}
      </div>
    </div>
  )
}
