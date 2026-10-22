/**
 * frontend/src/modules/admin/CatalogLook.jsx
 * STORE-6: "Look" screen - share the catalog link and choose how the public catalog looks
 * (Classic or Storefront), with the Storefront colour, announcement, trust points and logo.
 * Saves only the Storefront fields, so it can never overwrite the other catalog settings.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { catalogErrorText } from './catalogErrors'
import {
  ACCENT_PRESETS, ANNOUNCEMENT_MAX, TRUST_POINT_CHARS, DEFAULT_ACCENT, isHex,
  lookFromConfig, lookPayload, lookChanged, effectiveAccent, storefrontLocked,
} from './catalogStorefrontLogic'

const CARD = { background: 'white', borderRadius: 12, border: '1px solid #E2EFF4', padding: 24, marginBottom: 20 }
const H = { fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: '0 0 6px' }
const P = { fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', lineHeight: 1.5, margin: '0 0 16px' }
const LABEL = { fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600, color: '#4a7a8a', marginBottom: 6, display: 'block' }
const INPUT = {
  width: '100%', padding: '11px 12px', borderRadius: 8, border: '1px solid #D0E8F0', fontFamily: ds.fontDm,
  fontSize: 13.5, color: '#0a1a24', background: 'white', boxSizing: 'border-box', outline: 'none', minHeight: 44,
}
const BTN = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '0 22px', minHeight: 44,
  fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
}
const BTN_GHOST = {
  background: 'white', border: '1px solid #D0E8F0', borderRadius: 8, padding: '0 16px', minHeight: 44,
  fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, color: '#0a1a24', cursor: 'pointer',
}

function LookCard({ selected, locked, onPick, title, text, children }) {
  return (
    <button
      type="button" aria-pressed={selected} disabled={locked} onClick={onPick}
      style={{
        textAlign: 'left', padding: 14, borderRadius: 14, background: locked ? '#F4F8FA' : 'white',
        cursor: locked ? 'not-allowed' : 'pointer', opacity: locked ? 0.75 : 1,
        border: selected ? `2px solid ${ds.teal}` : '1px solid #D0E8F0',
      }}
    >
      {children}
      <div style={{ marginTop: 10, fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, color: '#0a1a24' }}>{title}</div>
      <div style={{ marginTop: 2, fontFamily: ds.fontDm, fontSize: 12, color: '#4a7a8a' }}>{text}</div>
    </button>
  )
}

export default function CatalogLook() {
  const [loaded, setLoaded] = useState(false)
  const [config, setConfig] = useState({})
  const [allowed, setAllowed] = useState(true)
  const [look, setLook] = useState(lookFromConfig({}))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    adminSvc.getCatalogConfigFull()
      .then((d) => {
        const c = d?.catalog_config || {}
        setConfig(c)
        setAllowed(d?.storefront_allowed !== false)
        setLook(lookFromConfig(c))
        setLoaded(true)
      })
      .catch((e) => { setError(catalogErrorText(e, 'Could not load your catalog settings. Please refresh.')); setLoaded(true) })
  }, [])

  const locked = storefrontLocked(allowed)
  const accent = effectiveAccent(look)
  const changed = lookChanged(look, config)
  const set = (k, v) => { setLook((p) => ({ ...p, [k]: v })); setError('') }
  const setPoint = (i, v) => setLook((p) => ({ ...p, trust_points: p.trust_points.map((t, n) => (n === i ? v : t)) }))

  async function save() {
    const r = lookPayload(look)
    if (r.error) { setError(r.error); return }
    setSaving(true); setError('')
    try {
      const saved = await adminSvc.updateCatalogConfig(r.payload)
      setConfig(saved || {})
      setLook(lookFromConfig(saved || {}))
      setToast('Look saved.')
      setTimeout(() => setToast(''), 3000)
    } catch (e) {
      setError(catalogErrorText(e, 'Could not save. Please try again.'))
    } finally {
      setSaving(false)
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(config.catalog_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { setError('Could not copy. Select the link and copy it by hand.') }
  }

  if (!loaded) return <div style={{ padding: 32, fontFamily: ds.fontDm, color: '#7A9BAD' }}>Loading…</div>

  const isStore = look.template === 'storefront'

  return (
    <div style={{ maxWidth: 680, padding: '4px 0 40px' }}>
      {config.catalog_url && (
        <div style={CARD}>
          <h3 style={H}>Your catalog link</h3>
          <p style={P}>Customers open this link and browse. Share it on WhatsApp, Instagram or your shop sign.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <div style={{ ...INPUT, flex: '1 1 260px', display: 'flex', alignItems: 'center', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
              {config.catalog_url}
            </div>
            <button type="button" style={BTN} onClick={copyLink}>{copied ? 'Copied' : 'Copy link'}</button>
            <a href={config.catalog_url} target="_blank" rel="noopener noreferrer"
              style={{ ...BTN_GHOST, display: 'inline-flex', alignItems: 'center', textDecoration: 'none' }}>Open catalog</a>
          </div>
        </div>
      )}

      <div style={CARD}>
        <h3 style={H}>Catalog look</h3>
        <p style={P}>Pick how your catalog looks to customers. You can switch back at any time.</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14 }}>
          <LookCard selected={!isStore} onPick={() => set('template', 'classic')} title="Classic" text="Warm and simple. Order on WhatsApp.">
            <div style={{ height: 96, borderRadius: 8, background: '#FAFAF8', border: '1px solid #E8E4DC', padding: 10, boxSizing: 'border-box' }}>
              <div style={{ height: 8, width: '60%', borderRadius: 4, background: '#D8D2C6' }} />
              <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
                {[0, 1, 2].map((i) => <div key={i} style={{ height: 44, borderRadius: 4, background: '#E8E4DC' }} />)}
              </div>
            </div>
          </LookCard>
          <LookCard selected={isStore} locked={locked && !isStore} onPick={() => set('template', 'storefront')} title="Storefront" text="Online-shop style with categories and search.">
            <div style={{ height: 96, borderRadius: 8, background: 'white', border: '1px solid #E6E4DF', padding: 10, boxSizing: 'border-box' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <div style={{ height: 8, width: '30%', borderRadius: 4, background: '#14181B' }} />
                <div style={{ height: 8, width: 14, borderRadius: 4, background: accent }} />
              </div>
              <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 5 }}>
                {['#E4E9E7', '#EAE6DE', '#E3E6EC', '#ECE4E4'].map((c) => <div key={c} style={{ height: 44, borderRadius: 6, background: c }} />)}
              </div>
            </div>
          </LookCard>
        </div>

        {locked && (
          <p role="status" style={{ ...P, marginTop: 14, marginBottom: 0, color: '#8a5a00' }}>
            {isStore
              ? 'Your plan no longer includes Storefront, so customers see Classic for now. Your Storefront settings are kept.'
              : 'Storefront is not included in your plan. Ask your Opsra contact to add it.'}
          </p>
        )}

        {isStore && (
          <div style={{ marginTop: 24 }}>
            <span style={LABEL}>Accent colour</span>
            <div role="group" aria-label="Accent colour" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              {ACCENT_PRESETS.map((p) => {
                const on = accent.toLowerCase() === p.hex.toLowerCase()
                return (
                  <button key={p.hex} type="button" aria-label={p.name} aria-pressed={on} onClick={() => set('accent', p.hex)}
                    style={{ width: 44, height: 44, borderRadius: '50%', background: p.hex, cursor: 'pointer', border: '2px solid white', boxShadow: on ? `0 0 0 3px #14181B` : '0 0 0 1px #D0E8F0' }} />
                )
              })}
              <input aria-label="Colour code" value={look.accent} placeholder={DEFAULT_ACCENT}
                onChange={(e) => set('accent', e.target.value)}
                style={{ ...INPUT, width: 130, borderColor: look.accent && !isHex(look.accent) ? '#e05c5c' : '#D0E8F0' }} />
              {look.accent && <button type="button" style={BTN_GHOST} onClick={() => set('accent', '')}>Use default</button>}
            </div>

            <div style={{ marginTop: 20 }}>
              <label htmlFor="sf-ann" style={LABEL}>Announcement bar <span style={{ fontWeight: 400 }}>(optional)</span></label>
              <input id="sf-ann" style={INPUT} value={look.announcement} maxLength={ANNOUNCEMENT_MAX + 40}
                placeholder="Delivery across Nigeria. Pay securely online or order on WhatsApp."
                onChange={(e) => set('announcement', e.target.value)} />
              <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: look.announcement.length > ANNOUNCEMENT_MAX ? '#e05c5c' : '#7A9BAD' }}>
                {look.announcement.length}/{ANNOUNCEMENT_MAX}
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <span style={LABEL}>Trust points <span style={{ fontWeight: 400 }}>(optional, up to 3 short lines)</span></span>
              <div style={{ display: 'grid', gap: 10 }}>
                {look.trust_points.map((t, i) => (
                  <input key={i} aria-label={`Trust point ${i + 1}`} style={INPUT} value={t}
                    placeholder={['Secure payment', 'Delivery across Nigeria', 'Talk to a person'][i]}
                    onChange={(e) => setPoint(i, e.target.value)} />
                ))}
              </div>
              <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>
                Shown under the order button. Up to {TRUST_POINT_CHARS} characters each. Only say what is true for your business.
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <label htmlFor="sf-logo" style={LABEL}>Logo link <span style={{ fontWeight: 400 }}>(optional)</span></label>
              <input id="sf-logo" style={INPUT} value={look.logo_url} placeholder="https://..."
                onChange={(e) => set('logo_url', e.target.value)} />
              <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>
                Without a logo, your shop name shows as initials in the accent colour.
              </div>
            </div>
          </div>
        )}

        {error && <p role="alert" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#c0392b', margin: '16px 0 0' }}>{error}</p>}

        <div style={{ marginTop: 22, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" style={{ ...BTN, opacity: saving || !changed ? 0.6 : 1 }} disabled={saving || !changed} onClick={save}>
            {saving ? 'Saving…' : 'Save look'}
          </button>
          {toast && <span role="status" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#1B6B49', fontWeight: 600 }}>{toast}</span>}
        </div>
      </div>
    </div>
  )
}
