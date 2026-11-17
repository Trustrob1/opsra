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
import { viewingChat, startContactChat, pingTyping, startChat, resumeChat, pollChat, sendChat, uploadChatFile, sendContact, sendBooking, getChatProducts, changeChatCart, chatCheckout, saveChatByEmail, stopChatEmails, tapChat, getChatConfig, requestChatCallback, editChatMessage, deleteChatMessage, chatErrorMessage } from '../services/webchat.service'

const POLL_MS = 4000
const URL_RE = /(https?:\/\/[^\s<>"']+)/g
const FONT = "'DM Sans', system-ui, sans-serif"
const INK = '#14222B'
const MUTED = '#566770'
const LINE = '#DCE4E8'
const FIELD_LINE = '#B9C6CC'
const BG = '#F4F7F8'

// WEBCHAT-EMBED-1: inside the website bubble (widget.js) the page is opened with ?embed=1&po=<the website>
const EMBED = (() => { try { return new URLSearchParams(window.location.search).get('embed') === '1' } catch { return false } })()
function parentSite() {
  if (!EMBED) return undefined
  try {
    const po = new URLSearchParams(window.location.search).get('po')
    if (po) return po
    if (window.location.ancestorOrigins?.length) return window.location.ancestorOrigins[0]
    if (document.referrer) return new URL(document.referrer).origin
  } catch { /* unknown */ }
  return 'unknown'
}
const closeEmbed = () => { try { window.parent.postMessage({ source: 'opsra-chat', type: 'close' }, '*') } catch { /* not framed */ } }

const NEED_WHY = { 'ask for a call back': 'callback', 'send your file': 'file', 'record your voice note': 'voice' }
function readStore(key) { try { return window.localStorage.getItem(key) } catch { return null } }
function writeStore(key, v) { try { v ? window.localStorage.setItem(key, v) : window.localStorage.removeItem(key) } catch { /* private mode */ } }

const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`

// the chat fills the screen; on a wide screen the words stay in a readable column in the middle
const GUT = 'max(16px, calc((100% - 880px) / 2))'
const EDIT_WINDOW_MS = 15 * 60 * 1000       // the server enforces this too
const MAX_MB = { image: 10, document: 15, audio: 5 }
const DOC_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.txt'
const IMG_ACCEPT = 'image/jpeg,image/png,image/gif,image/webp'
const REC_MAX_S = 120
const BAR_H = [10, 18, 14, 24, 16, 28, 12, 20, 26, 14, 22, 10, 18, 24, 12, 20, 16, 26, 14, 18, 22, 12, 24, 16]
const fmtTime = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`
const recorderSupported = () => typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof window.MediaRecorder !== 'undefined'
const pickMime = () => ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find((t) => window.MediaRecorder.isTypeSupported?.(t)) || ''

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
  if (name === 'phone') return <svg {...common}><path d="M6.6 3.5h2.8l1.4 4-1.8 1.3a11 11 0 005.2 5.2l1.3-1.8 4 1.4v2.8a2 2 0 01-2.2 2A15.5 15.5 0 014.6 5.7a2 2 0 012-2.2z" /></svg>
  if (name === 'chat') return <svg {...common}><path d="M4 5.5h16v11H9.5L5 20v-3.5H4z" /></svg>
  if (name === 'reply') return <svg {...common}><path d="M10 6L4 12l6 6M4 12h10a6 6 0 016 6" /></svg>
  if (name === 'edit') return <svg {...common}><path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4" /></svg>
  if (name === 'copy') return <svg {...common}><rect x="8" y="8" width="12" height="12" rx="2.5" /><path d="M16 8V6.5A2.5 2.5 0 0013.5 4h-7A2.5 2.5 0 004 6.5v7A2.5 2.5 0 006.5 16H8" /></svg>
  if (name === 'check') return <svg {...common} strokeWidth="2.4"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
  if (name === 'menu') return <svg {...common}><path d="M4 7h16M4 12h16M4 17h10" /></svg>
  if (name === 'chev') return <svg {...common}><path d="M9 5l7 7-7 7" /></svg>
  if (name === 'clip') return <svg {...common}><path d="M20 11.5l-7.8 7.8a5 5 0 01-7-7l8-8a3.3 3.3 0 014.7 4.7l-8 8a1.7 1.7 0 01-2.4-2.4l7.4-7.4" /></svg>
  if (name === 'mic') return <svg {...common}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21" /></svg>
  if (name === 'trash') return <svg {...common}><path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13M10.5 11v6M13.5 11v6" /></svg>
  if (name === 'play') return <svg {...common} fill="currentColor" stroke="none"><path d="M8 5.5v13l11-6.5z" /></svg>
  if (name === 'pause') return <svg {...common} fill="currentColor" stroke="none"><rect x="7" y="5" width="3.6" height="14" rx="1" /><rect x="13.4" y="5" width="3.6" height="14" rx="1" /></svg>
  if (name === 'image') return <svg {...common}><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><circle cx="9" cy="10" r="1.8" /><path d="M4 17l5-4.5 3.5 3L15 13l5 4.5" /></svg>
  if (name === 'camera') return <svg {...common}><path d="M4 8.5h3l1.5-2.5h7L17 8.5h3a1 1 0 011 1V18a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5a1 1 0 011-1z" /><circle cx="12" cy="13.5" r="3.4" /></svg>
  if (name === 'file') return <svg {...common}><path d="M7 3.5h7l4.5 4.5v12a1 1 0 01-1 1H7a1 1 0 01-1-1v-15a1 1 0 011-1z M14 3.5V8h4.5" /><path d="M9 13h6M9 16.5h6" /></svg>
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

const fmtClock = (iso) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

// WhatsApp-style ticks under the visitor's messages: one = sent, two = delivered, two in colour = the team has replied.
function Ticks({ state, color }) {
  const label = { sent: 'Sending', delivered: 'Delivered', read: 'Seen by the team' }[state]
  return (
    <svg role="img" aria-label={label} width="18" height="12" viewBox="0 0 18 12" fill="none" stroke={state === 'read' ? color : 'currentColor'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flex: 'none' }}>
      <path d="M1.5 6.5l3.2 3.2L11 2.5" />
      {state !== 'sent' && <path d="M7 9.2l.5.5L14.5 2.5" />}
    </svg>
  )
}

function VoiceNote({ src, mine, brand }) {
  const ref = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [pos, setPos] = useState(0)
  const [dur, setDur] = useState(0)
  const toggle = () => { const a = ref.current; if (!a) return; if (a.paused) a.play().catch(() => {}); else a.pause() }
  const total = Number.isFinite(dur) && dur > 0 ? dur : 0
  const frac = total ? pos / total : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: 230 }}>
      <audio ref={ref} src={src} preload="metadata"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setPos(0) }}
        onTimeUpdate={(e) => setPos(e.currentTarget.currentTime)} onLoadedMetadata={(e) => setDur(e.currentTarget.duration)} />
      <button type="button" aria-label={playing ? 'Pause voice note' : 'Play voice note'} onClick={toggle}
        style={{ width: 44, height: 44, flex: 'none', border: 0, borderRadius: 999, background: mine ? '#fff' : brand, color: mine ? brand : '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={playing ? 'pause' : 'play'} size={20} />
      </button>
      <div aria-hidden="true" style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 2, height: 30 }}>
        {BAR_H.map((h, i) => <span key={i} style={{ display: 'block', width: 3, height: h, borderRadius: 2, background: 'currentColor', opacity: i / BAR_H.length < frac ? 1 : 0.4 }} />)}
      </div>
      <span style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>{fmtTime(playing || pos ? pos : total)}</span>
    </div>
  )
}

function AttachmentBubble({ a, mine, brand }) {
  if (a.kind === 'image') {
    return (
      <a href={a.uploading ? undefined : a.url} target="_blank" rel="noopener noreferrer" style={{ position: 'relative', display: 'block', lineHeight: 0 }}>
        <img src={a.url} alt={a.name || 'Photo'} style={{ display: 'block', maxWidth: 240, maxHeight: 280, width: '100%', borderRadius: 14, background: '#e6edf0' }} />
        {a.uploading && (
          <span style={{ position: 'absolute', inset: 0, borderRadius: 14, background: 'rgba(20,34,43,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 14, fontWeight: 700, lineHeight: 1 }}>
            {a.progress || 0}%
          </span>
        )}
      </a>
    )
  }
  if (a.kind === 'audio') return <VoiceNote src={a.url} mine={mine} brand={brand} />
  return (
    <a href={a.uploading ? undefined : a.url} target="_blank" rel="noopener noreferrer" download={a.name || true}
      style={{ display: 'flex', alignItems: 'center', gap: 12, width: 230, color: 'inherit', textDecoration: 'none' }}>
      <span aria-hidden="true" style={{ width: 44, height: 44, flex: 'none', borderRadius: 12, background: mine ? 'rgba(255,255,255,0.2)' : `color-mix(in srgb, ${brand} 12%, white)`, color: mine ? '#fff' : brand, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Icon name="file" size={24} />
      </span>
      <span style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <span style={{ fontSize: 15, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.name || 'Document'}</span>
        <span style={{ fontSize: 13, opacity: 0.85 }}>{a.uploading ? `Sending ${a.progress || 0}%` : 'Tap to open'}</span>
      </span>
    </a>
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
  const [state, setState] = useState('loading')           // loading | ready | closed | blocked | error
  const [cfg, setCfg] = useState(null)
  const [messages, setMessages] = useState([])
  const [hasContact, setHasContact] = useState(false)
  const [verified, setVerified] = useState(false)
  const [human, setHuman] = useState(false)
  const typingPing = useRef(0)
  const [repTyping, setRepTyping] = useState(false)    // WEBCHAT-CONTACT-1d: a team member is writing a reply
  const [contactStep, setContactStep] = useState(null)   // WEBCHAT-CONTACT-1: null | 'name' | 'phone' | 'consent' (Chioma is asking for details in the chat)
  const [hiddenIds, setHiddenIds] = useState(null)       // WEBCHAT-CONTACT-1: back after a long quiet spell: earlier messages are folded away, one tap shows them
  const [meName, setMeName] = useState('')
  const [menuSeen, setMenuSeen] = useState(() => { try { return localStorage.getItem(`wc_menu_seen_${chatKey}`) === '1' } catch { return false } })
  const [msgMenu, setMsgMenu] = useState(null)         // { id, top, mine } while the message menu is open
  const [replyTo, setReplyTo] = useState(null)         // { id, role, text } the visitor is replying to
  const [editing, setEditing] = useState(null)         // { id } while a sent message is being edited
  const [confirmDel, setConfirmDel] = useState(null)   // message id awaiting 'Delete for everyone'
  const inputRef = useRef(null)
  const shellRef = useRef(null)
  const [callPhone, setCallPhone] = useState(null)         // null = not asked yet, string = the phone field is showing
  const [panel, setPanel] = useState(null)                // null | 'contact' | 'email' | 'booking' | 'shop' | 'cart' | 'save' | 'menu' | 'attach' | 'call'
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
  const [rec, setRec] = useState(null)                    // null | { seconds } while recording a voice note
  const recRef = useRef({ mr: null, stream: null, chunks: [], timer: null, cancelled: false, mime: '' })
  const uploadRef = useRef(null)
  const photoRef = useRef(null)
  const cameraRef = useRef(null)
  const docRef = useRef(null)
  const [pending, setPending] = useState(0)             // messages sent and waiting for the reply (drives the typing dots)
  const initialCount = useRef(0)                       // messages that were already there when the chat opened (no pop-in for those)
  const token = useRef(null)
  const listRef = useRef(null)
  const tokenKey = `wc_token_${chatKey}`

  const brand = cfg?.brand_color || '#028090'

  const merge = useCallback((incoming) => {
    if (!incoming?.length) return
    setMessages((cur) => {
      const byId = new Map(cur.map((m) => [m.id, m]))
      // a message the visitor or the server changed (edited, deleted): update it in place, only when something differs
      let touched = false
      const updated = cur.map((m) => {
        const n = incoming.find((x) => x.id === m.id)
        if (n && (n.deleted ? !m.deleted : (n.edited && (n.text !== m.text || !m.edited)))) { touched = true; return { ...m, ...n } }
        return m
      })
      const add = incoming.filter((m) => !byId.has(m.id))
      if (!add.length) return touched ? updated : cur
      const said = add.filter((m) => m.role === 'visitor').map((m) => m.text)
      const kept = said.length ? updated.filter((m) => !(m.tmp && said.includes(m.text))) : updated
      return [...kept, ...add].sort((a, b) => String(a.at).localeCompare(String(b.at)))
    })
  }, [])

  const apply = useCallback((snap) => {
    setCfg(snap.config)
    setMessages(snap.messages || [])
    const fold = !!snap.returning && (snap.messages || []).length > 0
    setHiddenIds(fold ? new Set(snap.messages.map((m) => m.id)) : null)
    initialCount.current = fold ? 0 : (snap.messages || []).length
    setContactStep(snap.contact_step || null)
    setMeName(snap.name ? String(snap.name).split(' ')[0].slice(0, 30) : '')
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
  useEffect(() => { if (cfg?.business_name) document.title = `Chat with Chioma · ${cfg.business_name}` }, [cfg])

  // open: hand-off link → resume stored session → new session
  useEffect(() => {
    let dead = false
    const params = new URLSearchParams(window.location.search)
    const handoff = params.get('h')
    const source = params.get('s') || (handoff ? 'whatsapp' : undefined)
    const fresh = async () => {
      const snap = await startChat(chatKey, { source, handoff: handoff || undefined, embedOrigin: parentSite() })
      token.current = snap.token
      writeStore(tokenKey, snap.token)
      return snap
    }
    ;(async () => {
      try {
        let snap
        const stored = handoff ? null : readStore(tokenKey)
        if (stored) {
          try { token.current = stored; snap = await resumeChat(chatKey, stored, parentSite()) }
          catch (e) { if (e?.response?.status === 401) snap = await fresh(); else throw e }
        } else {
          snap = await fresh()
        }
        if (dead) return
        if (handoff) window.history.replaceState({}, '', window.location.pathname)   // the one-time token is spent
        apply(snap)
        if (snap.needs_email && snap.messages.length > 2) setPanel('email')
      } catch (e) {
        if (!dead) setState(e?.response?.data?.detail?.code === 'EMBED_NOT_ALLOWED' ? 'blocked' : e?.response?.status === 404 ? 'closed' : 'error')
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
        const real = messages.filter((m) => !m.tmp)
        const last = real.length ? real[real.length - 1].at : undefined
        const res = await pollChat(chatKey, token.current, last)
        merge(res.messages)
        setHuman(!!res.human)
        setRepTyping(!!res.rep_typing)
      } catch (e) {
        if (e?.response?.status === 401) { writeStore(tokenKey, null); setState('error') }
      }
    }, POLL_MS)
    return () => clearInterval(id)
  }, [state, messages, chatKey, tokenKey, merge])

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    if (typeof el.scrollTo === 'function') el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }); else el.scrollTop = el.scrollHeight
  }, [messages, cards, pending])

  const handleReply = (res) => {
    merge(res.messages)
    if (typeof res.human === 'boolean') setHuman(res.human)
    setCards(res.cards || [])
    setContactStep(res.contact_step || null)
    if (res.form === 'booking') setPanel('booking')
    else if (res.ask_contact) setPanel('contact')
    else if (res.ask_email) setPanel('email')
  }

  // WEBCHAT-CATALOG-1: opened from a Storefront product page (?p=) or told so later by the page around us (postMessage).
  // The server checks the id against this business's catalogue; the chat works the same if anything here fails.
  const handleReplyRef = useRef(handleReply)
  handleReplyRef.current = handleReply
  const viewingSent = useRef(null)
  const sendViewing = useCallback(async (pid) => {
    const id = String(pid || '').slice(0, 60)
    if (!/^[A-Za-z0-9_-]{1,60}$/.test(id) || viewingSent.current === id || !token.current) return
    viewingSent.current = id
    try { handleReplyRef.current(await viewingChat(chatKey, token.current, id)) } catch { /* the chat still works */ }
  }, [chatKey])
  useEffect(() => {
    if (state !== 'ready') return
    let p = null
    try { p = new URLSearchParams(window.location.search).get('p') } catch { /* ignore */ }
    if (p) sendViewing(p)
  }, [state, sendViewing])
  useEffect(() => {
    const onMsg = (e) => {
      if (e.origin !== window.location.origin || !e.data || e.data.source !== 'opsra-catalog' || e.data.type !== 'viewing') return
      sendViewing(e.data.product)
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [sendViewing])

  const act = async (fn) => {
    if (busy) return
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(chatErrorMessage(e)) } finally { setBusy(false) }
  }

  const closePanel = () => { setPanel(null); setError('') }
  // Show the visitor's message at once, with typing dots until the reply arrives (the server can take a second or two).
  const sendOptimistic = async (label, payload, reply) => {
    const tmp = { id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, role: 'visitor', text: label, at: new Date().toISOString(), tmp: true, ...(reply ? { reply_to: reply.id, reply: { role: reply.role, text: reply.text } } : {}) }
    setMessages((cur) => [...cur, tmp])
    setPending((n) => n + 1)
    setError('')
    try {
      const res = await sendChat(chatKey, token.current, payload)
      setMessages((cur) => cur.filter((m) => m.id !== tmp.id))
      handleReply(res)
      return true
    } catch (e) {
      setMessages((cur) => cur.filter((m) => m.id !== tmp.id))
      setError(chatErrorMessage(e))
      return false
    } finally {
      setPending((n) => Math.max(0, n - 1))
    }
  }
  const openMenu = () => {
    setPanel('menu')
    if (!menuSeen) { setMenuSeen(true); try { localStorage.setItem(`wc_menu_seen_${chatKey}`, '1') } catch { /* storage blocked */ } }
  }
  const openCall = () => {
    setError(''); setCallPhone(null); setPanel('call')
    // the server decides open or closed; ask again so a page left open for hours is not out of date
    getChatConfig(chatKey).then((c) => { if (c) setCfg((old) => (old ? { ...old, call: c.call } : old)) }).catch(() => {})
  }
  const callBack = () => {
    if (!hasContact) { needContact('ask for a call back'); return }
    act(async () => {
      try {
        const res = await requestChatCallback(chatKey, token.current, callPhone || undefined)
        merge(res.messages); setPanel(null); setCallPhone(null)
      } catch (e) {
        if (e?.response?.data?.detail?.need_phone) { setCallPhone(''); setError('') ; return }
        throw e
      }
    })
  }
  const voiceFromCall = () => { setPanel(null); startRec() }
  const sendMenu = (id) => {
    setPanel(null)
    const label = cfg.menu.find((m) => m.id === id)?.label || ''
    return sendOptimistic(label, { kind: 'menu', menu_id: id })
  }
  const sendText = (e) => {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    if (editing) {
      const id = editing.id
      act(async () => {
        const m = await editChatMessage(chatKey, token.current, id, t)
        merge([m]); setEditing(null); setText('')
      })
      return
    }
    const rq = replyTo
    setText(''); setReplyTo(null)
    sendOptimistic(t, { kind: 'text', text: t, ...(rq ? { reply_to: rq.id } : {}) }, rq).then((ok) => { if (!ok) { setText(t); if (rq) setReplyTo(rq) } })
  }

  // WEBCHAT-MSG-1: tap a message for Reply / Copy / Edit / Delete (like WhatsApp)
  const whoLabel = (role) => (role === 'visitor' ? 'You' : role === 'rep' ? `${cfg.business_name} team` : cfg.business_name)
  const msgActions = (m) => {
    const mine = m.role === 'visitor'
    const acts = [['reply', 'Reply']]
    if (!m.attachment) acts.push(['copy', 'Copy'])
    if (mine && !m.attachment && Date.now() - Date.parse(m.at) < EDIT_WINDOW_MS) acts.push(['edit', 'Edit'])
    if (mine) acts.push(['delete', 'Delete'])
    return acts
  }
  const openMsgMenu = (e, m) => {
    if (m.tmp || m.deleted || m.attachment?.uploading || rec) return
    if (e.target.closest && e.target.closest('a,audio,button')) return
    const shell = shellRef.current?.getBoundingClientRect()
    const box = e.currentTarget.getBoundingClientRect()
    if (!shell) return
    const h = msgActions(m).length * 48 + 8
    let top = box.bottom - shell.top + 8
    if (top + h > shell.height - 130) top = Math.max(64, box.top - shell.top - h - 8)
    const mine = m.role === 'visitor'
    setMsgMenu({ id: m.id, top, mine, side: mine ? Math.max(8, shell.right - box.right) : Math.max(8, box.left - shell.left) })
  }
  const closeMsgMenu = () => setMsgMenu(null)
  const runMsgAction = (kind) => {
    const m = messages.find((x) => x.id === msgMenu?.id)
    setMsgMenu(null)
    if (!m) return
    if (kind === 'reply') {
      setEditing(null)
      setReplyTo({ id: m.id, role: m.role, text: m.attachment ? ({ image: 'Photo', audio: 'Voice note' }[m.attachment.kind] || m.attachment.name || 'Document') : m.text })
      setTimeout(() => inputRef.current?.focus(), 0)
    } else if (kind === 'copy') {
      try { navigator.clipboard?.writeText(m.text) } catch { /* clipboard not allowed */ }
    } else if (kind === 'edit') {
      setReplyTo(null); setEditing({ id: m.id }); setText(m.text)
      setTimeout(() => inputRef.current?.focus(), 0)
    } else if (kind === 'delete') {
      setConfirmDel(m.id); setError(''); setPanel('delete')
    }
  }
  const confirmDelete = () => act(async () => {
    const id = confirmDel
    const m = await deleteChatMessage(chatKey, token.current, id)
    merge([m]); setPanel(null); setConfirmDel(null)
    setReplyTo((r) => (r && r.id === id ? null : r)); setEditing((x) => (x && x.id === id ? null : x))
  })
  const cancelCompose = () => { if (editing) setText(''); setEditing(null); setReplyTo(null) }
  // WEBCHAT-ATTACH-1: photos, voice notes and documents. Shown at once with progress; the server checks the real file type.
  const uploadFile = async (file, kind) => {
    if (!file) return
    if (file.size > MAX_MB[kind] * 1024 * 1024) { setError(`That file is too big. The limit is ${MAX_MB[kind]} MB.`); return }
    const url = kind === 'document' ? undefined : URL.createObjectURL(file)
    const name = kind === 'audio' ? 'Voice note' : (file.name || 'File')
    const tmp = { id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, role: 'visitor', text: name, at: new Date().toISOString(), tmp: true,
      attachment: { kind, name, url, uploading: true, progress: 0 } }
    setMessages((cur) => [...cur, tmp])
    setError('')
    try {
      const res = await uploadChatFile(chatKey, token.current, file, kind, (p) => setMessages((cur) => cur.map((m) => (m.id === tmp.id ? { ...m, attachment: { ...m.attachment, progress: p } } : m))))
      setMessages((cur) => cur.filter((m) => m.id !== tmp.id))
      handleReply(res)
    } catch (e) {
      setMessages((cur) => cur.filter((m) => m.id !== tmp.id))
      if (e?.response?.data?.detail?.ask_contact) { askInChat('file', 'Please share your contact details first, then send your file.'); return }
      setError(chatErrorMessage(e))
    } finally {
      if (url) setTimeout(() => URL.revokeObjectURL(url), 8000)
    }
  }
  uploadRef.current = uploadFile
  // WEBCHAT-CONTACT-1: a button needs the visitor's details: Chioma asks in the chat; the form opens only if the business switched that off
  const askInChat = async (why, formMsg) => {
    if (cfg?.contact_in_chat !== false && token.current) {
      try {
        const res = await startContactChat(chatKey, token.current, why)
        if (!res.form) { setPanel(null); setError(''); handleReply(res); return }
      } catch { /* fall back to the form below */ }
    }
    setPanel('contact'); setError(formMsg)
  }
  const needContact = (why) => askInChat(NEED_WHY[why] || '', `Please share your contact details first, then ${why}.`)
  const onAttach = () => { if (!hasContact) needContact('send your file'); else { setError(''); setPanel('attach') } }
  const pickFile = (kind) => (e) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    setPanel(null)
    uploadFile(f, kind)
  }
  const startRec = async () => {
    if (!hasContact) { needContact('record your voice note'); return }
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = pickMime()
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
      const r = recRef.current
      r.mr = mr; r.stream = stream; r.chunks = []; r.cancelled = false; r.mime = mr.mimeType || mime
      mr.ondataavailable = (ev) => { if (ev.data?.size) r.chunks.push(ev.data) }
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        clearInterval(r.timer)
        setRec(null)
        if (r.cancelled || !r.chunks.length) return
        const type = (r.mime || 'audio/webm').split(';')[0]
        const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm'
        uploadRef.current?.(new File(r.chunks, `voice-note.${ext}`, { type }), 'audio')
      }
      mr.start()
      setRec({ seconds: 0 })
      r.timer = setInterval(() => setRec((c) => {
        if (!c) return c
        const n = c.seconds + 1
        if (n >= REC_MAX_S && r.mr?.state === 'recording') r.mr.stop()
        return { seconds: n }
      }), 1000)
    } catch {
      setError('We could not use your microphone. Allow microphone access in your browser to send voice notes.')
    }
  }
  const stopRec = () => { const r = recRef.current; r.cancelled = false; if (r.mr?.state === 'recording') r.mr.stop() }
  const cancelRec = () => { const r = recRef.current; r.cancelled = true; if (r.mr?.state === 'recording') r.mr.stop() }
  useEffect(() => () => {
    const r = recRef.current
    r.cancelled = true
    clearInterval(r.timer)
    try { if (r.mr?.state === 'recording') r.mr.stop() } catch { /* already stopped */ }
  }, [])

  const submitContact = (e) => {
    e.preventDefault()
    act(async () => {
      const res = await sendContact(chatKey, token.current, { ...contact, name: verified ? undefined : contact.name })
      merge(res.messages)
      setCards(res.cards || [])
      setContactStep(null)
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
    if (!hasContact) { await askInChat('checkout', 'Please share your contact details first, then check out.'); return }
    try {
      const res = await chatCheckout(chatKey, token.current)
      merge(res.messages); setCart(res.cart || { items: [], total: 0, count: 0 }); setPanel(null)
      if (res.human) setHuman(true)
    } catch (e) {
      if (e?.response?.data?.detail?.ask_contact) await askInChat('checkout', 'Please share your contact details first, then check out.'); else throw e
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
    page: { height: '100dvh', display: 'flex', background: BG, fontFamily: FONT, color: INK },
    shell: { width: '100%', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', background: BG, height: '100%' },
    head: { flex: 'none', display: 'flex', alignItems: 'center', gap: 12, padding: `12px ${GUT}`, background: '#fff', borderBottom: `1px solid ${LINE}` },
    avatar: { width: 40, height: 40, flex: 'none', borderRadius: 999, background: brand, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 16 },
    list: { flex: 1, minHeight: 0, overflowY: 'auto', padding: `16px ${GUT}`, display: 'flex', flexDirection: 'column', gap: 12 },
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
    dock: { flex: 'none', background: '#fff', borderTop: `1px solid ${LINE}`, padding: `10px ${GUT} 14px`, display: 'flex', flexDirection: 'column', gap: 10 },
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
    sheet: { position: 'absolute', left: 0, right: 0, margin: '0 auto', maxWidth: 560, bottom: 0, zIndex: 5, maxHeight: '92%', overflowY: 'auto', background: '#fff', borderRadius: '24px 24px 0 0', padding: '10px 20px 24px', display: 'flex', flexDirection: 'column', gap: 14 },
  }

  const css = (
    <style>{`
      .wc-root button:focus-visible, .wc-root input:focus-visible, .wc-root select:focus-visible { outline: 2px solid ${brand}; outline-offset: 2px; }
      .wc-root button:disabled { opacity: 0.55; cursor: default; }
      @keyframes wc-pulse { 0%,100% { opacity: .35; transform: scale(.92) } 50% { opacity: 1; transform: scale(1) } }
      @keyframes wc-pop { from { opacity: 0; transform: translateY(8px) scale(.98) } to { opacity: 1; transform: none } }
      @keyframes wc-ping { 0% { box-shadow: 0 0 0 0 rgba(232,89,12,.55) } 70%,100% { box-shadow: 0 0 0 9px rgba(232,89,12,0) } }
      .wc-ping { animation: wc-ping 1.6s ease-out infinite }
      @keyframes wc-bounce { 0%,60%,100% { transform: translateY(0); opacity: .45 } 30% { transform: translateY(-4px); opacity: 1 } }
      @media (prefers-reduced-motion: reduce) { .wc-pulse, .wc-anim, .wc-dot, .wc-ping { animation: none !important; } }
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
  if (state === 'blocked') return (
    <div style={S.page} className="wc-root">{css}<div style={S.shell}><div style={S.center}>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: '-0.4px', color: INK }}>This chat cannot be shown here</h1>
      <p style={{ margin: 0, maxWidth: 300 }}>The business has not allowed its chat on this website.</p>
    </div></div></div>
  )
  if (state === 'error') return (
    <div style={S.page} className="wc-root">{css}<div style={S.shell}><div style={S.center}>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: '-0.4px', color: INK }}>We could not open the chat</h1>
      <p style={{ margin: 0, maxWidth: 280 }}>Check your internet connection, then try again.</p>
      <button type="button" style={{ ...S.primary, width: 'auto', padding: '0 32px' }} onClick={() => { writeStore(tokenKey, null); window.location.reload() }}>Try again</button>
    </div></div></div>
  )

  const sheetOpen = ['contact', 'email', 'booking', 'save', 'menu', 'attach', 'call', 'delete'].includes(panel)
  const call = cfg.call || null
  const shown = hiddenIds ? messages.filter((m) => !hiddenIds.has(m.id)) : messages
  const visitorSpoke = shown.some((m) => m.role === 'visitor')
  const stepHint = contactStep === 'name' ? 'Your name' : contactStep === 'phone' ? 'Your WhatsApp number or email' : contactStep === 'consent' ? 'Reply Yes or No' : 'Type your message'
  const lastRepIdx = messages.reduce((a, m, i) => (m.role === 'rep' ? i : a), -1)
  // WEBCHAT-BUBBLE-2: Chioma is the face; once a team member takes over, the header shows them instead (and swaps back when the bot resumes).
  const chioma = cfg.chioma || {}
  const withTeam = !!human
  const teamWho = (lastRepIdx >= 0 && messages[lastRepIdx].by) || ''
  const dotOn = withTeam ? !!chioma.team_available : !!chioma.online
  const humanItem = cfg.human_menu_id ? cfg.menu.find((m) => m.id === cfg.human_menu_id) : null
  const teamLine = chioma.team_available ? 'The team is online now.' : (chioma.reopens ? `The team is back ${chioma.reopens}.` : '')
  const chiomaFace = (size) => (
    <span aria-hidden="true" style={{ position: 'relative', width: size, height: size, flex: 'none', display: 'inline-block' }}>
      <img src="/chioma/chioma-face-64.webp" srcSet="/chioma/chioma-face-64.webp 1x, /chioma/chioma-face-128.webp 2x" alt="" width={size} height={size}
        style={{ width: size, height: size, borderRadius: 999, objectFit: 'cover', display: 'block', background: '#E7EDF2' }} />
    </span>
  )
  const sheetTitle = { contact: 'Where can we reach you?', email: 'Get the reply by email?', booking: 'Send a booking request', save: 'Keep this chat', menu: 'How can I help?', attach: 'Send a file', call: call?.open ? 'Call us' : 'Phone calls are closed right now', delete: 'Delete this message?' }[panel]

  return (
    <div style={S.page} className="wc-root">
      {css}
      <div style={S.shell} ref={shellRef}>
        <header style={S.head}>
          {withTeam
            ? <div style={{ ...S.avatar, position: 'relative' }} aria-hidden="true">{(teamWho || cfg.business_name || '?').trim().charAt(0).toUpperCase()}</div>
            : <span style={{ position: 'relative', flex: 'none', width: 44, height: 44 }}>{chiomaFace(44)}</span>}
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700, letterSpacing: '-0.2px', lineHeight: 1.2, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{withTeam ? (teamWho || `${cfg.business_name} team`) : 'Chioma'}</span>
              {dotOn && <span role="img" aria-label="Online" title="Online" style={{ width: 9, height: 9, flex: 'none', borderRadius: 999, background: '#22C55E' }} />}
            </h1>
            <div style={{ fontSize: 12.5, color: MUTED, lineHeight: 1.25, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {withTeam ? (teamWho ? `${cfg.business_name} team` : 'Replying to you here') : `Virtual assistant for ${cfg.business_name}`}
            </div>
          </div>
          {call && (
            <button type="button" aria-label="Call us" aria-haspopup="dialog" onClick={openCall}
              style={{ width: 48, height: 48, flex: 'none', margin: '-6px 0', border: 0, borderRadius: 999, background: panel === 'call' ? brand : 'transparent', color: panel === 'call' ? '#fff' : INK, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="phone" size={22} />
            </button>
          )}
          {cfg.menu.length > 0 && (
            <button type="button" aria-label="Menu" aria-haspopup="dialog" onClick={openMenu}
              style={{ position: 'relative', height: 44, flex: 'none', margin: '-4px 0', padding: '0 14px 0 12px', border: `1.5px solid ${panel === 'menu' ? brand : tintLine}`, borderRadius: 999, background: panel === 'menu' ? brand : tint, color: panel === 'menu' ? '#fff' : brandDark, fontSize: 15, fontWeight: 700, fontFamily: 'inherit', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="menu" size={20} />Menu
              {!menuSeen && <span aria-hidden="true" className="wc-ping" style={{ position: 'absolute', top: -2, right: -2, width: 12, height: 12, borderRadius: 999, background: '#E8590C', border: '2px solid #fff' }} />}
            </button>
          )}
          {EMBED && (
            <button type="button" aria-label="Close chat" onClick={closeEmbed} style={{ ...S.iconBtn, margin: '-4px -6px -4px 0' }}><Icon name="close" size={22} /></button>
          )}
        </header>

        <main style={S.list} ref={listRef} role="log" aria-live="polite" aria-label="Chat messages">
          {hiddenIds && (
            <div role="note" style={{ margin: '4px 0 10px', padding: '12px 14px', borderRadius: 14, background: '#fff', border: `1px solid ${LINE}`, fontSize: 15, color: INK, textAlign: 'center' }}>
              <div style={{ fontWeight: 600 }}>Welcome back{meName ? `, ${meName}` : ''}.</div>
              <div style={{ color: MUTED, marginTop: 2 }}>How can I help today?</div>
              <button type="button" onClick={() => { setHiddenIds(null); initialCount.current = messages.length }}
                style={{ marginTop: 8, minHeight: 44, border: 0, background: 'transparent', color: brand, fontWeight: 600, fontSize: 14, cursor: 'pointer', textDecoration: 'underline' }}>Show earlier messages</button>
            </div>
          )}
          {shown.map((m, i) => {
            const lifted = msgMenu?.id === m.id
            const tappable = !m.tmp && !m.deleted
            return (
            <div key={m.id} className={i >= initialCount.current ? 'wc-anim' : undefined} style={{ ...S.row(m.role), ...(i >= initialCount.current ? { animation: 'wc-pop 0.18s ease-out' } : {}), ...(m.tmp ? { opacity: 0.85 } : {}), ...(lifted ? { position: 'relative', zIndex: 5 } : {}) }}>
              {m.role === 'rep' && (i === 0 || shown[i - 1].role !== 'rep') && <span style={S.who}>{m.by ? `${m.by} · ${cfg.business_name} team` : `${cfg.business_name} team`}</span>}
              {m.role === 'bot' && (i === 0 || shown[i - 1].role !== 'bot') && <span style={{ ...S.who, display: 'flex', alignItems: 'center', gap: 6 }}>{chiomaFace(22)}Chioma</span>}
              {m.deleted ? (
                <div style={{ border: `1px dashed ${LINE}`, background: '#fff', color: MUTED, padding: '10px 14px', borderRadius: 18, fontSize: 14, fontStyle: 'italic' }}>
                  {m.role === 'visitor' ? 'You deleted this message' : 'This message was deleted'}
                </div>
              ) : (
              <div role={tappable ? 'button' : undefined} tabIndex={tappable ? 0 : undefined} aria-label={tappable ? 'Message options' : undefined}
                onClick={tappable ? (e) => openMsgMenu(e, m) : undefined}
                onKeyDown={tappable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMsgMenu(e, m) } } : undefined}
                style={{ ...(m.attachment ? { ...S.bubble(m.role), padding: m.attachment.kind === 'image' ? 4 : '10px 12px' } : S.bubble(m.role)), cursor: tappable ? 'pointer' : 'default', ...(lifted ? { outline: `3px solid ${brand}55` } : {}) }}>
                {m.reply && (
                  <div style={{ background: m.role === 'visitor' ? 'rgba(255,255,255,0.18)' : '#F0F4F5', borderLeft: `4px solid ${m.role === 'visitor' ? '#fff' : brand}`, borderRadius: 8, padding: '6px 10px', margin: m.attachment?.kind === 'image' ? '6px 6px 6px' : '0 0 6px', textAlign: 'left' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: m.role === 'visitor' ? '#fff' : brandDark }}>{whoLabel(m.reply.role)}</div>
                    <div style={{ fontSize: 13, opacity: 0.9, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', maxWidth: 220 }}>{m.reply.text}</div>
                  </div>
                )}
                {m.attachment
                  ? <AttachmentBubble a={m.attachment} mine={m.role === 'visitor'} brand={brand} />
                  : <Linkified text={m.text} onTap={m.role === 'visitor' ? undefined : () => tapChat(chatKey, token.current)} />}
              </div>
              )}
              {m.role === 'bot' && cfg.menu.length > 0 && i === shown.length - 1 && ((cfg.fallback && m.text === cfg.fallback) || (cfg.scripted_tail && m.text.endsWith(cfg.scripted_tail))) && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 2 }}>
                  <button type="button" style={{ ...S.chip, minHeight: 40, display: 'flex', alignItems: 'center', gap: 8 }} onClick={openMenu}>
                    <Icon name="menu" size={18} />Open menu
                  </button>
                  {humanItem && !human && (
                    <button type="button" style={{ ...S.chip, minHeight: 40 }} disabled={busy} onClick={() => sendMenu(humanItem.id)}>Talk to the team</button>
                  )}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: MUTED, margin: '0 4px' }}>
                <span>{m.edited && !m.deleted ? 'Edited · ' : ''}{fmtClock(m.at)}</span>
                {m.role === 'visitor' && !m.deleted && <Ticks state={m.tmp ? 'sent' : (i < lastRepIdx ? 'read' : 'delivered')} color={brandDark} />}
              </div>
            </div>
            )
          })}

          {(pending > 0 || repTyping) && (
            <div role="status" aria-label={withTeam || repTyping ? 'The team is typing' : 'Chioma is typing'} className="wc-anim" style={{ ...S.row('bot'), animation: 'wc-pop 0.18s ease-out' }}>
              <div style={{ ...S.bubble('bot'), display: 'flex', alignItems: 'center', gap: 5, padding: '14px 16px' }}>
                {[0, 1, 2].map((d) => <span key={d} className="wc-dot" aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 999, background: MUTED, animation: `wc-bounce 1.2s ease-in-out ${d * 0.16}s infinite` }} />)}
              </div>
            </div>
          )}

          {cards.length > 0 && !panel && cards.map((p) => <ProductCard key={p.id} p={p} S={S} brand={brand} busy={busy} picked={picked} setPicked={setPicked} onAdd={addToCart} />)}

          {contactStep === 'consent' && !panel && (
            <div style={S.chips}>
              <button type="button" style={S.chip} disabled={busy} onClick={() => sendOptimistic('Yes', { kind: 'text', text: 'Yes' })}>Yes, that is okay</button>
              <button type="button" style={S.chip} disabled={busy} onClick={() => sendOptimistic('No', { kind: 'text', text: 'No' })}>No thanks</button>
            </div>
          )}

          {cfg.menu.length > 0 && !visitorSpoke && !panel && !contactStep && (
            <div style={S.chips}>
              {cfg.menu.map((m) => <button key={m.id} type="button" style={S.chip} disabled={busy} onClick={() => sendMenu(m.id)}>{m.label}</button>)}
            </div>
          )}

          {human && (
            <p style={{ margin: '4px 0', textAlign: 'center', fontSize: 13, color: MUTED }}>
              {chioma.team_available || !chioma.reopens
                ? `You are with the ${cfg.business_name} team now. A team member will reply here.`
                : `The ${cfg.business_name} team is away right now and is back ${chioma.reopens}. Your message is saved and they will reply here.`}
            </p>
          )}
        </main>

        {msgMenu && (() => {
          const m = messages.find((x) => x.id === msgMenu.id)
          if (!m) return null
          return (
            <>
              <div style={{ ...S.scrim, background: 'rgba(20,34,43,0.35)' }} onClick={closeMsgMenu} aria-hidden="true" />
              <div role="menu" aria-label="Message options" style={{ position: 'absolute', zIndex: 6, top: msgMenu.top, ...(msgMenu.mine ? { right: msgMenu.side } : { left: msgMenu.side }), width: 220, background: '#fff', borderRadius: 16, overflow: 'hidden', boxShadow: '0 8px 28px rgba(20,34,43,0.22)' }}>
                {msgActions(m).map(([k, label], n) => (
                  <button key={k} type="button" role="menuitem" onClick={() => runMsgAction(k)}
                    style={{ minHeight: 48, width: '100%', padding: '0 16px', border: 0, borderTop: n ? `1px solid ${LINE}` : 'none', background: '#fff', color: k === 'delete' ? '#B3261E' : INK, fontSize: 16, fontWeight: 500, fontFamily: 'inherit', textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 14 }}>
                    <Icon name={k === 'delete' ? 'trash' : k} size={20} />{label}
                  </button>
                ))}
              </div>
            </>
          )
        })()}

        {error && !sheetOpen && !panel && <div style={S.err} role="alert">{error}</div>}

        <div style={S.dock}>
          {cfg.shop_enabled && (
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" style={S.action} disabled={busy} onClick={openShop}><Icon name="bag" />Shop</button>
              <button type="button" style={{ ...S.action, flex: 1.6, background: brand, borderColor: brand, color: '#fff' }} disabled={busy}
                onClick={() => setPanel('cart')}><Icon name="cart" />Cart ({cart.count}){cart.count > 0 ? ` · ${naira(cart.total)}` : ''}</button>
            </div>
          )}
          {rec ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button type="button" aria-label="Cancel and delete recording" onClick={cancelRec}
                style={{ ...S.iconBtn, width: 48, height: 48, borderRadius: 999, background: '#FBE9E7', color: '#B3261E' }}><Icon name="trash" size={22} /></button>
              <div role="status" style={{ flex: 1, height: 48, boxSizing: 'border-box', border: `1px solid ${LINE}`, borderRadius: 999, background: BG, padding: '0 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
                <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 999, background: '#B3261E' }} />
                <span style={{ fontSize: 15, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{fmtTime(rec.seconds)}</span>
                <span style={{ fontSize: 14, color: MUTED }}>Recording</span>
              </div>
              <button type="button" aria-label="Send voice note" style={S.send} onClick={stopRec}><Icon name="send" size={22} /></button>
            </div>
          ) : (
            <>
            {(replyTo || editing) && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#F0F4F5', borderLeft: `4px solid ${brand}`, borderRadius: 10, padding: '8px 8px 8px 12px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: brandDark }}>{editing ? 'Edit message' : `Replying to ${whoLabel(replyTo.role)}`}</div>
                  <div style={{ fontSize: 14, color: MUTED, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{editing ? (messages.find((x) => x.id === editing.id)?.text || '') : replyTo.text}</div>
                </div>
                <button type="button" aria-label={editing ? 'Cancel editing' : 'Cancel reply'} onClick={cancelCompose} style={{ ...S.iconBtn, width: 40, height: 40 }}><Icon name="close" size={20} /></button>
              </div>
            )}
            <form onSubmit={sendText} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button type="button" aria-label="Attach a file" onClick={onAttach} disabled={!!editing} style={{ ...S.iconBtn, color: MUTED, opacity: editing ? 0.4 : 1 }}><Icon name="clip" size={22} /></button>
              <label htmlFor="wc-text" style={{ position: 'absolute', left: '-9999px' }}>Type your message</label>
              <input id="wc-text" ref={inputRef} style={S.input} value={text} maxLength={1000} placeholder={stepHint} autoComplete="off" inputMode={contactStep === 'phone' ? 'tel' : undefined}
                onChange={(e) => {
                  setText(e.target.value)
                  if (e.target.value.trim() && token.current && Date.now() - typingPing.current > 3000) { typingPing.current = Date.now(); pingTyping(chatKey, token.current) }   // the team's inbox shows "typing"
                }} />
              {!text.trim() && !editing && recorderSupported()
                ? <button type="button" aria-label="Record a voice note" style={{ ...S.send, marginLeft: 4 }} onClick={startRec}><Icon name="mic" size={22} /></button>
                : <button type="submit" aria-label={editing ? 'Save the change' : 'Send'} style={{ ...S.send, marginLeft: 4 }} disabled={busy || !text.trim()}><Icon name={editing ? 'check' : 'send'} size={22} /></button>}
            </form>
            </>
          )}
          <input ref={photoRef} type="file" accept={IMG_ACCEPT} hidden onChange={pickFile('image')} />
          <input ref={cameraRef} type="file" accept={IMG_ACCEPT} capture="environment" hidden onChange={pickFile('image')} />
          <input ref={docRef} type="file" accept={DOC_ACCEPT} hidden onChange={pickFile('document')} />
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
                    {panel === 'menu' && 'Pick one and I will answer here.'}
                    {panel === 'delete' && 'It is removed for everyone, including our team. They will see "This message was deleted".'}
                    {panel === 'attach' && 'Photos up to 10 MB. Documents up to 15 MB. Voice notes up to 2 minutes.'}
                    {panel === 'call' && call && (call.open
                      ? `Open now${call.closes ? `, until ${call.closes}` : ''}`
                      : `Phone calls reopen ${call.reopens || 'when we are next open'}`)}
                  </p>
                </div>
                <button type="button" aria-label="Close" style={{ ...S.iconBtn, margin: '-6px -10px 0 0' }} onClick={closePanel}><Icon name="close" size={22} /></button>
              </div>

              {error && <div style={{ ...S.err, borderRadius: 8 }} role="alert">{error}</div>}

              {panel === 'delete' && (
                <>
                  <button type="button" disabled={busy} onClick={confirmDelete} style={{ ...S.primary, background: '#B3261E', borderColor: '#B3261E', minHeight: 52 }}>Delete for everyone</button>
                  <button type="button" style={S.ghost} onClick={closePanel}>Cancel</button>
                </>
              )}

              {panel === 'call' && call && (call.open ? (
                <>
                  <div style={{ border: `1px solid ${LINE}`, borderRadius: 16, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: 13, color: MUTED }}>Our number</span>
                    <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.3px', fontVariantNumeric: 'tabular-nums' }}>{call.display}</span>
                  </div>
                  <a href={`tel:+${call.number}`} style={{ ...S.primary, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, textDecoration: 'none', minHeight: 52 }}>
                    <Icon name="phone" size={20} />Call now
                  </a>
                  <p style={{ margin: 0, fontSize: 13, color: MUTED, textAlign: 'center', lineHeight: 1.45 }}>
                    Phone calls: {call.hours}. Chat support and sales are open 24/7.
                  </p>
                </>
              ) : (
                <>
                  <p style={{ margin: 0, fontSize: 15, lineHeight: 1.5 }}>
                    Only phone calls are closed. Our support and sales team is still here in this chat, 24/7. Pick what suits you:
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {[['Leave a voice note', 'Tell us what you need. We listen first thing in the morning.', 'mic', '#E6F4F5', brand, voiceFromCall],
                      ['Keep chatting with us', 'Ask about prices, delivery or orders. We reply any time.', 'chat', '#E7ECFB', '#2F4AA8', () => setPanel(null)],
                      ['Ask us to call you back', `A team member calls you ${call.reopens || 'when we open'}.`, 'phone', '#FFF1D9', '#8A5A00', callBack]].map(([t, sub, icon, bg, fg, fn]) => (
                      <button key={t} type="button" disabled={busy} onClick={fn}
                        style={{ minHeight: 64, width: '100%', boxSizing: 'border-box', padding: '10px 14px', border: `1px solid ${LINE}`, borderRadius: 16, background: '#fff', color: INK, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 14 }}>
                        <span aria-hidden="true" style={{ width: 44, height: 44, flex: 'none', borderRadius: 999, background: bg, color: fg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon name={icon} size={22} /></span>
                        <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          <span style={{ fontSize: 16, fontWeight: 600 }}>{t}</span>
                          <span style={{ fontSize: 13, color: MUTED, lineHeight: 1.35 }}>{sub}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                  {callPhone !== null && (
                    <form onSubmit={(e) => { e.preventDefault(); callBack() }} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      <label><span style={S.lab}>Phone number to call</span>
                        <input style={S.field} value={callPhone} maxLength={30} inputMode="tel" autoComplete="tel" autoFocus
                          onChange={(e) => setCallPhone(e.target.value)} /></label>
                      <button type="submit" style={S.primary} disabled={busy || !callPhone.trim()}>Request call back</button>
                    </form>
                  )}
                </>
              ))}

              {panel === 'attach' && (
                <div style={{ display: 'flex', gap: 4 }}>
                  {[['Photos', 'image', '#E6F4F5', brand, photoRef], ['Camera', 'camera', '#FFF1D9', '#8A5A00', cameraRef], ['Document', 'file', '#E7ECFB', '#2F4AA8', docRef]].map(([label, icon, bg, fg, ref]) => (
                    <button key={label} type="button" onClick={() => ref.current?.click()}
                      style={{ flex: 1, minHeight: 96, border: 0, background: 'transparent', color: INK, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                      <span aria-hidden="true" style={{ width: 60, height: 60, borderRadius: 999, background: bg, color: fg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon name={icon} size={26} /></span>
                      {label}
                    </button>
                  ))}
                </div>
              )}

              {panel === 'menu' && cfg.menu.some((m) => m.id !== humanItem?.id) && (
                <div role="list" style={{ display: 'flex', flexDirection: 'column', border: `1px solid ${LINE}`, borderRadius: 16, overflow: 'hidden' }}>
                  {cfg.menu.filter((m) => m.id !== humanItem?.id).map((m, n) => (
                    <button key={m.id} type="button" role="listitem" disabled={busy} onClick={() => sendMenu(m.id)}
                      style={{ minHeight: 52, padding: '0 16px', border: 0, borderTop: n ? `1px solid ${LINE}` : 'none', background: '#fff', color: INK, fontSize: 16, fontWeight: 500, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                      <span>{m.label}</span><span style={{ color: MUTED }}><Icon name="chev" size={18} /></span>
                    </button>
                  ))}
                </div>
              )}

              {panel === 'menu' && humanItem && (
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: MUTED, margin: '0 4px 4px' }}>Need a person?</div>
                  {teamLine && <div style={{ fontSize: 13, color: MUTED, margin: '0 4px 8px' }}>{teamLine}</div>}
                  <button type="button" disabled={busy} onClick={() => sendMenu(humanItem.id)}
                    style={{ width: '100%', minHeight: 52, padding: '0 16px', border: `1px solid ${LINE}`, borderRadius: 16, background: '#fff', color: INK, fontSize: 16, fontWeight: 500, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span>{humanItem.label}</span><span style={{ color: MUTED }}><Icon name="chev" size={18} /></span>
                  </button>
                </div>
              )}

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

            </section>
          </>
        )}
      </div>
    </div>
  )
}
