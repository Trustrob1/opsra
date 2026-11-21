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
import {
  MessageCircle, Camera, Search, Circle, User, Bot,
  Paperclip, Send, Download, FileText, Video, File, Music,
  Image, Lightbulb, Clock, X, AlertTriangle,
  Sparkles, Reply, Mic, Pencil, Trash2, Copy, ChevronDown, ChevronLeft, Square,
} from 'lucide-react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import {
  getConversations,
  getThreadStatus,
  resumeAI,
  pauseAI,
  sendMediaMessage,
  sendInstagramMessage,
  sendMessengerMessage,
  sendWebchatMessage,
  pingWebchatTyping,
  getWebchatVisitorTyping,
  uploadWebchatFile,
  editWebchatMessage,
  deleteWebchatMessage,
  getMediaDownloadUrl,
  exportContactsCsv,
} from '../../services/conversations.service'
import { getCreditSummary, naira } from '../../services/credits.service'
import { getLeadMessages, markLeadMessagesRead } from '../../services/leads.service'
import { getCustomerMessages, sendMessage } from '../../services/whatsapp.service'

// ─── Channel config ───────────────────────────────────────────────────────────

const CHANNEL = {
  whatsapp:  { label: 'WhatsApp',  icon: 'whatsapp',  IconComp: MessageCircle, color: '#25D366', bg: '#E8F8EE' },
  instagram: { label: 'Instagram', icon: 'instagram', IconComp: Camera,        color: '#C13584', bg: '#FCE4EC' },
  messenger: { label: 'Messenger', icon: 'messenger', IconComp: MessageCircle,      color: '#0084FF', bg: '#E3F2FD' },
  webchat:   { label: 'Web chat',  icon: 'webchat',   IconComp: MessageCircle,      color: '#2467E3', bg: '#E4EDFD' },   // WEBCHAT-1
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

// WEBCHAT-STAFF-1 — what the web chat accepts from the team (same limits as the visitor side)
const WEBCHAT_ACCEPT = 'image/jpeg,image/png,image/gif,image/webp,audio/*,application/pdf,.doc,.docx,.xls,.xlsx,.txt'
const WEBCHAT_LIMIT_MB = { image: 10, document: 15, audio: 5 }
const WEBCHAT_EDIT_MIN = 15
const VOICE_MAX_SECONDS = 300
const webchatKind = (f) => (f.type?.startsWith('image/') ? 'image' : f.type?.startsWith('audio/') ? 'audio' : 'document')
const replySnippet = (m) => {
  if (m.message_type === 'image') return 'Photo'
  if (m.message_type === 'audio') return 'Voice note'
  if (m.message_type === 'document') return m.content || 'Document'
  return m.content || ''
}

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
  if (!type) return 'attach'
  if (type.startsWith('image/')) return 'image'
  if (type.startsWith('video/')) return 'video'
  if (type.startsWith('audio/')) return 'audio'
  return 'file'
}
function FileTypeIcon({ type, size = 20 }) {
  const t = fileIcon(type)
  if (t === 'image') return <Image size={size} />
  if (t === 'video') return <Video size={size} />
  if (t === 'audio') return <Music size={size} />
  if (t === 'attach') return <Paperclip size={size} />
  return <File size={size} />
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

// `simple` (WA-AUTO-2): the trimmed inbox for WhatsApp-automation-only businesses - three tabs, credit balance, contact export.
export default function ConversationsModule({ onOpenAria, simple = false, onOpenBilling, user }) {
  const isMobile = useIsMobile()
  const [tab, setTab]                     = useState('all')       // all | needs | bot (simple mode only)
  const [balance, setBalance]             = useState(null)
  const [exporting, setExporting]         = useState(false)
  const [exportError, setExportError]     = useState(null)
  const canExport = simple && (user?.roles?.template ?? '') === 'owner'

  useEffect(() => {
    if (!simple) return undefined
    let live = true
    getCreditSummary().then(s => { if (live) setBalance(s) }).catch(() => { if (live) setBalance(null) })
    return () => { live = false }
  }, [simple])

  const handleExport = async () => {
    setExporting(true); setExportError(null)
    try {
      const blob = await exportContactsCsv()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'contacts.csv'
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch {
      setExportError('Could not export your contacts. Please try again.')
    } finally {
      setExporting(false)
    }
  }

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
   // teplates kept for backwards compat — unused after AI-SUGGEST-1
  const [templates, setTemplates]         = useState([])
  const [threadStatus, setThreadStatus]   = useState({ window_open: false, ai_paused: false })
  const [statusLoading, setStatusLoading] = useState(false)
  const [resuming, setResuming]           = useState(false)
  const [pausing, setPausing]             = useState(false)

  // AI-SUGGEST-1 — KB suggestion state
  const [kbSuggestion, setKbSuggestion]         = useState(null)
  const [suggestionLoading, setSuggestionLoading] = useState(false)
  const injectTextRef                             = useRef(null)
  const threadRef                         = useRef(null)
  const isPollingRef                      = useRef(false)

  // CHAT-SCROLL-1 — preserve scroll position across background refreshes.
  // true = thread should snap to bottom on this messages update (initial open,
  // after sending). false = a background poll while the user has scrolled up —
  // leave their position alone, same as native WhatsApp.
  const wasNearBottomRef                  = useRef(true)
  // CHAT-SCROLL-1 — jump-to-original-message on reply-quote click
  const [highlightedMsgId, setHighlightedMsgId] = useState(null)

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

  // templates useEffect removed — AI-SUGGEST-1 (template mode removed from InlineComposer)

  // ── Load thread messages ───────────────────────────────────────────────
  const loadMessages = useCallback((showSpinner = false, forceScrollBottom = showSpinner) => {
    if (!active) return
    if (showSpinner) setMsgLoading(true)

    // CHAT-SCROLL-1 — capture scroll intent BEFORE the fetch resolves. Forced
    // (initial open, after sending) always snaps to bottom. Otherwise (e.g. a
    // background poll) only snap if the user was already near the bottom —
    // someone scrolled up to read history shouldn't get yanked back down.
    const el = threadRef.current
    const nearBottom = !el || (el.scrollHeight - el.scrollTop - el.clientHeight < 100)
    wasNearBottomRef.current = forceScrollBottom || nearBottom

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
    if (threadRef.current && messages.length > 0 && wasNearBottomRef.current) {
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

  // CHAT-SCROLL-1 — clicking a quoted-reply preview jumps to and briefly
  // highlights the original message, like native WhatsApp. Graceful no-op if
  // the original isn't currently loaded in this page of the thread.
  const handleJumpToMessage = useCallback((metaId) => {
    if (!metaId || !threadRef.current) return
    const el = Array.from(threadRef.current.querySelectorAll('[data-meta-id]'))
      .find(node => node.dataset.metaId === metaId)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightedMsgId(metaId)
    setTimeout(() => setHighlightedMsgId(prev => (prev === metaId ? null : prev)), 1500)
  }, [])

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
    loadMessages(false, true)
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

  // ── AI-SUGGEST-1 — KB suggestion fetch ────────────────────────────────────
  const handleRequestSuggestion = useCallback(async (msgId, content) => {
    if (!active || !content) return
    setKbSuggestion(null)
    setSuggestionLoading(true)
    try {
      const { default: api } = await import('../../services/api')
      const res = await api.get(
        `/api/v1/conversations/lead/${active.contact_id}/kb-suggestion`,
        { params: { content } }
      )
      const suggestion = res.data?.data ?? null
      if (suggestion) {
        setKbSuggestion({ ...suggestion, msgId })
      } else {
        // Show brief "no result" state then clear
        setKbSuggestion({ noResult: true, msgId })
        setTimeout(() => setKbSuggestion(null), 3000)
      }
    } catch {
      setKbSuggestion(null)
    } finally {
      setSuggestionLoading(false)
    }
  }, [active])

  const handleSuggestionFeedback = useCallback(async (msgId, articleId, accepted) => {
    if (!active || !msgId || !articleId) return
    try {
      const { default: api } = await import('../../services/api')
      await api.post(
        `/api/v1/conversations/lead/${active.contact_id}/kb-suggestion/feedback`,
        { message_id: msgId, article_id: articleId, accepted }
      )
    } catch {
      // analytics write failure is non-fatal
    }
  }, [active])

  // Clear suggestion when conversation changes
  useEffect(() => {
    setKbSuggestion(null)
    setSuggestionLoading(false)
  }, [active?.contact_id])

  // ── Filtered list ──────────────────────────────────────────────────────────
  const filtered = conversations.filter(c => {
    const q = search.toLowerCase()
    if (q && !c.contact_name.toLowerCase().includes(q) && !(c.phone || '').includes(q)) return false
    if (channelFilter !== 'all' && c.channel !== channelFilter) return false
    if (typeFilter !== 'all' && c.contact_type !== typeFilter) return false
    if (unreadOnly && !c.unread_count) return false
    if (simple && tab === 'needs' && !c.ai_paused) return false
    if (simple && tab === 'bot' && c.ai_paused) return false
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
      simple={simple} tab={tab} onTab={setTab}
      balance={balance} onOpenBilling={onOpenBilling}
      canExport={canExport} onExport={handleExport} exporting={exporting} exportError={exportError}
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
      kbSuggestion={kbSuggestion}
      suggestionLoading={suggestionLoading}
      injectTextRef={injectTextRef}
      onRequestSuggestion={active?.contact_type === 'lead' ? handleRequestSuggestion : null}
      onSuggestionFeedback={active?.contact_type === 'lead' ? handleSuggestionFeedback : null}
      onDismissSuggestion={() => setKbSuggestion(null)}
      onJumpToMessage={handleJumpToMessage}
      highlightedMsgId={highlightedMsgId}
      userId={user?.id}
      onRefresh={() => loadMessages(false, true)}
    />
  ) : (
    <EmptyState totalUnread={totalUnread} />
  )

  // UI-REDESIGN-1: tell the shell when a chat is open on a phone so the bottom tab bar steps aside for the message box.
  const threadOpenMobile = isMobile && panel !== 'list'
  useEffect(() => {
    window.__opsraThreadOpen = threadOpenMobile
    window.dispatchEvent(new Event('opsra:thread-state'))
    return () => { window.__opsraThreadOpen = false; window.dispatchEvent(new Event('opsra:thread-state')) }
  }, [threadOpenMobile])

  if (isMobile) {
    return (
      <div style={{ height: panel === 'list' ? 'calc(100dvh - 60px - 64px - env(safe-area-inset-bottom))' : 'calc(100dvh - 60px)', display: 'flex', flexDirection: 'column', background: ds.light, overflow: 'hidden' }}>
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

function ListPanel({ conversations, allCount, loading, error, search, onSearch, channelFilter, onChannelFilter, typeFilter, onTypeFilter, unreadOnly, onUnreadOnly, active, onSelect, totalUnread, simple, tab, onTab, balance, onOpenBilling, canExport, onExport, exporting, exportError }) {
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

        {simple && (balance || canExport) && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10, fontSize: 12.5, color: ds.gray }}>
            {balance && (
              <span>
                Credit balance <strong style={{ color: ds.dark }}>{naira(balance.balance_kobo)}</strong>
                {onOpenBilling && <> · <button type="button" onClick={onOpenBilling} style={{ background: 'none', border: 'none', padding: 0, color: ds.teal, cursor: 'pointer', fontSize: 12.5, textDecoration: 'underline' }}>Buy credits</button></>}
              </span>
            )}
            {canExport && (
              <button type="button" onClick={onExport} disabled={exporting}
                style={{ marginLeft: 'auto', background: 'none', border: `1px solid ${ds.border}`, borderRadius: 7, padding: '4px 9px', fontSize: 12, color: ds.dark, cursor: exporting ? 'default' : 'pointer' }}>
                {exporting ? 'Preparing…' : 'Export contacts'}
              </button>
            )}
            {exportError && <span role="alert" style={{ color: ds.red, width: '100%' }}>{exportError}</span>}
          </div>
        )}

        <div style={{ position: 'relative', marginBottom: 9 }}>
          <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: ds.gray, pointerEvents: 'none', display:'flex', alignItems:'center' }}><Search size={13} /></span>
          <input
            value={search}
            onChange={e => onSearch(e.target.value)}
            placeholder="Search name or number…"
            style={{ width: '100%', boxSizing: 'border-box', border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '9px 10px 9px 32px', fontSize: 13, fontFamily: ds.fontDm, outline: 'none', background: ds.light, color: ds.dark }}
          />
        </div>

        {simple ? (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {[{ v: 'all', l: 'All' }, { v: 'needs', l: 'Needs you' }, { v: 'bot', l: 'Bot handled' }].map(({ v, l }) => (
              <Chip key={v} active={tab === v} color={ds.teal} onClick={() => onTab(v)}>{l}</Chip>
            ))}
            <Chip active={unreadOnly} color='#E53E3E' onClick={() => onUnreadOnly(!unreadOnly)}><span style={{display:'inline-flex',alignItems:'center',gap:4}}><Circle size={8} fill='currentColor' strokeWidth={0} />Unread</span></Chip>
          </div>
        ) : (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {[{ v: 'all', l: 'All channels' }, { v: 'whatsapp', l: 'WA' }, { v: 'instagram', l: 'IG' }, { v: 'messenger', l: 'FB' }, { v: 'webchat', l: 'Web' }].map(({ v, l }) => (
            <Chip key={v} active={channelFilter === v} color={ds.teal} onClick={() => onChannelFilter(v)}>{l}</Chip>
          ))}
          {[{ v: 'all', l: 'All' }, { v: 'lead', l: 'Leads' }, { v: 'customer', l: 'Customers' }].map(({ v, l }) => (
            <Chip key={v} active={typeFilter === v} color={ds.dark} onClick={() => onTypeFilter(v)}>{l}</Chip>
          ))}
          <Chip active={unreadOnly} color='#E53E3E' onClick={() => onUnreadOnly(!unreadOnly)}><span style={{display:'inline-flex',alignItems:'center',gap:4}}><Circle size={8} fill='currentColor' strokeWidth={0} />Unread</span></Chip>
        </div>
        )}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {loading && [1,2,3,4,5,6].map(n => <ConvSkeleton key={n} />)}
        {!loading && error && <div style={{ padding: 28, textAlign: 'center', color: ds.red, fontSize: 13 }}>{error}</div>}
        {!loading && !error && allCount === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: ds.gray, fontSize: 13 }}>
            <div style={{ marginBottom: 10, display:'flex', justifyContent:'center' }}><MessageCircle size={36} color={ds.teal} strokeWidth={1.5} /></div>No conversations yet.
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
        <span style={{ position: 'absolute', bottom: -1, right: -1, width: 18, height: 18, borderRadius: '50%', background: '#fff', border: '1.5px solid #fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {ch.IconComp && <ch.IconComp size={10} color={ch.color} strokeWidth={2} />}
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
              <span title='Human mode — AI paused' style={{ display:'flex', alignItems:'center' }}><User size={12} color={ds.gray} /></span>
            )}
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 20, fontWeight: 600, fontFamily: ds.fontSyne, background: isLead ? '#FFF3E0' : '#E4EDFD', color: isLead ? '#C05A00' : ds.teal }}>
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

function ThreadPanel({ active, messages, loading, templates, threadStatus, statusLoading, humanModeDuration, showNudge, onDismissNudge, threadRef, onSent, onResumeAI, resuming, onPauseAI, pausing, onOpenAria, onBack, kbSuggestion, suggestionLoading, injectTextRef, onRequestSuggestion, onSuggestionFeedback, onDismissSuggestion, onJumpToMessage, highlightedMsgId, userId, onRefresh }) {
  const ch     = CHANNEL[active.channel] || CHANNEL.whatsapp
  const isLead = active.contact_type === 'lead'
  const isWebchat = active.channel === 'webchat'
  const [replyTo, setReplyTo] = useState(null)          // WEBCHAT-STAFF-1: { id, who, text }
  const { window_open: windowOpen, ai_paused: aiPaused } = threadStatus
  // WEBCHAT-CONTACT-1e: while this web chat is open, ask every 2.5 s whether the visitor is typing and show the dots bubble
  const [visitorTyping, setVisitorTyping] = useState(false)
  useEffect(() => {
    if (!isWebchat || !isLead || !active.contact_id) return undefined
    let dead = false
    const tick = async () => { const t = await getWebchatVisitorTyping(active.contact_id); if (!dead) setVisitorTyping(t) }
    tick()
    const id = setInterval(() => { if (!document.hidden) tick() }, 2500)
    return () => { dead = true; clearInterval(id); setVisitorTyping(false) }
  }, [isWebchat, isLead, active.contact_id])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Header (UI-REDESIGN-1, option A): name row + status strip ──────── */}
      <div style={{ flexShrink: 0, background: '#fff', borderBottom: `1px solid ${ds.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: onBack ? '8px 12px 8px 6px' : '10px 20px', minHeight: 60 }}>
          {onBack && (
            <button onClick={onBack} aria-label="Back to conversations" style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.dark, padding: 0, width: 44, height: 44, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><ChevronLeft size={24} /></button>
          )}
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <div style={{ width: 42, height: 42, borderRadius: '50%', background: isLead ? '#FFF1D9' : ds.mint, color: isLead ? '#8A4B00' : ds.tealDark, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15 }}>
              {initials(active.contact_name)}
            </div>
            <span title={ch.label} style={{ position: 'absolute', right: -3, bottom: -3, width: 20, height: 20, borderRadius: '50%', background: '#fff', border: `1.5px solid ${ds.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {ch.IconComp && <ch.IconComp size={11} color={ch.color} strokeWidth={2.2} />}
            </span>
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16.5, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{active.contact_name}</span>
              <span style={{ flexShrink: 0, fontSize: 11.5, padding: '2px 8px', borderRadius: 20, fontWeight: 700, background: isLead ? '#FFF1D9' : ds.mint, color: isLead ? '#8A4B00' : ds.tealDark }}>{isLead ? 'Lead' : 'Customer'}</span>
            </div>
            <div style={{ fontSize: 13, color: ds.gray, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {ch.label}{active.phone ? ` · ${active.phone}` : ''}
            </div>
          </div>
          {/* Ask Aria — opens the Aria panel without leaving Conversations */}
          {onOpenAria && (
            <button
              onClick={onOpenAria}
              title="Ask Aria — AI Operations Assistant"
              aria-label="Ask Aria"
              style={{ flexShrink: 0, minHeight: 40, minWidth: 40, padding: onBack ? 0 : '0 14px', borderRadius: 999, border: `1px solid ${ds.border}`, background: '#fff', color: ds.purple, fontWeight: 600, fontSize: 13.5, cursor: 'pointer', fontFamily: ds.fontDm, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
            >
              <Sparkles size={16} />{!onBack && 'Ask Aria'}
            </button>
          )}
        </div>

        {/* AI / Human status strip — sending a message switches to Human mode; Resume AI hands the chat back */}
        {aiPaused ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 16px', background: '#FFF3E0', borderTop: '1px solid #FFE0B2', minHeight: 44, boxSizing: 'border-box' }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#B45309', flexShrink: 0 }} />
            <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600, color: '#8A4B00' }}>You are replying{humanModeDuration ? ` · ${humanModeDuration}` : ''}</span>
            <button
              onClick={onResumeAI}
              disabled={resuming}
              style={{ minHeight: 36, padding: '0 16px', borderRadius: 999, border: '1.5px solid #176A3C', background: '#fff', color: '#176A3C', fontWeight: 600, fontSize: 14, cursor: resuming ? 'not-allowed' : 'pointer', fontFamily: ds.fontDm, display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0 }}
            >
              {resuming ? 'Resuming…' : <><Bot size={16} />Resume AI</>}
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 16px', background: '#E3F4EA', borderTop: '1px solid #CDE9D7', minHeight: 44, boxSizing: 'border-box' }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#176A3C', flexShrink: 0 }} />
            <span style={{ fontSize: 14, fontWeight: 600, color: '#176A3C' }}>AI is replying</span>
            {!onBack && <span style={{ fontSize: 13, color: '#3C4352', marginLeft: 'auto' }}>Send a message to take over</span>}
          </div>
        )}
      </div>

      {/* ── Message thread ──────────────────────────────────────────────── */}
      <div
        ref={threadRef}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', WebkitOverflowScrolling: 'touch', background: ds.light, padding: '14px 14px 8px' }}
      >
        {loading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <div style={{ width: 26, height: 26, border: `3px solid rgba(36,103,227,0.2)`, borderTopColor: ds.teal, borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
          </div>
        )}
        {!loading && messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#888', fontSize: 13, padding: '40px 20px', fontStyle: 'italic' }}>
            No messages yet — send the first one below.
          </div>
        )}
        {!loading && [...messages].reverse().map(msg => (
          <Bubble
            key={msg.id}
            msg={msg}
            onRequestSuggestion={onRequestSuggestion}
            onJumpToMessage={onJumpToMessage}
            isHighlighted={!!(msg.meta_message_id || isWebchat) && highlightedMsgId === (msg.meta_message_id || msg.id)}
            webchat={isWebchat}
            userId={userId}
            onReply={(m) => setReplyTo({ id: m.id, who: m.direction === 'outbound' ? (m.sent_by_name ? m.sent_by_name.split(' ')[0] : 'Bot') : (active.contact_name || 'Visitor'), text: replySnippet(m) })}
            onEdit={async (id, text) => { await editWebchatMessage(id, text); onRefresh?.() }}
            onDelete={async (id) => { await deleteWebchatMessage(id); setReplyTo((r) => (r?.id === id ? null : r)); onRefresh?.() }}
          />
        ))}
        {visitorTyping && (
          <div role="status" aria-label={`${active.contact_name || 'The visitor'} is typing`} style={{ display: 'flex', margin: '6px 0 4px' }}>
            <style>{'@keyframes wcv-bounce{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-4px);opacity:1}}'}</style>
            <div style={{ background: '#fff', borderRadius: 14, padding: '11px 14px', display: 'flex', gap: 5, boxShadow: '0 1px 1px rgba(0,0,0,0.08)' }}>
              {[0, 1, 2].map((d) => <span key={d} aria-hidden="true" style={{ width: 7, height: 7, borderRadius: 999, background: '#8A98A3', animation: `wcv-bounce 1.2s ease-in-out ${d * 0.16}s infinite` }} />)}
            </div>
          </div>
        )}
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
              <span style={{display:'inline-flex',alignItems:'center',gap:4}}><Bot size={11} />Resume AI</span>
            </button>
            <button
              onClick={onDismissNudge}
              title="Dismiss"
              style={{ fontSize: 13, padding: '2px 8px', background: 'none', border: 'none', cursor: 'pointer', color: '#A07820', lineHeight: 1 }}
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* ── AI-SUGGEST-1 — KB Suggestion bar ───────────────────────────── */}
      {(kbSuggestion || suggestionLoading) && (
        <KBSuggestionBar
          suggestion={kbSuggestion}
          loading={suggestionLoading}
          onUse={(snippet, articleId, msgId) => {
            injectTextRef.current?.(snippet)
            onSuggestionFeedback?.(msgId, articleId, true)
            onDismissSuggestion?.()
          }}
          onDismiss={(articleId, msgId) => {
            onSuggestionFeedback?.(msgId, articleId, false)
            onDismissSuggestion?.()
          }}
        />
      )}

      {/* ── Inline Composer ─────────────────────────────────────────────── */}
      <InlineComposer
        key={active.contact_id}
        leadId={isLead ? active.contact_id : undefined}
        customerId={!isLead ? active.contact_id : undefined}
        channel={active.channel || 'whatsapp'}
        windowOpen={windowOpen || active.channel === 'webchat'}
        statusLoading={statusLoading}
        templates={templates}
        onSent={onSent}
        injectTextRef={injectTextRef}
        replyTo={isWebchat ? replyTo : null}
        onClearReply={() => setReplyTo(null)}
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

function InlineComposer({ leadId, customerId, channel = 'whatsapp', windowOpen, statusLoading = false, templates = [], onSent, injectTextRef, replyTo = null, onClearReply }) {
  const isMobile                      = useIsMobile()
  const [mode, setMode]               = useState('text')
  const [text, setText]               = useState('')
  const [file, setFile]               = useState(null)       // File object
  const [fileError, setFileError]     = useState(null)
  const [sending, setSending]         = useState(false)
  const [sendError, setSendError]     = useState(null)
  const fileInputRef                  = useRef(null)
  const cameraInputRef                = useRef(null)
  const galleryInputRef               = useRef(null)
  const [attachOpen, setAttachOpen]    = useState(false)
  const textareaRef                   = useRef(null)
  const isWebchat                     = channel === 'webchat'
  // WEBCHAT-STAFF-1 — voice note recorder
  const [recording, setRecording]     = useState(false)
  const [recSecs, setRecSecs]         = useState(0)
  const recRef                        = useRef(null)         // { recorder, stream, chunks, timer }

  useEffect(() => {
    if (replyTo?.id) setTimeout(() => textareaRef.current?.focus(), 30)
  }, [replyTo?.id])

  // stop the microphone if the composer goes away mid-recording
  useEffect(() => () => {
    const r = recRef.current
    if (r) { clearInterval(r.timer); r.discard = true; try { r.recorder.stop() } catch { /* already stopped */ } r.stream.getTracks().forEach(t => t.stop()) }
  }, [])

  const startRecording = async () => {
    setFileError(null); setSendError(null)
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === 'undefined') {
      setFileError('Voice notes are not supported on this browser.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const wanted = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
        .find((t) => window.MediaRecorder.isTypeSupported?.(t))
      const recorder = wanted ? new window.MediaRecorder(stream, { mimeType: wanted }) : new window.MediaRecorder(stream)
      const rec = { recorder, stream, chunks: [], timer: null, discard: false }
      recorder.ondataavailable = (e) => { if (e.data) rec.chunks.push(e.data) }
      recorder.onerror = () => { setFileError('The recording failed. Please try again.') }
      recorder.onstop = () => {
        clearInterval(rec.timer)
        stream.getTracks().forEach(t => t.stop())
        recRef.current = null
        setRecording(false)
        if (rec.discard) return
        const type = (recorder.mimeType || 'audio/webm').split(';')[0]
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
        const blob = new Blob(rec.chunks, { type })
        if (blob.size < 200) {
          setFileError('No sound was recorded. Check your microphone is not muted and is the selected input device, then try again.')
          return
        }
        const f = new window.File([blob], `voice-note.${ext}`, { type })
        if (f.size > WEBCHAT_LIMIT_MB.audio * 1024 * 1024) {
          setFileError(`That voice note is too long — max ${WEBCHAT_LIMIT_MB.audio} MB.`)
          return
        }
        setFile(f); setMode('media')
      }
      recRef.current = rec
      recorder.start(250)
      setRecSecs(0); setRecording(true)
      rec.timer = setInterval(() => {
        setRecSecs((n) => {
          if (n + 1 >= VOICE_MAX_SECONDS) { try { recorder.stop() } catch { /* already stopped */ } }
          return n + 1
        })
      }, 1000)
    } catch {
      setFileError('Could not use the microphone. Please allow microphone access and try again.')
    }
  }

  const stopRecording = () => { try { recRef.current?.recorder.stop() } catch { /* already stopped */ } }
  const cancelRecording = () => { if (recRef.current) recRef.current.discard = true; stopRecording() }


  // AI-SUGGEST-1 — allow parent to inject text into composer
  useEffect(() => {
    if (!injectTextRef) return
    injectTextRef.current = (injected) => {
      setText(injected)
      setMode('text')
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
    return () => { if (injectTextRef) injectTextRef.current = null }
  }, [injectTextRef])

  // Auto-grow textarea height
  const autoGrow = (el) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }

  const typingPingAt = useRef(0)
  const handleTextChange = (e) => {
    if (isWebchat && leadId && e.target.value.trim() && Date.now() - typingPingAt.current > 3000) {
      typingPingAt.current = Date.now()
      pingWebchatTyping(leadId)                       // the visitor sees typing dots while we write
    }
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

    if (isWebchat) {
      const k = webchatKind(f)
      if (f.type?.startsWith('video/')) { setFileError('Videos cannot be sent in web chat. Send a photo, voice note or document.'); return }
      if (f.size > WEBCHAT_LIMIT_MB[k] * 1024 * 1024) {
        setFileError(`File too large — max ${WEBCHAT_LIMIT_MB[k]} MB for ${k === 'audio' ? 'a voice note' : k === 'image' ? 'a photo' : 'a document'} (this file is ${formatBytes(f.size)})`)
        return
      }
    } else if (f.size > MAX_MEDIA_BYTES) {
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
    setMode('text')
  }

  const handleSend = async () => {
    if (sending) return
    setSendError(null)
    setSending(true)
    const wasMediaSend = mode === 'media' && !!file

    try {
      if (wasMediaSend && isWebchat) {
        // WEBCHAT-STAFF-1 — a team member's photo / document / voice note
        const fd = new FormData()
        fd.append('lead_id', leadId)
        fd.append('kind', webchatKind(file))
        if (replyTo?.id) fd.append('reply_to', replyTo.id)
        fd.append('file', file)
        await uploadWebchatFile(fd)
        onClearReply?.()
      } else if (wasMediaSend) {
        const fd = new FormData()
        if (leadId)     fd.append('lead_id', leadId)
        if (customerId) fd.append('customer_id', customerId)
        fd.append('file', file)
        await sendMediaMessage(fd)

      } else {
        // text mode
        if (!text.trim()) return
        if (channel === 'instagram') {
          // Instagram DM — routes to dedicated endpoint, lead only
          await sendInstagramMessage(leadId, text.trim())
        } else if (channel === 'messenger') {
          // Facebook Messenger DM — routes to dedicated endpoint, lead only
          await sendMessengerMessage(leadId, text.trim())
        } else if (channel === 'webchat') {
          // Web chat — stored and shown on the visitor's page; no Meta call, no 24-hour window
          await sendWebchatMessage(leadId, text.trim(), replyTo?.id)
          onClearReply?.()
        } else {
          const payload = {}
          if (leadId)     payload.lead_id = leadId
          if (customerId) payload.customer_id = customerId
          payload.content = text.trim()
          await sendMessage(payload)
        }
        setText('')
        if (textareaRef.current) {
          textareaRef.current.style.height = 'auto'
        }
      }

      onSent?.()
    } catch (err) {
      const d = err.response?.data
      const msg = d?.error?.message || (typeof d?.detail === 'string' ? d.detail : null)
      setSendError(msg || 'Failed to send — please try again.')
    } finally {
      setSending(false)
      // Always clear file state so the preview never gets stuck,
      // even if the API threw — the file may have already been sent.
      if (wasMediaSend) {
        setFile(null)
        setMode('text')
      }
    }
  }

  // ── Can send? ──────────────────────────────────────────────────────────
  const canSend = !sending && (
    (mode === 'text'     && text.trim().length > 0) ||
    (mode === 'media'    && !!file)
  )

  // ── Styles ─────────────────────────────────────────────────────────────
  const barBg = '#FFFFFF'

  return (
    <div style={{ position: 'relative', background: barBg, borderTop: `1px solid ${ds.border}`, flexShrink: 0, paddingBottom: 'env(safe-area-inset-bottom)' }}>

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
          <AlertTriangle size={12} />
          <span style={{ fontSize: 11.5, color: '#7B6000', fontFamily: ds.fontDm }}>
            {(channel === 'instagram' || channel === 'messenger')
              ? '24-hour window closed — you can only reply within 24 hours of the last message'
              : '24-hour window closed — templates only (Meta rule)'}
          </span>
        </div>
      )}

      {/* WEBCHAT-STAFF-1 — replying to a specific message */}
      {replyTo && !statusLoading && (
        <div style={{ padding: '8px 14px 0', display: 'flex' }}>
          <div style={{ flex: 1, minWidth: 0, background: '#fff', borderLeft: `4px solid ${ds.teal}`, borderRadius: 8, padding: '5px 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Reply size={14} color={ds.teal} style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, color: ds.teal, fontFamily: ds.fontSyne }}>Replying to {replyTo.who}</div>
              <div style={{ fontSize: 12, color: ds.gray, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{replyTo.text}</div>
            </div>
            <button onClick={onClearReply} title="Cancel reply" style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.gray, padding: 2, display: 'flex' }}><X size={16} /></button>
          </div>
        </div>
      )}

      {/* WEBCHAT-STAFF-1 — voice note recording */}
      {recording && (
        <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#D93025', flexShrink: 0 }} />
          <span style={{ flex: 1, fontSize: 13, color: ds.dark, fontFamily: ds.fontDm }}>
            Recording… {Math.floor(recSecs / 60)}:{String(recSecs % 60).padStart(2, '0')}
          </span>
          <button onClick={cancelRecording} title="Cancel recording" style={{ background: 'none', border: `1px solid ${ds.border}`, borderRadius: 20, padding: '6px 12px', cursor: 'pointer', color: ds.gray, fontSize: 12, fontFamily: ds.fontDm }}>Cancel</button>
          <button onClick={stopRecording} title="Finish recording" style={{ background: ds.teal, border: 'none', borderRadius: 20, padding: '6px 14px', cursor: 'pointer', color: '#fff', fontSize: 12, fontWeight: 600, fontFamily: ds.fontSyne, display: 'flex', alignItems: 'center', gap: 5 }}><Square size={11} fill="#fff" />Done</button>
        </div>
      )}

      {/* File preview chip */}
      {file && (
        <div style={{ padding: '8px 14px 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 8, padding: '5px 10px', flex: 1, minWidth: 0 }}>
            <span style={{ fontSize: 16, flexShrink: 0 }}><FileTypeIcon type={file.type} size={18} /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: ds.dark, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</div>
              <div style={{ fontSize: 10.5, color: ds.gray }}>{formatBytes(file.size)}</div>
            </div>
            <button
              onClick={clearFile}
              title="Remove file"
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.gray, padding: 2, flexShrink: 0, display:'flex', alignItems:'center' }}
            ><X size={16} /></button>
          </div>
        </div>
      )}

      {/* File size / validation error */}
      {fileError && (
        <div style={{ padding: '4px 14px', fontSize: 11.5, color: '#C0392B', fontFamily: ds.fontDm }}>
          {fileError}
        </div>
      )}

      {/* Template mode removed — AI-SUGGEST-1 (templates only useful for broadcasts) */}

      {/* Text + attachment input row */}
      {!statusLoading && !recording && (mode === 'text' || mode === 'media') && (
        <div style={{ padding: '8px 10px 10px', display: 'flex', alignItems: 'center', gap: 2, minWidth: 0 }}>

          {/* Attachment menu (UI-REDESIGN-1c): one paperclip opens Photo / Camera / Document / Voice note — hidden for Instagram/Messenger (text only) and in media mode */}
          {mode === 'text' && channel !== 'instagram' && channel !== 'messenger' && (
            <>
              <input ref={fileInputRef} type="file" accept={isWebchat ? WEBCHAT_ACCEPT : ACCEPTED_MEDIA} onChange={handleFileSelect} style={{ display: 'none' }} />
              <input ref={galleryInputRef} type="file" accept={isWebchat ? 'image/jpeg,image/png,image/gif,image/webp' : 'image/*,video/*'} onChange={handleFileSelect} style={{ display: 'none' }} />
              {isWebchat && (
                <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" onChange={handleFileSelect} style={{ display: 'none' }} />
              )}
              <button
                onClick={() => setAttachOpen(o => !o)}
                title="Attach a photo, camera shot, document or voice note (max 25 MB)"
                aria-label="Attach"
                aria-expanded={attachOpen}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: attachOpen ? ds.teal : ds.gray, padding: 0, flexShrink: 0, width: 44, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'color 0.15s' }}
              >
                {attachOpen ? <X size={22} /> : <Paperclip size={22} />}
              </button>
              {attachOpen && (
                <>
                  <div onClick={() => setAttachOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
                  <div style={{ position: 'absolute', bottom: '100%', left: 10, right: isMobile ? 10 : 'auto', width: isMobile ? 'auto' : 340, marginBottom: 8, zIndex: 41, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 20, boxShadow: '0 8px 28px rgba(27,31,40,0.16)', padding: '18px 12px 14px', display: 'grid', gridTemplateColumns: `repeat(${isWebchat ? 4 : 2}, 1fr)`, gap: 12 }}>
                    {[
                      { key: 'photo',  label: 'Photo',      Icon: Image,    bg: '#E4EDFD', fg: '#2467E3', run: () => galleryInputRef.current?.click(), show: true },
                      { key: 'camera', label: 'Camera',     Icon: Camera,   bg: '#FDE7F0', fg: '#C21E56', run: () => cameraInputRef.current?.click(),  show: isWebchat },
                      { key: 'doc',    label: 'Document',   Icon: FileText, bg: '#EFE6FB', fg: '#5E1BB8', run: () => fileInputRef.current?.click(),    show: true },
                      { key: 'voice',  label: 'Voice note', Icon: Mic,      bg: '#E3F4EA', fg: '#176A3C', run: () => startRecording(),                 show: isWebchat },
                    ].filter(o => o.show).map(o => (
                      <button
                        key={o.key}
                        onClick={() => { setAttachOpen(false); o.run() }}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, padding: 0, fontFamily: ds.fontDm }}
                      >
                        <span style={{ width: 52, height: 52, borderRadius: '50%', background: o.bg, color: o.fg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><o.Icon size={24} /></span>
                        <span style={{ fontSize: 13, color: '#3C4352', fontWeight: 500 }}>{o.label}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </>
          )}

          {/* Textarea — shown for text mode; replaced by file preview in media mode */}
          {mode === 'text' && (
            <textarea
              ref={textareaRef}
              value={text}
              onChange={handleTextChange}
              onKeyDown={handleKeyDown}
              placeholder={typeof window !== 'undefined' && window.innerWidth < 768 ? 'Message' : 'Type a message… (Enter to send, Shift+Enter for new line)'}
              rows={1}
              style={{
                flex: 1,
                minWidth: 0,
                width: '100%',
                resize: 'none',
                border: `1.5px solid ${ds.border}`,
                borderRadius: 24,
                padding: '12px 18px',
                height: 48,
                fontSize: 16,
                fontFamily: ds.fontDm,
                outline: 'none',
                background: ds.light,
                color: ds.dark,
                lineHeight: 1.5,
                overflowY: 'auto',
                minHeight: 48,
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
          {sendError}
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
        width: 48,
        height: 48,
        marginLeft: 4,
        borderRadius: '50%',
        border: 'none',
        background: canSend ? ds.teal : '#C9CED8',
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
        : <Send size={20} />
      }
    </button>
  )
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

function Bubble({ msg, onRequestSuggestion, onJumpToMessage, isHighlighted, webchat = false, userId, onReply, onEdit, onDelete }) {
  const isOut  = msg.direction === 'outbound'
  const d      = msg.created_at ? new Date(msg.created_at) : null
  const time   = d ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
  const date   = d ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
  const isMedia = msg.message_type && msg.message_type !== 'text'
  const [downloading, setDownloading] = useState(false)

  // WEBCHAT-STAFF-1 — message menu (reply / copy / edit / delete) and inline edit, web chat only
  const [menuOpen, setMenuOpen]     = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const [editing, setEditing]       = useState(false)
  const [draft, setDraft]           = useState('')
  const [busy, setBusy]             = useState(false)
  const [actErr, setActErr]         = useState(null)
  const menuRef                     = useRef(null)
  const gone    = !!msg.deleted_at
  const mine    = webchat && isOut && !!msg.sent_by && msg.sent_by === userId
  const canEdit = mine && !gone && (!msg.message_type || msg.message_type === 'text') &&
                  d && (Date.now() - d.getTime()) < WEBCHAT_EDIT_MIN * 60 * 1000
  const hasMenu = webchat && !gone && !!msg.id

  useEffect(() => {
    if (!menuOpen) return undefined
    const close = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) { setMenuOpen(false); setConfirmDel(false) } }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  const copyText = async () => {
    setMenuOpen(false)
    try { await navigator.clipboard.writeText(msg.content || '') } catch { /* clipboard blocked: nothing to do */ }
  }
  const startEdit = () => { setMenuOpen(false); setActErr(null); setDraft(msg.content || ''); setEditing(true) }
  const saveEdit = async () => {
    const t = draft.trim()
    if (!t || busy) return
    if (t === (msg.content || '')) { setEditing(false); return }
    setBusy(true); setActErr(null)
    try { await onEdit?.(msg.id, t); setEditing(false) }
    catch (err) {
      const dd = err.response?.data
      setActErr((typeof dd?.detail === 'string' && dd.detail) || dd?.error?.message || 'Could not edit this message.')
    } finally { setBusy(false) }
  }
  const doDelete = async () => {
    if (busy) return
    setBusy(true); setActErr(null)
    try { await onDelete?.(msg.id); setMenuOpen(false); setConfirmDel(false) }
    catch (err) {
      const dd = err.response?.data
      setActErr((typeof dd?.detail === 'string' && dd.detail) || dd?.error?.message || 'Could not delete this message.')
    } finally { setBusy(false) }
  }

  // WhatsApp-style download: fetch a fresh signed URL from the backend,
  // then blob-download it so the file saves directly without opening a tab.
  // Falls back to opening media_url in a new tab if msg has no storage_path
  // (old messages before storage_path was saved).
  const handleDownload = async () => {
    if (downloading) return
    setDownloading(true)
    try {
      const res = await getMediaDownloadUrl(msg.id)
      const { url, filename } = res.data?.data ?? {}
      if (!url) throw new Error('no url')
      const fileRes = await fetch(url)
      const blob = await fileRes.blob()
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename || 'download'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(blobUrl)
    } catch {
      // Fallback for old messages with no storage_path: open in new tab
      if (msg.media_url) window.open(msg.media_url, '_blank')
    } finally {
      setDownloading(false)
    }
  }

  const DownloadBtn = ({ style = {} }) => (
    <button
      onClick={handleDownload}
      disabled={downloading}
      title="Download"
      style={{
        background: 'rgba(0,0,0,0.35)',
        border: 'none',
        borderRadius: 6,
        padding: '3px 8px',
        color: '#fff',
        fontSize: 12,
        cursor: downloading ? 'wait' : 'pointer',
        lineHeight: 1.4,
        flexShrink: 0,
        ...style,
      }}
    >
      {downloading ? '…' : <Download size={12} />}
    </button>
  )

  return (
    <div style={{ display: 'flex', justifyContent: isOut ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
      <div
        data-meta-id={msg.meta_message_id || msg.id || undefined}
        style={{ position: 'relative', maxWidth: '82%', minWidth: 0, overflowWrap: 'anywhere', background: isHighlighted ? '#FFF3B0' : (isOut ? '#E4EDFD' : '#fff'), border: `1px solid ${isOut ? '#C9DAF8' : ds.border}`, borderRadius: isOut ? '14px 14px 4px 14px' : '14px 14px 14px 4px', padding: '9px 12px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)', transition: 'background-color 0.4s ease' }}
      >
        {hasMenu && (
          <div ref={menuRef} style={{ position: 'absolute', top: 2, right: 4, zIndex: 3 }}>
            <button
              onClick={() => { setMenuOpen(o => !o); setConfirmDel(false) }}
              title="Message options"
              aria-label="Message options"
              style={{ background: 'rgba(255,255,255,0.7)', border: 'none', borderRadius: 10, cursor: 'pointer', color: ds.gray, padding: '1px 3px', display: 'flex', alignItems: 'center', opacity: menuOpen ? 1 : 0.55 }}
            ><ChevronDown size={14} /></button>
            {menuOpen && (
              <div role="menu" style={{ position: 'absolute', top: 22, right: 0, minWidth: 150, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 10, boxShadow: '0 6px 18px rgba(0,0,0,0.14)', padding: 4 }}>
                {confirmDel ? (
                  <div style={{ padding: '6px 8px' }}>
                    <div style={{ fontSize: 12, color: ds.dark, marginBottom: 6, fontFamily: ds.fontDm }}>Delete for everyone? The visitor will see "This message was deleted".</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button onClick={doDelete} disabled={busy} style={{ flex: 1, background: '#D93025', color: '#fff', border: 'none', borderRadius: 8, padding: '5px 8px', fontSize: 12, cursor: busy ? 'wait' : 'pointer' }}>{busy ? '…' : 'Delete'}</button>
                      <button onClick={() => setConfirmDel(false)} style={{ flex: 1, background: '#fff', color: ds.gray, border: `1px solid ${ds.border}`, borderRadius: 8, padding: '5px 8px', fontSize: 12, cursor: 'pointer' }}>Keep</button>
                    </div>
                  </div>
                ) : (
                  <>
                    {[
                      { k: 'reply', label: 'Reply', Icon: Reply, run: () => { setMenuOpen(false); onReply?.(msg) }, show: true },
                      { k: 'copy', label: 'Copy', Icon: Copy, run: copyText, show: !isMedia && !!msg.content },
                      { k: 'edit', label: 'Edit', Icon: Pencil, run: startEdit, show: canEdit },
                      { k: 'delete', label: 'Delete', Icon: Trash2, run: () => setConfirmDel(true), show: mine, danger: true },
                    ].filter(a => a.show).map(a => (
                      <button
                        key={a.k}
                        role="menuitem"
                        onClick={a.run}
                        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', borderRadius: 8, padding: '7px 10px', fontSize: 13, cursor: 'pointer', color: a.danger ? '#D93025' : ds.dark, fontFamily: ds.fontDm, textAlign: 'left' }}
                        onMouseEnter={e => { e.currentTarget.style.background = '#F3F5F6' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'none' }}
                      ><a.Icon size={14} />{a.label}</button>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* Quoted-reply preview — shown when this message was a WhatsApp native
            reply to an earlier message (text or image). Clicking it jumps to and
            highlights the original, like native WhatsApp. Falls back to a generic
            label if the original couldn't be resolved (e.g. predates this feature
            or isn't currently loaded in this page of the thread). */}
        {(msg.reply_to_message_id || msg.reply_to_id) && (
          <div
            onClick={() => onJumpToMessage?.(msg.reply_to_message_id || msg.reply_to_id)}
            style={{ background: 'rgba(0,0,0,0.045)', borderLeft: `3px solid ${ds.teal}`, borderRadius: 6, padding: '5px 8px', marginBottom: 6, fontSize: 11.5, color: ds.gray, display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden', cursor: onJumpToMessage ? 'pointer' : 'default' }}
            onMouseEnter={e => { if (onJumpToMessage) e.currentTarget.style.background = 'rgba(0,0,0,0.08)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(0,0,0,0.045)' }}
          >
            {msg.reply_preview ? (
              msg.reply_preview.message_type === 'image' && msg.reply_preview.media_url ? (
                <>
                  <img src={msg.reply_preview.media_url} alt="" style={{ width: 26, height: 26, borderRadius: 4, objectFit: 'cover', flexShrink: 0 }} />
                  <span>Photo</span>
                </>
              ) : msg.reply_preview.message_type && msg.reply_preview.message_type !== 'text' ? (
                <span>{`[${msg.reply_preview.message_type}]`}</span>
              ) : (
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {msg.reply_preview.content || '(message)'}
                </span>
              )
            ) : (
              <span>↪ Replying to a message</span>
            )}
          </div>
        )}

        {msg.template_name && (
          <p style={{ fontSize: 10, color: '#856404', background: '#FFF3CD', borderRadius: 4, padding: '2px 6px', margin: '0 0 5px', display: 'inline-block' }}>
            {msg.template_name}
          </p>
        )}

        {/* Media message display */}
        {isMedia && msg.media_url ? (
          <div style={{ marginBottom: 4 }}>
            {msg.message_type === 'image' ? (
              <div style={{ position: 'relative', display: 'inline-block' }}>
                <img
                  src={msg.media_url}
                  alt="Image"
                  style={{ maxWidth: '100%', maxHeight: 220, borderRadius: 8, display: 'block' }}
                />
                <DownloadBtn style={{ position: 'absolute', top: 6, right: 6 }} />
              </div>
            ) : msg.message_type === 'audio' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <audio
                  controls
                  src={msg.media_url}
                  style={{ maxWidth: '100%', borderRadius: 8, outline: 'none', height: 36, flex: 1 }}
                />
                <DownloadBtn />
              </div>
            ) : msg.message_type === 'video' ? (
              <div style={{ position: 'relative', display: 'inline-block' }}>
                <video
                  controls
                  preload="metadata"
                  src={msg.media_url}
                  style={{ maxWidth: '100%', maxHeight: 260, borderRadius: 8, display: 'block', background: '#000' }}
                />
                <DownloadBtn style={{ position: 'absolute', top: 6, right: 6 }} />
              </div>
            ) : (
              /* document */
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, background: 'rgba(0,0,0,0.05)', borderRadius: 8, padding: '8px 10px' }}>
                <span style={{ fontSize: 20 }}>
                  {msg.message_type === 'video' ? <Video size={20} /> : <FileText size={20} />}
                </span>
                <span style={{ fontSize: 12, color: ds.dark, fontWeight: 500, flex: 1, wordBreak: 'break-all' }}>
                  {msg.message_type === 'document'
                    ? (msg.content && msg.content !== '[Document]' ? msg.content : 'Document')
                    : 'Video'}
                </span>
                <DownloadBtn />
              </div>
            )}
          </div>
        ) : editing ? (
          <div style={{ minWidth: 220 }}>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit() } if (e.key === 'Escape') setEditing(false) }}
              rows={2}
              maxLength={2000}
              autoFocus
              style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', border: `1.5px solid ${ds.border}`, borderRadius: 8, padding: '6px 8px', fontSize: 13, fontFamily: ds.fontDm, outline: 'none' }}
            />
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 5 }}>
              <button onClick={() => setEditing(false)} style={{ background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 8, padding: '4px 10px', fontSize: 12, cursor: 'pointer', color: ds.gray }}>Cancel</button>
              <button onClick={saveEdit} disabled={busy || !draft.trim()} style={{ background: ds.teal, border: 'none', borderRadius: 8, padding: '4px 12px', fontSize: 12, cursor: busy ? 'wait' : 'pointer', color: '#fff', fontWeight: 600 }}>{busy ? '…' : 'Save'}</button>
            </div>
          </div>
        ) : (
          <p style={{ fontSize: 13, color: msg.deleted_at ? ds.gray : ds.dark, fontStyle: msg.deleted_at ? 'italic' : 'normal', margin: 0, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
            {msg.content || (isMedia ? '(Media)' : '(Empty)')}
          </p>
        )}
        {actErr && <div style={{ fontSize: 11.5, color: '#C0392B', marginTop: 4, fontFamily: ds.fontDm }}>{actErr}</div>}

        {!isOut && onRequestSuggestion && msg.content && (
          <button
            onClick={() => onRequestSuggestion(msg.id, msg.content)}
            title="Get a suggested reply from your knowledge base"
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.gray, fontSize: 11, padding: '3px 0 0', display: 'block', textAlign: 'left', opacity: 0.55, transition: 'opacity 0.15s', fontFamily: ds.fontDm }}
            onMouseEnter={e => e.currentTarget.style.opacity = '1'}
            onMouseLeave={e => e.currentTarget.style.opacity = '0.55'}
          >
            <span style={{display:'inline-flex',alignItems:'center',gap:4}}><Lightbulb size={11} />Suggest reply</span>
          </button>
        )}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: isOut ? 'space-between' : 'flex-end', gap: 4, marginTop: 4 }}>
          {isOut && (
            <span style={{
              fontSize:   9.5,
              fontFamily: ds.fontSyne,
              fontWeight: 600,
              color:      msg.sent_by_name ? ds.teal : ds.gray,
              flexShrink: 0,
            }}>
              {msg.sent_by_name ? `${msg.sent_by_name.split(' ')[0]}` : 'AI'}
            </span>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 10, color: ds.gray }}>{msg.edited_at && !msg.deleted_at ? 'Edited · ' : ''}{date} {time}</span>
            {isOut && <StatusTick status={msg.status} />}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Status tick ──────────────────────────────────────────────────────────────

function StatusTick({ status }) {
  if (!status || status === 'pending') return <Clock size={10} color={ds.gray} title='Pending' />
  if (status === 'sent')     return <span style={{ fontSize: 10, color: ds.gray }} title='Sent'>✓</span>
  if (status === 'delivered') return <span style={{ fontSize: 10, color: ds.gray }} title='Delivered'>✓✓</span>
  if (status === 'read')      return <span style={{ fontSize: 10, color: ds.teal }} title='Read'>✓✓</span>
  if (status === 'failed')    return <X size={10} color={ds.red} title='Failed' />
  return null
}

// ─── KB Suggestion Bar — AI-SUGGEST-1 ────────────────────────────────────────

function KBSuggestionBar({ suggestion, loading, onUse, onDismiss }) {
  if (loading) {
    return (
      <div style={{ flexShrink: 0, background: '#F0F7FF', borderTop: '1px solid #BFDBFE', padding: '9px 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 12, height: 12, border: '2px solid #BFDBFE', borderTopColor: '#3B82F6', borderRadius: '50%', animation: 'spin 0.7s linear infinite', flexShrink: 0 }} />
        <span style={{ fontSize: 12, color: '#1E40AF', fontFamily: ds.fontDm }}>Looking up knowledge base…</span>
      </div>
    )
  }

  if (!suggestion) return null

  if (suggestion.noResult) {
    return (
      <div style={{ flexShrink: 0, background: '#F9FAFB', borderTop: '1px solid #E5E7EB', padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: ds.gray, fontFamily: ds.fontDm }}><span style={{display:'inline-flex',alignItems:'center',gap:4}}><Lightbulb size={11} />No KB match found for this message.</span></span>
      </div>
    )
  }

  return (
    <div style={{ flexShrink: 0, background: '#F0F7FF', borderTop: '1px solid #BFDBFE', borderBottom: '1px solid #BFDBFE', padding: '9px 14px', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 10.5, fontWeight: 700, color: '#1E40AF', fontFamily: ds.fontSyne, marginBottom: 3 }}>
          <span style={{display:'inline-flex',alignItems:'center',gap:4}}><Lightbulb size={11} />KB · {suggestion.title}</span>
        </div>
        <div style={{ fontSize: 12, color: '#1E3A5F', fontFamily: ds.fontDm, lineHeight: 1.5, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical' }}>
          {suggestion.snippet}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, flexShrink: 0 }}>
        <button
          onClick={() => onUse(suggestion.snippet, suggestion.article_id, suggestion.msgId)}
          style={{ fontSize: 11, padding: '4px 10px', borderRadius: 20, border: 'none', background: '#3B82F6', color: '#fff', fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne, whiteSpace: 'nowrap' }}
        >
          Use this ↑
        </button>
        <button
          onClick={() => onDismiss(suggestion.article_id, suggestion.msgId)}
          style={{ fontSize: 11, padding: '4px 10px', borderRadius: 20, border: '1px solid #BFDBFE', background: '#fff', color: '#6B7280', fontWeight: 500, cursor: 'pointer', fontFamily: ds.fontSyne }}
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ totalUnread }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: 14, background: '#FAFCFD' }}>
      <div style={{ display:'flex', justifyContent:'center', marginBottom:0 }}><MessageCircle size={52} color={ds.teal} strokeWidth={1.2} /></div>
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
      style={{ padding: '0 14px', minHeight: 34, borderRadius: 999, border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: ds.fontSyne, background: active ? color : ds.light, color: active ? '#fff' : ds.gray, transition: 'all 0.15s', minHeight: 28 }}
    >
      {children}
    </button>
  )
}
