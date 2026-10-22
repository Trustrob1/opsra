/**
 * frontend/src/modules/admin/CatalogShare.jsx
 * STORE-5: "Share your store" - the short link, a tag for where it will be shared, the tagged link and its QR code.
 * Customers who add to the cart through a tagged link are counted under that tag in Admin > Web Chat > Insights.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { catalogErrorText } from './catalogErrors'
import { SHARE_PRESETS, SHARE_TAG_MAX, cleanTag, taggedLink, isPresetTag } from './catalogStorefrontLogic'

const CARD = { background: 'white', borderRadius: 12, border: '1px solid #E2EFF4', padding: 24, marginBottom: 20 }
const H = { fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: '0 0 6px' }
const P = { fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', lineHeight: 1.5, margin: '0 0 16px' }
const LABEL = { fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600, color: '#4a7a8a', marginBottom: 6, display: 'block' }
const INPUT = {
  width: '100%', padding: '11px 12px', borderRadius: 8, border: '1px solid #D0E8F0', fontFamily: ds.fontDm,
  fontSize: 13.5, color: '#0a1a24', background: 'white', boxSizing: 'border-box', outline: 'none', minHeight: 44,
}
const BTN = { background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '0 20px', minHeight: 44, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer' }
const GHOST = { background: 'white', border: '1px solid #D0E8F0', borderRadius: 8, padding: '0 16px', minHeight: 44, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, color: '#0a1a24', cursor: 'pointer' }

export default function CatalogShare({ fallbackUrl }) {
  const [info, setInfo] = useState(null)
  const [failed, setFailed] = useState('')
  const [tag, setTag] = useState('')
  const [custom, setCustom] = useState('')
  const [qr, setQr] = useState('')
  const [qrError, setQrError] = useState('')
  const [copied, setCopied] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    adminSvc.getCatalogShare()
      .then((d) => setInfo(d))
      .catch((e) => setFailed(catalogErrorText(e, 'Could not load your store link.')))
  }, [])

  // The picture follows the chosen tag.
  useEffect(() => {
    if (!info) return undefined
    let alive = true
    // wait a moment so typing a tag does not ask for a picture on every key
    const timer = setTimeout(() => {
      adminSvc.getCatalogQr(tag)
        .then((svg) => { if (alive) { setQr(svg); setQrError('') } })
        .catch(() => { if (alive) { setQr(''); setQrError('Could not make the QR code. Please try again.') } })
    }, 300)
    return () => { alive = false; clearTimeout(timer) }
  }, [info, tag])

  async function copy(which, value) {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(which)
      setTimeout(() => setCopied(''), 2000)
    } catch { setError('Could not copy. Select the link and copy it by hand.') }
  }

  async function downloadQr() {
    try {
      const svg = await adminSvc.getCatalogQr(tag)
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `store-qr-${tag || 'link'}.svg`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { setError('Could not download the QR code. Please try again.') }
  }

  if (failed) {
    if (!fallbackUrl) {
      return (
        <div style={CARD}>
          <h3 style={H}>Share your store</h3>
          <p role="alert" style={{ ...P, margin: 0, color: '#c0392b' }}>{failed}</p>
        </div>
      )
    }
    return (
      <div style={CARD}>
        <h3 style={H}>Your catalog link</h3>
        <p style={P}>Customers open this link and browse.</p>
        <div style={{ ...INPUT, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center' }}>{fallbackUrl}</div>
      </div>
    )
  }
  if (!info) return null

  const link = taggedLink(info.short_link, tag)
  const customTag = cleanTag(custom)

  function pick(t) { setTag((cur) => (cur === t ? '' : t)); setCustom('') }

  return (
    <div style={CARD}>
      <h3 style={H}>Share your store</h3>
      <p style={P}>Send customers this link, or print the QR code. Pick where you will share it so you can see what brings orders.</p>

      <span style={LABEL}>Where will you share it?</span>
      <div role="group" aria-label="Where will you share it" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {SHARE_PRESETS.map((p) => (
          <button key={p.tag} type="button" aria-pressed={tag === p.tag} onClick={() => pick(p.tag)}
            style={{ ...GHOST, minHeight: 40, padding: '0 14px', ...(tag === p.tag ? { background: ds.teal, color: 'white', border: `1px solid ${ds.teal}` } : {}) }}>
            {p.label}
          </button>
        ))}
      </div>

      <div style={{ marginTop: 14 }}>
        <label htmlFor="share-tag" style={LABEL}>Or name your own <span style={{ fontWeight: 400 }}>(letters and numbers, up to {SHARE_TAG_MAX})</span></label>
        <input id="share-tag" style={INPUT} value={custom} placeholder="radio-ad" maxLength={SHARE_TAG_MAX + 10}
          onChange={(e) => { setCustom(e.target.value); setTag(cleanTag(e.target.value)) }} />
        {custom && customTag !== custom.trim().toLowerCase() && (
          <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>We will use: {customTag || 'no tag'}</div>
        )}
      </div>

      <div style={{ marginTop: 18 }}>
        <span style={LABEL}>{tag ? `Your link for ${isPresetTag(tag) ? (SHARE_PRESETS.find((p) => p.tag === tag) || {}).label : tag}` : 'Your store link'}</span>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <div aria-label="Store link" style={{ ...INPUT, flex: '1 1 260px', display: 'flex', alignItems: 'center', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{link}</div>
          <button type="button" style={BTN} onClick={() => copy('link', link)}>{copied === 'link' ? 'Copied' : 'Copy link'}</button>
          <a href={link} target="_blank" rel="noopener noreferrer" style={{ ...GHOST, display: 'inline-flex', alignItems: 'center', textDecoration: 'none' }}>Open store</a>
        </div>
      </div>

      <div style={{ marginTop: 20, display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ width: 168, height: 168, border: '1px solid #E2EFF4', borderRadius: 12, padding: 8, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'white' }}>
          {qr
            ? <img alt={`QR code for ${link}`} width={150} height={150} src={`data:image/svg+xml;utf8,${encodeURIComponent(qr)}`} />
            : <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD', textAlign: 'center' }}>{qrError || 'Making QR…'}</span>}
        </div>
        <div style={{ flex: '1 1 220px' }}>
          <button type="button" style={GHOST} onClick={downloadQr} disabled={!qr}>Download QR code</button>
          <p style={{ ...P, margin: '10px 0 0', fontSize: 12.5 }}>
            Scanning opens your store. Customers who add something to their cart are counted under this tag in Admin, Web Chat, Insights.
          </p>
        </div>
      </div>
      {error && <p role="alert" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#c0392b', margin: '12px 0 0' }}>{error}</p>}
    </div>
  )
}
