/**
 * frontend/src/modules/admin/PaymentLinkConfig.jsx
 * PAY-LINK-1 — Paystack Storefront connect card + stage-trigger config.
 *
 * Mirrors ShopifyIntegration.jsx's visual pattern exactly (same S style
 * object, same card/label/input/button shapes) so this tab feels native
 * next to the existing integration tabs.
 *
 * Pattern 50: service calls via admin.service.js only.
 * Pattern 51: full rewrite — do not partially edit.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  getPipelineStages,
  getPaymentLinkConfig,
  updatePaymentLinkConfig,
  getPaystackStorefrontStatus,
  connectPaystackStorefront,
  disconnectPaystackStorefront,
} from '../../services/admin.service'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WEBHOOK_URL = `${BASE}/webhooks/payment/paystack-storefront`

const DEFAULT_CONFIG = {
  enabled: false,
  trigger_stage: null,
  target_stage_on_paid: null,
  deposit_ack_stage: null,
  allow_partial: false,
  message_template:
    'Hi {customer_name}! Please complete payment of {currency} {amount} to confirm your order: {link}',
}

export default function PaymentLinkConfig() {
  const [stages, setStages] = useState(null)       // pipeline stages, enabled only
  const [status, setStatus] = useState(null)        // paystack storefront connection status
  const [config, setConfig] = useState(null)        // payment_link_config
  const [publicKey, setPublicKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    getPipelineStages()
      .then(res => {
        const list = res?.stages || res?.data?.stages || []
        setStages(list.filter(s => s.enabled))
      })
      .catch(() => setStages([]))

    getPaystackStorefrontStatus()
      .then(res => setStatus(res?.data || res))
      .catch(() => setStatus({ connected: false }))

    getPaymentLinkConfig()
      .then(res => setConfig({ ...DEFAULT_CONFIG, ...(res?.data || res) }))
      .catch(() => setConfig(DEFAULT_CONFIG))
  }, [])

  useEffect(() => { load() }, [load])

  function flash(message) {
    setMsg(message)
    setTimeout(() => setMsg(''), 3500)
  }

  async function handleConnect(e) {
    e.preventDefault()
    setErr('')
    if (!publicKey.trim() || !secretKey.trim()) {
      setErr('Public key and secret key are both required.')
      return
    }
    setConnecting(true)
    try {
      await connectPaystackStorefront({
        public_key: publicKey.trim(),
        secret_key: secretKey.trim(),
      })
      flash('Paystack Storefront connected.')
      setSecretKey('')
      load()
    } catch (ex) {
      const d = ex?.response?.data
      setErr(d?.error?.message || 'Connection failed.')
    } finally {
      setConnecting(false)
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true)
    setErr('')
    try {
      await disconnectPaystackStorefront()
      setConfirming(false)
      flash('Paystack Storefront disconnected.')
      load()
    } catch (ex) {
      setErr('Disconnect failed.')
    } finally {
      setDisconnecting(false)
    }
  }

  async function handleSaveConfig() {
    setSaving(true)
    setErr('')
    try {
      await updatePaymentLinkConfig(config)
      flash('Payment link settings saved.')
    } catch (ex) {
      const d = ex?.response?.data
      setErr(d?.error?.message || 'Could not save settings — check your stage selections.')
    } finally {
      setSaving(false)
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(WEBHOOK_URL).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  function updateField(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  if (!status || !config || !stages) {
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
          Payment Links
        </h2>
        <p style={{ fontSize: 13, color: '#4a7a8a', margin: 0, lineHeight: 1.6 }}>
          Connect your own Paystack account so Opsra can send payment links to your
          customers — automatically prompted when a lead reaches a stage you choose.
        </p>
      </div>

      {msg && <div style={S.flashSuccess}>{msg}</div>}
      {err && <div style={S.flashErr}>⚠ {err}</div>}

      {connected ? (
        <div style={S.card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={S.connectedBadge}>● Connected</div>
              <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24' }}>
                Paystack Storefront
              </div>
            </div>
            {!confirming ? (
              <button onClick={() => setConfirming(true)} style={S.disconnectBtn}>Disconnect</button>
            ) : (
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => setConfirming(false)} style={S.cancelBtn}>Cancel</button>
                <button onClick={handleDisconnect} disabled={disconnecting} style={S.dangerBtn}>
                  {disconnecting ? 'Disconnecting…' : 'Confirm Disconnect'}
                </button>
              </div>
            )}
          </div>

          {/* Webhook URL */}
          <div style={{ marginBottom: 4 }}>
            <label style={S.label}>Webhook URL — add this in your Paystack dashboard</label>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <div style={S.codeBox}>{WEBHOOK_URL}</div>
              <button onClick={handleCopy} style={S.copyBtn}>{copied ? '✓ Copied' : 'Copy'}</button>
            </div>
          </div>
        </div>
      ) : (
        <form onSubmit={handleConnect} style={S.card}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', marginBottom: 6 }}>
            Connect your Paystack account
          </div>
          <p style={{ fontSize: 13, color: '#4a7a8a', margin: '0 0 16px', lineHeight: 1.6 }}>
            Charges go straight to your own Paystack account — Opsra never touches your funds.
          </p>
          <div style={{ marginBottom: 14 }}>
            <label style={S.label}>Public Key</label>
            <input
              style={S.input} value={publicKey}
              onChange={e => setPublicKey(e.target.value)}
              placeholder="pk_live_..."
            />
          </div>
          <div style={{ marginBottom: 18 }}>
            <label style={S.label}>Secret Key</label>
            <input
              style={S.input} type="password" value={secretKey}
              onChange={e => setSecretKey(e.target.value)}
              placeholder="sk_live_..."
            />
          </div>
          <button type="submit" disabled={connecting} style={{ ...S.primaryBtn, opacity: connecting ? 0.6 : 1 }}>
            {connecting ? 'Connecting…' : 'Connect Paystack'}
          </button>
        </form>
      )}

      {/* Trigger configuration — only meaningful once connected */}
      <div style={{ ...S.card, opacity: connected ? 1 : 0.5, pointerEvents: connected ? 'auto' : 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24' }}>
            Stage Trigger
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#4a7a8a' }}>
            <input
              type="checkbox" checked={!!config.enabled}
              onChange={e => updateField('enabled', e.target.checked)}
            />
            Enabled
          </label>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <label style={S.label}>Send payment link when lead reaches</label>
            <select
              style={S.input} value={config.trigger_stage || ''}
              onChange={e => updateField('trigger_stage', e.target.value || null)}
            >
              <option value="">— Select stage —</option>
              {stages.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label style={S.label}>Move to on full payment</label>
            <select
              style={S.input} value={config.target_stage_on_paid || ''}
              onChange={e => updateField('target_stage_on_paid', e.target.value || null)}
            >
              <option value="">— Select stage —</option>
              {stages.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#4a7a8a', marginBottom: 16 }}>
          <input
            type="checkbox" checked={!!config.allow_partial}
            onChange={e => updateField('allow_partial', e.target.checked)}
          />
          Allow deposit + balance (partial payments)
        </label>

        {config.allow_partial && (
          <div style={{ marginBottom: 16 }}>
            <label style={S.label}>Move to on deposit received</label>
            <select
              style={S.input} value={config.deposit_ack_stage || ''}
              onChange={e => updateField('deposit_ack_stage', e.target.value || null)}
            >
              <option value="">— Select stage —</option>
              {stages.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <p style={{ fontSize: 12, color: '#7A9BAD', margin: '6px 0 0' }}>
              e.g. "In Production" — the lead moves here on deposit, then to the
              full-payment stage above once the balance is paid.
            </p>
          </div>
        )}

        <div style={{ marginBottom: 18 }}>
          <label style={S.label}>WhatsApp message template</label>
          <textarea
            style={{ ...S.input, minHeight: 70, resize: 'vertical' }}
            value={config.message_template}
            onChange={e => updateField('message_template', e.target.value)}
          />
          <p style={{ fontSize: 12, color: '#7A9BAD', margin: '6px 0 0' }}>
            Tokens: <code>{'{customer_name}'}</code> <code>{'{amount}'}</code>{' '}
            <code>{'{currency}'}</code> <code>{'{link}'}</code>
          </p>
        </div>

        <button onClick={handleSaveConfig} disabled={saving} style={{ ...S.primaryBtn, opacity: saving ? 0.6 : 1 }}>
          {saving ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}

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
  flashSuccess: {
    background: '#DCFCE7', border: '1px solid #BBF7D0',
    borderRadius: 8, padding: '10px 14px', marginBottom: 16,
    fontSize: 13, color: '#166534',
  },
  flashErr: {
    background: '#FEE2E2', border: '1px solid #FECACA',
    borderRadius: 8, padding: '10px 14px', marginBottom: 16,
    fontSize: 13, color: '#991B1B',
  },
}
