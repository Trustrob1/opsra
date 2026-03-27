/**
 * BroadcastManager.jsx — WhatsApp broadcast management.
 *
 * State machine enforced in service layer:
 *   draft → scheduled (future date) | sending (immediate)
 *   draft | scheduled → cancelled
 *
 * Shows: broadcast list table, create form, approve/cancel actions.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  listBroadcasts,
  createBroadcast,
  approveBroadcast,
  cancelBroadcast,
  listTemplates,
} from '../../services/whatsapp.service'

const STATUS_STYLE = {
  draft:      { bg: '#EAF0F2', color: ds.gray },
  scheduled:  { bg: '#E8F0FF', color: '#3450A4' },
  sending:    { bg: '#FFF9E0', color: '#D4AC0D' },
  sent:       { bg: '#E8F8EE', color: '#27AE60' },
  cancelled:  { bg: '#FFE8E8', color: '#C0392B' },
}
function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.draft
  return (
    <span style={{
      background: s.bg, color: s.color, borderRadius: 20, padding: '3px 10px',
      fontSize: 11, fontWeight: 700, textTransform: 'capitalize',
    }}>
      {status}
    </span>
  )
}

const BLANK = { name: '', template_id: '', scheduled_at: '' }

export default function BroadcastManager() {
  const [broadcasts, setBroadcasts]   = useState([])
  const [templates, setTemplates]     = useState([])
  const [loading, setLoading]         = useState(true)
  const [showCreate, setShowCreate]   = useState(false)
  const [form, setForm]               = useState(BLANK)
  const [submitting, setSubmitting]   = useState(false)
  const [formErr, setFormErr]         = useState(null)
  const [actionErr, setActionErr]     = useState({})

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      listBroadcasts(),
      listTemplates(),
    ]).then(([bRes, tRes]) => {
      setBroadcasts(bRes.data?.data?.items ?? [])
      setTemplates(tRes.data?.data ?? [])
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function handleCreate() {
    setFormErr(null)
    if (!form.name.trim())      { setFormErr('Name is required.'); return }
    if (!form.template_id)      { setFormErr('Please select a template.'); return }

    const payload = {
      name: form.name.trim(),
      template_id: form.template_id,
      segment_filter: {},
    }
    if (form.scheduled_at) payload.scheduled_at = new Date(form.scheduled_at).toISOString()

    setSubmitting(true)
    try {
      await createBroadcast(payload)
      setShowCreate(false)
      setForm(BLANK)
      load()
    } catch (err) {
      setFormErr(err.response?.data?.error?.message || 'Failed to create broadcast.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleApprove(id) {
    setActionErr(e => ({ ...e, [id]: null }))
    try {
      await approveBroadcast(id)
      load()
    } catch (err) {
      setActionErr(e => ({ ...e, [id]: err.response?.data?.error?.message || 'Action failed.' }))
    }
  }

  async function handleCancel(id) {
    if (!window.confirm('Cancel this broadcast?')) return
    setActionErr(e => ({ ...e, [id]: null }))
    try {
      await cancelBroadcast(id)
      load()
    } catch (err) {
      setActionErr(e => ({ ...e, [id]: err.response?.data?.error?.message || 'Action failed.' }))
    }
  }

  const approvedTemplates = templates.filter(t => t.meta_status === 'approved')

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
    formTitle: { fontFamily: ds.fontHead, fontWeight: 700, fontSize: 14, color: ds.dark, marginBottom: 14 },
    label: {
      fontSize: 11, color: ds.gray, textTransform: 'uppercase',
      letterSpacing: '0.5px', fontWeight: 500, display: 'block', marginBottom: 5,
    },
    input: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 13px',
      fontSize: 13, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', marginBottom: 14,
    },
    select: {
      border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 13px',
      fontSize: 13, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', marginBottom: 14, background: '#fff',
    },
    hint: {
      fontSize: 12, color: ds.gray, marginBottom: 14,
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
      color: ds.dark, fontSize: 13, verticalAlign: 'top',
    },
    approveBtn: {
      padding: '5px 12px', background: '#E8F8EE', color: '#27AE60',
      border: 'none', borderRadius: 7, fontSize: 11.5, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer', marginRight: 6,
    },
    cancelActionBtn: {
      padding: '5px 12px', background: '#FFE8E8', color: '#C0392B',
      border: 'none', borderRadius: 7, fontSize: 11.5, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    empty: { padding: 32, textAlign: 'center', color: ds.gray, fontSize: 13 },
    statChip: {
      fontSize: 11.5, color: ds.gray,
      display: 'flex', gap: 12, marginTop: 4, flexWrap: 'wrap',
    },
  }

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <div style={S.title}>Broadcasts</div>
        {!showCreate && (
          <button style={S.addBtn} onClick={() => setShowCreate(true)}>
            + New Broadcast
          </button>
        )}
      </div>

      {/* Create form */}
      {showCreate && (
        <div style={S.formCard}>
          <div style={S.formTitle}>New Broadcast</div>
          {formErr && <div style={S.errBox}>⚠ {formErr}</div>}

          <div style={S.row2}>
            <div>
              <label style={S.label}>Broadcast Name</label>
              <input
                style={S.input}
                value={form.name}
                placeholder="e.g. May Feature Update"
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label style={S.label}>Template (approved only)</label>
              <select
                style={S.select}
                value={form.template_id}
                onChange={e => setForm(f => ({ ...f, template_id: e.target.value }))}
              >
                <option value="">— Select template —</option>
                {approvedTemplates.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              {approvedTemplates.length === 0 && (
                <div style={{ fontSize: 11, color: '#C0392B', marginTop: -10, marginBottom: 8 }}>
                  No approved templates. Create and get a template approved first.
                </div>
              )}
            </div>
          </div>

          <label style={S.label}>Schedule (optional — leave blank to send immediately on approval)</label>
          <input
            style={S.input}
            type="datetime-local"
            value={form.scheduled_at}
            onChange={e => setForm(f => ({ ...f, scheduled_at: e.target.value }))}
          />

          <div style={S.hint}>
            💡 Broadcast stays in <strong>Draft</strong> until approved. If no schedule is set, approving sends immediately.
          </div>

          <div style={S.btnRow}>
            <button style={S.submitBtn} onClick={handleCreate} disabled={submitting}>
              {submitting ? 'Creating…' : 'Save as Draft'}
            </button>
            <button style={S.cancelBtn} onClick={() => { setShowCreate(false); setForm(BLANK); setFormErr(null) }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Broadcasts table */}
      <div style={S.tableWrap}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['Name', 'Template', 'Status', 'Scheduled', 'Recipients / Delivered / Read', 'Actions'].map(h => (
                <th key={h} style={S.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} style={S.empty}>Loading…</td></tr>
            ) : broadcasts.length === 0 ? (
              <tr><td colSpan={6} style={S.empty}>No broadcasts yet.</td></tr>
            ) : broadcasts.map(b => (
              <tr key={b.id}>
                <td style={S.td}><strong>{b.name}</strong></td>
                <td style={{ ...S.td, fontSize: 12 }}>
                  <code style={{ background: '#F0F4F5', padding: '2px 6px', borderRadius: 4 }}>
                    {b.template_id}
                  </code>
                </td>
                <td style={S.td}><StatusBadge status={b.status} /></td>
                <td style={{ ...S.td, fontSize: 12, color: ds.gray }}>
                  {b.scheduled_at ? new Date(b.scheduled_at).toLocaleString() : '—'}
                </td>
                <td style={S.td}>
                  <div style={S.statChip}>
                    <span>👥 {b.recipient_count ?? 0}</span>
                    <span>✓ {b.delivered_count ?? 0}</span>
                    <span>👁 {b.read_count ?? 0}</span>
                  </div>
                </td>
                <td style={S.td}>
                  {b.status === 'draft' && (
                    <>
                      <button style={S.approveBtn} onClick={() => handleApprove(b.id)}>
                        ✓ Approve
                      </button>
                      <button style={S.cancelActionBtn} onClick={() => handleCancel(b.id)}>
                        ✕ Cancel
                      </button>
                    </>
                  )}
                  {b.status === 'scheduled' && (
                    <button style={S.cancelActionBtn} onClick={() => handleCancel(b.id)}>
                      ✕ Cancel
                    </button>
                  )}
                  {actionErr[b.id] && (
                    <div style={{ fontSize: 11, color: '#C0392B', marginTop: 4 }}>
                      ⚠ {actionErr[b.id]}
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
