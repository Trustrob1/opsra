/**
 * frontend/src/modules/admin/DripBusinessTypesConfig.jsx
 * CONFIG-2 — Drip Business Types configuration.
 *
 * Allows owners/admins to define the set of business types their drip
 * sequences can be filtered by. An empty list means "all types" (unrestricted).
 *
 * GET/PATCH /api/v1/admin/drip-business-types
 *
 * Pattern 51: full rewrite required for any edit — never sed.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  getDripBusinessTypes,
  updateDripBusinessTypes,
} from '../../services/admin.service'

function slugify(str) {
  return str
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

const BLANK_TYPE = () => ({
  _uid: Math.random().toString(36).slice(2),
  key: '',
  label: '',
  enabled: true,
})

export default function DripBusinessTypesConfig() {
  const [types, setTypes]     = useState([])
  const [draft, setDraft]     = useState([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving]   = useState(false)
  const [saveErr, setSaveErr] = useState(null)
  const [saved, setSaved]     = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    getDripBusinessTypes()
      .then(data => setTypes(data.business_types ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  function startEdit() {
    setDraft(
      types.map(t => ({
        ...t,
        _uid: t.key || Math.random().toString(36).slice(2),
      }))
    )
    setEditing(true)
    setSaveErr(null)
    setSaved(false)
  }

  function addType() {
    setDraft(d => [...d, BLANK_TYPE()])
  }

  function removeType(uid) {
    setDraft(d => d.filter(t => t._uid !== uid))
  }

  function updateLabel(uid, label) {
    setDraft(d =>
      d.map(t =>
        t._uid === uid
          ? { ...t, label, key: slugify(label) }
          : t
      )
    )
  }

  function updateKey(uid, key) {
    setDraft(d => d.map(t => t._uid === uid ? { ...t, key } : t))
  }

  function toggleEnabled(uid) {
    setDraft(d =>
      d.map(t => t._uid === uid ? { ...t, enabled: !t.enabled } : t)
    )
  }

  async function handleSave() {
    setSaveErr(null)

    // Validate
    for (let i = 0; i < draft.length; i++) {
      const t = draft[i]
      if (!t.label.trim()) {
        setSaveErr(`Row ${i + 1}: Label is required.`)
        return
      }
      if (!t.key || !/^[a-z0-9_]+$/.test(t.key)) {
        setSaveErr(`Row ${i + 1}: Key must be lowercase alphanumeric and underscores only.`)
        return
      }
    }
    const keys = draft.map(t => t.key)
    if (new Set(keys).size !== keys.length) {
      setSaveErr('Business type keys must be unique.')
      return
    }

    const business_types = draft.map(({ key, label, enabled }) => ({
      key,
      label: label.trim(),
      enabled,
    }))

    setSaving(true)
    try {
      await updateDripBusinessTypes({ business_types })
      setSaved(true)
      setEditing(false)
      load()
    } catch (err) {
      setSaveErr(err.response?.data?.error?.message || 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  // ── Styles ────────────────────────────────────────────────────────────────

  const S = {
    wrap: { padding: 28 },
    header: {
      display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', marginBottom: 20,
    },
    title: {
      fontFamily: ds.fontHead, fontWeight: 700,
      fontSize: 18, color: ds.dark,
    },
    editBtn: {
      padding: '9px 18px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 9, fontSize: 13, fontWeight: 600,
      fontFamily: ds.fontHead, cursor: 'pointer',
    },
    hint: {
      background: '#E0F4F6', border: `1px solid #B0DDD9`, borderRadius: 8,
      padding: '10px 14px', fontSize: 12.5, color: '#015F6B', marginBottom: 18,
    },
    card: {
      background: '#fff', border: `1px solid ${ds.border}`,
      borderRadius: 14, overflow: 'hidden',
    },
    tableHead: {
      background: '#E0F4F6', padding: '10px 16px',
      display: 'grid',
      gridTemplateColumns: '1fr 160px 80px 36px',
      gap: 10, alignItems: 'center',
    },
    hdrCell: {
      fontSize: 11, color: '#015F6B', fontWeight: 600,
      textTransform: 'uppercase', letterSpacing: '0.6px',
    },
    row: {
      display: 'grid',
      gridTemplateColumns: '1fr 160px 80px 36px',
      gap: 10, padding: '12px 16px',
      borderBottom: `1px solid ${ds.border}`,
      alignItems: 'center',
    },
    input: {
      border: `1.5px solid ${ds.border}`, borderRadius: 8,
      padding: '7px 10px', fontSize: 12.5,
      fontFamily: ds.fontBody, outline: 'none', width: '100%',
      boxSizing: 'border-box',
    },
    keyInput: {
      border: `1.5px solid ${ds.border}`, borderRadius: 8,
      padding: '7px 10px', fontSize: 11.5,
      fontFamily: 'monospace', outline: 'none', width: '100%',
      boxSizing: 'border-box', color: '#015F6B', background: '#F4FDFD',
    },
    removeBtn: {
      background: '#FFE8E8', color: '#C0392B', border: 'none',
      borderRadius: 7, cursor: 'pointer', fontWeight: 700, fontSize: 15,
      width: 28, height: 28, display: 'flex', alignItems: 'center',
      justifyContent: 'center', flexShrink: 0,
    },
    toggleOn: {
      padding: '4px 10px', background: ds.teal, color: '#fff',
      border: 'none', borderRadius: 20, fontSize: 11,
      fontWeight: 600, cursor: 'pointer',
    },
    toggleOff: {
      padding: '4px 10px', background: '#EAF0F2', color: ds.gray,
      border: 'none', borderRadius: 20, fontSize: 11,
      fontWeight: 600, cursor: 'pointer',
    },
    addBtn: {
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
      fontFamily: ds.fontHead,
      cursor: saving ? 'not-allowed' : 'pointer',
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
      padding: '12px 16px', borderBottom: `1px solid ${ds.border}`,
    },
    dot: {
      width: 10, height: 10, borderRadius: '50%',
      flexShrink: 0, marginTop: 2,
    },
    badge: {
      padding: '2px 9px', borderRadius: 20, fontSize: 11,
      fontWeight: 600, whiteSpace: 'nowrap',
    },
    empty: {
      padding: 32, textAlign: 'center',
      color: ds.gray, fontSize: 13,
    },
  }

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <div style={S.title}>Drip Business Types</div>
        {!editing && (
          <button style={S.editBtn} onClick={startEdit}>
            ✏ Edit Types
          </button>
        )}
      </div>

      <div style={S.hint}>
        💡 Define the business types your organisation serves. These are used to filter which
        drip sequence messages get sent to each customer. Leave the list empty to send all
        drip messages regardless of business type.
      </div>

      {saved && !editing && (
        <div style={S.savedBox}>✓ Drip business types saved successfully.</div>
      )}

      {loading ? (
        <div style={{ padding: 32, color: ds.teal }}>Loading…</div>
      ) : (
        <div style={S.card}>
          {/* Header */}
          <div style={S.tableHead}>
            <div style={S.hdrCell}>Label</div>
            <div style={S.hdrCell}>Key (slug)</div>
            <div style={S.hdrCell}>Status</div>
            {editing && <div />}
          </div>

          {/* View mode */}
          {!editing && (
            <>
              {types.length === 0 ? (
                <div style={S.empty}>
                  No business types configured — all drip messages are sent unrestricted.
                </div>
              ) : types.map(t => (
                <div key={t.key} style={S.viewRow}>
                  <div
                    style={{
                      ...S.dot,
                      background: t.enabled ? ds.teal : '#CBD5E0',
                    }}
                  />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13.5, color: ds.dark, fontWeight: 500 }}>
                      {t.label}
                    </div>
                    <div style={{ fontSize: 11, color: ds.gray, fontFamily: 'monospace', marginTop: 2 }}>
                      {t.key}
                    </div>
                  </div>
                  <span
                    style={{
                      ...S.badge,
                      background: t.enabled ? '#E0F4F6' : '#F0F4F7',
                      color: t.enabled ? ds.teal : ds.gray,
                    }}
                  >
                    {t.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
              ))}
            </>
          )}

          {/* Edit mode */}
          {editing && (
            <>
              {draft.length === 0 && (
                <div style={S.empty}>No types yet. Click "+ Add Type" to begin.</div>
              )}
              {draft.map((t, i) => (
                <div key={t._uid} style={S.row}>
                  <input
                    style={S.input}
                    value={t.label}
                    placeholder="e.g. Pharmacy"
                    maxLength={80}
                    onChange={e => updateLabel(t._uid, e.target.value)}
                  />
                  <input
                    style={S.keyInput}
                    value={t.key}
                    placeholder="auto-generated"
                    maxLength={80}
                    onChange={e => updateKey(t._uid, e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                  />
                  <button
                    style={t.enabled ? S.toggleOn : S.toggleOff}
                    onClick={() => toggleEnabled(t._uid)}
                  >
                    {t.enabled ? 'Enabled' : 'Disabled'}
                  </button>
                  <button style={S.removeBtn} onClick={() => removeType(t._uid)}>×</button>
                </div>
              ))}

              <button style={S.addBtn} onClick={addType}>+ Add Type</button>

              {saveErr && <div style={S.errBox}>⚠ {saveErr}</div>}

              <div style={S.actionRow}>
                <button style={S.saveBtn} onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving…' : 'Save Types'}
                </button>
                <button
                  style={S.cancelBtn}
                  onClick={() => { setEditing(false); setSaveErr(null) }}
                >
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
