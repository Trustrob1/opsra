/**
 * frontend/src/modules/assistant/AriaPanel.jsx
 * ----------------------------------------------
 * Aria AI Assistant slide-in panel (M01-10b).
 *
 * Fixed-position overlay, slides in from the right.
 * Pattern 26 — stays mounted (display:none) when closed.
 * z-index above all content.
 *
 * Props:
 *   open        {boolean}   Controls visibility
 *   onClose     {function}  Close the panel
 *   briefing    {string|null} Pre-generated briefing text (if any)
 *   onBadgeClear {function} Called after briefing is seen/dismissed
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { ds } from '../../utils/ds'
import BriefingCard from './BriefingCard'
import {
  markBriefingSeen,
  getAssistantHistory,
  streamAssistantMessage,
} from '../../services/assistant.service'

export default function AriaPanel({ open, onClose, briefing, onBadgeClear }) {
  const [messages,      setMessages]      = useState([])
  const [input,         setInput]         = useState('')
  const [streaming,     setStreaming]      = useState(false)
  const [showBriefing,  setShowBriefing]  = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [error,         setError]         = useState(null)
  const [showSuggestions, setShowSuggestions] = useState(false)

  const bottomRef   = useRef(null)
  const inputRef    = useRef(null)
  const abortRef    = useRef(null)

  // ── Load history on first open ──────────────────────────────────────────
  useEffect(() => {
    if (!open || historyLoaded) return
    ;(async () => {
      try {
        const history = await getAssistantHistory()
        setMessages(history)
        setHistoryLoaded(true)
      } catch {
        setHistoryLoaded(true)
      }
    })()
  }, [open, historyLoaded])

  // ── Show briefing when available ────────────────────────────────────────
  useEffect(() => {
    if (open && briefing) {
      setShowBriefing(true)
    }
  }, [open, briefing])

  // ── Scroll to bottom on new messages ───────────────────────────────────
  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, open, showBriefing])

  // ── Focus input when panel opens ────────────────────────────────────────
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 200)
    }
  }, [open])

  // ── Dismiss briefing ────────────────────────────────────────────────────
  const handleBriefingAccept = useCallback(async () => {
    setShowBriefing(false)
    onBadgeClear?.()
    try { await markBriefingSeen() } catch { /* non-fatal */ }
  }, [onBadgeClear])

  const handleBriefingDismiss = useCallback(async () => {
    setShowBriefing(false)
    onBadgeClear?.()
    try { await markBriefingSeen() } catch { /* non-fatal */ }
  }, [onBadgeClear])

  // ── Send message ─────────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return

    setInput('')
    setError(null)
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setStreaming(true)

    // Placeholder for streaming response
    setMessages(prev => [...prev, { role: 'assistant', content: '', _streaming: true }])

    try {
      const { stream, abort } = streamAssistantMessage(text)
      abortRef.current = abort

      let accumulated = ''
      for await (const chunk of stream) {
        if (chunk.done) break
        accumulated += chunk.text
        setMessages(prev => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?._streaming) {
            next[next.length - 1] = { role: 'assistant', content: accumulated, _streaming: true }
          }
          return next
        })
      }

      // Finalise — remove _streaming flag
      setMessages(prev => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last?._streaming) {
          next[next.length - 1] = { role: 'assistant', content: accumulated }
        }
        return next
      })

    } catch (err) {
      if (err?.name === 'AbortError') return
      setError('Unable to reach Aria. Please try again.')
      // Remove the placeholder
      setMessages(prev => prev.filter(m => !m._streaming))
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }, [input, streaming])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    // Pattern 26 — always mounted, hidden with display:none
    <div style={{ display: open ? 'flex' : 'none', flexDirection: 'column',
      position: 'fixed', top: 0, right: 0, bottom: 0,
      width: 380,
      background: '#0a1a24',
      borderLeft: '1px solid #1a3040',
      zIndex: ds.z.modal ?? 1100,
      boxShadow: '-8px 0 32px rgba(0,0,0,0.5)',
      fontFamily: ds.fontDm,
    }}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '14px 18px',
        borderBottom: '1px solid #1a3040',
        flexShrink: 0,
      }}>
        <div style={{
          width: 34, height: 34, borderRadius: '50%',
          background: `linear-gradient(135deg, ${ds.teal}, #0097a7)`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 16, flexShrink: 0,
        }}>
          ✦
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: 'white' }}>
            Aria
          </div>
          <div style={{ fontSize: 11, color: '#3a5a6a' }}>AI Operations Assistant</div>
        </div>

        {/* Clear chat */}
        {messages.length > 0 && (
          <button
            onClick={() => {
              setMessages([])
              setError(null)
              setShowBriefing(false)
            }}
            title="Clear chat"
            style={{
              background: 'none', border: '1px solid #1e3a4f', cursor: 'pointer',
              color: '#3a5a6a', fontSize: 11, padding: '4px 9px',
              borderRadius: 6, fontFamily: ds.fontDm, transition: 'all 0.15s',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#ef4444'; e.currentTarget.style.color = '#ef4444' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = '#1e3a4f'; e.currentTarget.style.color = '#3a5a6a' }}
          >
            Clear
          </button>
        )}

        {/* Close */}
        <button
          onClick={onClose}
          title="Close Aria"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#3a5a6a', fontSize: 18, padding: 4,
            borderRadius: 6, transition: 'color 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = '#7A9BAD'}
          onMouseLeave={e => e.currentTarget.style.color = '#3a5a6a'}
        >
          ✕
        </button>
      </div>

      {/* ── Message thread ──────────────────────────────────────────────── */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '16px 14px',
        display: 'flex', flexDirection: 'column', gap: 10,
      }}>

        {/* Briefing card at top */}
        {showBriefing && briefing && (
          <BriefingCard
            content={briefing}
            onAccept={handleBriefingAccept}
            onDismiss={handleBriefingDismiss}
          />
        )}

        {/* Empty state */}
        {!showBriefing && messages.length === 0 && !streaming && (
          <div style={{ textAlign: 'center', marginTop: 48, color: '#3a5a6a' }}>
            <div style={{ fontSize: 28, marginBottom: 10 }}>✦</div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13.5, color: '#7A9BAD', marginBottom: 4 }}>
              How can I help?
            </div>
            <div style={{ fontSize: 11 }}>
              Type a question or tap <span style={{ color: ds.teal }}>Suggestions</span> below
            </div>
          </div>
        )}

        {/* Messages */}
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} />
        ))}

        {/* Error */}
        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#fca5a5',
          }}>
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Suggestions tray — always available, collapsible ───────────── */}
      <div style={{ borderTop: '1px solid #1a3040', flexShrink: 0 }}>

        {/* Toggle button */}
        <button
          onClick={() => setShowSuggestions(s => !s)}
          style={{
            width: '100%', background: 'none', border: 'none',
            padding: '8px 14px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            cursor: 'pointer', color: showSuggestions ? ds.teal : '#3a5a6a',
            fontFamily: ds.fontDm, fontSize: 11, fontWeight: 600,
            letterSpacing: '0.5px', textTransform: 'uppercase',
            transition: 'color 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = ds.teal}
          onMouseLeave={e => e.currentTarget.style.color = showSuggestions ? ds.teal : '#3a5a6a'}
        >
          <span>💡 Suggested questions</span>
          <span style={{ fontSize: 10, transition: 'transform 0.2s', display: 'inline-block', transform: showSuggestions ? 'rotate(180deg)' : 'rotate(0deg)' }}>▲</span>
        </button>

        {/* Expandable suggestions */}
        {showSuggestions && (
          <div style={{ padding: '0 14px 12px', maxHeight: 260, overflowY: 'auto' }}>
            {[
              {
                label: '📊 Pipeline & Leads',
                items: [
                  'How many leads do I have right now?',
                  'Which leads are most urgent today?',
                  'Give me a summary of my pipeline',
                ],
              },
              {
                label: '✅ Tasks & Actions',
                items: [
                  'What tasks are overdue?',
                  'What should I focus on today?',
                  'Do I have any tasks due this week?',
                ],
              },
              {
                label: '🎫 Tickets & Support',
                items: [
                  'Are there any SLA breaches right now?',
                  'How many open tickets do we have?',
                ],
              },
              {
                label: '🔄 Renewals & Revenue',
                items: [
                  'Which subscriptions are renewing soon?',
                  'What commissions are pending approval?',
                ],
              },
            ].map(group => (
              <div key={group.label} style={{ marginBottom: 12 }}>
                <div style={{
                  fontSize: 9.5, fontWeight: 700, color: '#3a5a6a',
                  textTransform: 'uppercase', letterSpacing: '1px',
                  marginBottom: 5,
                }}>
                  {group.label}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {group.items.map(suggestion => (
                    <button
                      key={suggestion}
                      onClick={() => {
                        setShowSuggestions(false)
                        // Set input then immediately send via handleSend equivalent
                        setInput('')
                        setError(null)
                        setMessages(prev => [...prev, { role: 'user', content: suggestion }])
                        setStreaming(true)
                        setMessages(prev => [...prev, { role: 'assistant', content: '', _streaming: true }])
                        ;(async () => {
                          try {
                            const { stream, abort } = streamAssistantMessage(suggestion)
                            abortRef.current = abort
                            let accumulated = ''
                            for await (const chunk of stream) {
                              if (chunk.done) break
                              accumulated += chunk.text
                              setMessages(prev => {
                                const next = [...prev]
                                const last = next[next.length - 1]
                                if (last?._streaming) next[next.length - 1] = { role: 'assistant', content: accumulated, _streaming: true }
                                return next
                              })
                            }
                            setMessages(prev => {
                              const next = [...prev]
                              const last = next[next.length - 1]
                              if (last?._streaming) next[next.length - 1] = { role: 'assistant', content: accumulated }
                              return next
                            })
                          } catch (err) {
                            if (err?.name !== 'AbortError') {
                              setError('Unable to reach Aria. Please try again.')
                              setMessages(prev => prev.filter(m => !m._streaming))
                            }
                          } finally {
                            setStreaming(false)
                            abortRef.current = null
                          }
                        })()
                      }}
                      style={{
                        background:   '#0a1a24',
                        border:       '1px solid #1e3a4f',
                        borderRadius: 7,
                        padding:      '7px 11px',
                        textAlign:    'left',
                        fontSize:     12,
                        color:        '#7A9BAD',
                        fontFamily:   ds.fontDm,
                        cursor:       'pointer',
                        transition:   'all 0.15s',
                        lineHeight:   1.4,
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.borderColor = ds.teal
                        e.currentTarget.style.color = 'white'
                        e.currentTarget.style.background = '#0e2030'
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.borderColor = '#1e3a4f'
                        e.currentTarget.style.color = '#7A9BAD'
                        e.currentTarget.style.background = '#0a1a24'
                      }}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Input area ──────────────────────────────────────────────────── */}
      <div style={{
        padding: '10px 14px 16px',
        borderTop: '1px solid #1a3040',
        flexShrink: 0,
      }}>
        <div style={{
          display: 'flex', gap: 8, alignItems: 'flex-end',
          background: '#0e2030', border: '1.5px solid #1e3a4f',
          borderRadius: 10, padding: '8px 10px',
          transition: 'border-color 0.15s',
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask Aria…"
            rows={1}
            disabled={streaming}
            style={{
              flex: 1, background: 'none', border: 'none', outline: 'none',
              resize: 'none', overflow: 'hidden',
              fontSize: 13.5, color: 'white', fontFamily: ds.fontDm,
              lineHeight: 1.5,
              maxHeight: 120,
            }}
            onInput={e => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || streaming}
            style={{
              background:   (!input.trim() || streaming) ? '#1a3040' : ds.teal,
              border:       'none',
              borderRadius: 7,
              width:        32, height: 32,
              display:      'flex', alignItems: 'center', justifyContent: 'center',
              cursor:       (!input.trim() || streaming) ? 'default' : 'pointer',
              transition:   'background 0.15s',
              flexShrink:   0,
            }}
          >
            {streaming ? (
              <span style={{ width: 14, height: 14, border: '2px solid #7A9BAD', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
            ) : (
              <span style={{ color: 'white', fontSize: 14 }}>↑</span>
            )}
          </button>
        </div>
        <div style={{ fontSize: 10, color: '#2a4a5a', textAlign: 'center', marginTop: 6 }}>
          Powered by Claude Haiku · Enter to send
        </div>
      </div>
    </div>
  )
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }) {
  const isUser      = msg.role === 'user'
  const isStreaming = msg._streaming && !msg.content

  return (
    <div style={{
      display:    'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
    }}>
      {/* Aria avatar for assistant messages */}
      {!isUser && (
        <div style={{
          width: 24, height: 24, borderRadius: '50%',
          background: `linear-gradient(135deg, ${ds.teal}, #0097a7)`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, marginRight: 8, flexShrink: 0, marginTop: 2,
        }}>
          ✦
        </div>
      )}

      <div style={{
        maxWidth:     '78%',
        background:   isUser ? ds.teal : '#0e2030',
        border:       isUser ? 'none' : '1px solid #1a3040',
        borderRadius: isUser ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
        padding:      '9px 13px',
        fontSize:     13.5,
        lineHeight:   1.6,
        color:        isUser ? 'white' : '#c8dde8',
        fontFamily:   ds.fontDm,
        whiteSpace:   'pre-wrap',
        wordBreak:    'break-word',
      }}>
        {isStreaming ? (
          <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            {[0, 1, 2].map(i => (
              <span key={i} style={{
                width: 5, height: 5, borderRadius: '50%',
                background: '#3a5a6a',
                animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
              }} />
            ))}
          </span>
        ) : msg.content}
      </div>
    </div>
  )
}
