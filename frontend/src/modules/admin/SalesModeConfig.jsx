/**
 * frontend/src/modules/admin/SalesModeConfig.jsx
 * SM-1 — Sales Mode Engine configuration
 *
 * Three-card mode selector: Consultative / Transactional / Hybrid.
 * Hybrid shows a live preview of the Buy Now / Speak to Sales gate.
 * Transactional and Hybrid both require Shopify integration (SHOP-1).
 * Pattern 51: full rewrite if editing later.
 * Pattern 50: service calls via admin.service.js only (axios + _h()).
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { getSalesMode, updateSalesMode, getShopifyStatus } from '../../services/admin.service'

const MODES = [
  {
    value: 'consultative',
    icon: '🤝',
    label: 'Consultative',
    tagline: 'Sales-led, qualification-first',
    description:
      'Every new WhatsApp contact goes straight into your lead pipeline and the qualification bot fires immediately. Best for businesses where personal selling drives conversion.',
    useCases: ['B2B SaaS', 'High-value retail', 'Professional services'],
    requiresShopify: false,
  },
  {
    value: 'transactional',
    icon: '🛒',
    label: 'Transactional',
    tagline: 'Commerce-first, self-service buying',
    description:
      'New contacts are taken directly into a shopping and checkout flow powered by your Shopify store. No lead is created unless they choose to speak to sales.',
    useCases: ['E-commerce', 'FMCG / repeat purchases', 'Shopify-first businesses'],
    requiresShopify: true,
  },
  {
    value: 'hybrid',
    icon: '⚡',
    label: 'Hybrid',
    tagline: 'Let customers choose their path',
    description:
      'New contacts see a simple choice upfront — "Buy Now" or "Speak to Sales". The Buy Now path is powered by your Shopify store. Returning leads and customers each get their own configured menu.',
    useCases: ['Mixed retail + enterprise', 'Growing SaaS with self-serve tier', 'High-volume + high-touch mix'],
    requiresShopify: true,
  },
]

const SHOPIFY_WARNING = 'Connect your Shopify store on the Shopify tab before enabling this mode. Contacts will be routed via the consultative path until Shopify is connected.'

export default function SalesModeConfig() {
  const [mode, setMode]               = useState('consultative')
  const [pending, setPending]         = useState('consultative')
  const [saving, setSaving]           = useState(false)
  const [loading, setLoading]         = useState(true)
  const [saveMsg, setSaveMsg]         = useState('')
  const [saveErr, setSaveErr]         = useState('')
  const [shopifyConnected, setShopifyConnected] = useState(false)

  useEffect(() => {
    Promise.all([getSalesMode(), getShopifyStatus()])
      .then(([modeRes, shopifyRes]) => {
        const m = modeRes?.data?.mode || 'consultative'
        setMode(m)
        setPending(m)
        setShopifyConnected(
          shopifyRes?.data?.connected ?? shopifyRes?.connected ?? false
        )
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setSaveMsg('')
    setSaveErr('')
    try {
      await updateSalesMode(pending)
      setMode(pending)
      setSaveMsg('Sales mode saved')
      setTimeout(() => setSaveMsg(''), 3000)
    } catch (err) {
      setSaveErr(err?.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const pendingRequiresShopify = MODES.find(m => m.value === pending)?.requiresShopify || false

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
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 6px' }}>
          Sales Mode
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0, lineHeight: 1.6 }}>
          Controls how new WhatsApp contacts enter your system. This setting affects all
          inbound WhatsApp routing for your organisation.
        </p>
      </div>

      {/* Mode cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 24 }}>
        {MODES.map(m => {
          const isSelected = pending === m.value
          return (
            <button
              key={m.value}
              onClick={() => setPending(m.value)}
              style={{
                background:   isSelected ? '#F0FAFA' : 'white',
                border:       `2px solid ${isSelected ? ds.teal : '#D6E8EC'}`,
                borderRadius: 12,
                padding:      '18px 18px 16px',
                textAlign:    'left',
                cursor:       'pointer',
                transition:   'all 0.15s',
                position:     'relative',
              }}
            >
              {/* Selected indicator */}
              {isSelected && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  background: ds.teal, color: 'white',
                  borderRadius: 20, fontSize: 10, fontWeight: 700,
                  padding: '2px 8px', fontFamily: ds.fontSyne,
                }}>
                  ACTIVE
                </div>
              )}

              <div style={{ fontSize: 26, marginBottom: 10 }}>{m.icon}</div>
              <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', marginBottom: 2 }}>
                {m.label}
              </div>
              <div style={{ fontSize: 11.5, color: ds.teal, fontWeight: 600, marginBottom: 10 }}>
                {m.tagline}
              </div>
              <div style={{ fontSize: 12.5, color: '#4a7a8a', lineHeight: 1.55, marginBottom: 12 }}>
                {m.description}
              </div>

              {/* Use cases */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginBottom: m.requiresShopify ? 12 : 0 }}>
                {m.useCases.map(uc => (
                  <div key={uc} style={{ fontSize: 11.5, color: '#7A9BAD', display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ color: ds.teal }}>✓</span> {uc}
                  </div>
                ))}
              </div>

              {/* Shopify badge */}
              {m.requiresShopify && (
                <div style={{
                  fontSize: 10.5, background: '#FFF8E7', color: '#92400E',
                  borderRadius: 5, padding: '3px 8px', display: 'inline-block', fontWeight: 600,
                }}>
                  🔗 Requires Shopify integration
                </div>
              )}
            </button>
          )
        })}
      </div>

      {/* Shopify warning — shown when a Shopify-dependent mode is selected */}
      {pendingRequiresShopify && !shopifyConnected && (
        <div style={{
          background: '#FFF8E7', border: '1px solid #FDE68A',
          borderRadius: 10, padding: '14px 18px', marginBottom: 20,
          display: 'flex', gap: 12, alignItems: 'flex-start',
        }}>
          <div style={{ fontSize: 20, flexShrink: 0 }}>⚠️</div>
          <div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: '#92400E', marginBottom: 4 }}>
              Shopify integration required
            </div>
            <div style={{ fontSize: 12.5, color: '#92400E', lineHeight: 1.55 }}>
              {SHOPIFY_WARNING}
            </div>
          </div>
        </div>
      )}

      {/* Hybrid preview — only shown when hybrid is selected */}
      {pending === 'hybrid' && (
        <div style={{
          background: '#F0FAFA', border: `1px solid ${ds.teal}30`,
          borderRadius: 12, padding: '18px 22px', marginBottom: 24,
        }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: '#0a1a24', marginBottom: 12 }}>
            New contacts will first see:
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <div style={{
              background: '#DCF8C6', borderRadius: '0 10px 10px 10px',
              padding: '10px 14px', fontSize: 13, color: '#0a1a24',
              maxWidth: 280, boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
            }}>
              Hi! How can we help you today?
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={hybridBtn}>🛒 Buy Now</div>
              <div style={hybridBtn}>💬 Speak to Sales</div>
            </div>
          </div>
          <p style={{ fontSize: 12, color: '#4a7a8a', margin: '14px 0 0', lineHeight: 1.5 }}>
            <strong>Buy Now</strong> routes to your Shopify store (requires Shopify integration).{' '}
            <strong>Speak to Sales</strong> fires the qualification bot — available now.
            Returning leads will see the <strong>Returning Contact Menu</strong> and known customers
            will see the <strong>Known Customer Menu</strong> configured in the Contact Menus tab.
          </p>
        </div>
      )}

      {/* Unsaved changes banner */}
      {pending !== mode && (!pendingRequiresShopify || shopifyConnected) && (
        <div style={{
          background: '#FFFBEB', border: '1px solid #FDE68A',
          borderRadius: 8, padding: '10px 14px', marginBottom: 16,
          fontSize: 13, color: '#92400E',
        }}>
          ⚠ You have unsaved changes. Click Save to apply.
        </div>
      )}

      {/* Save */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleSave}
          disabled={saving || pending === mode}
          style={{
            padding: '10px 24px', background: ds.teal, color: 'white',
            border: 'none', borderRadius: 9, fontSize: 13.5, fontWeight: 600,
            fontFamily: ds.fontSyne,
            cursor: (saving || pending === mode) ? 'not-allowed' : 'pointer',
            opacity: (saving || pending === mode) ? 0.55 : 1,
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

const hybridBtn = {
  background: 'white', border: `1.5px solid ${ds.teal}`,
  borderRadius: 8, padding: '7px 18px', fontSize: 12.5,
  color: ds.teal, fontWeight: 600, fontFamily: 'inherit',
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}
