/**
 * frontend/src/modules/admin/WhatsAppNumbers.jsx
 * AI-AGENT-1C — WhatsApp Numbers management panel.
 *
 * Manages the org's whatsapp_numbers rows: add a new number, view masked
 * credentials, edit label. Mode selection (Human/Bot/AI Agent) happens in
 * WASalesModeConfig.jsx, not here — this panel is about number inventory.
 *
 * Pattern 13: no react-router-dom.
 * Pattern 12: org_id never in payload.
 * All interactive elements >= 44px tap target.
 */
import { useState, useEffect, useCallback } from 'react'
import { getWhatsAppNumbers, addWhatsAppNumber, updateWhatsAppNumber } from '../../services/admin.service'
import { useIsMobile } from '../../hooks/useIsMobile'
import { ds } from '../../utils/ds'

const MODE_LABELS = {
  human: { label: 'Human', color: '#0e6c7e', bg: '#f0f9fa' },
  bot: { label: 'Bot', color: '#7c3aed', bg: '#f5f3ff' },
  ai_agent: { label: 'AI Agent', color: '#d97706', bg: '#fffbeb' },
}

const inputStyle = {
  width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: 8,
  padding: '9px 12px', fontSize: 13.5, fontFamily: 'inherit',
  color: ds.dark, boxSizing: 'border-box', minHeight: 44,
}

const EMPTY_FORM = { phone_id: '', access_token: '', waba_id: '', label: '', wa_sales_mode: 'human' }

function ModeBadge({ mode }) {
  const m = MODE_LABELS[mode] || MODE_LABELS.human
  return (
    <span style={{
      display: 'inline-block', padding: '3px 10px', borderRadius: 20,
      fontSize: 11, fontWeight: 700, letterSpacing: '0.3px',
      color: m.color, background: m.bg,
    }}>
      {m.label}
    </span>
  )
}

function NumberCard({ number, isMobile, onLabelSaved }) {
  const [editing, setEditing] = useState(false)
  const [label, setLabel]     = useState(number.label)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  async function handleSave() {
    if (!label.trim()) { setError('Label is required'); return }
    setSaving(true)
    setError('')
    try {
      await updateWhatsAppNumber(number.id, { label: label.trim() })
      onLabelSaved(number.id, label.trim())
      setEditing(false)
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError((typeof detail === 'object' ? detail?.message : detail) ?? 'Failed to save label.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      border: `1.5px solid ${ds.border}`, borderRadius: 12,
      padding: isMobile ? 14 : '16px 18px', marginBottom: 10, background: 'white',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {editing ? (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
              <input
                type="text" value={label} onChange={e => setLabel(e.target.value)}
                maxLength={100} style={{ ...inputStyle, maxWidth: 220 }}
              />
              <button
                type="button" onClick={handleSave} disabled={saving}
                style={{
                  minHeight: 40, padding: '0 14px', borderRadius: 8, border: 'none',
                  background: ds.teal, color: 'white', fontSize: 12.5, fontWeight: 600,
                  cursor: saving ? 'not-allowed' : 'pointer',
                }}
              >
                {saving ? '…' : 'Save'}
              </button>
              <button
                type="button" onClick={() => { setEditing(false); setLabel(number.label) }}
                style={{
                  minHeight: 40, padding: '0 12px', borderRadius: 8,
                  border: `1.5px solid ${ds.border}`, background: 'white',
                  color: ds.gray, fontSize: 12.5, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <p style={{
              fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14.5,
              color: ds.dark, margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 8,
            }}>
              {number.label}
              {number.is_primary && (
                <span style={{ fontSize: 10, fontWeight: 600, color: ds.gray }}>· Primary</span>
              )}
              <button
                type="button" onClick={() => setEditing(true)}
                style={{
                  border: 'none', background: 'none', color: ds.teal,
                  fontSize: 11.5, fontWeight: 600, cursor: 'pointer', padding: 0,
                }}
              >
                Edit
              </button>
            </p>
          )}
          <p style={{ fontSize: 12, color: ds.gray, margin: '0 0 2px', fontFamily: 'monospace' }}>
            Phone ID: {number.phone_id}
          </p>
          <p style={{ fontSize: 12, color: ds.gray, margin: 0, fontFamily: 'monospace' }}>
            Token: {number.access_token_masked}
          </p>
        </div>
        <ModeBadge mode={number.wa_sales_mode} />
      </div>
      {error && <p style={{ color: ds.red, fontSize: 12, margin: '8px 0 0' }}>⚠ {error}</p>}
    </div>
  )
}

export default function WhatsAppNumbers() {
  const isMobile = useIsMobile()
  const [numbers, setNumbers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm]       = useState(EMPTY_FORM)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  const load = useCallback(() => {
    setLoading(true)
    getWhatsAppNumbers()
      .then(data => setNumbers(data || []))
      .catch(() => setError('Could not load WhatsApp numbers.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  function handleLabelSaved(id, newLabel) {
    setNumbers(prev => prev.map(n => n.id === id ? { ...n, label: newLabel } : n))
  }

  async function handleAdd() {
    if (!form.phone_id.trim() || !form.access_token.trim() || !form.waba_id.trim() || !form.label.trim()) {
      setError('All fields are required.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const created = await addWhatsAppNumber(form)
      setNumbers(prev => [...prev, created])
      setForm(EMPTY_FORM)
      setShowAdd(false)
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError((typeof detail === 'object' ? detail?.message : detail) ?? 'Failed to add number.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          border: `4px solid ${ds.teal}`, borderTopColor: 'transparent',
          animation: 'wanumspin 0.7s linear infinite',
        }} />
        <style>{'@keyframes wanumspin { to { transform: rotate(360deg); } }'}</style>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: isMobile ? 16 : 20,
      }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: isMobile ? 15 : 17, color: '#0f172a', margin: 0 }}>
            WhatsApp Numbers
          </h2>
          <p style={{ fontSize: isMobile ? 12 : 13, color: '#64748b', margin: '3px 0 0' }}>
            Manage the WhatsApp numbers connected to this org
          </p>
        </div>
        {!showAdd && (
          <button
            type="button" onClick={() => setShowAdd(true)}
            style={{
              minHeight: 44, padding: '0 16px', borderRadius: 8, border: 'none',
              background: ds.teal, color: 'white', fontSize: 13, fontWeight: 600,
              fontFamily: ds.fontSyne, cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >
            + Add Number
          </button>
        )}
      </div>

      {error && !showAdd && <p style={{ color: ds.red, fontSize: 13, marginBottom: 12 }}>⚠ {error}</p>}

      {showAdd && (
        <div style={{
          border: `1.5px solid ${ds.border}`, borderRadius: 12,
          padding: isMobile ? 14 : 18, marginBottom: 16, background: '#f8fafc',
        }}>
          <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13.5, color: ds.dark, margin: '0 0 12px' }}>
            Add a new number
          </p>
          <div style={{ display: 'grid', gap: 10, marginBottom: 10 }}>
            <input
              type="text" placeholder="Label (e.g. Secondary Sales Line)"
              value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
              maxLength={100} style={inputStyle}
            />
            <input
              type="text" placeholder="Phone Number ID"
              value={form.phone_id} onChange={e => setForm(f => ({ ...f, phone_id: e.target.value }))}
              style={inputStyle}
            />
            <input
              type="password" placeholder="Access Token"
              value={form.access_token} onChange={e => setForm(f => ({ ...f, access_token: e.target.value }))}
              style={inputStyle}
            />
            <input
              type="text" placeholder="WABA ID"
              value={form.waba_id} onChange={e => setForm(f => ({ ...f, waba_id: e.target.value }))}
              style={inputStyle}
            />
            <select
              value={form.wa_sales_mode}
              onChange={e => setForm(f => ({ ...f, wa_sales_mode: e.target.value }))}
              style={{ ...inputStyle, cursor: 'pointer' }}
            >
              <option value="human">Human</option>
              <option value="bot">Bot</option>
              <option value="ai_agent">AI Agent</option>
            </select>
          </div>
          {form.wa_sales_mode === 'ai_agent' && (
            <p style={{ fontSize: 12, color: '#92400e', background: '#fffbeb', padding: '8px 10px', borderRadius: 8, margin: '0 0 10px' }}>
              AI Agent mode requires qualifying criteria to already be set in AI Agent Settings, or this will be rejected.
            </p>
          )}
          {error && <p style={{ color: ds.red, fontSize: 12, margin: '0 0 10px' }}>⚠ {error}</p>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button" onClick={handleAdd} disabled={saving}
              style={{
                minHeight: 44, padding: '0 18px', borderRadius: 8, border: 'none',
                background: saving ? '#9ca3af' : ds.teal, color: 'white',
                fontSize: 13, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer',
              }}
            >
              {saving ? 'Adding…' : 'Add Number'}
            </button>
            <button
              type="button"
              onClick={() => { setShowAdd(false); setForm(EMPTY_FORM); setError('') }}
              style={{
                minHeight: 44, padding: '0 16px', borderRadius: 8,
                border: `1.5px solid ${ds.border}`, background: 'white',
                color: ds.gray, fontSize: 13, cursor: 'pointer',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {numbers.length === 0 && !showAdd ? (
        <div style={{
          textAlign: 'center', padding: '48px 24px', border: `1.5px dashed ${ds.border}`, borderRadius: 12,
        }}>
          <p style={{ fontSize: 14, color: ds.gray, margin: 0 }}>
            No WhatsApp numbers connected yet. Add one to get started.
          </p>
        </div>
      ) : (
        numbers.map(n => (
          <NumberCard key={n.id} number={n} isMobile={isMobile} onLabelSaved={handleLabelSaved} />
        ))
      )}
    </div>
  )
}
