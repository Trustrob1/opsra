/**
 * frontend/src/modules/admin/CatalogLook.jsx
 * STORE-6: "Look" screen - share the catalog link and choose how the public catalog looks
 * (Classic or Storefront), with the Storefront colour, announcement, trust points and logo.
 * Saves only the Storefront fields, so it can never overwrite the other catalog settings.
 * STOREFRONT-2: the logo (both looks) and the Storefront banner photo are uploaded here and saved straight away;
 * the banner headline and text save with the rest of the look.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { catalogErrorText } from './catalogErrors'
import CatalogShare from './CatalogShare'
import {
  ACCENT_PRESETS, ANNOUNCEMENT_MAX, TRUST_POINT_CHARS, DEFAULT_ACCENT, isHex, HERO_TITLE_MAX, HERO_TEXT_MAX,
  lookFromConfig, lookPayload, lookChanged, effectiveAccent, storefrontLocked,
} from './catalogStorefrontLogic'
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1

const CARD = { background: 'white', borderRadius: 12, border: '1px solid #E1E5EC', padding: 24, marginBottom: 20 }
const H = { fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#1B1F28', margin: '0 0 6px' }
const P = { fontFamily: ds.fontDm, fontSize: 13, color: '#5B6270', lineHeight: 1.5, margin: '0 0 16px' }
const LABEL = { fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600, color: '#5B6270', marginBottom: 6, display: 'block' }
const INPUT = {
  width: '100%', padding: '11px 12px', borderRadius: 8, border: '1px solid #E1E5EC', fontFamily: ds.fontDm,
  fontSize: 13.5, color: '#1B1F28', background: 'white', boxSizing: 'border-box', outline: 'none', minHeight: 44,
}
const BTN = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '0 22px', minHeight: 44,
  fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
}
const BTN_GHOST = {
  background: 'white', border: '1px solid #E1E5EC', borderRadius: 8, padding: '0 16px', minHeight: 44,
  fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, color: '#1B1F28', cursor: 'pointer',
}

function LookCard({ selected, locked, onPick, title, text, children }) {
  return (
    <button
      type="button" aria-pressed={selected} disabled={locked} onClick={onPick}
      style={{
        textAlign: 'left', padding: 14, borderRadius: 14, background: locked ? '#F4F8FA' : 'white',
        cursor: locked ? 'not-allowed' : 'pointer', opacity: locked ? 0.75 : 1,
        border: selected ? `2px solid ${ds.teal}` : '1px solid #E1E5EC',
      }}
    >
      {children}
      <div style={{ marginTop: 10, fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, color: '#1B1F28' }}>{title}</div>
      <div style={{ marginTop: 2, fontFamily: ds.fontDm, fontSize: 12, color: '#5B6270' }}>{text}</div>
    </button>
  )
}

/** STOREFRONT-2: upload / change / remove one picture. Saves on its own (no "Save look" needed). */
function PictureField({ id, label, help, url, wide, busy, onPick, onRemove }) {
  return (
    <div style={{ marginTop: 20 }}>
      <span style={LABEL}>{label} <span style={{ fontWeight: 400 }}>(optional)</span></span>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{
          width: wide ? 200 : 120, height: wide ? 112 : 64, borderRadius: 10, border: '1px dashed #C9D2DC', background: '#F7F9FB',
          display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flex: 'none',
        }}>
          {url
            ? <img src={url} alt={`Current ${label.toLowerCase()}`} style={{ width: '100%', height: '100%', objectFit: wide ? 'cover' : 'contain' }} />
            : <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#7A8594' }}>None yet</span>}
        </div>
        <label htmlFor={id} style={{ ...BTN_GHOST, display: 'inline-flex', alignItems: 'center', opacity: busy ? 0.6 : 1, cursor: busy ? 'default' : 'pointer' }}>
          {busy ? 'Uploading…' : url ? 'Change' : 'Upload'}
        </label>
        <input id={id} type="file" accept="image/png,image/jpeg,image/webp" disabled={busy}
          style={{ position: 'absolute', width: 1, height: 1, opacity: 0, overflow: 'hidden' }}
          onChange={(e) => { const f = e.target.files && e.target.files[0]; e.target.value = ''; if (f) onPick(f) }} />
        {url && !busy && <button type="button" style={{ ...BTN_GHOST, color: '#B3261E' }} onClick={onRemove}>Remove</button>}
      </div>
      <div style={{ marginTop: 6, fontFamily: ds.fontDm, fontSize: 12, color: '#5B6270' }}>{help}</div>
    </div>
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
  const [picBusy, setPicBusy] = useState('')     // STOREFRONT-2: 'logo' | 'hero' while uploading

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

  async function changePicture(kind, file) {
    const field = kind === 'logo' ? 'logo_url' : 'hero_image_url'
    if (file && file.size > 5 * 1024 * 1024) { setError('The picture must be under 5 MB.'); return }
    setPicBusy(kind); setError('')
    try {
      const d = file ? await adminSvc.uploadCatalogLookImage(kind, file) : await adminSvc.removeCatalogLookImage(kind)
      const c = d?.catalog_config || {}
      setConfig(c)
      setLook((p) => ({ ...p, [field]: String(c[field] || '') }))
      setToast(file ? (kind === 'logo' ? 'Logo saved.' : 'Banner photo saved.') : 'Picture removed.')
      setTimeout(() => setToast(''), 3000)
    } catch (e) {
      setError(catalogErrorText(e, 'Could not save the picture. Please try again.'))
    } finally {
      setPicBusy('')
    }
  }

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

  if (!loaded) return <div style={{ padding: 32, fontFamily: ds.fontDm, color: '#5B6270' }}>Loading…</div>

  const isStore = look.template === 'storefront'

  return (
    <div style={{ maxWidth: 680, padding: '4px 0 40px' }}>
      <CatalogShare fallbackUrl={config.catalog_url} />

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

        <PictureField id="cat-logo" label="Logo" url={look.logo_url} busy={picBusy === 'logo'}
          help="Shown at the top of your catalog. PNG, JPG or WebP under 5 MB; a see-through PNG looks best. Without a logo, your shop name shows instead."
          onPick={(f) => changePicture('logo', f)} onRemove={() => changePicture('logo', null)} />

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
                style={{ ...INPUT, width: 130, border: `1px solid ${look.accent && !isHex(look.accent) ? '#e05c5c' : '#D0E8F0'}` }} />
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
              <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: '#5B6270' }}>
                Shown under the order button. Up to {TRUST_POINT_CHARS} characters each. Only say what is true for your business.
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <label htmlFor="sf-chat" style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
                <input id="sf-chat" type="checkbox" checked={look.chat_button !== false} onChange={(e) => set('chat_button', e.target.checked)}
                  style={{ width: 22, height: 22, marginTop: 1, flex: 'none' }} />
                <span>
                  <span style={{ ...LABEL, display: 'block', marginBottom: 2 }}>Show the "Chat with Chioma" button</span>
                  <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#5B6270' }}>
                    A chat button in the corner of your Storefront. Chioma answers questions about the item the customer is looking at. It shows only while your web chat is on.
                  </span>
                </span>
              </label>
            </div>

            <div style={{ marginTop: 20 }}>
              <label htmlFor="sf-hero-title" style={LABEL}>Banner headline <span style={{ fontWeight: 400 }}>(optional)</span></label>
              <input id="sf-hero-title" style={INPUT} value={look.hero_title} maxLength={HERO_TITLE_MAX + 20}
                placeholder="Welcome to our shop"
                onChange={(e) => set('hero_title', e.target.value)} />
              <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: look.hero_title.length > HERO_TITLE_MAX ? '#e05c5c' : '#7A9BAD' }}>
                {look.hero_title.length}/{HERO_TITLE_MAX}
              </div>
            </div>
            <div style={{ marginTop: 12 }}>
              <label htmlFor="sf-hero-text" style={LABEL}>Banner text <span style={{ fontWeight: 400 }}>(optional)</span></label>
              <textarea id="sf-hero-text" rows={2} style={{ ...INPUT, resize: 'vertical' }} value={look.hero_text} maxLength={HERO_TEXT_MAX + 40}
                placeholder="What you sell and why customers love it, in one short line."
                onChange={(e) => set('hero_text', e.target.value)} />
              <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: look.hero_text.length > HERO_TEXT_MAX ? '#e05c5c' : '#7A9BAD' }}>
                {look.hero_text.length}/{HERO_TEXT_MAX}. The banner is the big welcome block at the top of your shop.
              </div>
            </div>

            <PictureField id="sf-hero-img" label="Banner photo" wide url={look.hero_image_url} busy={picBusy === 'hero'}
              help="A wide photo works best (PNG, JPG or WebP, under 5 MB). Without one, your shop shows photos of your products."
              onPick={(f) => changePicture('hero', f)} onRemove={() => changePicture('hero', null)} />
          </div>
        )}

        {error && <p role="alert" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#c0392b', margin: '16px 0 0' }}>{error}</p>}

        <div style={{ marginTop: 22, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" style={{ ...BTN, opacity: saving || !changed ? 0.6 : 1 }} disabled={saving || !changed} onClick={save}>
            {saving ? 'Saving…' : 'Save look'}
          </button>
          {toast && <span role="status" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#1B6B49', fontWeight: 600 }}>{toast}</span>}
          <WhyDisabled style={{ margin: 0 }} reason={!saving && !changed && !toast ? "No changes to save yet." : ''} />
        </div>
      </div>
    </div>
  )
}
