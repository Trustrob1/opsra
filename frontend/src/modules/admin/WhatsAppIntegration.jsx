/**
 * frontend/src/modules/admin/WhatsAppIntegration.jsx
 * MULTI-ORG-WA-1 — Per-org WhatsApp Business number connection management.
 *
 * Allows owner/ops_manager to connect their org's WhatsApp Business number
 * by supplying a Phone Number ID and Access Token from Meta for Developers.
 * Credentials are verified against Meta Graph API before being saved.
 *
 * Pattern 50: all API calls via admin.service.js (axios + _h()).
 * Pattern 51: full rewrite only — never sed.
 * S3: access token is never returned or displayed after save.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import {
  getWhatsAppStatus,
  connectWhatsApp,
  disconnectWhatsApp,
} from '../../services/admin.service'

export default function WhatsAppIntegration() {
  const [status, setStatus]                   = useState(null)
  const [loading, setLoading]                 = useState(true)
  const [saving, setSaving]                   = useState(false)
  const [disconnecting, setDisconnecting]     = useState(false)
  const [showForm, setShowForm]               = useState(false)
  const [showDisconnectModal, setShowDisconnectModal] = useState(false)
  const [flash, setFlash]                     = useState(null)

  const [form, setForm] = useState({
    whatsapp_phone_id:     '',
    whatsapp_access_token: '',
    whatsapp_waba_id:      '',
  })

  useEffect(() => { fetchStatus() }, [])

  async function fetchStatus() {
    setLoading(true)
    try {
      const data = await getWhatsAppStatus()
      setStatus(data)
    } catch {
      showFlashMsg('error', 'Could not load WhatsApp status.')
    } finally {
      setLoading(false)
    }
  }

  function showFlashMsg(type, msg) {
    setFlash({ type, msg })
    setTimeout(() => setFlash(null), 4500)
  }

  function resetForm() {
    setForm({ whatsapp_phone_id: '', whatsapp_access_token: '', whatsapp_waba_id: '' })
  }

  async function handleConnect(e) {
    e.preventDefault()
    if (!form.whatsapp_phone_id.trim() || !form.whatsapp_access_token.trim()) return
    setSaving(true)
    try {
      await connectWhatsApp({
        whatsapp_phone_id:     form.whatsapp_phone_id.trim(),
        whatsapp_access_token: form.whatsapp_access_token.trim(),
        whatsapp_waba_id:      form.whatsapp_waba_id.trim() || null,
      })
      showFlashMsg('success', 'WhatsApp connected successfully.')
      setShowForm(false)
      resetForm()
      await fetchStatus()
    } catch (e) {
      const detail = e?.response?.data?.detail
      const msg = typeof detail === 'string'
        ? detail
        : 'Connection failed. Please check your Phone ID and Access Token.'
      showFlashMsg('error', msg)
    } finally {
      setSaving(false)
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true)
    try {
      await disconnectWhatsApp()
      showFlashMsg('success', 'WhatsApp disconnected.')
      setShowDisconnectModal(false)
      await fetchStatus()
    } catch {
      showFlashMsg('error', 'Failed to disconnect. Please try again.')
    } finally {
      setDisconnecting(false)
    }
  }

  // ── Styles ───────────────────────────────────────────────────────────────

  const card = {
    background: '#0a1a24',
    border: '1px solid #1a2f3f',
    borderRadius: 10,
    padding: '22px 26px',
    marginBottom: 18,
  }

  const inputStyle = {
    width: '100%',
    background: '#0a1a24',
    border: '1px solid #1a2f3f',
    borderRadius: 7,
    padding: '9px 12px',
    color: '#e2e8f0',
    fontSize: 13,
    outline: 'none',
    boxSizing: 'border-box',
    fontFamily: ds.fontDm,
  }

  const labelStyle = {
    display: 'block',
    color: '#5a8a9f',
    fontSize: 12,
    marginBottom: 5,
    fontFamily: ds.fontDm,
  }

  const overlay = {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.55)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 2000,
  }

  const modalCard = {
    background: '#0a1a24',
    border: '1px solid #1a2f3f',
    borderRadius: 12,
    padding: 32,
    width: '100%',
    maxWidth: 480,
  }

  // ── Render ───────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#5a8a9f', fontSize: 14 }}>
        Loading WhatsApp status…
      </div>
    )
  }

  const connected = status?.connected

  return (
    <div style={{ maxWidth: 620 }}>

      {/* Flash */}
      {flash && (
        <div style={{
          background: flash.type === 'success' ? 'rgba(0,201,167,0.10)' : 'rgba(239,68,68,0.10)',
          border: `1px solid ${flash.type === 'success' ? ds.teal : '#ef4444'}`,
          borderRadius: 8, padding: '11px 15px', marginBottom: 18,
          color: flash.type === 'success' ? ds.teal : '#ef4444',
          fontSize: 13, fontFamily: ds.fontDm,
        }}>
          {flash.msg}
        </div>
      )}

      {/* Status card */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: 'white', margin: 0 }}>
            📱 WhatsApp Business Connection
          </h3>
          <span style={{
            background: connected ? 'rgba(0,201,167,0.12)' : 'rgba(251,191,36,0.12)',
            color: connected ? ds.teal : '#fbbf24',
            borderRadius: 6, padding: '4px 10px',
            fontSize: 12, fontWeight: 600, fontFamily: ds.fontDm,
          }}>
            {connected ? '● Connected' : '○ Not connected'}
          </span>
        </div>

        {connected ? (
          <>
            <div style={{ marginBottom: 14 }}>
              <div style={labelStyle}>Phone Number ID</div>
              <div style={{
                background: '#061219', border: '1px solid #1a2f3f',
                borderRadius: 6, padding: '8px 12px',
                color: '#e2e8f0', fontSize: 13, fontFamily: 'monospace',
              }}>
                {status.whatsapp_phone_id}
              </div>
            </div>
            {status.whatsapp_waba_id && (
              <div style={{ marginBottom: 14 }}>
                <div style={labelStyle}>WhatsApp Business Account ID (WABA)</div>
                <div style={{
                  background: '#061219', border: '1px solid #1a2f3f',
                  borderRadius: 6, padding: '8px 12px',
                  color: '#e2e8f0', fontSize: 13, fontFamily: 'monospace',
                }}>
                  {status.whatsapp_waba_id}
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
              <button
                onClick={() => setShowForm(true)}
                style={{
                  background: 'rgba(0,201,167,0.10)', color: ds.teal,
                  border: `1px solid ${ds.teal}`, borderRadius: 7,
                  padding: '8px 16px', cursor: 'pointer',
                  fontSize: 13, fontWeight: 500, fontFamily: ds.fontDm,
                }}
              >
                Update Credentials
              </button>
              <button
                onClick={() => setShowDisconnectModal(true)}
                style={{
                  background: 'rgba(239,68,68,0.08)', color: '#ef4444',
                  border: '1px solid rgba(239,68,68,0.3)', borderRadius: 7,
                  padding: '8px 16px', cursor: 'pointer',
                  fontSize: 13, fontWeight: 500, fontFamily: ds.fontDm,
                }}
              >
                Disconnect
              </button>
            </div>
          </>
        ) : (
          <>
            <p style={{ color: '#5a8a9f', fontSize: 13, margin: '0 0 16px', lineHeight: 1.6, fontFamily: ds.fontDm }}>
              Connect your WhatsApp Business number to enable all messaging features —
              drip sequences, broadcasts, two-way conversations, and template delivery.
            </p>
            <button
              onClick={() => setShowForm(true)}
              style={{
                background: ds.teal, color: '#061219',
                border: 'none', borderRadius: 7,
                padding: '10px 20px', cursor: 'pointer',
                fontSize: 13, fontWeight: 700, fontFamily: ds.fontDm,
              }}
            >
              Connect WhatsApp
            </button>
          </>
        )}
      </div>

      {/* Setup instructions */}
      <div style={{ ...card, borderColor: 'rgba(99,102,241,0.35)', background: 'rgba(99,102,241,0.13)' }}>
        <h4 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: 'white', margin: '0 0 10px' }}>
          📋 Where to find your credentials
        </h4>
        <ol style={{ color: '#c4cfe0', fontSize: 13, lineHeight: 1.9, paddingLeft: 18, margin: 0, fontFamily: ds.fontDm }}>
          <li>Go to <strong style={{ color: 'white' }}>Meta for Developers</strong> → Your App → WhatsApp → API Setup</li>
          <li>Copy the <strong style={{ color: 'white' }}>Phone Number ID</strong> (the numeric ID below the phone number, not the number itself)</li>
          <li>In <strong style={{ color: 'white' }}>Meta Business Manager</strong> → System Users, generate a <strong style={{ color: 'white' }}>Permanent Access Token</strong> with <code style={{ fontSize: 12, color: '#a5b4fc' }}>whatsapp_business_messaging</code> permission</li>
          <li>The <strong style={{ color: 'white' }}>WABA ID</strong> is optional but required for template submission — find it in Business Manager → WhatsApp Accounts</li>
        </ol>
        <div style={{
          marginTop: 12, padding: '9px 12px',
          background: 'rgba(251,191,36,0.15)', borderRadius: 6,
          border: '1px solid rgba(251,191,36,0.45)',
          color: '#fde68a', fontSize: 12, fontFamily: ds.fontDm,
        }}>
          ⚠️ Use a <strong>permanent</strong> access token — temporary tokens expire in 24 hours and will break all automated messaging.
        </div>
      </div>

      {/* Connect / Update form modal */}
      {showForm && (
        <div style={overlay}>
          <div style={modalCard}>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: 'white', margin: '0 0 20px' }}>
              {connected ? 'Update WhatsApp Credentials' : 'Connect WhatsApp Business'}
            </h3>

            <form onSubmit={handleConnect}>
              <div style={{ marginBottom: 14 }}>
                <label style={labelStyle}>
                  Phone Number ID <span style={{ color: '#ef4444' }}>*</span>
                </label>
                <input
                  type="text"
                  value={form.whatsapp_phone_id}
                  onChange={e => setForm(f => ({ ...f, whatsapp_phone_id: e.target.value }))}
                  placeholder="e.g. 123456789012345"
                  style={inputStyle}
                  required
                />
                <div style={{ color: '#5a8a9f', fontSize: 11, marginTop: 4, fontFamily: ds.fontDm }}>
                  Found in Meta for Developers → WhatsApp → API Setup
                </div>
              </div>

              <div style={{ marginBottom: 14 }}>
                <label style={labelStyle}>
                  Access Token <span style={{ color: '#ef4444' }}>*</span>
                </label>
                <input
                  type="password"
                  value={form.whatsapp_access_token}
                  onChange={e => setForm(f => ({ ...f, whatsapp_access_token: e.target.value }))}
                  placeholder="Permanent access token from Meta Business Manager"
                  style={inputStyle}
                  required
                />
                <div style={{ color: '#5a8a9f', fontSize: 11, marginTop: 4, fontFamily: ds.fontDm }}>
                  Must have whatsapp_business_messaging permission
                </div>
              </div>

              <div style={{ marginBottom: 22 }}>
                <label style={labelStyle}>
                  WABA ID <span style={{ color: '#5a8a9f', fontWeight: 400 }}>(optional — required for template submission)</span>
                </label>
                <input
                  type="text"
                  value={form.whatsapp_waba_id}
                  onChange={e => setForm(f => ({ ...f, whatsapp_waba_id: e.target.value }))}
                  placeholder="e.g. 987654321098765"
                  style={inputStyle}
                />
                <div style={{ color: '#5a8a9f', fontSize: 11, marginTop: 4, fontFamily: ds.fontDm }}>
                  Found in Meta Business Manager → WhatsApp Accounts
                </div>
              </div>

              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={() => { setShowForm(false); resetForm() }}
                  style={{
                    background: 'transparent', color: '#5a8a9f',
                    border: '1px solid #1a2f3f', borderRadius: 7,
                    padding: '9px 18px', cursor: 'pointer',
                    fontSize: 13, fontFamily: ds.fontDm,
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !form.whatsapp_phone_id.trim() || !form.whatsapp_access_token.trim()}
                  style={{
                    background: saving ? '#1a2f3f' : ds.teal,
                    color: saving ? '#5a8a9f' : '#061219',
                    border: 'none', borderRadius: 7,
                    padding: '9px 20px',
                    cursor: saving ? 'not-allowed' : 'pointer',
                    fontSize: 13, fontWeight: 700, fontFamily: ds.fontDm,
                  }}
                >
                  {saving ? 'Verifying with Meta…' : 'Connect'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Disconnect confirm modal */}
      {showDisconnectModal && (
        <div style={overlay}>
          <div style={{ ...modalCard, borderColor: 'rgba(239,68,68,0.3)', maxWidth: 420 }}>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#ef4444', margin: '0 0 12px' }}>
              Disconnect WhatsApp?
            </h3>
            <p style={{ color: '#5a8a9f', fontSize: 13, margin: '0 0 22px', lineHeight: 1.6, fontFamily: ds.fontDm }}>
              This will remove your WhatsApp credentials from Opsra. All automated
              messaging — drip sequences, broadcasts, and alerts — will stop
              immediately until you reconnect.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowDisconnectModal(false)}
                style={{
                  background: 'transparent', color: '#5a8a9f',
                  border: '1px solid #1a2f3f', borderRadius: 7,
                  padding: '9px 18px', cursor: 'pointer',
                  fontSize: 13, fontFamily: ds.fontDm,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                style={{
                  background: 'rgba(239,68,68,0.12)', color: '#ef4444',
                  border: '1px solid rgba(239,68,68,0.35)', borderRadius: 7,
                  padding: '9px 18px',
                  cursor: disconnecting ? 'not-allowed' : 'pointer',
                  fontSize: 13, fontWeight: 600, fontFamily: ds.fontDm,
                }}
              >
                {disconnecting ? 'Disconnecting…' : 'Yes, Disconnect'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
