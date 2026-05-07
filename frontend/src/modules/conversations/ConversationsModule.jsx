/**
 * ConversationsModule.jsx — Unified Conversations inbox.
 *
 * Fixes applied in this version:
 *   - Real-time polling: thread refreshes every 5s, list every 15s
 *   - Conversation list auto-refresh: unread badges and order update live
 *   - Window status: fetched per thread (no more hardcoded windowOpen=true)
 *   - AI/Human mode indicator: thread header shows AI Active / Human Mode
 *   - Resume AI button: hands conversation back to AI with one click
 *   - Optimistic send: messages appear instantly after sending
 *   - ai_paused indicator: conversation rows show 👤 when human has taken over
 *
 * Layout:
 *   Desktop: two-panel (conversation list left, thread right)
 *   Mobile PWA: single panel — list by default, tap to open full-screen thread
 *
 * Pattern 51: full rewrite required for any future edit — never sed.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getConversations, getThreadStatus, resumeAI } from '../../services/conversations.service'
import { getLeadMessages, markLeadMessagesRead } from '../../services/leads.service'
import { getCustomerMessages, listTemplates } from '../../services/whatsapp.service'
import MessageComposer from '../whatsapp/MessageComposer'

// ─── Channel config ───────────────────────────────────────────────────────────

const CHANNEL = {
  whatsapp:  { label: 'WhatsApp',  icon: '💬', color: '#25D366', bg: '#E8F8EE' },
  instagram: { label: 'Instagram', icon: '📷', color: '#C13584', bg: '#FCE4EC' },
}

const THREAD_POLL_MS  = 5000   // refresh active thread every 5s
const LIST_POLL_MS    = 15000  // refresh conversation list every 15s

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

// ─── Main component ───────────────────────────────────────────────────────────

export default function ConversationsModule() {
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
  const [threadStatus, setThreadStatus]   = useState({ window_open: true, ai_paused: false })
  const [resuming, setResuming]           = useState(false)
  const threadRef                         = useRef(null)
  const isPollingRef                      = useRef(false)

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

  // Poll conversation list every 15s (silent — no loading spinner)
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
        if (active.contact_type === 'lead') {
          markLeadMessagesRead(active.contact_id).catch(() => {})
        }
        setConversations(prev =>
          prev.map(c => c.contact_id === active.contact_id ? { ...c, unread_count: 0 } : c)
        )
      })
      .catch(() => {})
      .finally(() => setMsgLoading(false))
  }, [active])

  // Load messages when active conversation changes (show spinner on first load)
  useEffect(() => {
    if (active) loadMessages(true)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll thread every 5s
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

  // Scroll to bottom when messages load
  useEffect(() => {
    if (threadRef.current && messages.length > 0) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages])

  // ── Fetch thread status (window_open + ai_paused) ──────────────────────
  const fetchThreadStatus = useCallback(() => {
    if (!active) return
    getThreadStatus(active.contact_type, active.contact_id)
      .then(res => setThreadStatus(res.data?.data ?? { window_open: true, ai_paused: false }))
      .catch(() => {})
  }, [active])

  useEffect(() => { fetchThreadStatus() }, [fetchThreadStatus])

  // ── Open a conversation ────────────────────────────────────────────────
  const openConversation = (conv) => {
    setActive(conv)
    setMessages([])
    setThreadStatus({ window_open: true, ai_paused: conv.ai_paused ?? false })
    if (isMobile) setPanel('thread')
  }

  // ── After sending a message ────────────────────────────────────────────
  const handleSent = () => {
    // Immediately re-fetch messages (message is in DB — no delay needed)
    loadMessages(false)
    // Refresh list and thread status after a short delay to reflect ai_paused change
    setTimeout(() => {
      loadConversations(true)
      fetchThreadStatus()
    }, 600)
  }

  // ── Resume AI ──────────────────────────────────────────────────────────
  const handleResumeAI = async () => {
    if (!active || resuming) return
    setResuming(true)
    try {
      await resumeAI(active.contact_type, active.contact_id)
      setThreadStatus(prev => ({ ...prev, ai_paused: false }))
      setConversations(prev =>
        prev.map(c => c.contact_id === active.contact_id ? { ...c, ai_paused: false } : c)
      )
    } catch {
      // silent — status will refresh on next poll
    } finally {
      setResuming(false)
    }
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
      threadRef={threadRef}
      onSent={handleSent}
      onResumeAI={handleResumeAI}
      resuming={resuming}
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

function ThreadPanel({ active, messages, loading, templates, threadStatus, threadRef, onSent, onResumeAI, resuming, onBack }) {
  const ch     = CHANNEL[active.channel] || CHANNEL.whatsapp
  const isLead = active.contact_type === 'lead'
  const { window_open: windowOpen, ai_paused: aiPaused } = threadStatus

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
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

        {/* AI / Human mode indicator */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
          {aiPaused ? (
            <>
              <span style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, background: '#FFF3E0', color: '#C05A00', fontWeight: 700, fontFamily: ds.fontSyne }}>
                👤 Human Mode
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
            <span style={{ fontSize: 10.5, padding: '2px 8px', borderRadius: 20, background: '#E8F8EE', color: '#27AE60', fontWeight: 700, fontFamily: ds.fontSyne }}>
              🤖 AI Active
            </span>
          )}
        </div>
      </div>

      {/* Message thread */}
      <div ref={threadRef} style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', background: '#ECE5DD', padding: '14px 14px 8px' }}>
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

      {/* Composer */}
      <div style={{ flexShrink: 0, borderTop: `1px solid ${ds.border}` }}>
        <MessageComposer
          {...(isLead ? { leadId: active.contact_id } : { customerId: active.contact_id })}
          windowOpen={windowOpen}
          templates={templates}
          onSent={onSent}
        />
      </div>
    </div>
  )
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

function Bubble({ msg }) {
  const isOut = msg.direction === 'outbound'
  const d     = msg.created_at ? new Date(msg.created_at) : null
  const time  = d ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
  const date  = d ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''

  return (
    <div style={{ display: 'flex', justifyContent: isOut ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
      <div style={{ maxWidth: '72%', background: isOut ? '#DCF8C6' : '#fff', border: `1px solid ${isOut ? '#B0DDB8' : ds.border}`, borderRadius: isOut ? '14px 14px 4px 14px' : '14px 14px 14px 4px', padding: '9px 12px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
        {msg.template_name && (
          <p style={{ fontSize: 10, color: '#856404', background: '#FFF3CD', borderRadius: 4, padding: '2px 6px', margin: '0 0 5px', display: 'inline-block' }}>
            📋 {msg.template_name}
          </p>
        )}
        <p style={{ fontSize: 13, color: ds.dark, margin: 0, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
          {msg.content || '(Media message)'}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4, marginTop: 4 }}>
          <span style={{ fontSize: 10, color: ds.gray }}>{date} {time}</span>
          {isOut && <StatusTick status={msg.status} />}
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
