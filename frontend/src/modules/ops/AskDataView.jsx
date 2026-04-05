/**
 * modules/ops/AskDataView.jsx
 * Ask-Your-Data — conversational AI interface — Phase 6B.
 *
 * Design:
 *   - Message thread grows upward from the input bar
 *   - User messages on the right, AI answers on the left
 *   - Example question chips to get started
 *   - Rate limit (429) handled with a clear, friendly message
 *   - AI responses rendered as plain text (no innerHTML — F4 not needed)
 *   - Max 1,000 characters enforced client-side (mirrors §11.2 server validation)
 *   - Send on Enter (Shift+Enter for newline)
 *
 * Security:
 *   - No innerHTML / dangerouslySetInnerHTML — plain text rendering (F4 safe)
 *   - Input length capped at 1,000 chars (§11.2)
 */

import { useState, useRef, useEffect } from 'react'
import { ds } from '../../utils/ds'

const MAX_QUESTION_LENGTH = 1000

const EXAMPLE_QUESTIONS = [
  'Which customers are at high churn risk?',
  'How many open support tickets do we have?',
  'What are our renewals due in the next 30 days?',
  'How many leads came in this week?',
  'What is our average NPS score?',
]

// ─── Message bubble ───────────────────────────────────────────────────────────

function Bubble({ role, content, isError }) {
  const isUser = role === 'user'
  return (
    <div style={{
      display:        'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom:   12,
      animation:      'fadeIn 0.2s ease',
    }}>
      {!isUser && (
        <div style={{
          width: 30, height: 30, borderRadius: '50%',
          background: ds.teal, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, marginRight: 8, marginTop: 2,
        }}>
          📊
        </div>
      )}
      <div style={{
        maxWidth:     '72%',
        background:   isUser ? ds.teal : (isError ? '#fff1f0' : ds.dark2),
        border:       isError ? '1px solid #fca5a5' : (isUser ? 'none' : '1px solid #1a2f3f'),
        borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
        padding:      '12px 16px',
        fontSize:     14,
        lineHeight:   1.6,
        color:        isUser ? 'white' : (isError ? '#b91c1c' : '#c8dde6'),
        whiteSpace:   'pre-wrap',
        wordBreak:    'break-word',
      }}>
        {content}
      </div>
    </div>
  )
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <div style={{
        width: 30, height: 30, borderRadius: '50%', background: ds.teal, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
      }}>
        📊
      </div>
      <div style={{ display: 'flex', gap: 4, padding: '10px 14px', background: ds.dark2, border: '1px solid #1a2f3f', borderRadius: '16px 16px 16px 4px' }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 7, height: 7, borderRadius: '50%', background: ds.teal,
            animation: `pulse 1.2s ${i * 0.2}s infinite`,
          }} />
        ))}
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function AskDataView({ onAsk }) {
  const [messages,  setMessages]  = useState([])
  const [input,     setInput]     = useState('')
  const [thinking,  setThinking]  = useState(false)
  const threadRef                  = useRef(null)
  const inputRef                   = useRef(null)

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages, thinking])

  const handleSend = async () => {
    const question = input.trim()
    if (!question || thinking) return
    if (question.length > MAX_QUESTION_LENGTH) return

    setMessages(prev => [...prev, { role: 'user', content: question }])
    setInput('')
    setThinking(true)

    try {
      const answer = await onAsk(question)
      setMessages(prev => [...prev, { role: 'assistant', content: answer }])
    } catch (err) {
      const status = err?.response?.status
      let errorMsg
      if (status === 429) {
        errorMsg = 'You\'ve reached the AI query limit (30 per hour). Please try again later.'
      } else if (status === 422) {
        errorMsg = 'Your question was too long. Please keep it under 1,000 characters.'
      } else {
        errorMsg = 'Something went wrong. Please try again.'
      }
      setMessages(prev => [...prev, { role: 'assistant', content: errorMsg, isError: true }])
    } finally {
      setThinking(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleExample = (q) => {
    if (thinking) return
    setInput(q)
    inputRef.current?.focus()
  }

  const handleClear = () => {
    setMessages([])
    setInput('')
    inputRef.current?.focus()
  }

  const charsLeft = MAX_QUESTION_LENGTH - input.length
  const isOverLimit = charsLeft < 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px - 54px)', padding: '0 28px 0' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 0 16px' }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 20, color: ds.dark, margin: 0 }}>
            Ask Your Data
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: '4px 0 0' }}>
            Ask any question about your business in plain English
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleClear}
            style={{
              background: 'none', border: '1px solid #dde4e8',
              borderRadius: 7, padding: '6px 12px', fontSize: 12,
              color: ds.gray, cursor: 'pointer', fontFamily: ds.fontDm,
            }}
          >
            Clear chat
          </button>
        )}
      </div>

      {/* ── Example questions (shown when no messages yet) ── */}
      {messages.length === 0 && (
        <div style={{ marginBottom: 20 }}>
          <p style={{ fontSize: 12, fontWeight: 600, color: '#4a7a8a', textTransform: 'uppercase', letterSpacing: '1px', margin: '0 0 10px' }}>
            Try asking…
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {EXAMPLE_QUESTIONS.map(q => (
              <button
                key={q}
                onClick={() => handleExample(q)}
                style={{
                  background: ds.dark2, border: '1px solid #1a2f3f',
                  borderRadius: 20, padding: '7px 14px',
                  fontSize: 12.5, color: '#7A9BAD',
                  cursor: 'pointer', fontFamily: ds.fontDm,
                  transition: 'all 0.15s',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => { e.target.style.borderColor = ds.teal; e.target.style.color = ds.teal }}
                onMouseLeave={e => { e.target.style.borderColor = '#1a2f3f'; e.target.style.color = '#7A9BAD' }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Message thread ── */}
      <div
        ref={threadRef}
        style={{
          flex:       1,
          overflowY:  'auto',
          paddingRight: 4,
          paddingBottom: 16,
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#3a5a6a' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 16, color: '#4a7a8a', margin: '0 0 8px' }}>
              Your operations data, answered instantly
            </p>
            <p style={{ fontSize: 13, color: '#3a5a6a', lineHeight: 1.6, maxWidth: 360, margin: '0 auto' }}>
              Ask anything about your leads, customers, tickets, renewals, or business health.
              Answers are scoped to your role.
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <Bubble key={i} role={msg.role} content={msg.content} isError={msg.isError} />
        ))}
        {thinking && <TypingIndicator />}
      </div>

      {/* ── Input bar ── */}
      <div style={{
        borderTop:  '1px solid #dde4e8',
        paddingTop: 14,
        paddingBottom: 16,
      }}>
        <div style={{
          display:      'flex',
          gap:          10,
          background:   ds.dark2,
          border:       `1.5px solid ${isOverLimit ? '#dc2626' : '#1a2f3f'}`,
          borderRadius: 12,
          padding:      '10px 14px',
          transition:   'border-color 0.2s',
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about your business data…"
            rows={1}
            style={{
              flex:       1,
              background: 'none',
              border:     'none',
              outline:    'none',
              resize:     'none',
              fontSize:   14,
              color:      '#c8dde6',
              fontFamily: ds.fontDm,
              lineHeight: 1.5,
              minHeight:  24,
              maxHeight:  120,
              overflowY:  'auto',
            }}
          />
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', justifyContent: 'space-between', gap: 4 }}>
            <span style={{ fontSize: 11, color: isOverLimit ? '#dc2626' : '#3a5a6a', whiteSpace: 'nowrap' }}>
              {charsLeft}
            </span>
            <button
              onClick={handleSend}
              disabled={thinking || !input.trim() || isOverLimit}
              style={{
                background:   (thinking || !input.trim() || isOverLimit) ? '#1a2f3f' : ds.teal,
                border:       'none',
                borderRadius: 8,
                width:        34,
                height:       34,
                display:      'flex',
                alignItems:   'center',
                justifyContent: 'center',
                cursor:       (thinking || !input.trim() || isOverLimit) ? 'not-allowed' : 'pointer',
                fontSize:     16,
                transition:   'background 0.2s',
                flexShrink:   0,
              }}
            >
              {thinking ? (
                <span style={{ display: 'inline-block', animation: 'spin 0.8s linear infinite', color: ds.teal }}>↻</span>
              ) : '→'}
            </button>
          </div>
        </div>
        <p style={{ fontSize: 11, color: '#3a5a6a', margin: '6px 0 0', lineHeight: 1.5 }}>
          Enter to send · Shift+Enter for new line · Answers are scoped to your role · 30 queries/hour
        </p>
      </div>
    </div>
  )
}
