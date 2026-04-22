/**
 * TicketCreateModal.jsx
 * Create a new support ticket.
 * AI triage (Sonnet) runs server-side — UI provides content + optional overrides.
 *
 * Props:
 *   onClose()    — close without creating
 *   onCreated()  — close and refresh after creation
 *   customerId   — optional UUID: links ticket to a customer record
 *   leadId       — optional UUID: links ticket to a lead record
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { createTicket } from '../../services/support.service'
import { getTicketCategories } from '../../services/admin.service'

const DEFAULT_CATEGORIES = ['technical_bug', 'billing', 'feature_question', 'onboarding_help', 'account_access', 'hardware']
const URGENCIES  = ['critical', 'high', 'medium', 'low']
const AI_MODES   = ['draft_review', 'auto', 'human_only']

export default function TicketCreateModal({ onClose, onCreated, customerId, leadId }) {
  const [form, setForm]           = useState({ content: '', ai_handling_mode: 'draft_review' })
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
  const [categories, setCategories] = useState(
    DEFAULT_CATEGORIES.map(k => ({ key: k, label: k.replace(/_/g, ' '), enabled: true }))
  )

  useEffect(() => {
    getTicketCategories()
      .then(data => {
        const cats = data?.categories
        if (Array.isArray(cats) && cats.length > 0) setCategories(cats)
      })
      .catch(() => {}) // fallback to defaults
  }, [])

  function set(key, val) {
    setForm(f => ({ ...f, [key]: val || undefined }))
  }

  async function handleSubmit() {
    if (!form.content?.trim()) { setError('Problem description is required'); return }
    setLoading(true)
    setError(null)
    try {
      // Strip empty optional fields — org_id never sent (Pattern 12)
      const payload = {}
      if (form.content)          payload.content          = form.content.trim()
      if (form.category)         payload.category         = form.category
      if (form.urgency)          payload.urgency          = form.urgency
      if (form.title)            payload.title            = form.title.trim()
      if (form.ai_handling_mode) payload.ai_handling_mode = form.ai_handling_mode
      // Link to customer or lead when opened from a profile page
      if (customerId)            payload.customer_id      = customerId
      if (leadId)                payload.lead_id          = leadId
      await createTicket(payload)
      onCreated()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={overlay}>
      <div style={modal}>
        <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: 20, color: ds.dark, marginBottom: 4 }}>
          New Support Ticket
        </div>
        <div style={{ fontSize: 13, color: ds.gray, marginBottom: 22 }}>
          AI will classify and draft a first-touch reply automatically.
        </div>

        <label style={lbl}>Problem Description *</label>
        <textarea
          value={form.content || ''}
          onChange={e => set('content', e.target.value)}
          placeholder="Describe the customer's issue in detail…"
          rows={4}
          style={{ ...inp, resize: 'vertical' }}
        />

        <label style={lbl}>Title (optional — AI will generate if blank)</label>
        <input
          value={form.title || ''}
          onChange={e => set('title', e.target.value)}
          placeholder="Brief issue summary"
          style={inp}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <div>
            <label style={lbl}>Category (optional)</label>
            <select value={form.category || ''} onChange={e => set('category', e.target.value)} style={inp}>
              <option value="">AI will classify</option>
              {categories.filter(c => c.enabled !== false).map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <div>
            <label style={lbl}>Urgency (optional)</label>
            <select value={form.urgency || ''} onChange={e => set('urgency', e.target.value)} style={inp}>
              <option value="">AI will assess</option>
              {URGENCIES.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
        </div>

        <label style={lbl}>AI Handling Mode</label>
        <select
          value={form.ai_handling_mode || 'draft_review'}
          onChange={e => set('ai_handling_mode', e.target.value)}
          style={{ ...inp, marginBottom: 20 }}
        >
          {AI_MODES.map(m => (
            <option key={m} value={m}>
              {m === 'draft_review' ? 'Draft Review — AI drafts, human approves'
               : m === 'auto'      ? 'Auto — AI sends immediately'
               :                     'Human Only — No AI involvement'}
            </option>
          ))}
        </select>

        {error && <div style={{ color: ds.red, fontSize: 13, marginBottom: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={btnOutline}>Cancel</button>
          <button onClick={handleSubmit} disabled={loading} style={btnPrimary}>
            {loading ? 'Creating…' : 'Create Ticket'}
          </button>
        </div>
      </div>
    </div>
  )
}

const overlay = {
  position: 'fixed', inset: 0, background: 'rgba(13,27,42,0.55)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
}
const modal = {
  background: '#fff', borderRadius: 16, padding: 32,
  width: '100%', maxWidth: 560,
  boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
  maxHeight: '90vh', overflowY: 'auto',
}
const lbl = {
  display: 'block', fontSize: 12, fontWeight: 500, color: ds.gray,
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 6,
}
const inp = {
  width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: 9,
  padding: '11px 14px', fontSize: 13.5, color: ds.dark,
  fontFamily: 'DM Sans, sans-serif', outline: 'none',
  boxSizing: 'border-box', marginBottom: 14, background: '#fff',
}
const btnPrimary = {
  background: ds.teal, color: '#fff', border: 'none',
  borderRadius: 9, padding: '10px 22px', fontSize: 13,
  fontWeight: 600, cursor: 'pointer', fontFamily: 'DM Sans, sans-serif',
}
const btnOutline = {
  background: '#fff', color: ds.dark, border: `1.5px solid ${ds.border}`,
  borderRadius: 9, padding: '10px 18px', fontSize: 13,
  fontWeight: 500, cursor: 'pointer', fontFamily: 'DM Sans, sans-serif',
}
