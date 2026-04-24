/**
 * frontend/src/modules/admin/ContactMenuConfig.jsx
 * SM-1 — Returning Contact Menu + Known Customer Menu configuration
 *
 * Two tabbed sections following the same ItemEditor + WhatsAppPreview pattern
 * as CustomerMenuConfig.jsx.
 *
 * Action types: qualify | kb_enquiry | support_ticket | route_to_role | free_form
 * Pattern 26: tabs use display:none (not conditional render).
 * Pattern 50: service calls via admin.service.js only.
 * Pattern 51: full rewrite if editing later.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getContactMenus, updateContactMenus } from '../../services/admin.service'

// ── Constants ─────────────────────────────────────────────────────────────────

const ACTION_OPTIONS = [
  { value: 'qualify',        label: 'Route to assigned rep (qualify)' },
  { value: 'kb_enquiry',     label: 'Answer from knowledge base' },
  { value: 'support_ticket', label: 'Create support ticket' },
  { value: 'route_to_role',  label: 'Route to a team role' },
  { value: 'free_form',      label: 'General enquiry (free form)' },
]

const ROLE_OPTIONS = [
  { value: 'owner',         label: 'Owner' },
  { value: 'ops_manager',   label: 'Ops Manager' },
  { value: 'sales_agent',   label: 'Sales Agent' },
  { value: 'support_agent', label: 'Support Agent' },
  { value: 'finance',       label: 'Finance' },
]

const DEFAULT_RETURNING_ITEMS = [
  { id: 'ready_to_buy',  label: 'Ready to buy',      description: 'Pick up where we left off', action: 'qualify',        role: undefined },
  { id: 'enquiry',       label: 'Make an enquiry',   description: 'Ask a question',            action: 'kb_enquiry',     role: undefined },
  { id: 'complaint',     label: 'Lodge a complaint', description: 'Raise an issue',            action: 'support_ticket', role: undefined },
]

const DEFAULT_KNOWN_ITEMS = [
  { id: 'buy_again',  label: 'Purchase another product', description: '', action: 'qualify',        role: undefined },
  { id: 'kc_support', label: 'Speak to support',         description: '', action: 'support_ticket', role: undefined },
  { id: 'kc_enquiry', label: 'Make an enquiry',          description: '', action: 'kb_enquiry',     role: undefined },
]

// ── Shared sub-components ─────────────────────────────────────────────────────

function ItemEditor({ items, setItems, sectionKey }) {
  function addItem() {
    if (items.length >= 10) return
    setItems([...items, {
      id:          `${sectionKey}_${Date.now()}`,
      label:       '',
      description: '',
      action:      'free_form',
    }])
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
      if (field === 'action' && value !== 'route_to_role') {
        delete updated.role
      }
      return updated
    })
    setItems(next)
  }

  return (
    <>
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
                Label <span style={{ color: '#9CA3AF' }}>{(item.label || '').length}/24</span>
              </label>
              <input
                style={S.input}
                value={item.label || ''}
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
                value={item.action || 'free_form'}
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
                <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
                  <label style={S.label}>What happens</label>
                  <div style={{ ...S.input, background: '#F5FAFB', color: '#7A9BAD', cursor: 'default', fontSize: 12 }}>
                    {ACTION_OPTIONS.find(a => a.value === item.action)?.label || '—'}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Remove */}
          <button
            onClick={() => removeItem(idx)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: '#C0392B', fontSize: 16, padding: '0 4px', flexShrink: 0,
            }}
            title="Remove item"
          >
            ✕
          </button>
        </div>
      ))}
    </>
  )
}

function WhatsAppPreview({ greeting, sectionTitle, items }) {
  return (
    <div style={{ width: 230, flexShrink: 0 }}>
      <div style={{ fontSize: 11, color: '#7A9BAD', fontWeight: 600, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.4px' }}>
        Preview
      </div>
      <div style={{ background: '#ECE5DD', borderRadius: 12, padding: 12, minHeight: 160 }}>
        {/* Greeting bubble */}
        <div style={{
          background: 'white', borderRadius: '0 10px 10px 10px',
          padding: '8px 11px', fontSize: 12.5, color: '#0a1a24',
          marginBottom: 8, boxShadow: '0 1px 3px rgba(0,0,0,0.07)', maxWidth: '85%',
        }}>
          {greeting || 'Hi! How can we help you today?'}
        </div>
        {/* List trigger */}
        <div style={{
          background: 'white', borderRadius: '0 10px 10px 10px',
          padding: '8px 11px', fontSize: 12, color: '#1a7a8a',
          fontWeight: 600, marginBottom: 6, maxWidth: '60%',
          boxShadow: '0 1px 3px rgba(0,0,0,0.07)', textAlign: 'center',
          border: `1px solid ${ds.teal}40`,
        }}>
          ☰ See options
        </div>
        {/* Item previews */}
        {items.slice(0, 4).map((item, i) => (
          <div key={i} style={{
            background: '#F0F0F0', borderRadius: 6, padding: '5px 9px',
            fontSize: 11.5, color: '#333', marginTop: 4,
          }}>
            {item.label || <span style={{ color: '#aaa' }}>Item {i + 1}</span>}
          </div>
        ))}
        {items.length > 4 && (
          <div style={{ fontSize: 10.5, color: '#9CA3AF', marginTop: 4, paddingLeft: 2 }}>
            +{items.length - 4} more
          </div>
        )}
        {items.length === 0 && (
          <div style={{ fontSize: 11.5, color: '#9CA3AF', fontStyle: 'italic', marginTop: 4 }}>
            No items yet
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ContactMenuConfig() {
  const [activeTab, setActiveTab] = useState('returning')

  // Returning contact menu state
  const [rcGreeting,      setRcGreeting]      = useState('Hi! How can we help you today?')
  const [rcSectionTitle,  setRcSectionTitle]  = useState('Choose an option')
  const [rcItems,         setRcItems]         = useState(DEFAULT_RETURNING_ITEMS)

  // Known customer menu state
  const [kcGreeting,      setKcGreeting]      = useState('Hi! How can we help you today?')
  const [kcSectionTitle,  setKcSectionTitle]  = useState('Choose an option')
  const [kcItems,         setKcItems]         = useState(DEFAULT_KNOWN_ITEMS)

  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [saveErr, setSaveErr] = useState('')

  useEffect(() => {
    getContactMenus()
      .then(res => {
        const d = res?.data || {}

        const rc = d.returning_contact_menu || {}
        if (rc.greeting)      setRcGreeting(rc.greeting)
        if (rc.section_title) setRcSectionTitle(rc.section_title)
        if (rc.items?.length) setRcItems(rc.items)

        const kc = d.known_customer_menu || {}
        if (kc.greeting)      setKcGreeting(kc.greeting)
        if (kc.section_title) setKcSectionTitle(kc.section_title)
        if (kc.items?.length) setKcItems(kc.items)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setSaveMsg('')
    setSaveErr('')
    try {
      await updateContactMenus({
        returning_contact_menu: {
          greeting:      rcGreeting,
          section_title: rcSectionTitle,
          items:         rcItems,
        },
        known_customer_menu: {
          greeting:      kcGreeting,
          section_title: kcSectionTitle,
          items:         kcItems,
        },
      })
      setSaveMsg('Contact menus saved')
      setTimeout(() => setSaveMsg(''), 3000)
    } catch (err) {
      setSaveErr(err?.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 13 }}>
        Loading…
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 6px' }}>
          Contact Menus
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0, lineHeight: 1.6 }}>
          Configure the menus shown to returning leads and known customers in Hybrid mode.
          These menus are also used in Transactional mode for known customers.
        </p>
      </div>

      {/* Section tabs */}
      <div style={{ display: 'flex', borderBottom: '2px solid #E2EFF4', marginBottom: 24 }}>
        {[
          { key: 'returning', label: '🔁 Returning Contact Menu' },
          { key: 'known',     label: '⭐ Known Customer Menu' },
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '10px 20px', border: 'none', background: 'none',
              fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
              color: activeTab === tab.key ? ds.teal : '#7A9BAD',
              borderBottom: `2px solid ${activeTab === tab.key ? ds.teal : 'transparent'}`,
              marginBottom: -2, fontFamily: ds.fontSyne,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Returning Contact Menu ────────────────────────────────────────── */}
      <div style={{ display: activeTab === 'returning' ? 'block' : 'none' }}>
        <div style={{ ...S.card, background: '#F0FAFA', border: `1px solid ${ds.teal}30`, marginBottom: 20 }}>
          <p style={{ fontSize: 13, color: '#1a7a8a', margin: 0, lineHeight: 1.6 }}>
            Shown to contacts who are already in your leads pipeline (returning leads) and to
            contacts who previously started a commerce session but chose "Speak to Sales".
          </p>
        </div>

        <div style={S.card}>
          <div style={S.cardTitle}>Menu Text</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <label style={S.label}>Greeting message</label>
              <input
                style={S.input}
                value={rcGreeting}
                maxLength={200}
                onChange={e => setRcGreeting(e.target.value)}
                placeholder="Hi! How can we help you today?"
              />
            </div>
            <div>
              <label style={S.label}>Section title <span style={{ color: '#9CA3AF' }}>{rcSectionTitle.length}/24</span></label>
              <input
                style={S.input}
                value={rcSectionTitle}
                maxLength={24}
                onChange={e => setRcSectionTitle(e.target.value)}
                placeholder="Choose an option"
              />
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 20, alignItems: 'start' }}>
          <div style={S.card}>
            <ItemEditor items={rcItems} setItems={setRcItems} sectionKey="rc" />
          </div>
          <WhatsAppPreview greeting={rcGreeting} sectionTitle={rcSectionTitle} items={rcItems} />
        </div>
      </div>

      {/* ── Known Customer Menu ───────────────────────────────────────────── */}
      <div style={{ display: activeTab === 'known' ? 'block' : 'none' }}>
        <div style={{ ...S.card, background: '#F0FAFA', border: `1px solid ${ds.teal}30`, marginBottom: 20 }}>
          <p style={{ fontSize: 13, color: '#1a7a8a', margin: 0, lineHeight: 1.6 }}>
            Shown to contacts who already have a completed purchase record (known customers),
            across all sales modes. Leave empty to fall through to automatic intent detection.
          </p>
        </div>

        <div style={S.card}>
          <div style={S.cardTitle}>Menu Text</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <label style={S.label}>Greeting message</label>
              <input
                style={S.input}
                value={kcGreeting}
                maxLength={200}
                onChange={e => setKcGreeting(e.target.value)}
                placeholder="Hi! How can we help you today?"
              />
            </div>
            <div>
              <label style={S.label}>Section title <span style={{ color: '#9CA3AF' }}>{kcSectionTitle.length}/24</span></label>
              <input
                style={S.input}
                value={kcSectionTitle}
                maxLength={24}
                onChange={e => setKcSectionTitle(e.target.value)}
                placeholder="Choose an option"
              />
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 20, alignItems: 'start' }}>
          <div style={S.card}>
            <ItemEditor items={kcItems} setItems={setKcItems} sectionKey="kc" />
          </div>
          <WhatsAppPreview greeting={kcGreeting} sectionTitle={kcSectionTitle} items={kcItems} />
        </div>
      </div>

      {/* Save */}
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

// ── Styles ────────────────────────────────────────────────────────────────────
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
}
