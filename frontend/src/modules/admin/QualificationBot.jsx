/**
 * QualificationBot.jsx — M01-3 + M01-4 + M01-7
 *
 * Admin panel for configuring the WhatsApp qualification bot.
 * Reads/writes GET+PATCH /api/v1/admin/qualification-bot
 * and calls POST /api/v1/admin/qualification-bot/ai-recommendations
 * for AI-generated defaults.
 *
 * M01-4 addition: Sending Mode section (full_approval / review_window / auto_send)
 * M01-7 addition: Demo Offer Setting toggle (qualification_demo_offer_enabled)
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

const FIELD_OPTIONS = [
  { value: 'problem_stated',  label: 'Problem / Need Stated' },
  { value: 'business_type',   label: 'Business Type' },
  { value: 'business_size',   label: 'Business Size (branches/locations)' },
  { value: 'staff_count',     label: 'Staff Count' },
  { value: 'next_step',       label: 'Preferred Next Step (demo/trial/questions)' },
]

const DEFAULT_FIELDS = ['problem_stated', 'business_type', 'business_size', 'staff_count', 'next_step']

const SENDING_MODES = [
  {
    value: 'full_approval',
    label: '✋ Full Approval',
    desc: 'Every AI-drafted message waits in the outbox until a rep manually approves it.',
  },
  {
    value: 'review_window',
    label: '⏱ Review Window',
    desc: 'Message auto-sends after the configured minutes unless the rep cancels it first.',
  },
  {
    value: 'auto_send',
    label: '⚡ Auto-Send',
    desc: 'Messages are dispatched immediately with no rep review required.',
  },
]

export default function QualificationBot() {
  const [config, setConfig]       = useState(null)
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [saved, setSaved]         = useState(false)
  const [error, setError]         = useState(null)

  useEffect(() => {
    adminSvc.getQualificationBot()
      .then(d => {
        d = d || {}
        setConfig({
          org_whatsapp_number:              d.org_whatsapp_number              || '',
          org_business_contact_number:      d.org_business_contact_number      || '',
          qualification_bot_name:           d.qualification_bot_name           || '',
          qualification_opening_message:    d.qualification_opening_message    || '',
          qualification_script:             d.qualification_script             || '',
          qualification_fields:             d.qualification_fields             || DEFAULT_FIELDS,
          qualification_handoff_triggers:   d.qualification_handoff_triggers   || '',
          qualification_fallback_hours:     d.qualification_fallback_hours     || 2,
          qualification_sending_mode:       d.qualification_sending_mode       || 'full_approval',
          review_window_minutes:            d.review_window_minutes            || 5,
          qualification_demo_offer_enabled: d.qualification_demo_offer_enabled ?? false,
        })
      })
      .catch(() => setError('Failed to load qualification bot settings.'))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await adminSvc.updateQualificationBot(config)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleAiRecommendations = async () => {
    setAiLoading(true)
    setError(null)
    try {
      const res = await adminSvc.getQualificationAiRecommendations()
      const suggestions = res || {}
      setConfig(prev => ({
        ...prev,
        qualification_bot_name:           suggestions.qualification_bot_name           || prev.qualification_bot_name,
        qualification_opening_message:    suggestions.qualification_opening_message    || prev.qualification_opening_message,
        qualification_script:             suggestions.qualification_script             || prev.qualification_script,
        qualification_handoff_triggers:   suggestions.qualification_handoff_triggers   || prev.qualification_handoff_triggers,
      }))
    } catch {
      setError('Failed to generate AI recommendations.')
    } finally {
      setAiLoading(false)
    }
  }

  const toggleField = (val) => {
    setConfig(prev => {
      const current = prev.qualification_fields || []
      return {
        ...prev,
        qualification_fields: current.includes(val)
          ? current.filter(f => f !== val)
          : [...current, val],
      }
    })
  }

  const S = {
    section: {
      background: '#fff',
      border: `1px solid ${ds.border}`,
      borderRadius: 12,
      padding: '20px 24px',
      marginBottom: 16,
    },
    sectionTitle: {
      fontFamily: ds.fontSyne,
      fontWeight: 700,
      fontSize: 14,
      color: ds.dark,
      marginBottom: 4,
    },
    sectionDesc: {
      fontSize: 12.5,
      color: ds.gray,
      marginBottom: 16,
      lineHeight: 1.5,
    },
    label: {
      display: 'block',
      fontSize: 12.5,
      fontWeight: 600,
      color: ds.dark,
      marginBottom: 6,
    },
    input: {
      width: '100%',
      border: `1.5px solid ${ds.border}`,
      borderRadius: 8,
      padding: '10px 12px',
      fontSize: 13,
      fontFamily: ds.fontBody,
      outline: 'none',
      marginBottom: 14,
    },
    textarea: {
      width: '100%',
      border: `1.5px solid ${ds.border}`,
      borderRadius: 8,
      padding: '10px 12px',
      fontSize: 13,
      fontFamily: ds.fontBody,
      resize: 'vertical',
      minHeight: 90,
      outline: 'none',
      marginBottom: 14,
      lineHeight: 1.5,
    },
    row: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
    checkRow: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '8px 12px',
      borderRadius: 8,
      background: ds.light,
      marginBottom: 8,
      cursor: 'pointer',
    },
    modeCard: (selected) => ({
      border: `2px solid ${selected ? ds.teal : ds.border}`,
      borderRadius: 10,
      padding: '14px 16px',
      marginBottom: 10,
      cursor: 'pointer',
      background: selected ? ds.mint : '#fff',
      transition: 'border-color 0.15s, background 0.15s',
    }),
    saveBtn: {
      padding: '10px 24px',
      background: saving ? '#9ca3af' : ds.teal,
      color: '#fff',
      border: 'none',
      borderRadius: 8,
      fontFamily: ds.fontSyne,
      fontWeight: 600,
      fontSize: 13,
      cursor: saving ? 'not-allowed' : 'pointer',
    },
    aiBtn: {
      padding: '10px 20px',
      background: 'white',
      color: ds.teal,
      border: `1.5px solid ${ds.teal}`,
      borderRadius: 8,
      fontFamily: ds.fontSyne,
      fontWeight: 600,
      fontSize: 13,
      cursor: aiLoading ? 'not-allowed' : 'pointer',
      opacity: aiLoading ? 0.6 : 1,
    },
  }

  if (loading) return <p style={{ fontSize: 13, color: ds.gray, padding: 8 }}>Loading…</p>

  if (!config) return (
    <p style={{ fontSize: 13, color: '#e53e3e', padding: 8 }}>
      {error || 'Failed to load settings.'}
    </p>
  )

  const demoOfferEnabled = config.qualification_demo_offer_enabled

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: 0 }}>
            🤖 WhatsApp Qualification Bot
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, marginTop: 4, lineHeight: 1.5 }}>
            Configure how the AI bot greets and qualifies new leads on WhatsApp.
          </p>
        </div>
        <button style={S.aiBtn} onClick={handleAiRecommendations} disabled={aiLoading}>
          {aiLoading ? '✨ Generating…' : '✨ Get AI Recommendations'}
        </button>
      </div>

      {error && (
        <div style={{ background: '#fff5f5', border: '1px solid #fed7d7', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#e53e3e', marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}

      {/* Contact Numbers */}
      <div style={S.section}>
        <div style={S.sectionTitle}>📱 Contact Numbers</div>
        <div style={S.sectionDesc}>
          The lead-facing WhatsApp number is used to build the "Continue on WhatsApp" link on the form.
          The business contact number is for internal escalations.
        </div>
        <div style={S.row}>
          <div>
            <label style={S.label}>Lead-Facing WhatsApp Number</label>
            <input
              style={S.input}
              placeholder="e.g. 2348012345678"
              value={config.org_whatsapp_number}
              onChange={e => setConfig(p => ({ ...p, org_whatsapp_number: e.target.value }))}
            />
          </div>
          <div>
            <label style={S.label}>Business Contact Number (internal)</label>
            <input
              style={S.input}
              placeholder="e.g. 2348099999999"
              value={config.org_business_contact_number}
              onChange={e => setConfig(p => ({ ...p, org_business_contact_number: e.target.value }))}
            />
          </div>
        </div>
      </div>

      {/* Bot Identity */}
      <div style={S.section}>
        <div style={S.sectionTitle}>🤖 Bot Identity</div>
        <div style={S.sectionDesc}>
          The bot name is used in conversation. Leave opening message blank to let the AI generate one dynamically.
        </div>
        <label style={S.label}>Bot Name</label>
        <input
          style={S.input}
          placeholder="e.g. Amaka from Ovaloop"
          value={config.qualification_bot_name}
          onChange={e => setConfig(p => ({ ...p, qualification_bot_name: e.target.value }))}
        />
        <label style={S.label}>Opening Message (first reply when lead messages)</label>
        <textarea
          style={S.textarea}
          placeholder="e.g. Hi [Name]! 👋 Thanks for reaching out to Ovaloop. I'm Amaka and I'd love to learn a bit about your business so we can help you better. What challenge are you currently trying to solve?"
          value={config.qualification_opening_message}
          onChange={e => setConfig(p => ({ ...p, qualification_opening_message: e.target.value }))}
        />
      </div>

      {/* Sending Mode — M01-4 */}
      <div style={S.section}>
        <div style={S.sectionTitle}>📤 Message Sending Mode</div>
        <div style={S.sectionDesc}>
          Controls how AI-drafted qualification messages are handled before being sent to leads.
        </div>
        {SENDING_MODES.map(mode => {
          const selected = config.qualification_sending_mode === mode.value
          return (
            <div
              key={mode.value}
              style={S.modeCard(selected)}
              onClick={() => setConfig(p => ({ ...p, qualification_sending_mode: mode.value }))}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 16, height: 16, borderRadius: '50%',
                  border: `2px solid ${selected ? ds.teal : ds.border}`,
                  background: selected ? ds.teal : '#fff',
                  flexShrink: 0,
                }} />
                <span style={{ fontWeight: 600, fontSize: 13, color: ds.dark }}>
                  {mode.label}
                </span>
              </div>
              <p style={{ fontSize: 12.5, color: ds.gray, margin: '6px 0 0 26px', lineHeight: 1.5 }}>
                {mode.desc}
              </p>
            </div>
          )
        })}

        {/* Review window minutes — only shown when review_window is selected */}
        {config.qualification_sending_mode === 'review_window' && (
          <div style={{ marginTop: 12 }}>
            <label style={S.label}>Auto-send after (minutes)</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <input
                type="number"
                style={{ ...S.input, width: 100, marginBottom: 0 }}
                min={1} max={60}
                value={config.review_window_minutes}
                onChange={e => setConfig(p => ({ ...p, review_window_minutes: Number(e.target.value) }))}
              />
              <span style={{ fontSize: 12.5, color: ds.gray }}>
                minutes of inactivity before the message auto-sends
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Fields to Collect */}
      <div style={S.section}>
        <div style={S.sectionTitle}>📋 Fields to Collect</div>
        <div style={S.sectionDesc}>
          The bot will collect these fields in order. Uncheck any you don't need.
        </div>
        {FIELD_OPTIONS.map(opt => {
          const checked = (config.qualification_fields || []).includes(opt.value)
          return (
            <div
              key={opt.value}
              style={{ ...S.checkRow, background: checked ? ds.mint : ds.light }}
              onClick={() => toggleField(opt.value)}
            >
              <span style={{ fontSize: 16 }}>{checked ? '✅' : '⬜'}</span>
              <span style={{ fontSize: 13, color: ds.dark, fontWeight: checked ? 500 : 400 }}>
                {opt.label}
              </span>
            </div>
          )
        })}
      </div>

      {/* Conversation Guidelines */}
      <div style={S.section}>
        <div style={S.sectionTitle}>💬 Conversation Guidelines</div>
        <div style={S.sectionDesc}>
          Additional instructions for the AI on how to conduct the conversation.
          Leave blank to use sensible defaults.
        </div>
        <textarea
          style={S.textarea}
          placeholder="e.g. Focus on understanding the lead's inventory management challenges. If they mention multiple branches, ask about stock tracking across locations specifically."
          value={config.qualification_script}
          onChange={e => setConfig(p => ({ ...p, qualification_script: e.target.value }))}
        />
      </div>

      {/* Handoff & Fallback */}
      <div style={S.section}>
        <div style={S.sectionTitle}>🔀 Handoff & Re-engagement</div>
        <div style={S.sectionDesc}>
          Define what phrases trigger immediate handoff to a human rep.
          Set how many hours of silence before a re-engagement message is sent.
        </div>
        <label style={S.label}>Handoff Trigger Phrases (comma-separated)</label>
        <input
          style={S.input}
          placeholder="e.g. demo, pricing, speak to someone, ready to start, I want to sign up"
          value={config.qualification_handoff_triggers}
          onChange={e => setConfig(p => ({ ...p, qualification_handoff_triggers: e.target.value }))}
        />
        <label style={S.label}>Re-engagement Fallback (hours of silence before follow-up)</label>
        <input
          type="number"
          style={{ ...S.input, width: 100 }}
          min={1} max={168}
          value={config.qualification_fallback_hours}
          onChange={e => setConfig(p => ({ ...p, qualification_fallback_hours: Number(e.target.value) }))}
        />
      </div>

      {/* Demo Offer Setting — M01-7 */}
      <div style={S.section}>
        <div style={S.sectionTitle}>📅 Demo Offer Setting</div>
        <div style={S.sectionDesc}>
          When enabled, the bot will offer to book a product demo at the end of qualification —
          asking the lead for their preferred medium (virtual or in-person) and time.
          A demo request is automatically created for admin to confirm.
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '12px 14px',
            borderRadius: 8,
            background: demoOfferEnabled ? '#f0fff4' : '#f8fafc',
            border: `1.5px solid ${demoOfferEnabled ? '#9ae6b4' : '#e2e8f0'}`,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
          onClick={() => setConfig(p => ({ ...p, qualification_demo_offer_enabled: !p.qualification_demo_offer_enabled }))}
        >
          {/* Toggle track */}
          <div style={{
            width: 40,
            height: 22,
            borderRadius: 11,
            background: demoOfferEnabled ? '#38a169' : '#cbd5e0',
            position: 'relative',
            transition: 'background 0.2s',
            flexShrink: 0,
          }}>
            {/* Toggle thumb */}
            <div style={{
              width: 18,
              height: 18,
              borderRadius: '50%',
              background: 'white',
              position: 'absolute',
              top: 2,
              left: demoOfferEnabled ? 20 : 2,
              transition: 'left 0.2s',
              boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
            }} />
          </div>
          <div>
            <p style={{ fontSize: 13, fontWeight: 600, color: '#1a202c', margin: 0 }}>
              {demoOfferEnabled ? '✅ Demo offer enabled' : 'Demo offer disabled'}
            </p>
            <p style={{ fontSize: 12, color: '#718096', margin: '2px 0 0' }}>
              {demoOfferEnabled
                ? 'Bot will ask for preferred demo medium and time before handing off.'
                : 'Bot will hand off without offering a demo.'}
            </p>
          </div>
        </div>
      </div>

      {/* Save */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button style={S.saveBtn} onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : '💾 Save Settings'}
        </button>
        {saved && (
          <span style={{ fontSize: 13, color: '#27ae60', fontWeight: 500 }}>
            ✓ Saved successfully
          </span>
        )}
      </div>
    </div>
  )
}
