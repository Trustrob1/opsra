/**
 * frontend/src/modules/admin/IntegrationStatus.jsx
 * Integration Status — Phase 8B
 *
 * Read-only traffic-light display of all platform integrations.
 * Status: connected (green) | not_configured (gray)
 *
 * Per Phase 8 scope decision: no reconnect button or error log here.
 * Those are Opsra team concerns (Phase 10). A note directs client admins
 * to contact Opsra support for reconnection.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

// Display metadata per integration key returned by the backend
const INTEGRATION_META = {
  whatsapp: {
    icon:  '💬',
    title: 'WhatsApp (Meta Cloud API)',
    desc:  'Inbound and outbound WhatsApp messaging via Meta Business Platform.',
  },
  meta_lead_ads: {
    icon:  '📢',
    title: 'Meta Lead Ads',
    desc:  'Receives new lead records from Facebook / Instagram ad campaigns.',
  },
  anthropic: {
    icon:  '🤖',
    title: 'Anthropic Claude API',
    desc:  'Powers AI triage, KB suggestions, ask-your-data, and digest generation.',
  },
  email: {
    icon:  '✉️',
    title: 'Resend (Email)',
    desc:  'Transactional email delivery for notifications and digests.',
  },
  redis: {
    icon:  '⚡',
    title: 'Redis (Background Jobs)',
    desc:  'Upstash Redis broker for Celery workers and scheduled tasks.',
  },
}

export default function IntegrationStatus() {
  const [integrations, setIntegrations] = useState(null)
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setIntegrations(await adminSvc.getIntegrationStatus())
    } catch {
      setError('Failed to load integration status.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 14 }}>Loading integrations…</div>
  if (error)   return (
    <div style={{ padding: 32, color: '#DC2626', fontSize: 14 }}>
      ⚠ {error}
      <button onClick={load} style={{ background: 'white', border: '1px solid #CBD5E1', borderRadius: 6, padding: '5px 10px', fontSize: 12, cursor: 'pointer', marginLeft: 10 }}>
        Retry
      </button>
    </div>
  )

  const entries = Object.entries(integrations ?? {})
  const connected    = entries.filter(([, v]) => v.status === 'connected').length
  const total        = entries.length

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>
          Integration Status
        </h2>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>
          {connected} of {total} integration{total !== 1 ? 's' : ''} connected
        </p>
      </div>

      {/* Status cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, marginBottom: 28 }}>
        {entries.map(([key, info]) => {
          const meta       = INTEGRATION_META[key] ?? { icon: '🔌', title: info.name, desc: '' }
          const connected  = info.status === 'connected'
          const statusColor = connected ? '#059669' : '#94A3B8'
          const statusBg    = connected ? '#ECFDF5' : '#F8FAFC'
          const dotColor    = connected ? '#22c55e' : '#CBD5E1'

          return (
            <div key={key} style={{
              background:   'white',
              borderRadius: 12,
              border:       `1px solid ${connected ? '#BBF7D0' : '#E4EEF2'}`,
              padding:      '20px 22px',
            }}>
              {/* Card header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 22 }}>{meta.icon}</span>
                  <div>
                    <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24' }}>
                      {meta.title}
                    </div>
                  </div>
                </div>
                {/* Status pill */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: statusBg, borderRadius: 20, padding: '4px 12px', flexShrink: 0 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor }} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: statusColor, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    {connected ? 'Connected' : 'Not Configured'}
                  </span>
                </div>
              </div>

              {/* Description */}
              <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: 0, lineHeight: 1.5 }}>
                {meta.desc}
              </p>
            </div>
          )
        })}
      </div>

      {/* Support note */}
      <div style={{
        background:   '#FEF9C3',
        border:       '1px solid #FDE68A',
        borderRadius: 10,
        padding:      '14px 18px',
        display:      'flex',
        alignItems:   'flex-start',
        gap:          12,
      }}>
        <span style={{ fontSize: 18, flexShrink: 0 }}>ℹ️</span>
        <div>
          <p style={{ fontSize: 13.5, fontWeight: 600, color: '#92400E', margin: '0 0 4px' }}>
            Need to connect or reconnect an integration?
          </p>
          <p style={{ fontSize: 13, color: '#78350F', margin: 0, lineHeight: 1.5 }}>
            Integration setup and reconnection is handled by the Opsra team.
            Please contact <strong>support@opsra.io</strong> with your organisation name
            and the integration you need help with.
          </p>
        </div>
      </div>
    </div>
  )
}
