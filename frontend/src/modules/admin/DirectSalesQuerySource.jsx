/**
 * frontend/src/modules/admin/DirectSalesQuerySource.jsx
 * Sales Data Source — chooses which sales channel feeds the WhatsApp
 * owner-query bot and PDF reports: Commerce (Shopify) or Direct Sales
 * (Business Activities > Sales Record). Mutually exclusive by design —
 * see registry.py's SALES_CHANNEL_GROUPS for why.
 *
 * This panel does NOT manage Shopify credentials — that stays on the
 * dedicated Shopify tab (ShopifyIntegration.jsx), since connecting
 * Shopify requires shop_domain/client_id/client_secret and this toggle
 * has none of that. This panel only:
 *   - shows Shopify's current connected state (read-only, for context)
 *   - lets the admin connect/disconnect Direct Sales
 *   - blocks connecting Direct Sales while Shopify is connected, with a
 *     clear pointer to the Shopify tab rather than silently disconnecting
 *     Shopify on the admin's behalf
 *
 * Backend: GET/POST/DELETE /api/v1/admin/integrations/direct-sales/*
 *          GET /api/v1/admin/shopify/status (read-only, for context)
 */
import { useState, useEffect, useCallback } from 'react'
import { Database, ShoppingBag, CheckCircle2, AlertTriangle } from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  getDirectSalesStatus,
  connectDirectSales,
  disconnectDirectSales,
  getShopifyStatus,
  disconnectShopify,
} from '../../services/admin.service'

function StatusPill({ connected }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 12, fontWeight: 600, fontFamily: ds.fontDm,
      padding: '4px 10px', borderRadius: 999,
      background: connected ? 'rgba(16,163,127,0.12)' : '#eef2f4',
      color: connected ? '#0e8a6f' : '#7a9bad',
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: connected ? '#10a37f' : '#b7c4cb',
      }} />
      {connected ? 'Connected' : 'Not connected'}
    </span>
  )
}

function ChannelCard({ icon: Icon, title, description, connected, disabled, disabledReason, children }) {
  return (
    <div style={{
      border: `1.5px solid ${connected ? ds.teal : '#dde4e8'}`,
      borderRadius: 12,
      padding: 20,
      background: connected ? 'rgba(2,128,144,0.04)' : 'white',
      opacity: disabled ? 0.6 : 1,
      transition: 'all 0.15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 9,
            background: connected ? ds.teal : '#eef2f4',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            <Icon size={17} color={connected ? 'white' : '#7a9bad'} strokeWidth={2} />
          </div>
          <div>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: 0 }}>
              {title}
            </h3>
          </div>
        </div>
        <StatusPill connected={connected} />
      </div>
      <p style={{ fontSize: 13, color: '#5a8a9f', lineHeight: 1.5, margin: '0 0 14px' }}>
        {description}
      </p>
      {disabled && disabledReason && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 8,
          background: '#FFF8E1', border: '1px solid #F5DFA0',
          borderRadius: 8, padding: '10px 12px', marginBottom: 14,
        }}>
          <AlertTriangle size={15} color="#B8860B" style={{ flexShrink: 0, marginTop: 1 }} />
          <p style={{ fontSize: 12.5, color: '#7a6420', margin: 0, lineHeight: 1.5 }}>
            {disabledReason}
          </p>
        </div>
      )}
      {children}
    </div>
  )
}

export default function DirectSalesQuerySource() {
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState(null)
  const [actionError, setActionError]   = useState(null)
  const [busy, setBusy]                 = useState(false)
  const [directSales, setDirectSales]   = useState({ connected: false })
  const [shopify, setShopify]           = useState({ connected: false })
  const [showSwitchConfirm, setShowSwitchConfirm] = useState(false)
  const [switching, setSwitching]       = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [dsStatus, shopifyStatusResponse] = await Promise.all([
        getDirectSalesStatus(),
        getShopifyStatus(),
      ])
      setDirectSales(dsStatus || { connected: false })
      // getShopifyStatus() returns the full {success, data, error} envelope
      // (unlike getDirectSalesStatus(), which already unwraps to .data.data) —
      // the real status fields are one level deeper, at .data.
      setShopify(shopifyStatusResponse?.data || { connected: false })
    } catch (e) {
      setError(e?.response?.data?.error?.message ?? 'Could not load data source status.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleConnectDirectSales = async () => {
    setBusy(true); setActionError(null)
    try {
      await connectDirectSales()
      await load()
    } catch (e) {
      const msg = e?.response?.status === 409
        ? (e?.response?.data?.error?.message ?? 'Direct Sales conflicts with the currently connected commerce source.')
        : (e?.response?.data?.error?.message ?? 'Could not connect Direct Sales. Please try again.')
      setActionError(msg)
    } finally {
      setBusy(false)
    }
  }

  const handleSwitchToDirectSales = async () => {
    setSwitching(true); setActionError(null)
    try {
      await disconnectShopify()
      await connectDirectSales()
      setShowSwitchConfirm(false)
      await load()
    } catch (e) {
      // Disconnect may have succeeded even if connect then failed — reload
      // so the cards reflect real state rather than a stale assumption.
      await load()
      setActionError(
        e?.response?.data?.error?.message ??
        'Something went wrong switching channels. Check both cards\u2019 status below before trying again.'
      )
    } finally {
      setSwitching(false)
    }
  }

  const handleDisconnectDirectSales = async () => {
    setBusy(true); setActionError(null)
    try {
      await disconnectDirectSales()
      await load()
    } catch (e) {
      setActionError(e?.response?.data?.error?.message ?? 'Could not disconnect Direct Sales. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
        Loading data source status…
      </div>
    )
  }

  const directSalesBlocked = shopify.connected && !directSales.connected

  return (
    <div style={{ maxWidth: 720 }}>
      <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 6px' }}>
        Sales Data Source
      </h2>
      <p style={{ fontSize: 13.5, color: '#5a8a9f', lineHeight: 1.6, margin: '0 0 22px', maxWidth: 560 }}>
        Choose which sales channel powers your WhatsApp owner-query answers and PDF reports.
        Only one can be active at a time — having both connected would risk double-counting
        revenue in your reports.
      </p>

      {error && (
        <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 8, padding: '10px 14px', marginBottom: 18 }}>
          <p style={{ fontSize: 13, color: '#B91C1C', margin: 0 }}>{error}</p>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <ChannelCard
          icon={ShoppingBag}
          title="Commerce (Shopify)"
          description="Live Shopify storefront orders, revenue, and fulfilment data. Manage credentials on the Shopify tab."
          connected={shopify.connected}
        >
          {shopify.connected ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: '#0e8a6f' }}>
              <CheckCircle2 size={14} />
              Currently powering your reports
              {shopify.shop_domain ? ` — ${shopify.shop_domain}` : ''}
            </div>
          ) : (
            <p style={{ fontSize: 12.5, color: '#a0b4bd', margin: 0 }}>
              Not connected. Go to the Shopify tab to connect.
            </p>
          )}
        </ChannelCard>

        <ChannelCard
          icon={Database}
          title="Direct Sales"
          description="Rep-logged and imported sales from Business Activities > Sales Record — no credentials needed."
          connected={directSales.connected}
          disabled={directSalesBlocked}
          disabledReason={directSalesBlocked
            ? 'Shopify is currently connected. Disconnect Shopify on the Shopify tab before enabling Direct Sales.'
            : null}
        >
          {actionError && (
            <p style={{ fontSize: 12.5, color: '#B91C1C', margin: '0 0 10px' }}>{actionError}</p>
          )}
          {directSales.connected ? (
            <button
              onClick={handleDisconnectDirectSales}
              disabled={busy}
              style={{
                background: 'white', color: '#B91C1C', border: '1.5px solid #FCA5A5',
                borderRadius: 8, padding: '8px 16px', fontSize: 13, fontWeight: 600,
                fontFamily: 'inherit', cursor: busy ? 'not-allowed' : 'pointer',
              }}
            >
              {busy ? 'Disconnecting…' : 'Disconnect Direct Sales'}
            </button>
          ) : directSalesBlocked ? (
            <button
              onClick={() => setShowSwitchConfirm(true)}
              style={{
                background: 'white', color: ds.teal, border: `1.5px solid ${ds.teal}`,
                borderRadius: 8, padding: '8px 16px', fontSize: 13, fontWeight: 600,
                fontFamily: 'inherit', cursor: 'pointer',
              }}
            >
              Switch to Direct Sales
            </button>
          ) : (
            <button
              onClick={handleConnectDirectSales}
              disabled={busy}
              style={{
                background: ds.teal, color: 'white',
                border: 'none', borderRadius: 8, padding: '8px 16px',
                fontSize: 13, fontWeight: 600, fontFamily: 'inherit',
                cursor: busy ? 'not-allowed' : 'pointer',
              }}
            >
              {busy ? 'Connecting…' : 'Connect Direct Sales'}
            </button>
          )}
        </ChannelCard>
      </div>

      {showSwitchConfirm && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(13,27,42,0.55)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
        }} onClick={() => !switching && setShowSwitchConfirm(false)}>
          <div style={{
            background: 'white', borderRadius: 14, padding: 26, width: '100%', maxWidth: 420,
          }} onClick={e => e.stopPropagation()}>
            <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: '#0a1a24', margin: '0 0 10px' }}>
              Switch to Direct Sales?
            </h3>
            <p style={{ fontSize: 13, color: '#5a8a9f', lineHeight: 1.6, margin: '0 0 10px' }}>
              This will disconnect Shopify — its shop domain and API credentials will
              be cleared. If you switch back to Shopify later, you'll need to
              re-enter your shop domain and API keys.
            </p>
            {actionError && (
              <p style={{ fontSize: 12.5, color: '#B91C1C', margin: '0 0 10px' }}>{actionError}</p>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 16 }}>
              <button
                onClick={() => setShowSwitchConfirm(false)}
                disabled={switching}
                style={{ background: 'white', color: '#0a1a24', border: '1.5px solid #D4E6EC', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontFamily: 'inherit', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleSwitchToDirectSales}
                disabled={switching}
                style={{ background: '#B91C1C', color: 'white', border: 'none', borderRadius: 8, padding: '9px 18px', fontSize: 13, fontWeight: 600, fontFamily: 'inherit', cursor: switching ? 'not-allowed' : 'pointer' }}
              >
                {switching ? 'Switching…' : 'Disconnect Shopify & Switch'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
