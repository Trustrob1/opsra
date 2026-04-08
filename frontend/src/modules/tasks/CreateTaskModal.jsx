/**
 * modules/tasks/CreateTaskModal.jsx
 * Manual task creation modal — Phase 7B.
 *
 * Props:
 *   onClose()     — close without creating
 *   onCreated()   — close and refresh after successful creation
 *
 * Pattern 12: org_id never in payload
 * Fields: title (required), description, due_at, priority, source_module
 * Backdrop click closes modal
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import { createTask } from '../../services/tasks.service'
import useAuthStore from '../../store/authStore'
import UserSelect   from '../../shared/UserSelect'

const PRIORITIES = ['critical', 'high', 'medium', 'low']
const MODULES    = [
  { value: '',          label: 'No module' },
  { value: 'leads',     label: 'Lead Command Center' },
  { value: 'whatsapp',  label: 'WhatsApp Engine' },
  { value: 'support',   label: 'Support Tickets' },
  { value: 'renewal',   label: 'Renewal & Upsell' },
  { value: 'ops',       label: 'Operations Intel' },
]

export default function CreateTaskModal({ onClose, onCreated }) {
  const isManager  = useAuthStore.getState().isManager()
  const [title,    setTitle]    = useState('')
  const [desc,     setDesc]     = useState('')
  const [dueAt,    setDueAt]    = useState('')
  const [priority, setPriority] = useState('medium')
  const [assignedTo, setAssignedTo] = useState('')
  const [module,   setModule]   = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const handleSubmit = async () => {
    if (!title.trim()) { setError('Title is required.'); return }
    if (title.length > 255) { setError('Title must be 255 characters or fewer.'); return }
    setLoading(true)
    setError(null)
    try {
      const payload = { title: title.trim(), priority }
      if (desc.trim())   payload.description   = desc.trim()
      if (dueAt)         payload.due_at         = new Date(`${dueAt}T09:00:00`).toISOString()
      if (module)        payload.source_module  = module
      if (isManager && assignedTo)  payload.assigned_to  = assignedTo
      // Pattern 12: org_id never sent — derived server-side
      await createTask(payload)
      onCreated?.()
    } catch (err) {
      const msg = err?.response?.data?.error?.message || 'Failed to create task.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') onClose()
  }

  return (
    <div
      onKeyDown={handleKeyDown}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'white', borderRadius: 14,
        width: '100%', maxWidth: 520,
        boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        animation: 'fadeIn 0.2s ease',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '20px 24px 0',
        }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: 0 }}>
            Create Task
          </h3>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: 20, color: '#9ca3af', cursor: 'pointer', lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px' }}>

          {/* Title */}
          <label style={labelStyle}>Title *</label>
          <input
            autoFocus
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="What needs to be done?"
            maxLength={255}
            style={{ ...inputStyle, marginBottom: 16 }}
          />

          {/* Description */}
          <label style={labelStyle}>Description</label>
          <textarea
            value={desc}
            onChange={e => setDesc(e.target.value)}
            placeholder="Optional notes or context…"
            rows={3}
            maxLength={5000}
            style={{ ...inputStyle, resize: 'none', marginBottom: 16 }}
          />

          {/* Due date + Priority row */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Due Date</label>
              <input
                type="date"
                value={dueAt}
                onChange={e => setDueAt(e.target.value)}
                style={{ ...inputStyle, cursor: 'pointer' }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Priority</label>
              <select
                value={priority}
                onChange={e => setPriority(e.target.value)}
                style={{ ...inputStyle, cursor: 'pointer' }}
              >
                {PRIORITIES.map(p => (
                  <option key={p} value={p}>
                    {p.charAt(0).toUpperCase() + p.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Module */}
          <label style={labelStyle}>Source Module</label>
          <select
            value={module}
            onChange={e => setModule(e.target.value)}
            style={{ ...inputStyle, marginBottom: 8 }}
          >
            {MODULES.map(m => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>

          {/* Assign To — managers only */}
          {isManager && (
            <>
              <label style={{ ...labelStyle, marginTop: 8 }}>Assign To</label>
              <UserSelect
                value={assignedTo}
                onChange={setAssignedTo}
                placeholder="— Assign to user —"
                style={{ ...inputStyle, marginBottom: 4 }}
              />
              <p style={{ fontSize: 11, color: '#6b7280', margin: '0 0 8px' }}>
                Leave blank to assign to yourself.
              </p>
            </>
          )}
          
          {error && (
            <p style={{ fontSize: 13, color: '#dc2626', margin: '8px 0 0' }}>⚠ {error}</p>
          )}
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', gap: 10, justifyContent: 'flex-end',
          padding: '0 24px 20px',
        }}>
          <button onClick={onClose} style={btnGhost}>Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={loading || !title.trim()}
            style={{
              background: (loading || !title.trim()) ? '#9ca3af' : ds.teal,
              color: 'white', border: 'none', borderRadius: 8,
              padding: '10px 20px', fontSize: 14, fontWeight: 600,
              fontFamily: ds.fontDm,
              cursor: (loading || !title.trim()) ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? 'Creating…' : 'Create Task'}
          </button>
        </div>
      </div>
    </div>
  )
}

const labelStyle = {
  display: 'block', fontSize: 11, fontWeight: 600,
  color: '#6b7280', textTransform: 'uppercase',
  letterSpacing: '0.6px', marginBottom: 6,
}

const inputStyle = {
  width: '100%', border: '1.5px solid #e5e7eb',
  borderRadius: 8, padding: '10px 12px', fontSize: 13.5,
  color: ds.dark, fontFamily: ds.fontDm, outline: 'none',
  transition: 'border-color 0.2s', boxSizing: 'border-box',
}

const btnGhost = {
  background: 'none', border: '1px solid #e5e7eb',
  borderRadius: 8, padding: '10px 16px',
  fontSize: 14, color: '#6b7280',
  fontFamily: ds.fontDm, cursor: 'pointer',
}
