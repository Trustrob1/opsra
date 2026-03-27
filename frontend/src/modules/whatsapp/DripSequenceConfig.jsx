/**
 * DripSequenceConfig.jsx — Drip sequence configuration (Admin/Owner only).
 *
 * GET  /api/v1/drip-sequences       — loads current active sequence
 * PUT  /api/v1/drip-sequences       — replaces entire sequence (Admin only)
 *
 * Replace strategy: the PUT deactivates all existing messages and inserts the
 * new list. Order is controlled by sequence_order field.
 *
 * Non-owner users see a read-only view.
 *
 * Props:
 *   isOwner — bool  (from org.roles.template === 'owner')
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import { getDripSequence, updateDripSequence, listTemplates } from '../../services/whatsapp.service'

const BLANK_MSG = () => ({
  _key: Math.random().toString(36).slice(2),
  name: '',
  template_id: '',
  delay_days: 1,
  sequence_order: 1,
  business_types: [],
  is_active: true,
})

export default function DripSequenceConfig({ isOwner = false }) {
  const [sequence, setSequence]         = useState([])
  const [templates, setTemplates]       = useState([])
  const [loading, setLoading]           = useState(true)
  const [editing, setEditing]           = useState(false)
  const [draft, setDraft]               = useState([])
  const [saving, setSaving]             = useState(false)
  const [saveErr, setSaveErr]           = useState(null)
  const [saved, setSaved]               = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([getDripSequence(), listTemplates()])
      .then(([sRes, tRes]) => {
        setSequence(sRes.data?.data ?? [])
        setTemplates(tRes.data?.data ?? [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const approvedTemplates = templates.filter(t => t.meta_status === 'approved')

  function startEdit() {
    // pre-fill draft from current sequence, add _key for React reconciliation
    setDraft(sequence.map(m => ({
      ...m,
      _key: m.id || Math.random().toString(36).slice(2),
      business_types: m.business_types || [],
    })))
    setEditing(true)
    setSaveErr(null)
    setSaved(false)
  }

  function addMessage() {
    setDraft(d => [
      ...d,
      { ...BLANK_MSG(), sequence_order: d.length + 1 },
    ])
  }

  function removeMessage(key) {
    setDraft(d => d.filter(m => m._key !== key))
  }

  function updateMessage(key, field, value) {
    setDraft(d => d.map(m => m._key === key ? { ...m, [field]: value } : m))
  }

  async function handleSave() {
    setSaveErr(null)
    // Validate all rows
    for (let i = 0; i < draft.length; i++) {
      const m = draft[i]
      if (!m.name.trim())      { setSaveErr(`Row ${i + 1}: Name is required.`); return }
      if (!m.template_id)      { setSaveErr(`Row ${i + 1}: Template is required.`); return }
      if (!m.delay_days || m.delay_days < 0) { setSaveErr(`Row ${i + 1}: Delay must be ≥ 0.`); return }
    }

    const messages = draft.map((m, i) => ({
      name: m.name.trim(),
      template_id: m.template_id,
      delay_days: Number(m.delay_days),
      sequence_order: m.sequence_order ?? i + 1,
      business_types: m.business_types || [],
      is_active: true,
    }))

    setSaving(true)
    try {
      await updateDripSequence({ messages })
      setSaved(true)
      setEditing(false)
      load()
    } catch (err) {
      setSaveErr(err.response?.data?.error?.message || 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  const S = {
    wrap: { padding: 28 },
    header: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20,
    },
    title: { fontFamily: ds.fontHead, fontWeight: 700, fontSize: 18, color: ds.dark },
    editBtn: {
      padding: '9px 18px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    hint: {
      background: '#E0F4F6', border: `1px solid #B0DDD9`, borderRadius: 8,
      padding: '10px 14px', fontSize: 12.5, color: '#015F6B', marginBottom: 18,
    },
    adminHint: {
      background: '#FFF3CD', border: `1px solid #FFD97D`, borderRadius: 8,
      padding: '10px 14px', fontSize: 12.5, color: '#856404', marginBottom: 18,
    },
    seqCard: {
      background: '#fff', border: `1px solid ${ds.border}`, borderRadius: 14,
      overflow: 'hidden',
    },
    seqRow: {
      display: 'grid',
      gridTemplateColumns: '36px 2fr 2fr 80px 1fr 36px',
      gap: 10, padding: '14px 16px',
      borderBottom: `1px solid ${ds.border}`,
      alignItems: 'center',
    },
    seqHeader: {
      background: '#E0F4F6', padding: '10px 16px',
      display: 'grid',
      gridTemplateColumns: '36px 2fr 2fr 80px 1fr 36px',
      gap: 10, alignItems: 'center',
    },
    hdrCell: {
      fontSize: 11, color: '#015F6B', fontWeight: 600,
      textTransform: 'uppercase', letterSpacing: '0.6px',
    },
    input: {
      border: `1.5px solid ${ds.border}`, borderRadius: 8, padding: '8px 11px',
      fontSize: 12.5, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box',
    },
    select: {
      border: `1.5px solid ${ds.border}`, borderRadius: 8, padding: '8px 11px',
      fontSize: 12.5, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', background: '#fff',
    },
    numInput: {
      border: `1.5px solid ${ds.border}`, borderRadius: 8, padding: '8px 11px',
      fontSize: 12.5, fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box', textAlign: 'center',
    },
    removeBtn: {
      background: '#FFE8E8', color: '#C0392B', border: 'none',
      borderRadius: 7, cursor: 'pointer', fontWeight: 700, fontSize: 14,
      width: 28, height: 28, display: 'flex', alignItems: 'center',
      justifyContent: 'center',
    },
    orderNum: {
      width: 28, height: 28, background: '#E0F4F6', color: ds.teal,
      borderRadius: '50%', display: 'flex', alignItems: 'center',
      justifyContent: 'center', fontWeight: 700, fontSize: 13,
    },
    addRowBtn: {
      margin: '12px 16px', padding: '8px 16px', background: '#E0F4F6',
      color: ds.teal, border: `1px dashed ${ds.teal}`, borderRadius: 9,
      fontSize: 13, fontWeight: 600, fontFamily: ds.fontHead, cursor: 'pointer',
    },
    actionRow: {
      display: 'flex', gap: 8, padding: '14px 16px',
      borderTop: `1px solid ${ds.border}`, background: '#F9FDFD',
    },
    saveBtn: {
      padding: '9px 20px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: saving ? 'not-allowed' : 'pointer',
      opacity: saving ? 0.6 : 1,
    },
    cancelBtn: {
      padding: '9px 16px', background: '#EAF0F2', color: ds.dark,
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    errBox: {
      background: '#FFE8E8', color: '#C0392B', borderRadius: 7,
      padding: '8px 12px', fontSize: 12, margin: '0 16px 12px',
    },
    savedBox: {
      background: '#E8F8EE', color: '#27AE60', borderRadius: 7,
      padding: '8px 12px', fontSize: 12, marginBottom: 16,
    },
    viewRow: {
      display: 'flex', gap: 12, alignItems: 'center',
      padding: '14px 16px', borderBottom: `1px solid ${ds.border}`,
    },
    dot: {
      width: 10, height: 10, borderRadius: '50%',
      background: ds.teal, flexShrink: 0, marginTop: 2,
    },
    viewLabel: { fontSize: 11, color: ds.gray, marginBottom: 2 },
    viewVal: { fontSize: 13.5, color: ds.dark, fontWeight: 500 },
    empty: { padding: 32, textAlign: 'center', color: ds.gray, fontSize: 13 },
  }

  const rows = editing ? draft : sequence

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <div style={S.title}>Drip Sequence</div>
        {isOwner && !editing && (
          <button style={S.editBtn} onClick={startEdit}>
            ✏ Edit Sequence
          </button>
        )}
      </div>

      <div style={S.hint}>
        💡 The drip sequence sends automatic WhatsApp messages to new customers after conversion. Messages are sent in order by delay (days after conversion). Replacing the sequence deactivates all previous messages.
      </div>

      {!isOwner && (
        <div style={S.adminHint}>
          🔒 Only Owner/Admin can edit the drip sequence. Contact your administrator to make changes.
        </div>
      )}

      {saved && !editing && (
        <div style={S.savedBox}>✓ Drip sequence updated successfully.</div>
      )}

      {loading ? (
        <div style={{ padding: 32, color: ds.teal }}>Loading sequence…</div>
      ) : (
        <div style={S.seqCard}>
          {/* Header row */}
          <div style={S.seqHeader}>
            <div style={S.hdrCell}>#</div>
            <div style={S.hdrCell}>Name</div>
            <div style={S.hdrCell}>Template</div>
            <div style={S.hdrCell}>Delay (days)</div>
            <div style={S.hdrCell}>Business Types</div>
            {editing && <div />}
          </div>

          {/* Rows */}
          {rows.length === 0 && !editing && (
            <div style={S.empty}>No drip messages configured.</div>
          )}

          {editing ? draft.map((m, i) => (
            <div key={m._key} style={S.seqRow}>
              <div style={S.orderNum}>{i + 1}</div>
              <input
                style={S.input}
                value={m.name}
                placeholder="e.g. Day 1 Welcome"
                onChange={e => updateMessage(m._key, 'name', e.target.value)}
              />
              <select
                style={S.select}
                value={m.template_id}
                onChange={e => updateMessage(m._key, 'template_id', e.target.value)}
              >
                <option value="">— Template —</option>
                {approvedTemplates.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              <input
                style={S.numInput}
                type="number"
                min={0}
                value={m.delay_days}
                onChange={e => updateMessage(m._key, 'delay_days', e.target.value)}
              />
              <input
                style={S.input}
                value={(m.business_types || []).join(', ')}
                placeholder="e.g. Pharmacy, Supermarket (blank = all)"
                onChange={e => updateMessage(m._key, 'business_types',
                  e.target.value ? e.target.value.split(',').map(v => v.trim()).filter(Boolean) : [])}
              />
              <button style={S.removeBtn} onClick={() => removeMessage(m._key)}>×</button>
            </div>
          )) : sequence.map((m, i) => (
            <div key={m.id || i} style={S.viewRow}>
              <div style={S.dot} />
              <div style={{ flex: 1 }}>
                <div style={S.viewVal}>{m.name}</div>
                <div style={{ ...S.viewLabel, marginTop: 2 }}>
                  Day {m.delay_days} · Template: <code style={{ fontSize: 11 }}>{m.template_id}</code>
                  {m.business_types?.length > 0 && ` · ${m.business_types.join(', ')}`}
                </div>
              </div>
              <span style={{ fontSize: 12, color: ds.teal, fontWeight: 600 }}>
                +{m.delay_days} day{m.delay_days !== 1 ? 's' : ''}
              </span>
            </div>
          ))}

          {editing && (
            <button style={S.addRowBtn} onClick={addMessage}>
              + Add Message
            </button>
          )}

          {editing && (
            <>
              {saveErr && <div style={S.errBox}>⚠ {saveErr}</div>}
              <div style={S.actionRow}>
                <button style={S.saveBtn} onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving…' : 'Save & Replace Sequence'}
                </button>
                <button style={S.cancelBtn} onClick={() => { setEditing(false); setSaveErr(null) }}>
                  Cancel
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
