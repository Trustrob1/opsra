/**
 * frontend/src/modules/admin/CatalogShareProduct.jsx
 * STORE-5b: "Share this product" window. The link is the product's own page, so a customer can pick a size,
 * add to cart and pay from it. The size (optional) and a where-I-share tag are added to the link, and the same link
 * is the QR code. Notices at the top say when the link would not do what the owner hopes (hidden, out of stock, ...).
 */
import { useEffect, useRef, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { catalogErrorText } from './catalogErrors'
import {
  SHARE_PRESETS, SHARE_TAG_MAX, cleanTag, productWarnings, whatsappShareLink, productQrFileName,
} from './catalogStorefrontLogic'

const H = { fontFamily: ds.fontDm, fontSize: 14, fontWeight: 800, color: '#0a1a24', margin: 0 }
const SUB = { fontFamily: ds.fontDm, fontSize: 12, lineHeight: 1.5, color: '#5C6166', margin: '4px 0 0' }
const INPUT = {
  width: '100%', minHeight: 48, padding: '0 14px', borderRadius: 12, border: '1px solid #C9C6BF', fontFamily: ds.fontDm,
  fontSize: 14, color: '#0a1a24', background: 'white', boxSizing: 'border-box', outline: 'none',
}
const BTN = { minHeight: 48, padding: '0 18px', border: 'none', borderRadius: 12, background: ds.teal, color: 'white', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, cursor: 'pointer', minWidth: 108 }
const OUTLINE = { minHeight: 44, padding: '0 16px', border: '1px solid #14181B', borderRadius: 12, background: 'white', color: '#14181B', fontFamily: ds.fontDm, fontSize: 13, fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8, textDecoration: 'none', boxSizing: 'border-box' }

function focusables(root) {
  return [...root.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')]
}

export default function CatalogShareProduct({ item, onClose, onItemChanged }) {
  const [info, setInfo] = useState(null)
  const [tag, setTag] = useState('')
  const [custom, setCustom] = useState('')
  const [variant, setVariant] = useState('')
  const [qr, setQr] = useState('')
  const [qrError, setQrError] = useState('')
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const [fixing, setFixing] = useState(false)
  const [reload, setReload] = useState(0)
  const panel = useRef(null)
  const returnTo = useRef(null)

  // The link follows the choices; wait a moment so typing a tag does not ask on every key.
  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => {
      adminSvc.getCatalogShare({ item: item.id, ...(variant ? { variant } : {}), ...(tag ? { src: tag } : {}) })
        .then((d) => { if (alive) { setInfo(d); setError('') } })
        .catch((e) => { if (alive) setError(catalogErrorText(e, 'Could not make the link. Please try again.')) })
    }, info ? 300 : 0)
    return () => { alive = false; clearTimeout(timer) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, tag, variant, reload])

  const link = info && info.link                         // the page itself: Open page and the QR code
  const shareLink = (info && (info.share_link || info.link)) || ''   // STORE-5c: the one to send; chat apps show the photo from it
  useEffect(() => {
    if (!link) return undefined
    let alive = true
    adminSvc.getCatalogQr(tag, { item: item.id, ...(variant ? { variant } : {}) })
      .then((svg) => { if (alive) { setQr(svg); setQrError('') } })
      .catch(() => { if (alive) { setQr(''); setQrError('Could not make the QR code. Please try again.') } })
    return () => { alive = false }
  }, [link, tag, variant, item.id])

  // Focus moves into the window, Escape closes it, and focus goes back to the button that opened it.
  useEffect(() => {
    returnTo.current = document.activeElement
    const t = setTimeout(() => { if (panel.current) panel.current.focus() }, 0)
    return () => { clearTimeout(t); if (returnTo.current && returnTo.current.focus) returnTo.current.focus() }
  }, [])

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
    if (e.key !== 'Tab' || !panel.current) return
    const f = focusables(panel.current)
    if (!f.length) return
    const first = f[0], last = f[f.length - 1]
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(shareLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { setError('Could not copy. Select the link and copy it by hand.') }
  }

  async function downloadQr() {
    try {
      const svg = await adminSvc.getCatalogQr(tag, { item: item.id, ...(variant ? { variant } : {}) })
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
      const a = document.createElement('a')
      a.href = url
      a.download = productQrFileName(info && info.item && info.item.slug)
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { setError('Could not download the QR code. Please try again.') }
  }

  async function showInCatalog() {
    setFixing(true); setError('')
    try {
      const updated = await adminSvc.updateCatalogItem(item.id, { catalog_visible: true })
      if (onItemChanged) onItemChanged(updated || { id: item.id, catalog_visible: true })
      setReload((n) => n + 1)
    } catch (e) {
      setError(catalogErrorText(e, 'Could not show this product. Please try again.'))
    } finally { setFixing(false) }
  }

  const it = (info && info.item) || { title: item.title, price: item.price, image: (item.catalog_images || [])[0] }
  const price = it.price != null && it.price !== '' ? `₦${Number(it.price).toLocaleString()}` : ''
  const warnings = productWarnings(info && info.warnings)
  const sizes = (info && info.sizes) || []

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1100 }} onKeyDown={onKeyDown}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.35)' }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Share this product" tabIndex={-1} style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 'min(480px, 100%)', background: 'white', display: 'flex', flexDirection: 'column',
        outline: 'none', boxShadow: '-4px 0 32px rgba(0,0,0,0.15)',
      }}>
        <div style={{ height: 68, padding: '0 12px 0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #E6E4DF', flexShrink: 0 }}>
          <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24' }}>Share this product</div>
          <button onClick={onClose} aria-label="Close" style={{ width: 44, height: 44, border: 0, background: 'transparent', fontSize: 20, cursor: 'pointer', color: '#7A9BAD' }}>✕</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '22px 24px 8px' }}>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
            <div style={{ width: 64, height: 72, borderRadius: 10, flexShrink: 0, background: it.image ? `#F4F2EE url(${it.image}) center/cover` : 'repeating-linear-gradient(135deg, #E4E9E7 0 8px, #F4F2EE 8px 16px)' }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: ds.fontDm, fontSize: 17, fontWeight: 800, color: '#0a1a24' }}>{it.title}</div>
              {price && <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 13, color: '#3A3F44' }}>{price}</div>}
            </div>
          </div>

          {warnings.map((w) => (
            <div key={w.code} role="status" style={{ marginTop: 16, padding: '14px 16px', borderRadius: 12, background: '#FFF4E0', border: '1px solid #F0D9A8', display: 'flex', gap: 14, alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#5A4300' }}><b style={{ fontWeight: 800 }}>{w.title}</b> {w.text}</div>
              {w.fix && w.code === 'hidden' && (
                <button onClick={showInCatalog} disabled={fixing} style={{ ...OUTLINE, borderColor: '#5A4300', color: '#5A4300', flexShrink: 0 }}>{fixing ? 'Showing…' : w.fix}</button>
              )}
            </div>
          ))}

          <div style={{ marginTop: 24 }}>
            <h3 style={H}>Product link</h3>
            <p style={SUB}>Send this link. WhatsApp, Facebook and Instagram show the photo, name and price. Customers pick a size, add to cart and pay. No sign-up.</p>
            <div style={{ marginTop: 10, display: 'flex', gap: 10 }}>
              <div aria-label="Product link" style={{ ...INPUT, flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', fontSize: 13, fontWeight: 600, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{shareLink || 'Making your link…'}</div>
              <button onClick={copy} disabled={!shareLink} style={BTN}>{copied ? 'Copied' : 'Copy link'}</button>
            </div>
            <div style={{ marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {link ? <a href={link} target="_blank" rel="noopener noreferrer" style={OUTLINE}>Open page</a> : <span />}
              {link && <a href={whatsappShareLink(shareLink, it.title)} target="_blank" rel="noopener noreferrer" style={OUTLINE}>Send on WhatsApp</a>}
            </div>
          </div>

          {sizes.length > 0 && (
            <div style={{ marginTop: 24 }}>
              <label htmlFor="sp-size" style={{ ...H, display: 'block' }}>Size shown first <span style={{ fontWeight: 500, color: '#5C6166' }}>(optional)</span></label>
              <select id="sp-size" value={variant} onChange={(e) => setVariant(e.target.value)} style={{ ...INPUT, marginTop: 8, cursor: 'pointer' }}>
                <option value="">Customer chooses</option>
                {sizes.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <p style={SUB}>The page opens with that size already picked.</p>
            </div>
          )}

          <div style={{ marginTop: 24 }}>
            <h3 style={H}>Where will you share it?</h3>
            <p style={SUB}>The link is tagged, so orders show where they came from.</p>
            <div role="group" aria-label="Where will you share it" style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {SHARE_PRESETS.map((p) => (
                <button key={p.tag} type="button" aria-pressed={tag === p.tag} onClick={() => { setTag(tag === p.tag ? '' : p.tag); setCustom('') }} style={{
                  minHeight: 40, padding: '0 14px', borderRadius: 20, fontFamily: ds.fontDm, fontSize: 13, fontWeight: 700, cursor: 'pointer',
                  border: `1px solid ${tag === p.tag ? ds.teal : '#C9C6BF'}`, background: tag === p.tag ? ds.teal : 'white', color: tag === p.tag ? 'white' : '#14181B',
                }}>{p.label}</button>
              ))}
            </div>
            <div style={{ marginTop: 12 }}>
              <label htmlFor="sp-own" style={{ fontFamily: ds.fontDm, fontSize: 12, fontWeight: 700, color: '#5C6166' }}>Or name your own <span style={{ fontWeight: 400 }}>(letters and numbers, up to {SHARE_TAG_MAX})</span></label>
              <input id="sp-own" value={custom} placeholder="radio-ad" maxLength={SHARE_TAG_MAX + 10} style={{ ...INPUT, marginTop: 6 }}
                onChange={(e) => { setCustom(e.target.value); setTag(cleanTag(e.target.value)) }} />
              {custom && cleanTag(custom) !== custom.trim().toLowerCase() && (
                <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>We will use: {cleanTag(custom) || 'no tag'}</div>
              )}
            </div>
          </div>

          <div style={{ marginTop: 24, display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ width: 128, height: 128, border: '1px solid #E6E4DF', borderRadius: 12, padding: 6, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              {qr
                ? <img alt={`QR code for ${it.title}`} width={114} height={114} src={`data:image/svg+xml;utf8,${encodeURIComponent(qr)}`} />
                : <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD', textAlign: 'center' }}>{qrError || 'Making QR…'}</span>}
            </div>
            <div style={{ flex: '1 1 180px' }}>
              <p style={{ fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#3A3F44', margin: '0 0 10px' }}>Print it on the product's box, tag or shelf label. A scan opens this product.</p>
              <button onClick={downloadQr} disabled={!qr} style={OUTLINE}>Download QR code</button>
            </div>
          </div>

          {error && <p role="alert" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#c0392b', margin: '16px 0 0' }}>{error}</p>}
        </div>

        <div style={{ flexShrink: 0, padding: '14px 24px 18px', borderTop: '1px solid #E6E4DF', fontFamily: ds.fontDm, fontSize: 12, lineHeight: 1.5, color: '#5C6166' }}>
          Customers who add to cart from a tagged link are counted under that tag in Admin, Web Chat, Insights.
        </div>
      </div>
    </div>
  )
}
