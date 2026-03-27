/**
 * TemplateManager.jsx — WhatsApp template management.
 *
 * Shows all templates with Meta approval status.
 * Create form: name (snake_case), category, body, variables.
 * Edit: rejected templates only (meta_status === 'rejected') → resets to pending.
 *
 * Valid categories (from Tech Spec): marketing | utility | authentication
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  listTemplates,
  createTemplate,
  updateTemplate,
} from '../../services/whatsapp.service'

const CATEGORIES = ['marketing', 'utility', 'authentication']

const STATUS_STYLE = {
  pending:  { bg: '#FFF9E0', color: '#D4AC0D' },
  approved: { bg: '#E8F8EE', color: '#27AE60' },
  rejected: { bg: '#FFE8E8', color: '#C0392B' },
}

function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.pending
  return (
    <span style={{
      background: s.bg, color: s.color, borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 700, textTransform: 'capitalize',
    }}>
      {status}
    </span>
  )
}

const BLANK_FORM = { name: '', category: 'marketing', body: '', variables: '' }

export default function TemplateManager() {
  const [templates, setTemplates]   = useState([])
  const [loading, setLoading]       = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm]             = useState(BLANK_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [formErr, setFormErr]       = useState(null)
  const [editingId, setEditingId]   = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    listTemplates()
      .then(res => setTemplates(res.data?.data ?? []))
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  function startEdit(t) {
    setForm({
      name: t.name,
      category: t.category,
      body: t.body,
      variables: (t.variables || []).join(', '),
    })
    setEditingId(t.id)
    setShowCreate(true)
    setFormErr(null)
  }

  function cancelForm() {
    setShowCreate(false)
    setEditingId(null)
    setForm(BLANK_FORM)
    setFormErr(null)
  }

  async function handleSubmit() {
    setFormErr(null)
    if (!form.name.trim())     { setFormErr('Template name is required.'); return }
    if (!form.body.trim())     { setFormErr('Template body is required.'); return }
    if (!CATEGORIES.includes(form.category)) { setFormErr('Invalid category.'); return }

    const payload = {
      name: form.name.trim().toLowerCase().replace(/\s+/g, '_'),
      category: form.category,
      body: form.body.trim(),
      variables: form.variables
        ? form.variables.split(',').map(v => v.trim()).filter(Boolean)
        : [],
    }

    setSubmitting(true)
    try {
      if (editingId) {
        await updateTemplate(editingId, { body: payload.body, variables: payload.variables })
      } else {
        await createTemplate(payload)
      }
      cancelForm()
      load()
    } catch (err) {
      setFormErr(err.response?.data?.error?.message || 'Submission failed.')
    } finally {
      setSubmitting(false)
    }
  }

  const S = {
    wrap: { padding: 28 },
    header: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20,
    },
    title: { fontFamily: ds.fontHead, fontWeight: 700, fontSize: 18, color: ds.dark },
    addBtn: {
      padding: '9px 18px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    formCard: {
      background: '#fff', border: `1.5px solid ${ds.teal}`,
      borderRadius: 14, padding: '20px 24px', marginBottom: 20,
    },
    formTitle: { fontFamily: ds.fontHead, fontWeight: 700, fontSize: 14, color: ds.dark, marginBottom: 16 },
    label: {
      fontSize: 11, color: ds.gray, textTransform: 'uppercase',
      letterSpacing: '0.5px', fontWeight: 500, display: 'block', marginBottom: 5,
    },
    input: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 13px',
      fontSize: 13, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', marginBottom: 14,
    },
    textarea: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 13px',
      fontSize: 13, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', marginBottom: 14, minHeight: 100, resize: 'vertical',
    },
    select: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 13px',
      fontSize: 13, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', marginBottom: 14, background: '#fff',
    },
    row2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
    btnRow: { display: 'flex', gap: 8, marginTop: 4 },
    submitBtn: {
      padding: '9px 20px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: submitting ? 'not-allowed' : 'pointer',
      opacity: submitting ? 0.6 : 1,
    },
    cancelBtn: {
      padding: '9px 16px', background: '#EAF0F2', color: ds.dark,
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    errBox: {
      background: '#FFE8E8', color: '#C0392B', borderRadius: 7,
      padding: '8px 12px', fontSize: 12, marginBottom: 12,
    },
    tableWrap: {
      background: '#fff', border: `1px solid ${ds.border}`,
      borderRadius: 14, overflow: 'hidden',
    },
    th: {
      background: '#E0F4F6', color: '#015F6B', fontWeight: 600,
      padding: '11px 16px', textAlign: 'left',
      fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.6px',
    },
    td: {
      padding: '12px 16px', borderBottom: `1px solid ${ds.border}`,
      color: ds.dark, fontSize: 13,
    },
    editBtn: {
      padding: '5px 12px', background: '#FFF9E0', color: '#D4AC0D',
      border: 'none', borderRadius: 7, fontSize: 11.5, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    empty: { padding: 32, textAlign: 'center', color: ds.gray, fontSize: 13 },
    hint: {
      background: '#E0F4F6', border: `1px solid #B0DDD9`, borderRadius: 8,
      padding: '10px 14px', fontSize: 12.5, color: '#015F6B', marginBottom: 16,
    },
  }

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <div style={S.title}>WhatsApp Templates</div>
        {!showCreate && (
          <button style={S.addBtn} onClick={() => { setShowCreate(true); setEditingId(null); setForm(BLANK_FORM) }}>
            + New Template
          </button>
        )}
      </div>

      <div style={S.hint}>
        💡 Templates must be approved by Meta before use. Submitted templates show as <strong>Pending</strong>. Only <strong>Rejected</strong> templates can be edited and resubmitted.
      </div>

      {/* Create / Edit form */}
      {showCreate && (
        <div style={S.formCard}>
          <div style={S.formTitle}>{editingId ? 'Edit Rejected Template' : 'New Template'}</div>
          {formErr && <div style={S.errBox}>⚠ {formErr}</div>}

          <div style={S.row2}>
            <div>
              <label style={S.label}>Template Name (snake_case)</label>
              <input
                style={S.input}
                value={form.name}
                placeholder="e.g. renewal_reminder_14_days"
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                disabled={!!editingId}
              />
            </div>
            <div>
              <label style={S.label}>Category</label>
              <select
                style={S.select}
                value={form.category}
                onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
                disabled={!!editingId}
              >
                {CATEGORIES.map(c => (
                  <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
                ))}
              </select>
            </div>
          </div>

          <label style={S.label}>Body — use {`{{variable}}`} for dynamic fields</label>
          <textarea
            style={S.textarea}
            value={form.body}
            placeholder="Hello {{name}}, your subscription renews on {{date}}. Reply HELP for assistance."
            onChange={e => setForm(f => ({ ...f, body: e.target.value }))}
          />

          <label style={S.label}>Variables (comma-separated)</label>
          <input
            style={S.input}
            value={form.variables}
            placeholder="name, date"
            onChange={e => setForm(f => ({ ...f, variables: e.target.value }))}
          />

          <div style={S.btnRow}>
            <button style={S.submitBtn} onClick={handleSubmit} disabled={submitting}>
              {submitting ? 'Submitting…' : editingId ? 'Resubmit to Meta' : 'Submit to Meta'}
            </button>
            <button style={S.cancelBtn} onClick={cancelForm}>Cancel</button>
          </div>
        </div>
      )}

      {/* Templates table */}
      <div style={S.tableWrap}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['Name', 'Category', 'Body', 'Status', 'Actions'].map(h => (
                <th key={h} style={S.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={S.empty}>Loading…</td></tr>
            ) : templates.length === 0 ? (
              <tr><td colSpan={5} style={S.empty}>No templates yet. Create your first template above.</td></tr>
            ) : templates.map(t => (
              <tr key={t.id}>
                <td style={S.td}>
                  <code style={{ fontSize: 12, background: '#F0F4F5', padding: '2px 6px', borderRadius: 4 }}>
                    {t.name}
                  </code>
                </td>
                <td style={S.td}>{t.category}</td>
                <td style={{ ...S.td, maxWidth: 300, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {t.body}
                </td>
                <td style={S.td}><StatusBadge status={t.meta_status} /></td>
                <td style={S.td}>
                  {t.meta_status === 'rejected' && (
                    <button style={S.editBtn} onClick={() => startEdit(t)}>
                      ✏ Edit & Resubmit
                    </button>
                  )}
                  {t.meta_status === 'rejected' && t.rejection_reason && (
                    <div style={{ fontSize: 11, color: '#C0392B', marginTop: 4 }}>
                      {t.rejection_reason}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
