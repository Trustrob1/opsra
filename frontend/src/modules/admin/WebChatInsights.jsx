/**
 * WebChatInsights.jsx — WEBCHAT-5
 * Link and QR builder (any source tag), plus a short summary of the numbers with a button to the Web chat page.
 * WEBCHAT-RESULTS-1: the full numbers (funnel, by source, chat facts, AI cost, goals) moved to the Web chat page in the left menu.
 */
import { useEffect, useMemo, useState } from 'react'
import { getWebchatAnalytics, getWebchatQr } from '../../services/webchat.service'
import { headline } from '../webchat/resultsView'
import { ds } from '../../utils/ds'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const input = { boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
const h = { fontSize: 15, fontWeight: 700, color: ds.dark, margin: '0 0 8px', fontFamily: ds.fontDm }
const small = { fontSize: 12, color: ds.gray, margin: '6px 0 0' }

const cleanTag = (v) => (v || '').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 30)

export default function WebChatInsights({ baseLink }) {
  const [an, setAn] = useState(null)
  const [tag, setTag] = useState('flyer')
  const [qr, setQr] = useState('')
  const [qrErr, setQrErr] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {          // a one-line summary for the card below; the page in the left menu has the full numbers
    let live = true
    getWebchatAnalytics(30).then((d) => live && setAn(d)).catch(() => {})
    return () => { live = false }
  }, [])

  const t = cleanTag(tag) || 'link'
  const link = useMemo(() => (baseLink ? `${baseLink.split('?')[0]}?s=${t}` : ''), [baseLink, t])

  useEffect(() => {
    let live = true
    setQrErr('')
    const id = setTimeout(() => {
      getWebchatQr(t).then((svg) => live && setQr(svg)).catch(() => live && (setQr(''), setQrErr('QR code did not load.')))
    }, 300)
    return () => { live = false; clearTimeout(id) }
  }, [t])

  const qrUrl = useMemo(() => (qr ? URL.createObjectURL(new Blob([qr], { type: 'image/svg+xml' })) : ''), [qr])
  useEffect(() => () => { if (qrUrl) URL.revokeObjectURL(qrUrl) }, [qrUrl])

  const copy = async () => {
    try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* ignore */ }
  }
  const save = () => {
    if (!qrUrl) return
    const a = document.createElement('a'); a.href = qrUrl; a.download = `chat-qr-${t}.svg`; a.click()
  }

  return (
    <>
      <div style={card}>
        <p style={h}>Make a tagged link or QR code</p>
        <p style={small}>Pick a name for where you will put it (flyer, shop-door, tiktok, radio). The Web chat page then shows how many people came from it.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
          <input aria-label="Source tag" style={{ ...input, width: 160 }} value={tag} maxLength={30} onChange={(e) => setTag(e.target.value)} />
          <input readOnly aria-label="Tagged link" style={{ ...input, flex: 1, minWidth: 220 }} value={link} onFocus={(e) => e.target.select()} />
          <button type="button" style={btn(false)} onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12 }}>
          {qrUrl ? <img src={qrUrl} alt={`QR code for ${t}`} style={{ width: 120, height: 120, border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm }} /> : <div style={{ width: 120, height: 120, background: '#f3f5f7', borderRadius: ds.radius.sm }} />}
          <div>
            <button type="button" style={btn(true)} onClick={save} disabled={!qrUrl}>Download QR (SVG)</button>
            <p style={small}>SVG stays sharp at any print size.</p>
            {qrErr && <p style={{ ...small, color: ds.red }}>{qrErr}</p>}
          </div>
        </div>
      </div>

      <div style={card}>
        <p style={h}>How the chat is doing</p>
        <p style={{ fontSize: 14, color: ds.dark, margin: '0 0 10px' }}>{an ? `Last 30 days: ${headline(an.funnel.steps)}.` : 'Your numbers are on the Web chat page.'}</p>
        <button type="button" style={btn(true)} onClick={() => window.dispatchEvent(new CustomEvent('opsra:goto', { detail: 'webchat' }))}>Open Web chat results</button>
        <p style={small}>Also in the left menu, under Conversations.</p>
      </div>
    </>
  )
}
