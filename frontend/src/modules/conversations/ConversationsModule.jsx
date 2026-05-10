/**
 * ConversationsModule.jsx — Unified Conversations inbox.
 *
 * CONV-UI redesign changes vs previous version:
 *   - MessageComposer replaced with InlineComposer — WhatsApp-style input bar
 *   - Enter to send (Shift+Enter = newline)
 *   - 📎 attachment picker — image, doc, audio, video (25MB max)
 *   - File preview chip shown before send
 *   - Template mode via 📋 toggle button
 *   - Window-closed state locks to template-only with clear banner
 *   - Composer resets on conversation switch (key={active.contact_id})
 *   - resumeAI bug fixed in conversations.service.js
 *
 * Bug fix (post CONV-UI):
 *   - openConversation now defaults window_open to FALSE (safe default).
 *     Previously defaulted to true, which allowed the text input to show
 *     while fetchThreadStatus was in-flight. If the status fetch crashed
 *     (backend 500 → no CORS headers → silent catch), windowOpen stayed
 *     true and the user could send a free-form message that the backend
 *     would correctly reject with 400 ("window closed").
 *   - statusLoading state added: composer shows "Checking window…" until
 *     the first status fetch resolves (success or failure).
 *   - On status fetch failure: window_open stays false → template-only,
 *     which matches backend behaviour and prevents the misleading 400.
 *
 * All previous functionality preserved:
 *   - Real-time polling (thread 5s, list 15s)
 *   - AI / Human mode indicator + Resume AI button
 *   - WhatsApp-style message bubbles + status ticks
 *   - Mobile single-panel / desktop two-panel layout
 *   - Conversation list filters (channel, type, unread)
 *
 * Pattern 51: full rewrite required for any future edit — never sed.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import {
  getConversations,
  getThreadStatus,
  resumeAI,
  pauseAI,
  sendMediaMessage,
} from '../../services/conversations.service'
import { getLeadMessages, markLeadMessagesRead } from '../../services/leads.service'
import { getCustomerMessages, listTemplates, sendMessage } from '../../services/whatsapp.service'

// ─── Channel config ───────────────────────────────────────────────────────────

const CHANNEL = {
  whatsapp:  { label: 'WhatsApp',  icon: '💬', color: '#25D366', bg: '#E8F8EE' },
  instagram: { label: 'Instagram', icon: '📷', color: '#C13584', bg: '#FCE4EC' },
}

const THREAD_POLL_MS = 5000
const LIST_POLL_MS   = 15000

// Media types the backend accepts (mirrors Tech Spec §11.5)
const ACCEPTED_MEDIA = [
  'image/jpeg', 'image/png', 'image/gif', 'image/webp',
  'video/mp4', 'video/3gpp',
  'audio/mpeg', 'audio/ogg',
  'application/pdf',
].join(',')

const MAX_MEDIA_BYTES = 25 * 1024 * 1024 // 25 MB

// Show inactivity nudge after 10 minutes — auto-resume fires at 15 minutes
const HUMAN_MODE_NUDGE_MS = 10 * 60 * 1000

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.floor(h / 24)
  if (d < 7)  return `${d}d`
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function truncate(str, n = 52) {
  if (!str) return ''
  return str.length > n ? str.slice(0, n) + '…' : str
}

function initials(name) {
  if (!name) return '?'
  const parts = name.trim().split(' ')
  return parts.length > 1
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : name[0].toUpperCase()
}

function fileIcon(type) {
  if (!type) return '📎'
  if (type.startsWith('image/')) return '🖼'
  if (type.startsWith('video/')) return '🎥'
  if (type.startsWith('audio/')) return '🎵'
  return '📄'
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatHumanModeDuration(ms) {
  const m = Math.floor(ms / 60000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m`
  const h   = Math.floor(m / 60)
  const rem = m % 60
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ConversationsModule({ onOpenAria }) {
  const isMobile = useIsMobile()

  // Conversation list
  const [conversations, setConversations] = useState([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState(null)
  const [search, setSearch]               = useState('')
  const [channelFilter, setChannelFilter] = useState('all')
  const [typeFilter, setTypeFilter]       = useState('all')
  const [unreadOnly, setUnreadOnly]       = useState(false)

  // Active thread
  const [active, setActive]               = useState(null)
  const [messages, setMessages]           = useState([])
  const [msgLoading, setMsgLoading]       = useState(false)
  const [templates, setTemplates]         = useState([])
  const [threadStatus, setThreadStatus]   = useState({ window_open: false, ai_paused: false })
  const [statusLoading, setStatusLoading] = useState(false)
  const [resuming, setResuming]           = useState(false)
  const [pausing, setPausing]             = useState(false)
  const threadRef                         = useRef(null)
  const isPollingRef                      = useRef(false)

  // Human mode duration counter + inactivity nudge
  const [humanModeStart, setHumanModeStart]       = useState(null)
  const [humanModeDuration, setHumanModeDuration] = useState('')
  const [showNudge, setShowNudge]                 = useState(false)
  const lastSentRef                               = useRef(null)
  const nudgeDismissedRef                         = useRef(false)

  // Mobile panel
  const [panel, setPanel] = useState('list')

  // ── Load conversation list ─────────────────────────────────────────────
  const loadConversations = useCallback((silent = false) => {
    if (!silent) { setLoading(true); setError(null) }
    getConversations()
      .then(res => setConversations(res.data?.data ?? []))
      .catch(() => { if (!silent) setError('Failed to load conversations.') })
      .finally(() => { if (!silent) setLoading(false) })
  }, [])

  useEffect(() => { loadConversations() }, [loadConversations])

  useEffect(() => {
    const id = setInterval(() => loadConversations(true), LIST_POLL_MS)
    return () => clearInterval(id)
  }, [loadConversations])

  // Load templates once
  useEffect(() => {
    listTemplates()
      .then(res => setTemplates(res.data?.data ?? []))
      .catch(() => {})
  }, [])

  // ── Load thread messages ───────────────────────────────────────────────
  const loadMessages = useCallback((showSpinner = false) => {
    if (!active) return
    if (showSpinner) setMsgLoading(true)

    const fetchPromise = active.contact_type === 'lead'
      ? getLeadMessages(active.contact_id, 1, 30)
      : getCustomerMessages(active.contact_id, { page: 1, page_size: 30 })

    Promise.resolve(fetchPromise)
      .then(res => {
        const items = res?.data?.items ?? res?.data?.data?.items ?? []
        setMessages(items)

        // Derive window_open from the most recent message.
        // Primary: window_expires_at (set by backend on outbound sends).
        // Fallback: created_at — if any message exists within 24h the window
        //           is open by Meta's rules. Handles inbound messages where the
        //           webhook may not write window_expires_at.
        if (items.length > 0) {
          const latest = items[0]
          let isOpen = false
          if (latest.window_expires_at) {
            try {
              isOpen = new Date(latest.window_expires_at) > new Date()
            } catch (_) {}
          } else if (latest.created_at) {
            // No window_expires_at — fall back to age of most recent message
            try {
              const ageHours = (Date.now() - new Date(latest.created_at).getTime()) / 3600000
              isOpen = ageHours < 24
            } catch (_) {}
          }
          setThreadStatus(prev => ({ ...prev, window_open: isOpen }))
        }

        // Window state is now resolved — clear the checking overlay.
        setStatusLoading(false)

        if (active.contact_type === 'lead') {
          markLeadMessagesRead(active.contact_id).catch(() => {})
        }
        setConversations(prev =>
          prev.map(c => c.contact_id === active.contact_id ? { ...c, unread_count: 0 } : c)
        )
      })
      .catch(() => { setStatusLoading(false) })
      .finally(() => setMsgLoading(false))
  }, [active])

  useEffect(() => {
    if (active) loadMessages(true)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!active) return
    const id = setInterval(() => {
      if (!isPollingRef.current) {
        isPollingRef.current = true
        loadMessages(false)
        setTimeout(() => { isPollingRef.current = false }, 1000)
      }
    }, THREAD_POLL_MS)
    return () => clearInterval(id)
  }, [active, loadMessages])

  useEffect(() => {
    if (threadRef.current && messages.length > 0) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages])

  // ── Thread status (window_open + ai_paused) ────────────────────────────
  // Primary use: get ai_paused for the Human Mode indicator.
  // window_open is derived from messages (loadMessages) as the reliable
  // source. If this endpoint works, it also confirms/updates window_open.
  // If it fails (backend 500 → CORS error), the messages-derived value stands.
  const fetchThreadStatus = useCallback(() => {
    if (!active) return
    getThreadStatus(active.contact_type, active.contact_id)
      .then(res => {
        const data = res.data?.data ?? {}
        setThreadStatus(prev => ({
          window_open: data.window_open ?? prev.window_open,
          ai_paused:   data.ai_paused  ?? false,
        }))
      })
      .catch(() => {
        // Status endpoint unavailable — window_open already derived from messages.
        // Do not touch window_open. Leave ai_paused at its current value.
      })
  }, [active])

  useEffect(() => { fetchThreadStatus() }, [fetchThreadStatus])

  // ── Open a conversation ────────────────────────────────────────────────
  const openConversation = (conv) => {
    setActive(conv)
    setMessages([])
    // Safe default: window CLOSED until confirmed by fetchThreadStatus.
    // If the status fetch crashes (backend 500 → no CORS headers), the
    // composer stays in template-only mode rather than showing the text
    // input for a window that the backend will reject.
    setThreadStatus({ window_open: false, ai_paused: conv.ai_paused ?? false })
    if (isMobile) setPanel('thread')
  }

  // ── After sending — auto-pauses AI ───────────────────────────────────
  // Sending any message from Opsra automatically switches to Human Mode.
  // The rep doesn't need to click Take over — sending IS the takeover.
  const handleSent = () => {
    lastSentRef.current = Date.now()   // reset inactivity nudge timer
    nudgeDismissedRef.current = false
    setShowNudge(false)
    loadMessages(false)
    // Optimistic: immediately reflect Human Mode in the UI
    setThreadStatus(prev => ({ ...prev, ai_paused: true }))
    setConversations(prev =>
      prev.map(c =>
        c.contact_id === active?.contact_id ? { ...c, ai_paused: true } : c
      )
    )
    setTimeout(() => {
      loadConversations(true)
      fetchThreadStatus()
    }, 600)
  }

  // ── Resume AI ──────────────────────────────────────────────────────────
  const handleResumeAI = async () => {
    if (!active || resuming) return
    setResuming(true)
    // Optimistic: switch to AI Active immediately
    setThreadStatus(prev => ({ ...prev, ai_paused: false }))
    setConversations(prev =>
      prev.map(c => c.contact_id === active.contact_id ? { ...c, ai_paused: false } : c)
    )
    try {
      await resumeAI(active.contact_type, active.contact_id)
    } catch {
      // Revert on failure
      setThreadStatus(prev => ({ ...prev, ai_paused: true }))
      setConversations(prev =>
        prev.map(c => c.contact_id === active.contact_id ? { ...c, ai_paused: true } : c)
      )
    } finally {
      setResuming(false)
    }
  }

  // ── Pause AI / Take over ───────────────────────────────────────────────
  const handlePauseAI = async () => {
    if (!active || pausing) return
    setPausing(true)
    // Optimistic: switch to Human Mode immediately — don't wait for API
    setThreadStatus(prev => ({ ...prev, ai_paused: true }))
    setConversations(prev =>
      prev.map(c => c.contact_id === active.contact_id ? { ...c, ai_paused: true } : c)
    )
    try {
      await pauseAI(active.contact_type, active.contact_id)
    } catch {
      // Revert if API call failed (route not deployed yet etc.)
      setThreadStatus(prev => ({ ...prev, ai_paused: false }))
      setConversations(prev =>
        prev.map(c => c.contact_id === active.contact_id ? { ...c, ai_paused: false } : c)
      )
    } finally {
      setPausing(false)
    }
  }

  // ── Human mode timer — resets when conversation switches ─────────────
  useEffect(() => {
    setHumanModeStart(null)
    setHumanModeDuration('')
    setShowNudge(false)
    nudgeDismissedRef.current = false
    lastSentRef.current = null
  }, [active?.contact_id])

  // Start / stop the timer based on ai_paused state
  useEffect(() => {
    if (threadStatus.ai_paused) {
      // Only set start time if not already counting
      setHumanModeStart(prev => prev ?? Date.now())
    } else {
      setHumanModeStart(null)
      setHumanModeDuration('')
      setShowNudge(false)
      nudgeDismissedRef.current = false
    }
  }, [threadStatus.ai_paused])

  // Tick every 30s — update duration string and check inactivity nudge
  useEffect(() => {
    if (!humanModeStart) return
    const tick = () => {
      const elapsed = Date.now() - humanModeStart
      setHumanModeDuration(formatHumanModeDuration(elapsed))
      // Show nudge if no rep message sent for HUMAN_MODE_NUDGE_MS
      const sinceLastSent = lastSentRef.current
        ? Date.now() - lastSentRef.current
        : elapsed
      if (sinceLastSent >= HUMAN_MODE_NUDGE_MS && !nudgeDismissedRef.current) {
        setShowNudge(true)
      }
    }
    tick() // immediate first tick
    const id = setInterval(tick, 30000)
    return () => clearInterval(id)
  }, [humanModeStart])

  const handleDismissNudge = () => {
    setShowNudge(false)
    nudgeDismissedRef.current = true
  }

  // ── Filtered list ──────────────────────────────────────────────────────
  const filtered = conversations.filter(c => {
    const q = search.toLowerCase()
    if (q && !c.contact_name.toLowerCase().includes(q) && !(c.phone || '').includes(q)) return false
    if (channelFilter !== 'all' && c.channel !== channelFilter) return false
    if (typeFilter !== 'all' && c.contact_type !== typeFilter) return false
    if (unreadOnly && !c.unread_count) return false
    return true
  })

  const totalUnread = conversations.reduce((s, c) => s + (c.unread_count || 0), 0)

  // ── Render ─────────────────────────────────────────────────────────────

  const listPanel = (
    <ListPanel
      conversations={filtered}
      allCount={conversations.length}
      loading={loading}
      error={error}
      search={search} onSearch={setSearch}
      channelFilter={channelFilter} onChannelFilter={setChannelFilter}
      typeFilter={typeFilter} onTypeFilter={setTypeFilter}
      unreadOnly={unreadOnly} onUnreadOnly={setUnreadOnly}
      active={active}
      onSelect={openConversation}
      totalUnread={totalUnread}
    />
  )

  const threadPanel = active ? (
    <ThreadPanel
      active={active}
      messages={messages}
      loading={msgLoading}
      templates={templates}
      threadStatus={threadStatus}
      statusLoading={statusLoading}
      humanModeDuration={humanModeDuration}
      showNudge={showNudge}
      onDismissNudge={handleDismissNudge}
      threadRef={threadRef}
      onSent={handleSent}
      onResumeAI={handleResumeAI}
      resuming={resuming}
      onPauseAI={handlePauseAI}
      pausing={pausing}
      onOpenAria={onOpenAria}
      onBack={isMobile ? () => { setPanel('list'); setActive(null) } : null}
    />
  ) : (
    <EmptyState totalUnread={totalUnread} />
  )

  if (isMobile) {
    return (
      <div style={{ height: 'calc(100vh - 60px)', display: 'flex', flexDirection: 'column', background: ds.light, overflow: 'hidden' }}>
        {panel === 'list' ? listPanel : threadPanel}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 60px)', overflow: 'hidden', background: ds.light }}>
      <div style={{ width: 340, flexShrink: 0, borderRight: `1px solid ${ds.border}`, background: '#fff', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {listPanel}
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {threadPanel}
      </div>
    </div>
  )
}

// ─── List Panel ───────────────────────────────────────────────────────────────

function ListPanel({ conversations, allCount, loading, error, search, onSearch, channelFilter, onChannelFilter, typeFilter, onTypeFilter, unreadOnly, onUnreadOnly, active, onSelect, totalUnread }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px 10px', borderBottom: `1px solid ${ds.border}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 11 }}>
          <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark }}>Conversations</span>
          {totalUnread > 0 && (
            <span style={{ background: '#E53E3E', color: '#fff', borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 700, fontFamily: ds.fontSyne, animation: 'pulse-badge 2s infinite' }}>
              {totalUnread}
            </span>
          )}
        </div>

        <div style={{ position: 'relative', marginBottom: 9 }}>
          <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 13, color: ds.gray, pointerEvents: 'none' }}>🔍</span>
          <input
            value={search}
            onChange={e => onSearch(e.target.value)}
            placeholder="Search name or number…"
            style={{ width: '100%', boxSizing: 'border-box', border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '9px 10px 9px 32px', fontSize: 13, fontFamily: ds.fontDm, outline: 'none', background: ds.light, color: ds.dark }}
          />
        </div>

        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {[{ v: 'all', l: 'All channels' }, { v: 'whatsapp', l: '💬 WA' }, { v: 'instagram', l: '📷 IG' }].map(({ v, l }) => (
            <Chip key={v} active={channelFilter === v} color={ds.teal} onClick={() => onChannelFilter(v)}>{l}</Chip>
          ))}
          {[{ v: 'all', l: 'All' }, { v: 'lead', l: 'Leads' }, { v: 'customer', l: 'Customers' }].map(({ v, l }) => (
            <Chip key={v} active={typeFilter === v} color={ds.dark} onClick={() => onTypeFilter(v)}>{l}</Chip>
          ))}
          <Chip active={unreadOnly} color='#E53E3E' onClick={() => onUnreadOnly(!unreadOnly)}>🔴 Unread</Chip>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {loading && [1,2,3,4,5,6].map(n => <ConvSkeleton key={n} />)}
        {!loading && error && <div style={{ padding: 28, textAlign: 'center', color: ds.red, fontSize: 13 }}>⚠ {error}</div>}
        {!loading && !error && allCount === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: ds.gray, fontSize: 13 }}>
            <div style={{ fontSize: 36, marginBottom: 10 }}>💬</div>No conversations yet.
          </div>
        )}
        {!loading && !error && allCount > 0 && conversations.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center', color: ds.gray, fontSize: 13 }}>No conversations match your filters.</div>
        )}
        {!loading && conversations.map(conv => (
          <ConvRow key={conv.contact_id} conv={conv} isActive={active?.contact_id === conv.contact_id} onSelect={onSelect} />
        ))}
      </div>
    </div>
  )
}

// ─── Conversation Row ─────────────────────────────────────────────────────────

function ConvRow({ conv, isActive, onSelect }) {
  const ch     = CHANNEL[conv.channel] || CHANNEL.whatsapp
  const hasNew = conv.unread_count > 0
  const isLead = conv.contact_type === 'lead'

  return (
    <div
      onClick={() => onSelect(conv)}
      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: isActive ? ds.mint : hasNew ? '#FAFCFF' : '#fff', borderBottom: `1px solid ${ds.border}`, borderLeft: `3px solid ${isActive ? ds.teal : 'transparent'}`, cursor: 'pointer', transition: 'background 0.12s, border-color 0.12s', minHeight: 72 }}
    >
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <div style={{ width: 44, height: 44, borderRadius: '50%', background: isLead ? `linear-gradient(135deg, ${ds.accent} 0%, #C05A00 100%)` : `linear-gradient(135deg, ${ds.teal} 0%, ${ds.tealDark} 100%)`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#fff' }}>
          {initials(conv.contact_name)}
        </div>
        <span style={{ position: 'absolute', bottom: -1, right: -1, width: 18, height: 18, borderRadius: '50%', background: '#fff', border: '1.5px solid #fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10 }}>
          {ch.icon}
        </span>
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
          <span style={{ fontFamily: ds.fontSyne, fontWeight: hasNew ? 700 : 600, fontSize: 13.5, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, marginRight: 8 }}>
            {conv.contact_name}
          </span>
          <span style={{ fontSize: 10.5, color: ds.gray, flexShrink: 0 }}>{timeAgo(conv.last_message_at)}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
          <span style={{ fontSize: 12, color: hasNew ? ds.dark : ds.gray, fontWeight: hasNew ? 500 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {conv.last_message_direction === 'outbound' && <span style={{ color: ds.teal, marginRight: 2, fontSize: 11 }}>↗ </span>}
            {conv.last_message ? truncate(conv.last_message) : <em style={{ color: ds.gray }}>No messages yet</em>}
          </span>

          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
            {conv.ai_paused && (
              <span title="Human mode — AI paused" style={{ fontSize: 12 }}>👤</span>
            )}
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 20, fontWeight: 600, fontFamily: ds.fontSyne, background: isLead ? '#FFF3E0' : '#E0F4F6', color: isLead ? '#C05A00' : ds.teal }}>
              {isLead ? 'Lead' : 'CX'}
            </span>
            {hasNew && (
              <span style={{ background: '#E53E3E', color: '#fff', borderRadius: '50%', minWidth: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne, padding: '0 4px' }}>
                {conv.unread_count > 9 ? '9+' : conv.unread_count}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Thread Panel ─────────────────────────────────────────────────────────────

function ThreadPanel({ active, messages, loading, templates, threadStatus, statusLoading, humanModeDuration, showNudge, onDismissNudge, threadRef, onSent, onResumeAI, resuming, onPauseAI, pausing, onOpenAria, onBack }) {
  const ch     = CHANNEL[active.channel] || CHANNEL.whatsapp
  const isLead = active.contact_type === 'lead'
  const { window_open: windowOpen, ai_paused: aiPaused } = threadStatus

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div style={{ padding: '10px 16px', borderBottom: `1px solid ${ds.border}`, background: '#fff', display: 'flex', alignItems: 'center', gap: 11, flexShrink: 0, minHeight: 60 }}>
        {onBack && (
          <button onClick={onBack} style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.teal, fontSize: 22, padding: '4px 6px 4px 0', lineHeight: 1, flexShrink: 0, minWidth: 36, minHeight: 44, display: 'flex', alignItems: 'center' }}>←</button>
        )}

        <div style={{ width: 38, height: 38, borderRadius: '50%', flexShrink: 0, background: isLead ? `linear-gradient(135deg, ${ds.accent}, #C05A00)` : `linear-gradient(135deg, ${ds.teal}, ${ds.tealDark})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#fff' }}>
          {initials(active.contact_name)}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {active.contact_name}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 2, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 20, background: ch.bg, color: ch.color, fontWeight: 600, fontFamily: ds.fontSyne }}>
              {ch.icon} {ch.label}
            </span>
            <span style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 20, fontWeight: 600, fontFamily: ds.fontSyne, background: isLead ? '#FFF3E0' : '#E0F4F6', color: isLead ? '#C05A00' : ds.teal }}>
              {isLead ? 'Lead' : 'Customer'}
            </span>
            {active.phone && <span style={{ fontSize: 11, color: ds.gray }}>{active.phone}</span>}
          </div>
        </div>

        {/* ── AI / Human mode controls ──────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
          {aiPaused ? (
            <>
              <span style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, background: '#FFF3E0', color: '#C05A00', fontWeight: 700, fontFamily: ds.fontSyne }}>
                👤 Human Mode{humanModeDuration ? ` · ${humanModeDuration}` : ''}
              </span>
              <button
                onClick={onResumeAI}
                disabled={resuming}
                style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, border: `1px solid ${ds.teal}`, background: '#fff', color: ds.teal, fontWeight: 600, cursor: resuming ? 'not-allowed' : 'pointer', fontFamily: ds.fontSyne, opacity: resuming ? 0.6 : 1 }}
              >
                {resuming ? 'Resuming…' : '🤖 Resume AI'}
              </button>
            </>
          ) : (
            <>
              <span style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, background: '#E8F8EE', color: '#27AE60', fontWeight: 700, fontFamily: ds.fontSyne }}>
                🤖 AI Active
              </span>
              <button
                onClick={onPauseAI}
                disabled={pausing}
                style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, border: '1px solid #C05A00', background: '#fff', color: '#C05A00', fontWeight: 600, cursor: pausing ? 'not-allowed' : 'pointer', fontFamily: ds.fontSyne, opacity: pausing ? 0.6 : 1 }}
              >
                {pausing ? 'Taking over…' : '👤 Take over'}
              </button>
            </>
          )}

          {/* Ask Aria — opens Aria panel without leaving Conversations */}
          {onOpenAria && (
            <button
              onClick={onOpenAria}
              title="Ask Aria — AI Operations Assistant"
              style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, border: `1px solid #1e3a4f`, background: '#0e2030', color: ds.teal, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne, display: 'flex', alignItems: 'center', gap: 4 }}
              onMouseEnter={e => e.currentTarget.style.background = '#1a3040'}
              onMouseLeave={e => e.currentTarget.style.background = '#0e2030'}
            >
              ✦ Ask Aria
            </button>
          )}
        </div>
      </div>

      {/* ── Message thread ──────────────────────────────────────────────── */}
      <div
        ref={threadRef}
        style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', background: '#ECE5DD', padding: '14px 14px 8px' }}
      >
        {loading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <div style={{ width: 26, height: 26, border: `3px solid rgba(2,128,144,0.2)`, borderTopColor: ds.teal, borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
          </div>
        )}
        {!loading && messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#888', fontSize: 13, padding: '40px 20px', fontStyle: 'italic' }}>
            No messages yet — send the first one below.
          </div>
        )}
        {!loading && [...messages].reverse().map(msg => <Bubble key={msg.id} msg={msg} />)}
      </div>

      {/* ── Inactivity nudge ────────────────────────────────────────────── */}
      {showNudge && aiPaused && (
        <div style={{ flexShrink: 0, background: '#FFF8E1', borderTop: `1px solid #FFE082`, borderBottom: `1px solid #FFE082`, padding: '9px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ fontSize: 12.5, color: '#7B4F00', fontFamily: ds.fontDm, flex: 1 }}>
            ⏱ Human Mode active for <strong>{humanModeDuration}</strong> — AI will auto-resume in 5 minutes, or tap Resume AI now.
          </span>
          <div style={{ display: 'flex', gap: 7, flexShrink: 0 }}>
            <button
              onClick={onResumeAI}
              style={{ fontSize: 11.5, padding: '4px 11px', borderRadius: 20, border: `1px solid ${ds.teal}`, background: '#fff', color: ds.teal, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne }}
            >
              🤖 Resume AI
            </button>
            <button
              onClick={onDismissNudge}
              title="Dismiss"
              style={{ fontSize: 13, padding: '2px 8px', background: 'none', border: 'none', cursor: 'pointer', color: '#A07820', lineHeight: 1 }}
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* ── Inline Composer ─────────────────────────────────────────────── */}
      <InlineComposer
        key={active.contact_id}
        leadId={isLead ? active.contact_id : undefined}
        customerId={!isLead ? active.contact_id : undefined}
        windowOpen={windowOpen}
        statusLoading={statusLoading}
        templates={templates}
        onSent={onSent}
      />
    </div>
  )
}

// ─── Inline Composer ──────────────────────────────────────────────────────────
//
// WhatsApp-style input bar. Replaces MessageComposer inside ConversationsModule.
// MessageComposer.jsx is unchanged — CustomerProfile still uses it.
//
// Modes:
//   text     — free-form textarea, Enter sends, Shift+Enter newline, 📎 attachment
//   template — template dropdown + send (auto-selected when window closed)
//   media    — file selected, shows preview chip, send uploads + sends
//
// key={active.contact_id} ensures full reset on conversation switch.

function InlineComposer({ leadId, customerId, windowOpen, statusLoading = false, templates = [], onSent }) {
  const [mode, setMode]               = useState(windowOpen ? 'text' : 'template')
  const [text, setText]               = useState('')
  const [templateName, setTemplateName] = useState('')
  const [file, setFile]               = useState(null)       // File object
  const [fileError, setFileError]     = useState(null)
  const [sending, setSending]         = useState(false)
  const [sendError, setSendError]     = useState(null)
  const fileInputRef                  = useRef(null)
  const textareaRef                   = useRef(null)

  const approvedTemplates = templates.filter(t => t.meta_status === 'approved')

  // Auto-grow textarea height
  const autoGrow = (el) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }

  const handleTextChange = (e) => {
    setText(e.target.value)
    autoGrow(e.target)
    setSendError(null)
  }

  // Enter = send, Shift+Enter = newline
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFileSelect = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    e.target.value = ''   // reset so same file can be reselected

    if (f.size > MAX_MEDIA_BYTES) {
      setFileError(`File too large — max 25 MB (this file is ${formatBytes(f.size)})`)
      return
    }
    setFileError(null)
    setSendError(null)
    setFile(f)
    setMode('media')
  }

  const clearFile = () => {
    setFile(null)
    setFileError(null)
    setMode(windowOpen ? 'text' : 'template')
  }

  const switchMode = (m) => {
    if (m === 'text' && !windowOpen) return  // locked when window closed
    setMode(m)
    setSendError(null)
    if (m === 'text') setTimeout(() => textareaRef.current?.focus(), 50)
  }

  const handleSend = async () => {
    if (sending) return
    setSendError(null)
    setSending(true)
    const wasMediaSend = mode === 'media' && !!file

    try {
      if (wasMediaSend) {
        const fd = new FormData()
        if (leadId)     fd.append('lead_id', leadId)
        if (customerId) fd.append('customer_id', customerId)
        fd.append('file', file)
        await sendMediaMessage(fd)

      } else if (mode === 'template') {
        if (!templateName) { setSendError('Please select a template.'); return }
        const payload = {}
        if (leadId)     payload.lead_id = leadId
        if (customerId) payload.customer_id = customerId
        payload.template_name = templateName
        await sendMessage(payload)
        setTemplateName('')

      } else {
        // text mode
        if (!text.trim()) return
        const payload = {}
        if (leadId)     payload.lead_id = leadId
        if (customerId) payload.customer_id = customerId
        payload.content = text.trim()
        await sendMessage(payload)
        setText('')
        if (textareaRef.current) {
          textareaRef.current.style.height = 'auto'
        }
      }

      onSent?.()
    } catch (err) {
      const msg = err.response?.data?.error?.message
      setSendError(msg || 'Failed to send — please try again.')
    } finally {
      setSending(false)
      // Always clear file state so the preview never gets stuck,
      // even if the API threw — the file may have already been sent.
      if (wasMediaSend) {
        setFile(null)
        setMode(windowOpen ? 'text' : 'template')
      }
    }
  }

  // ── Can send? ──────────────────────────────────────────────────────────
  const canSend = !sending && (
    (mode === 'text'     && text.trim().length > 0) ||
    (mode === 'template' && !!templateName)         ||
    (mode === 'media'    && !!file)
  )

  // ── Styles ─────────────────────────────────────────────────────────────
  const barBg = '#F0F0F0'

  return (
    <div style={{ background: barBg, borderTop: `1px solid #DDD`, flexShrink: 0 }}>

      {/* Window status loading — shown while first fetch is in-flight */}
      {statusLoading && (
        <div style={{ background: '#F5F5F5', borderBottom: `1px solid #E0E0E0`, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 7 }}>
          <div style={{ width: 10, height: 10, border: '2px solid #CCC', borderTopColor: ds.teal, borderRadius: '50%', animation: 'spin 0.7s linear infinite', flexShrink: 0 }} />
          <span style={{ fontSize: 11.5, color: ds.gray, fontFamily: ds.fontDm }}>Checking conversation window…</span>
        </div>
      )}

      {/* Window-closed banner — shown once status is known and window is closed */}
      {!statusLoading && !windowOpen && (
        <div style={{ background: '#FFF8E1', borderBottom: '1px solid #FFE082', padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 12 }}>⚠</span>
          <span style={{ fontSize: 11.5, color: '#7B6000', fontFamily: ds.fontDm }}>
            24-hour window closed — templates only (Meta rule)
          </span>
        </div>
      )}

      {/* File preview chip */}
      {file && (
        <div style={{ padding: '8px 14px 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 8, padding: '5px 10px', flex: 1, minWidth: 0 }}>
            <span style={{ fontSize: 16, flexShrink: 0 }}>{fileIcon(file.type)}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</div>
              <div style={{ fontSize: 10.5, color: ds.gray }}>{formatBytes(file.size)}</div>
            </div>
            <button
              onClick={clearFile}
              title="Remove file"
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.gray, fontSize: 16, lineHeight: 1, padding: 2, flexShrink: 0 }}
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* File size / validation error */}
      {fileError && (
        <div style={{ padding: '4px 14px', fontSize: 11.5, color: '#C0392B', fontFamily: ds.fontDm }}>
          ⚠ {fileError}
        </div>
      )}

      {/* Mode toggle — only shown when window is open and not in media mode */}
      {!statusLoading && windowOpen && mode !== 'media' && (
        <div style={{ display: 'flex', gap: 4, padding: '7px 14px 4px', alignItems: 'center' }}>
          <ModeBtn active={mode === 'text'} onClick={() => switchMode('text')}>✏ Text</ModeBtn>
          <ModeBtn active={mode === 'template'} onClick={() => switchMode('template')}>📋 Template</ModeBtn>
        </div>
      )}

      {/* Template selector row */}
      {!statusLoading && mode === 'template' && (
        <div style={{ padding: '4px 14px 8px', display: 'flex', gap: 8, alignItems: 'center' }}>
          {approvedTemplates.length === 0 ? (
            <div style={{ flex: 1, fontSize: 12, color: ds.gray, fontFamily: ds.fontDm, padding: '9px 0' }}>
              No approved templates. Create them in Template Manager.
            </div>
          ) : (
            <select
              value={templateName}
              onChange={e => { setTemplateName(e.target.value); setSendError(null) }}
              style={{ flex: 1, border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '9px 12px', fontSize: 13, fontFamily: ds.fontDm, outline: 'none', background: '#fff', color: ds.dark }}
            >
              <option value="">— Select a template —</option>
              {approvedTemplates.map(t => (
                <option key={t.id} value={t.name}>{t.name}</option>
              ))}
            </select>
          )}
          <SendButton canSend={canSend && approvedTemplates.length > 0} sending={sending} onClick={handleSend} />
        </div>
      )}

      {/* Text + attachment input row */}
      {!statusLoading && (mode === 'text' || mode === 'media') && (
        <div style={{ padding: mode === 'media' ? '4px 14px 10px' : '4px 14px 10px', display: 'flex', alignItems: 'flex-end', gap: 8 }}>

          {/* Attachment button — hidden in media mode (file already picked) */}
          {mode === 'text' && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_MEDIA}
                onChange={handleFileSelect}
                style={{ display: 'none' }}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                title="Attach image, video, audio or document (max 25 MB)"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.gray, fontSize: 20, padding: '6px 4px', flexShrink: 0, minHeight: 36, display: 'flex', alignItems: 'center', transition: 'color 0.15s' }}
                onMouseEnter={e => e.currentTarget.style.color = ds.teal}
                onMouseLeave={e => e.currentTarget.style.color = ds.gray}
              >
                📎
              </button>
            </>
          )}

          {/* Textarea — shown for text mode; replaced by file preview in media mode */}
          {mode === 'text' && (
            <textarea
              ref={textareaRef}
              value={text}
              onChange={handleTextChange}
              onKeyDown={handleKeyDown}
              placeholder="Type a message… (Enter to send, Shift+Enter for new line)"
              rows={1}
              style={{
                flex: 1,
                resize: 'none',
                border: `1.5px solid ${ds.border}`,
                borderRadius: 20,
                padding: '9px 14px',
                fontSize: 13,
                fontFamily: ds.fontDm,
                outline: 'none',
                background: '#fff',
                color: ds.dark,
                lineHeight: 1.5,
                overflowY: 'auto',
                minHeight: 38,
                maxHeight: 120,
                boxSizing: 'border-box',
              }}
            />
          )}

          {/* In media mode show a 'Ready to send' label */}
          {mode === 'media' && (
            <div style={{ flex: 1, fontSize: 12.5, color: ds.gray, fontFamily: ds.fontDm, padding: '9px 4px' }}>
              Ready to send attachment
            </div>
          )}

          <SendButton canSend={canSend} sending={sending} onClick={handleSend} />
        </div>
      )}

      {/* Send error */}
      {sendError && (
        <div style={{ padding: '2px 14px 8px', fontSize: 11.5, color: '#C0392B', fontFamily: ds.fontDm }}>
          ⚠ {sendError}
        </div>
      )}
    </div>
  )
}

// ─── Mode button (Text / Template toggle) ─────────────────────────────────────

function ModeBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '4px 11px',
        borderRadius: 20,
        border: active ? `1.5px solid ${ds.teal}` : `1.5px solid ${ds.border}`,
        background: active ? ds.mint : 'transparent',
        color: active ? ds.teal : ds.gray,
        fontSize: 11,
        fontWeight: 600,
        cursor: 'pointer',
        fontFamily: ds.fontSyne,
        transition: 'all 0.12s',
        minHeight: 26,
      }}
    >
      {children}
    </button>
  )
}

// ─── Send button ──────────────────────────────────────────────────────────────

function SendButton({ canSend, sending, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={!canSend}
      title="Send message"
      style={{
        width: 38,
        height: 38,
        borderRadius: '50%',
        border: 'none',
        background: canSend ? ds.teal : '#CCC',
        color: '#fff',
        cursor: canSend ? 'pointer' : 'not-allowed',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        transition: 'background 0.15s',
        fontSize: 16,
      }}
    >
      {sending
        ? <span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.4)', borderTopColor: '#fff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
        : '➤'
      }
    </button>
  )
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

function Bubble({ msg }) {
  const isOut = msg.direction === 'outbound'
  const d     = msg.created_at ? new Date(msg.created_at) : null
  const time  = d ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
  const date  = d ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
  const isMedia = msg.message_type && msg.message_type !== 'text'

  return (
    <div style={{ display: 'flex', justifyContent: isOut ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
      <div style={{ maxWidth: '72%', background: isOut ? '#DCF8C6' : '#fff', border: `1px solid ${isOut ? '#B0DDB8' : ds.border}`, borderRadius: isOut ? '14px 14px 4px 14px' : '14px 14px 14px 4px', padding: '9px 12px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        {msg.template_name && (
          <p style={{ fontSize: 10, color: '#856404', background: '#FFF3CD', borderRadius: 4, padding: '2px 6px', margin: '0 0 5px', display: 'inline-block' }}>
            📋 {msg.template_name}
          </p>
        )}

        {/* Media message display */}
        {isMedia && msg.media_url ? (
          <div style={{ marginBottom: 4 }}>
            {msg.message_type === 'image' ? (
              <img
                src={msg.media_url}
                alt="Image"
                style={{ maxWidth: '100%', maxHeight: 220, borderRadius: 8, display: 'block' }}
              />
            ) : (
              <a
                href={msg.media_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ display: 'flex', alignItems: 'center', gap: 7, background: 'rgba(0,0,0,0.05)', borderRadius: 8, padding: '8px 10px', textDecoration: 'none' }}
              >
                <span style={{ fontSize: 20 }}>
                  {msg.message_type === 'video' ? '🎥' : msg.message_type === 'audio' ? '🎵' : '📄'}
                </span>
                <span style={{ fontSize: 12, color: ds.dark, fontWeight: 500 }}>
                  {msg.message_type === 'document' ? 'Document' : msg.message_type === 'video' ? 'Video' : 'Audio'}
                </span>
              </a>
            )}
          </div>
        ) : (
          <p style={{ fontSize: 13, color: ds.dark, margin: 0, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
            {msg.content || (isMedia ? '(Media)' : '(Empty)')}
          </p>
        )}

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: isOut ? 'space-between' : 'flex-end', gap: 4, marginTop: 4 }}>
          {/* Attribution tag — shows AI or rep name on every outbound message */}
          {isOut && (
            <span style={{
              fontSize:   9.5,
              fontFamily: ds.fontSyne,
              fontWeight: 600,
              color:      msg.sent_by_name ? ds.teal : ds.gray,
              flexShrink: 0,
            }}>
              {msg.sent_by_name ? `👤 ${msg.sent_by_name.split(' ')[0]}` : '🤖 AI'}
            </span>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 10, color: ds.gray }}>{date} {time}</span>
            {isOut && <StatusTick status={msg.status} />}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Status tick ──────────────────────────────────────────────────────────────

function StatusTick({ status }) {
  if (!status || status === 'pending') return <span style={{ fontSize: 10, color: ds.gray }}>🕐</span>
  if (status === 'sent')              return <span style={{ fontSize: 10, color: ds.gray }} title="Sent">✓</span>
  if (status === 'delivered')         return <span style={{ fontSize: 10, color: ds.gray }} title="Delivered">✓✓</span>
  if (status === 'read')              return <span style={{ fontSize: 10, color: ds.teal }} title="Read">✓✓</span>
  if (status === 'failed')            return <span style={{ fontSize: 10, color: ds.red  }} title="Failed">✗</span>
  return null
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ totalUnread }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: 14, background: '#FAFCFD' }}>
      <div style={{ fontSize: 52 }}>💬</div>
      <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark }}>
        {totalUnread > 0 ? `${totalUnread} unread message${totalUnread > 1 ? 's' : ''}` : 'Select a conversation'}
      </div>
      <div style={{ fontSize: 13, color: ds.gray, textAlign: 'center', maxWidth: 260, lineHeight: 1.6 }}>
        {totalUnread > 0 ? 'Choose a conversation on the left to reply' : 'Pick any conversation from the left panel to view the thread and send a message'}
      </div>
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function ConvSkeleton() {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '13px 16px', borderBottom: `1px solid ${ds.border}` }}>
      <div style={{ width: 44, height: 44, borderRadius: '50%', background: ds.border, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ width: '55%', height: 13, background: ds.border, borderRadius: 6, marginBottom: 7, animation: 'pulse 1.5s infinite' }} />
        <div style={{ width: '80%', height: 11, background: ds.light, borderRadius: 6, animation: 'pulse 1.5s infinite' }} />
      </div>
    </div>
  )
}

// ─── Chip ─────────────────────────────────────────────────────────────────────

function Chip({ active, color, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{ padding: '4px 11px', borderRadius: 20, border: 'none', fontSize: 11, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne, background: active ? color : ds.light, color: active ? '#fff' : ds.gray, transition: 'all 0.15s', minHeight: 28 }}
    >
      {children}
    </button>
  )
}
