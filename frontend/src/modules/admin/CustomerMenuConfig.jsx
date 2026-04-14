/**
 * frontend/src/modules/admin/CustomerMenuConfig.jsx
 * WH-0 — WhatsApp Triage Menu Configuration
 *
 * Allows owners/ops_managers to configure:
 *   1. unknown_contact_behavior toggle (triage_first | qualify_immediately)
 *   2. Triage menu items for unknown contacts
 *   3. Live WhatsApp preview panel
 *
 * Pattern 26: not applicable (no tabs within this component).
 * Pattern 51: full rewrite if editing later.
 * Colors: ds.teal for all accents.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getTriageConfig, updateTriageConfig } from '../../services/admin.service'

const ACTION_OPTIONS = [
  { value: 'qualify',            label: 'Sales interest (qualify)' },
  { value: 'identify_customer',  label: 'Existing customer' },
  { value: 'route_to_role',      label: 'Route to a team role' },
  { value: 'free_form',          label: 'General enquiry (free form)' },
]

const ROLE_OPTIONS = [
  { value: 'owner',       label: 'Owner' },
  { value: 'ops_manager', label: 'Ops Manager' },
  { value: 'finance',     label: 'Finance' },
]

const CONTACT_TYPE_MAP = {
  qualify:           'sales_lead',
  identify_customer: 'support_contact',
  route_to_role:     'business_inquiry',
  free_form:         'other',
}

const DEFAULT_ITEMS = [
  { id: 'interested',        label: "I'm interested in your product", description: 'Learn about what we offer',  action: 'qualify',           contact_type: 'sales_lead'       },
  { id: 'existing_customer', label: "I'm an existing customer",       description: 'Get help with your account', action: 'identify_customer', contact_type: 'support_contact'  },
  { id: 'business',          label: 'Business inquiry',               description: 'Partner or vendor query',    action: 'route_to_role',     contact_type: 'business_inquiry', role: 'owner' },
  { id: 'other',             label: 'Something else',                 description: '',                           action: 'free_form',          contact_type: 'other'            },
]

const DEFAULT_CONFIG = {
  unknown: {
    greeting:      'Hi! How can we help you today?',
    section_title: 'Choose an option',
    items:         DEFAULT_ITEMS,
  },
}

export default function CustomerMenuConfig() {
  const [behavior, setBehavior]     = useState('triage_first')
  const [config, setConfig]         = useState(DEFAULT_CONFIG)
  const [loading, setLoading]       = useState(true)
  const [saving, setSaving]         = useState(false)
  const [saveMsg, setSaveMsg]       = useState(null)
  const [saveErr, setSaveErr]       = useState(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  useEffect(() => {
    getTriageConfig()
      .then(data => {
        if (data) {
          setBehavior(data.unknown_contact_behavior || 'triage_first')
          setConfig(data.whatsapp_triage_config || DEFAULT_CONFIG)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const items = (config?.unknown?.items) || []
  const greeting = config?.unknown?.greeting || ''
  const sectionTitle = config?.unknown?.section_title || 'Choose an option'

  function setItems(newItems) {
    setConfig(c => ({ ...c, unknown: { ...c.unknown, items: newItems } }))
  }
  function setGreeting(v) {
    setConfig(c => ({ ...c, unknown: { ...c.unknown, greeting: v } }))
  }
  function setSectionTitle(v) {
    setConfig(c => ({ ...c, unknown: { ...c.unknown, section_title: v } }))
  }

  function addItem() {
    if (items.length >= 10) return
    const newItem = {
      id:           `item_${Date.now()}`,
      label:        '',
      description:  '',
      action:       'free_form',
      contact_type: 'other',
    }
    setItems([...items, newItem])
  }

  function removeItem(idx) {
    setItems(items.filter((_, i) => i !== idx))
  }

  function moveItem(idx, dir) {
    const next = [...items]
    const swap = idx + dir
    if (swap < 0 || swap >= next.length) return
    ;[next[idx], next[swap]] = [next[swap], next[idx]]
    setItems(next)
  }

  function updateItem(idx, field, value) {
    const next = items.map((item, i) => {
      if (i !== idx) return item
      const updated = { ...item, [field]: value }
      if (field === 'action') {
        updated.contact_type = CONTACT_TYPE_MAP[value] || 'other'
        if (value !== 'route_to_role') delete updated.role
      }
      return updated
    })
    setItems(next)
  }

  async function handleSave() {
    setSaving(true)
    setSaveMsg(null)
    setSaveErr(null)
    try {
      await updateTriageConfig({
        unknown_contact_behavior: behavior,
        whatsapp_triage_config:   config,
      })
      setSaveMsg('Saved successfully.')
    } catch (e) {
      setSaveErr(e?.response?.data?.error?.message || 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 13 }}>Loading triage config…</div>
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 4px' }}>
          WhatsApp Triage Menu
        </h2>
        <p style={{ fontSize: 13, color: '#5a8a9f', margin: 0 }}>
          Configure how Opsra handles inbound WhatsApp messages from unknown contacts.
        </p>
      </div>

      {/* ── Behavior toggle ─────────────────────────────────────────────── */}
      <div style={S.card}>
        <div style={S.cardTitle}>Unknown Contact Behavior</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            {
              value: 'triage_first',
              label: 'Triage first (recommended)',
              desc:  'Send an interactive menu to unknown contacts. They select their intent before any pipeline action fires.',
            },
            {
              value: 'qualify_immediately',
              label: 'Qualify immediately (legacy)',
              desc:  'Auto-create a sales lead and start the qualification bot for every unknown number. Use only if all inbound messages are sales enquiries.',
            },
          ].map(opt => (
            <label key={opt.value} style={{
              display: 'flex', alignItems: 'flex-start', gap: 12, cursor: 'pointer',
              padding: '12px 14px', borderRadius: 10,
              border: `1.5px solid ${behavior === opt.value ? ds.teal : '#D6E8EC'}`,
              background: behavior === opt.value ? '#F0FAFA' : '#FAFAFA',
            }}>
              <input
                type="radio"
                name="behavior"
                value={opt.value}
                checked={behavior === opt.value}
                onChange={() => setBehavior(opt.value)}
                style={{ marginTop: 2, accentColor: ds.teal, flexShrink: 0 }}
              />
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: '#0a1a24', marginBottom: 2 }}>
                  {opt.label}
                </div>
                <div style={{ fontSize: 12.5, color: '#5a8a9f', lineHeight: 1.5 }}>
                  {opt.desc}
                </div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* ── Menu text ───────────────────────────────────────────────────── */}
      {behavior === 'triage_first' && (
        <div style={S.card}>
          <div style={S.cardTitle}>Menu Text</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <label style={S.label}>Greeting message</label>
              <input
                style={S.input}
                value={greeting}
                maxLength={200}
                onChange={e => setGreeting(e.target.value)}
                placeholder="Hi! How can we help you today?"
              />
            </div>
            <div>
              <label style={S.label}>Section title (shown in menu)</label>
              <input
                style={S.input}
                value={sectionTitle}
                maxLength={24}
                onChange={e => setSectionTitle(e.target.value)}
                placeholder="Choose an option"
              />
              <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 3 }}>
                {sectionTitle.length}/24 characters
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Menu items + preview ─────────────────────────────────────────── */}
      {behavior === 'triage_first' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 20, alignItems: 'start' }}>

          {/* Items editor */}
          <div style={S.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div style={S.cardTitle}>Menu Items</div>
              <button
                onClick={addItem}
                disabled={items.length >= 10}
                style={{
                  ...S.addBtn,
                  opacity: items.length >= 10 ? 0.4 : 1,
                  cursor:  items.length >= 10 ? 'not-allowed' : 'pointer',
                }}
              >
                + Add item
              </button>
            </div>

            {items.length === 0 && (
              <div style={{ fontSize: 13, color: '#9CA3AF', textAlign: 'center', padding: '20px 0' }}>
                No menu items. Add at least one.
              </div>
            )}

            {items.map((item, idx) => (
              <div key={item.id || idx} style={S.itemRow}>
                {/* Reorder */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flexShrink: 0 }}>
                  <button onClick={() => moveItem(idx, -1)} style={S.arrowBtn} disabled={idx === 0} title="Move up">▲</button>
                  <button onClick={() => moveItem(idx, 1)}  style={S.arrowBtn} disabled={idx === items.length - 1} title="Move down">▼</button>
                </div>

                {/* Fields */}
                <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <div>
                    <label style={S.label}>
                      Label <span style={{ color: '#9CA3AF' }}>{item.label.length}/24</span>
                    </label>
                    <input
                      style={S.input}
                      value={item.label}
                      maxLength={24}
                      onChange={e => updateItem(idx, 'label', e.target.value)}
                      placeholder="Button label"
                    />
                  </div>
                  <div>
                    <label style={S.label}>
                      Description <span style={{ color: '#9CA3AF' }}>{(item.description || '').length}/72</span>
                    </label>
                    <input
                      style={S.input}
                      value={item.description || ''}
                      maxLength={72}
                      onChange={e => updateItem(idx, 'description', e.target.value)}
                      placeholder="Optional sub-text"
                    />
                  </div>
                  <div>
                    <label style={S.label}>Action</label>
                    <select
                      style={S.input}
                      value={item.action}
                      onChange={e => updateItem(idx, 'action', e.target.value)}
                    >
                      {ACTION_OPTIONS.map(a => (
                        <option key={a.value} value={a.value}>{a.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    {item.action === 'route_to_role' ? (
                      <>
                        <label style={S.label}>Route to role</label>
                        <select
                          style={S.input}
                          value={item.role || 'owner'}
                          onChange={e => updateItem(idx, 'role', e.target.value)}
                        >
                          {ROLE_OPTIONS.map(r => (
                            <option key={r.value} value={r.value}>{r.label}</option>
                          ))}
                        </select>
                      </>
                    ) : (
                      <>
                        <label style={S.label}>Contact type (auto)</label>
                        <div style={{ ...S.input, background: '#F5FAFB', color: '#7A9BAD', cursor: 'default' }}>
                          {item.contact_type || CONTACT_TYPE_MAP[item.action] || 'other'}
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {/* Remove */}
                <button
                  onClick={() => removeItem(idx)}
                  style={{ ...S.arrowBtn, color: '#E53E3E', alignSelf: 'center', flexShrink: 0 }}
                  title="Remove item"
                >
                  ✕
                </button>
              </div>
            ))}

            <div style={{ fontSize: 12, color: '#9CA3AF', marginTop: 8 }}>
              {items.length}/10 items
            </div>
          </div>

          {/* WhatsApp preview */}
          <div style={{ width: 280, flexShrink: 0 }}>
            <div style={S.card}>
              <div style={S.cardTitle}>Preview</div>
              <div style={S.phoneFrame}>
                {/* Chat header */}
                <div style={{ background: '#075E54', color: 'white', padding: '8px 12px', borderRadius: '10px 10px 0 0', fontSize: 12, fontWeight: 600 }}>
                  📱 WhatsApp
                </div>
                <div style={{ background: '#ECE5DD', padding: 10, borderRadius: '0 0 10px 10px', minHeight: 140 }}>
                  {/* Incoming bubble */}
                  <div style={S.waBubble}>
                    <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                      {greeting || 'Hi! How can we help you today?'}
                    </div>
                    <button
                      onClick={() => setPreviewOpen(p => !p)}
                      style={{
                        marginTop: 8, width: '100%', padding: '6px 0',
                        border: `1px solid ${ds.teal}`, borderRadius: 6,
                        background: 'white', color: ds.teal,
                        fontSize: 11, fontWeight: 600, cursor: 'pointer',
                      }}
                    >
                      {previewOpen ? '▲ Hide options' : '☰ See options'}
                    </button>
                  </div>

                  {/* Options list */}
                  {previewOpen && (
                    <div style={{ background: 'white', borderRadius: 8, marginTop: 8, overflow: 'hidden', boxShadow: '0 1px 4px rgba(0,0,0,0.12)' }}>
                      <div style={{ padding: '6px 10px', fontSize: 10, fontWeight: 700, color: '#5a8a9f', textTransform: 'uppercase', borderBottom: '1px solid #F0F0F0' }}>
                        {sectionTitle || 'Choose an option'}
                      </div>
                      {items.slice(0, 10).map((item, i) => (
                        <div key={i} style={{ padding: '8px 10px', borderBottom: i < items.length - 1 ? '1px solid #F0F0F0' : 'none' }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: '#0a1a24' }}>{item.label || '(empty)'}</div>
                          {item.description && (
                            <div style={{ fontSize: 10.5, color: '#7A9BAD', marginTop: 1 }}>{item.description}</div>
                          )}
                        </div>
                      ))}
                      {items.length === 0 && (
                        <div style={{ padding: '10px', fontSize: 12, color: '#9CA3AF', textAlign: 'center' }}>No items added</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <p style={{ fontSize: 11, color: '#9CA3AF', margin: '8px 0 0', lineHeight: 1.5 }}>
                Static preview only. Actual appearance may vary by device.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Save ────────────────────────────────────────────────────────── */}
      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            padding: '10px 24px', background: ds.teal, color: 'white',
            border: 'none', borderRadius: 9, fontSize: 13.5, fontWeight: 600,
            fontFamily: ds.fontSyne, cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.65 : 1,
          }}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        {saveMsg && <span style={{ fontSize: 13, color: '#27AE60' }}>✓ {saveMsg}</span>}
        {saveErr && <span style={{ fontSize: 13, color: '#C0392B' }}>⚠ {saveErr}</span>}
      </div>
    </div>
  )
}

// ── Shared styles ─────────────────────────────────────────────────────────────
const S = {
  card: {
    background: 'white', border: '1px solid #E2EFF4', borderRadius: 12,
    padding: '20px 22px', marginBottom: 20,
  },
  cardTitle: {
    fontFamily: 'var(--font-syne, sans-serif)', fontWeight: 700, fontSize: 14,
    color: '#0a1a24', marginBottom: 14,
  },
  label: {
    display: 'block', fontSize: 11, color: '#7A9BAD',
    textTransform: 'uppercase', letterSpacing: '0.4px',
    fontWeight: 500, marginBottom: 4,
  },
  input: {
    border: '1.5px solid #D6E8EC', borderRadius: 8, padding: '8px 11px',
    fontSize: 13, fontFamily: 'inherit', outline: 'none', width: '100%',
    boxSizing: 'border-box', background: 'white',
  },
  itemRow: {
    display: 'flex', gap: 10, alignItems: 'flex-start',
    padding: '14px 0', borderBottom: '1px solid #F0F6F8',
  },
  arrowBtn: {
    background: 'none', border: '1px solid #D6E8EC', borderRadius: 5,
    cursor: 'pointer', padding: '2px 5px', fontSize: 10, color: '#7A9BAD',
    lineHeight: 1.4,
  },
  addBtn: {
    padding: '6px 14px', background: '#E0F4F6', color: '#1a7a8a',
    border: 'none', borderRadius: 7, fontSize: 12.5, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer',
  },
  phoneFrame: {
    border: '1.5px solid #E2EFF4', borderRadius: 12, overflow: 'hidden',
  },
  waBubble: {
    background: 'white', borderRadius: '0 10px 10px 10px',
    padding: '8px 10px', maxWidth: '90%', boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
  },
}
