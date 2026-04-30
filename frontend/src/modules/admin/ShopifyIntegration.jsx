/**
 * frontend/src/modules/admin/ShopifyIntegration.jsx
 * SHOP-1B — Shopify Integration admin UI
 *
 * Two states:
 *   Disconnected: connection card (domain + access token inputs + Connect button)
 *   Connected:    status panel (domain, product count, last sync) +
 *                 manual sync button + disconnect button with confirmation +
 *                 webhook instructions (copy-paste URL + events list)
 *
 * Pattern 50: service calls via admin.service.js only (axios + { headers: _h() }).
 * Pattern 51: full rewrite if editing later.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  getShopifyStatus,
  connectShopify,
  disconnectShopify,
  triggerShopifySync,
} from '../../services/admin.service'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WEBHOOK_URL = `${BASE}/webhooks/shopify`

const WEBHOOK_EVENTS = [
  'products/create',
  'products/update',
  'products/delete',
  'orders/create',
  'checkouts/update',
  'fulfillments/create',
]

export default function ShopifyIntegration() {
  const [status,      setStatus]      = useState(null)   // null = loading
  const [domain,      setDomain]      = useState('')
  const [clientId,    setClientId]    = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [secret,      setSecret]      = useState('')
  const [connecting,  setConnecting]  = useState(false)
  const [syncing,     setSyncing]     = useState(false)
  const [confirming,  setConfirming]  = useState(false)  // disconnect confirm modal
  const [disconnecting, setDisconnecting] = useState(false)
  const [copied,      setCopied]      = useState(false)
  const [err,         setErr]         = useState('')
  const [msg,         setMsg]         = useState('')

  const load = useCallback(() => {
    getShopifyStatus()
      .then(res => setStatus(res?.data || res))
      .catch(() => setStatus({ connected: false }))
  }, [])

  useEffect(() => { load() }, [load])

  function flash(message) {
    setMsg(message)
    setTimeout(() => setMsg(''), 3500)
  }

  async function handleConnect(e) {
    e.preventDefault()
    setErr('')
    if (!domain.trim() || !clientId.trim() || !clientSecret.trim()) {
      setErr('Store domain, Client ID and Client Secret are all required.')
      return
    }
    setConnecting(true)
    try {
      await connectShopify({
        shop_domain:   domain.trim(),
        client_id:     clientId.trim(),
        client_secret: clientSecret.trim(),
        webhook_secret: secret.trim() || undefined,
      })
      flash('Shopify connected. Product sync started.')
      load()
    } catch (ex) {
      const d = ex?.response?.data
      const msg =
        d?.error?.message ||
        (typeof d?.detail === 'string' ? d.detail : d?.detail?.message) ||
        'Connection failed.'
      setErr(msg)
    } finally {
      setConnecting(false)
    }
  }

  async function handleSync() {
    setSyncing(true)
    setErr('')
    try {
      await triggerShopifySync()
      flash('Product sync started.')
      setTimeout(load, 4000) // reload status after sync kicks off
    } catch (ex) {
      setErr(ex?.response?.data?.detail || 'Sync failed.')
    } finally {
      setSyncing(false)
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true)
    setErr('')
    try {
      await disconnectShopify()
      setConfirming(false)
      flash('Shopify disconnected.')
      load()
    } catch (ex) {
      setErr(ex?.response?.data?.detail || 'Disconnect failed.')
    } finally {
      setDisconnecting(false)
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(WEBHOOK_URL).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (!status) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 13 }}>
        Loading…
      </div>
    )
  }

  const connected = status.connected

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: '#0a1a24', margin: '0 0 6px' }}>
          Shopify Integration
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0, lineHeight: 1.6 }}>
          Connect your Shopify store to enable abandoned cart recovery, order confirmations,
          and dispatch notifications via WhatsApp.
        </p>
      </div>

      {/* Flash messages */}
      {msg && (
        <div style={S.flashSuccess}>{msg}</div>
      )}
      {err && (
        <div style={S.flashErr}>⚠ {err}</div>
      )}

      {connected ? (
        /* ── Connected state ───────────────────────────────────────────── */
        <>
          {/* Status panel */}
          <div style={S.card}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={S.connectedBadge}>● Connected</div>
                <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24' }}>
                  {status.shop_domain}
                </div>
              </div>
              <button
                onClick={() => setConfirming(true)}
                style={S.disconnectBtn}
              >
                Disconnect
              </button>
            </div>

            {/* Stats row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 20 }}>
              <StatCard
                label="Products synced"
                value={status.product_count ?? '—'}
                icon="📦"
              />
              <StatCard
                label="Last sync"
                value={status.last_sync_at ? _formatDate(status.last_sync_at) : 'Never'}
                icon="🔄"
              />
              <StatCard
                label="Store"
                value={status.shop_domain || '—'}
                icon="🛍️"
                small
              />
            </div>

            {/* Manual sync */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                onClick={handleSync}
                disabled={syncing}
                style={{
                  ...S.primaryBtn,
                  opacity: syncing ? 0.6 : 1,
                  cursor: syncing ? 'not-allowed' : 'pointer',
                }}
              >
                {syncing ? 'Syncing…' : '🔄 Sync Products Now'}
              </button>
              <span style={{ fontSize: 12, color: '#7A9BAD' }}>
                Products sync automatically every night and on each Shopify event.
              </span>
            </div>
          </div>

          {/* Webhook instructions */}
          <div style={S.card}>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', marginBottom: 6 }}>
              Shopify Webhook Setup
            </div>
            <p style={{ fontSize: 13, color: '#4a7a8a', margin: '0 0 16px', lineHeight: 1.6 }}>
              In your Shopify admin go to <strong>Settings → Notifications → Webhooks</strong> and
              add the URL below for each event listed.
            </p>

            {/* Webhook URL copy */}
            <div style={{ marginBottom: 16 }}>
              <label style={S.label}>Webhook URL</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <div style={S.codeBox}>{WEBHOOK_URL}</div>
                <button onClick={handleCopy} style={S.copyBtn}>
                  {copied ? '✓ Copied' : 'Copy'}
                </button>
              </div>
            </div>

            {/* Events list */}
            <div>
              <label style={S.label}>Subscribe to these events</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
                {WEBHOOK_EVENTS.map(ev => (
                  <div key={ev} style={S.eventChip}>{ev}</div>
                ))}
              </div>
            </div>

            {/* Webhook secret note */}
            <div style={{ marginTop: 16, padding: '10px 14px', background: '#F0FAFA', borderRadius: 8, fontSize: 12.5, color: '#1a7a8a', lineHeight: 1.6 }}>
              💡 Set the same <strong>webhook secret</strong> in Shopify and in the connection form below to enable signature verification. If left blank, all incoming webhooks will be accepted without verification.
            </div>
          </div>

          {/* Disconnect confirm modal */}
          {confirming && (
            <div style={S.overlay}>
              <div style={S.modal}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>⚠️</div>
                <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: '#0a1a24', margin: '0 0 10px' }}>
                  Disconnect Shopify?
                </h3>
                <p style={{ fontSize: 13, color: '#4a7a8a', margin: '0 0 20px', lineHeight: 1.6 }}>
                  Your synced products and commerce history will be preserved, but
                  abandoned cart recovery, order confirmations, and dispatch notifications
                  will stop working immediately.
                </p>
                <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                  <button
                    onClick={() => setConfirming(false)}
                    style={S.cancelBtn}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleDisconnect}
                    disabled={disconnecting}
                    style={{ ...S.dangerBtn, opacity: disconnecting ? 0.6 : 1 }}
                  >
                    {disconnecting ? 'Disconnecting…' : 'Yes, disconnect'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      ) : (
        /* ── Disconnected state ────────────────────────────────────────── */
        <>
          {/* What you get panel */}
          <div style={{ ...S.card, background: '#F0FAFA', border: `1px solid ${ds.teal}30`, marginBottom: 20 }}>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: '#0a1a24', marginBottom: 12 }}>
              What Shopify integration enables
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {[
                { icon: '🛒', text: 'Abandoned cart recovery via WhatsApp' },
                { icon: '✅', text: 'Automatic order confirmations' },
                { icon: '📦', text: 'Dispatch & tracking notifications' },
                { icon: '🔄', text: 'Live product catalogue sync' },
              ].map(f => (
                <div key={f.text} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, color: '#1a7a8a' }}>
                  <span style={{ flexShrink: 0 }}>{f.icon}</span>
                  <span>{f.text}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Dev Dashboard instructions panel */}
          <div style={{ ...S.card, background: '#FFFBEB', border: '1px solid #FDE68A', marginBottom: 20 }}>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: '#92400E', marginBottom: 8 }}>
              📋 How to get your credentials
            </div>
            <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#78350F', lineHeight: 1.9 }}>
              <li>Go to <strong>dev.shopify.com</strong> and open your app (<em>opsra-integration</em>)</li>
              <li>Click <strong>Settings</strong> in the left sidebar</li>
              <li>Under <strong>Credentials</strong>, copy your <strong>Client ID</strong></li>
              <li>Click the eye icon to reveal your <strong>Secret</strong> and copy it</li>
              <li>Paste both below and click Connect</li>
            </ol>
          </div>

          {/* Connection form */}
          <div style={S.card}>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', marginBottom: 18 }}>
              Connect your Shopify store
            </div>

            <form onSubmit={handleConnect}>
              {/* Row 1: domain */}
              <div style={{ marginBottom: 16 }}>
                <label style={S.label}>
                  Store domain <span style={{ color: '#C0392B' }}>*</span>
                </label>
                <input
                  style={{ ...S.input, maxWidth: 360 }}
                  value={domain}
                  onChange={e => setDomain(e.target.value)}
                  placeholder="my-store.myshopify.com"
                  autoComplete="off"
                />
                <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>
                  Without https://
                </div>
              </div>

              {/* Row 2: Client ID + Client Secret */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                <div>
                  <label style={S.label}>
                    Client ID <span style={{ color: '#C0392B' }}>*</span>
                  </label>
                  <input
                    style={S.input}
                    value={clientId}
                    onChange={e => setClientId(e.target.value)}
                    placeholder="07de4763403b7fcfe2f..."
                    autoComplete="off"
                  />
                  <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>
                    dev.shopify.com → Settings → Credentials
                  </div>
                </div>
                <div>
                  <label style={S.label}>
                    Client Secret <span style={{ color: '#C0392B' }}>*</span>
                  </label>
                  <input
                    style={S.input}
                    value={clientSecret}
                    onChange={e => setClientSecret(e.target.value)}
                    placeholder="••••••••••••••••"
                    type="password"
                    autoComplete="off"
                  />
                  <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>
                    Click the eye icon in Dev Dashboard to reveal
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: 20 }}>
                <label style={S.label}>Webhook secret <span style={{ color: '#9CA3AF' }}>(optional)</span></label>
                <input
                  style={{ ...S.input, maxWidth: 360 }}
                  value={secret}
                  onChange={e => setSecret(e.target.value)}
                  placeholder="Leave blank to skip signature verification"
                  type="password"
                  autoComplete="off"
                />
              </div>

              <button
                type="submit"
                disabled={connecting}
                style={{
                  ...S.primaryBtn,
                  opacity: connecting ? 0.6 : 1,
                  cursor: connecting ? 'not-allowed' : 'pointer',
                }}
              >
                {connecting ? 'Connecting…' : '🔗 Connect Shopify'}
              </button>
            </form>
          </div>
        </>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ icon, label, value, small }) {
  return (
    <div style={{
      background: '#F8FCFD', border: '1px solid #E2EFF4',
      borderRadius: 10, padding: '14px 16px',
    }}>
      <div style={{ fontSize: 18, marginBottom: 6 }}>{icon}</div>
      <div style={{
        fontFamily: ds.fontSyne, fontWeight: 700,
        fontSize: small ? 12 : 20, color: '#0a1a24',
        marginBottom: 2, wordBreak: 'break-all',
      }}>
        {value}
      </div>
      <div style={{ fontSize: 11.5, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
        {label}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _formatDate(iso) {
  try {
    return new Date(iso).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

// ── Styles ────────────────────────────────────────────────────────────────────
const S = {
  card: {
    background: 'white', border: '1px solid #E2EFF4',
    borderRadius: 12, padding: '22px 24px', marginBottom: 20,
  },
  label: {
    display: 'block', fontSize: 11, color: '#7A9BAD',
    textTransform: 'uppercase', letterSpacing: '0.4px',
    fontWeight: 500, marginBottom: 5,
  },
  input: {
    border: '1.5px solid #D6E8EC', borderRadius: 8, padding: '8px 11px',
    fontSize: 13, fontFamily: 'inherit', outline: 'none', width: '100%',
    boxSizing: 'border-box', background: 'white',
  },
  primaryBtn: {
    padding: '10px 22px', background: '#2D9596', color: 'white',
    border: 'none', borderRadius: 9, fontSize: 13.5, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer',
  },
  disconnectBtn: {
    padding: '7px 16px', background: 'none', color: '#C0392B',
    border: '1.5px solid #C0392B', borderRadius: 8, fontSize: 13,
    fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
  },
  cancelBtn: {
    padding: '9px 20px', background: '#F0F6F8', color: '#4a7a8a',
    border: 'none', borderRadius: 8, fontSize: 13.5, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer',
  },
  dangerBtn: {
    padding: '9px 20px', background: '#C0392B', color: 'white',
    border: 'none', borderRadius: 8, fontSize: 13.5, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer',
  },
  connectedBadge: {
    background: '#DCFCE7', color: '#166534',
    borderRadius: 20, fontSize: 11.5, fontWeight: 700,
    padding: '3px 10px',
  },
  codeBox: {
    flex: 1, background: '#F5FAFB', border: '1.5px solid #D6E8EC',
    borderRadius: 8, padding: '8px 12px', fontSize: 12.5,
    color: '#1a7a8a', fontFamily: 'monospace', wordBreak: 'break-all',
  },
  copyBtn: {
    padding: '8px 14px', background: '#E0F4F6', color: '#1a7a8a',
    border: 'none', borderRadius: 7, fontSize: 12.5, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer', flexShrink: 0,
  },
  eventChip: {
    background: '#F0F6F8', border: '1px solid #D6E8EC',
    borderRadius: 6, padding: '4px 10px', fontSize: 12,
    color: '#1a7a8a', fontFamily: 'monospace',
  },
  flashSuccess: {
    background: '#DCFCE7', border: '1px solid #BBF7D0',
    borderRadius: 8, padding: '10px 14px', marginBottom: 16,
    fontSize: 13, color: '#166534',
  },
  flashErr: {
    background: '#FEF2F2', border: '1px solid #FECACA',
    borderRadius: 8, padding: '10px 14px', marginBottom: 16,
    fontSize: 13, color: '#C0392B',
  },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    background: 'white', borderRadius: 14, padding: '32px 36px',
    maxWidth: 420, width: '90%', textAlign: 'center',
    boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
  },
}
