/**
 * frontend/src/modules/webchat/WebChatChats.jsx — WEBCHAT-CHATS-1
 * The Chats tab: every web chat in the period, newest first, including visitors who never left a contact ("Visitor 4F2A").
 * Read-only. Click a chat to read it (side panel). Chats with a contact also live in Conversations; this is the whole picture.
 */
import { useCallback, useEffect, useState } from 'react'
import { getWebchatChats, getWebchatChat, getWebchatSettings } from '../../services/webchat.service'
import { ds } from '../../utils/ds'
import { FILTERS, chatTitle, sourceLabel, chatFacts, ago } from './chatsView'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, boxShadow: ds.cardShadow }
const input = { boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const TONES = { good: ['#E6F6EC', '#13663A'], info: ['#E8F1FB', '#1D4F91'], warn: ['#FFF6E0', '#8A5A00'], muted: ['#F1F3F5', '#5B6570'] }
const PAGE = 50
const naira = (n) => (n == null || n === '' ? '' : `₦${Number(n).toLocaleString('en-NG', { maximumFractionDigits: 2 })}`)

function Tag({ tone, children }) {
  const [bg, fg] = TONES[tone] || TONES.muted
  return <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: bg, color: fg, whiteSpace: 'nowrap' }}>{children}</span>
}

function Transcript({ id, ads, onClose }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    getWebchatChat(id).then((x) => live && setD(x)).catch(() => live && setErr('This chat did not load.'))
    return () => { live = false }
  }, [id])
  const c = d?.chat
  return (
    <aside aria-label="Chat transcript" style={{ ...card, flex: '1 1 340px', minWidth: 300, padding: 16, alignSelf: 'flex-start', maxHeight: '75vh', overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: ds.dark, fontFamily: ds.fontDm }}>{c ? chatTitle(c) : 'Loading…'}</div>
          {c && <div style={{ fontSize: 12, color: ds.gray }}>{sourceLabel(c.source, ads)} · started {ago(c.started_at)}</div>}
        </div>
        <button type="button" aria-label="Close chat" onClick={onClose} style={{ border: 0, background: 'none', fontSize: 20, cursor: 'pointer', color: ds.gray, minWidth: 40, minHeight: 40 }}>×</button>
      </div>
      {err && <p style={{ color: '#B42318', fontSize: 13 }}>{err}</p>}
      {c && (
        <>
          {(c.viewing || d.cart.length > 0) && (
            <div style={{ margin: '10px 0', padding: 10, background: '#F5F7F9', borderRadius: ds.radius.sm, fontSize: 13, color: ds.dark }}>
              {c.viewing && <div>Looking at: <strong>{c.viewing}</strong></div>}
              {d.cart.length > 0 && <div>Cart: {d.cart.map((i) => `${i.qty} × ${i.title}${i.price != null ? ` (${naira(i.price)})` : ''}`).join(', ')}</div>}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '10px 0' }}>
            {d.messages.length === 0 && <p style={{ fontSize: 13, color: ds.gray }}>No messages in this chat.</p>}
            {d.messages.map((m, i) => {
              const mine = m.role === 'visitor'
              return (
                <div key={m.id || i} style={{ alignSelf: mine ? 'flex-start' : 'flex-end', maxWidth: '85%', padding: '8px 10px', borderRadius: 12, fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  background: mine ? '#F1F3F5' : m.role === 'rep' ? '#E8F1FB' : '#E3F5F2', color: ds.dark }}>
                  <div style={{ fontSize: 10, color: ds.gray, marginBottom: 2 }}>{mine ? 'Visitor' : m.role === 'rep' ? 'Team' : 'Chioma'}</div>
                  {m.text}
                </div>
              )
            })}
          </div>
          {c.has_contact
            ? <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('opsra:goto', { detail: 'conversations' }))}
                style={{ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: `1px solid ${ds.teal}`, background: '#fff', color: ds.teal, fontWeight: 600, cursor: 'pointer' }}>
                Reply in Conversations
              </button>
            : <p style={{ fontSize: 12, color: ds.gray, margin: 0 }}>This visitor did not leave a contact, so there is no one to reply to.</p>}
        </>
      )}
    </aside>
  )
}

export default function WebChatChats() {
  const [days, setDays] = useState(30)
  const [flt, setFlt] = useState('all')
  const [source, setSource] = useState('')
  const [data, setData] = useState(null)
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(null)
  const [ads, setAds] = useState([])

  useEffect(() => {
    let live = true
    getWebchatSettings().then((d) => live && setAds(Array.isArray(d?.config?.campaigns) ? d.config.campaigns : [])).catch(() => {})
    return () => { live = false }
  }, [])

  const load = useCallback(async (offset) => {
    setBusy(true); setErr('')
    try {
      const d = await getWebchatChats({ days, filter: flt, source: source || undefined, limit: PAGE, offset })
      setData(d)
      setRows((prev) => (offset ? [...prev, ...d.chats] : d.chats))
    } catch (e) {
      setErr(e?.response?.status === 403 && typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'The chats did not load. Try again.')
    } finally { setBusy(false) }
  }, [days, flt, source])

  useEffect(() => { load(0) }, [load])

  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div style={{ flex: '2 1 480px', minWidth: 300 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={flt === k} onClick={() => setFlt(k)}
              style={{ minHeight: 36, padding: '6px 12px', borderRadius: 999, border: `1px solid ${flt === k ? ds.teal : ds.border}`, background: flt === k ? ds.teal : '#fff', color: flt === k ? '#fff' : ds.dark, fontSize: 13, cursor: 'pointer' }}>
              {label}{data ? ` · ${data.counts[k] ?? 0}` : ''}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <select aria-label="Source" style={input} value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            {(data?.sources || []).map((s) => <option key={s} value={s}>{sourceLabel(s, ads)}</option>)}
          </select>
          <select aria-label="Period" style={input} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
          </select>
        </div>
        {err && <p role="alert" style={{ color: '#B42318', fontSize: 13 }}>{err}</p>}
        <div style={card}>
          {!data && busy && <p style={{ padding: 16, margin: 0, fontSize: 13, color: ds.gray }}>Loading chats…</p>}
          {data && rows.length === 0 && (
            <p style={{ padding: 16, margin: 0, fontSize: 14, color: ds.gray }}>
              {flt === 'all' ? 'No chats in this period yet. When someone opens your chat link, they appear here.' : 'No chats match this filter.'}
            </p>
          )}
          {rows.map((c) => (
            <button key={c.id} type="button" onClick={() => setOpen(c.id)} aria-label={`Open chat with ${chatTitle(c)}`}
              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '12px 16px', border: 0, borderBottom: `1px solid ${ds.border}`, background: open === c.id ? '#F0F8F7' : '#fff', cursor: 'pointer', minHeight: 56 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: ds.dark }}>{chatTitle(c)}</span>
                <span style={{ fontSize: 12, color: ds.gray }}>{ago(c.last_at)}</span>
              </div>
              <div style={{ fontSize: 12, color: ds.gray, margin: '2px 0 6px' }}>{sourceLabel(c.source, ads)}{c.viewing ? ` · looked at ${c.viewing}` : ''}</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{chatFacts(c).map((f) => <Tag key={f.key} tone={f.tone}>{f.text}</Tag>)}</div>
            </button>
          ))}
          {data && rows.length < data.total && (
            <div style={{ padding: 12, textAlign: 'center' }}>
              <button type="button" disabled={busy} onClick={() => load(rows.length)}
                style={{ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: `1px solid ${ds.teal}`, background: '#fff', color: ds.teal, fontWeight: 600, cursor: 'pointer' }}>
                {busy ? 'Loading…' : `Show more (${data.total - rows.length} left)`}
              </button>
            </div>
          )}
        </div>
        {data?.capped && <p style={{ fontSize: 12, color: ds.gray }}>Showing the newest chats only. Choose a shorter period to see the rest.</p>}
      </div>
      {open && <Transcript key={open} id={open} ads={ads} onClose={() => setOpen(null)} />}
    </div>
  )
}
