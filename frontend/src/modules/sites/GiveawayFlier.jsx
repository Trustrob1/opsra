/**
 * frontend/src/modules/sites/GiveawayFlier.jsx
 * GIVEAWAY-4 — a downloadable flier for ONE giveaway, drawn in the browser (no image service needed).
 * Light Trust Robert look: warm grey page, navy top strip, a big navy slot count, brand-blue accents, a real website
 * shown in a browser frame and a phone frame (screenshots of alfadiva.com.ng, used with the owner's permission, kept in
 * /public/flier), and a blue strip with the QR code. Everything else comes from the giveaway itself: slots, group,
 * campaign name, fee, closing date and the giveaway's own link.
 * Feed (1080x1350) or Stories (1080x1920, key content kept out of the top 250px and bottom 340px the app covers).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { X, Download } from 'lucide-react'
import { qrSvgUrl } from '../../services/site_forms.service'
import { Button } from './sitesUi'
import { T, INPUT } from './sitesKit'

const NAVY = '#0F1733', BLUE = '#2438A8', SOFT = '#D3D9F5', ON_NAVY = '#E9EBF5', MUTED = '#A9B0D0'
const GREY = '#E4E3DF', MUTED_INK = '#5B6075'
const HEAD = '"Bricolage Grotesque", "Syne", system-ui, sans-serif'
const BODY = '"Hanken Grotesk", "DM Sans", system-ui, sans-serif'
const MONO = '"JetBrains Mono", ui-monospace, monospace'
const FONT_CSS = 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@700;800&family=Hanken+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@500&display=swap'
const W = 1080
const MOCK_SRC = { desktop: '/flier/alfa_desktop.jpg', phone: '/flier/alfa_phone.jpg' }

function loadFonts() {
  if (!document.getElementById('flier-fonts')) {
    const l = document.createElement('link')
    l.id = 'flier-fonts'; l.rel = 'stylesheet'; l.href = FONT_CSS
    document.head.appendChild(l)
  }
  const wait = Promise.all([
    document.fonts.load('800 80px "Bricolage Grotesque"'), document.fonts.load('700 30px "Hanken Grotesk"'),
    document.fonts.load('500 24px "JetBrains Mono"'),
  ]).catch(() => null)
  return Promise.race([wait, new Promise((r) => setTimeout(r, 2500))])     // never hang: fall back to the system fonts
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve(img); img.onerror = () => resolve(null)
    img.src = src
  })
}

const rr = (ctx, x, y, w, h, r) => { ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, y, w, h, r) : ctx.rect(x, y, w, h) }
const ls = (ctx, px) => { if ('letterSpacing' in ctx) ctx.letterSpacing = `${px}px` }

/** plain text, greedy wrap */
function wrap(ctx, text, maxW) {
  const words = String(text || '').split(/\s+/).filter(Boolean)
  const lines = []
  let line = ''
  for (const w of words) {
    const t = line ? `${line} ${w}` : w
    if (ctx.measureText(t).width <= maxW || !line) line = t
    else { lines.push(line); line = w }
  }
  if (line) lines.push(line)
  return lines
}

/** tokens [{t, c} | {br:true}] -> lines of tokens (greedy wrap; {br} forces a new line) */
function wrapRich(ctx, tokens, maxW) {
  const sp = ctx.measureText(' ').width
  const lines = [[]]
  let w = 0
  for (const tk of tokens) {
    if (tk.br) { lines.push([]); w = 0; continue }
    const tw = ctx.measureText(tk.t).width
    const cur = lines[lines.length - 1]
    if (cur.length && w + sp + tw > maxW) { lines.push([tk]); w = tw }
    else { cur.push(tk); w += (cur.length > 1 ? sp : 0) + tw }
  }
  return lines.filter((l) => l.length)
}

/** draw an image to fill (x,y,w,h), keeping the top of the picture */
function coverTop(ctx, img, x, y, w, h) {
  const r = Math.max(w / img.width, h / img.height)
  const sw = w / r, sh = h / r
  ctx.drawImage(img, (img.width - sw) / 2, 0, sw, sh, x, y, w, h)
}

function closesText(iso) {
  try {
    return new Date(iso).toLocaleDateString('en-NG', { timeZone: 'Africa/Lagos', day: 'numeric', month: 'short' }).toUpperCase()
  } catch { return '' }
}

function drawBrowser(ctx, img, x, y, s) {
  const bw = 620 * s, bar = 46 * s, ch = 283 * s, bh = bar + ch
  ctx.save()
  ctx.translate(x + bw / 2, y + bh / 2); ctx.rotate((-3 * Math.PI) / 180); ctx.translate(-bw / 2, -bh / 2)
  ctx.shadowColor = 'rgba(15,23,51,0.22)'; ctx.shadowBlur = 40 * s; ctx.shadowOffsetY = 24 * s
  rr(ctx, 0, 0, bw, bh, 22 * s); ctx.fillStyle = '#FFFFFF'; ctx.fill()
  ctx.shadowColor = 'transparent'
  rr(ctx, 0, 0, bw, bh, 22 * s); ctx.clip()
  ctx.fillStyle = '#EEF0F7'; ctx.fillRect(0, 0, bw, bar)
  ctx.fillStyle = '#C9CEE3'
  for (let i = 0; i < 3; i++) { ctx.beginPath(); ctx.arc((24 + i * 21) * s, bar / 2, 6.5 * s, 0, Math.PI * 2); ctx.fill() }
  rr(ctx, 86 * s, (bar - 26 * s) / 2, bw - 86 * s - 18 * s, 26 * s, 13 * s); ctx.fillStyle = '#FFFFFF'; ctx.fill()
  ctx.font = `500 ${15 * s}px ${MONO}`; ctx.fillStyle = '#8A90AB'; ctx.textBaseline = 'middle'; ls(ctx, 0)
  ctx.fillText('alfadiva.com.ng', 100 * s, bar / 2 + 1)
  ctx.textBaseline = 'alphabetic'
  if (img) coverTop(ctx, img, 0, bar, bw, ch)
  else { ctx.fillStyle = '#F1F2F9'; ctx.fillRect(0, bar, bw, ch) }
  ctx.restore()
}

function drawPhone(ctx, img, cx, y, s) {
  const pw = 270 * s, ph = 400 * s, b = 12 * s
  ctx.save()
  ctx.translate(cx, y + ph / 2); ctx.rotate((4 * Math.PI) / 180); ctx.translate(-pw / 2, -ph / 2)
  ctx.shadowColor = 'rgba(15,23,51,0.28)'; ctx.shadowBlur = 40 * s; ctx.shadowOffsetY = 24 * s
  rr(ctx, 0, 0, pw, ph, 52 * s); ctx.fillStyle = NAVY; ctx.fill()
  ctx.shadowColor = 'transparent'
  rr(ctx, b, b, pw - 2 * b, ph - 2 * b, 40 * s); ctx.clip()
  if (img) coverTop(ctx, img, b, b, pw - 2 * b, ph - 2 * b)
  else { ctx.fillStyle = '#F1F2F9'; ctx.fillRect(b, b, pw - 2 * b, ph - 2 * b) }
  ctx.restore()
}

export function drawFlier(canvas, g, opts, qrImg, mock = {}) {
  const story = opts.format === 'story'
  const H = story ? 1920 : 1350
  const M = 64
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')
  ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left'

  const stripH = story ? 330 : 120                 // navy top strip (on Stories its top 250px sits under the app bar)
  const barH = 240
  const barTop = (story ? H - 340 : H) - barH      // blue bottom strip (on Stories it ends above the app's bottom area)

  ctx.fillStyle = GREY; ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = NAVY; ctx.fillRect(0, 0, W, stripH)
  ctx.fillStyle = BLUE; ctx.fillRect(0, barTop, W, H - barTop)

  // top labels
  const labelY = story ? stripH - 48 : 70
  ctx.font = `500 26px ${MONO}`; ls(ctx, 2.5)
  ctx.fillStyle = ON_NAVY; ctx.fillText('TRUST ROBERT · OPSRA LAUNCH', M, labelY)
  if (g.ends_at) {
    ctx.fillStyle = MUTED; ctx.textAlign = 'right'; ctx.fillText(`CLOSES ${closesText(g.ends_at)}`, W - M, labelY); ctx.textAlign = 'left'
  }

  // the big slot count
  const slots = String(g.total_slots || 5)
  let ns = 560
  ctx.font = `800 ${ns}px ${HEAD}`; ls(ctx, -ns * 0.06)
  while (ns > 160 && ctx.measureText(slots).width > 380) { ns -= 20; ctx.font = `800 ${ns}px ${HEAD}`; ls(ctx, -ns * 0.06) }
  const numW = ctx.measureText(slots).width
  const numBase = stripH + 50 + ns * 0.72
  ctx.fillStyle = NAVY; ctx.fillText(slots, 44, numBase)

  // headline: "free websites for {group}"
  const RX = Math.max(300, Math.round(44 + numW + 50)), rw = W - M - RX
  const tokens = [{ t: 'free', c: NAVY }, { t: g.total_slots === 1 ? 'website' : 'websites', c: NAVY }]
  if (g.owner_name) {
    tokens.push({ br: true }, { t: 'for', c: NAVY })
    String(g.owner_name).split(/\s+/).filter(Boolean).forEach((w) => tokens.push({ t: w, c: BLUE }))
  }
  let size = 92, lines = []
  const widest = () => Math.max(...tokens.filter((t) => t.t).map((t) => ctx.measureText(t.t).width))
  for (; size >= 56; size -= 4) {
    ctx.font = `800 ${size}px ${HEAD}`; ls(ctx, -size * 0.03)
    lines = wrapRich(ctx, tokens, rw)
    if (lines.length <= 3 && widest() <= rw) break
  }
  if (lines.length > 3) {
    lines = lines.slice(0, 3)
    const last = lines[2]
    if (last.length > 1) last.pop()                        // drop the last word that did not fit, then mark the cut
    const lt = last[last.length - 1]
    last[last.length - 1] = { ...lt, t: `${lt.t.replace(/[.,;:]+$/, '')}…` }
  }
  ctx.font = `800 ${size}px ${HEAD}`; ls(ctx, -size * 0.03)
  const sp = ctx.measureText(' ').width
  let y = stripH + 50 + size * 0.8
  lines.forEach((ln, i) => {
    let x = RX
    for (const tk of ln) { ctx.fillStyle = tk.c; ctx.fillText(tk.t, x, y); x += ctx.measureText(tk.t).width + sp }
    if (i < lines.length - 1) y += size * 1.0
  })

  // campaign name + "first N forms win"
  const camp = (g.campaign_name || g.title || '').trim().toUpperCase()
  const winTxt = g.total_slots === 1 ? 'FIRST FORM WINS' : `FIRST ${g.total_slots} FORMS WIN`
  let ms = 26
  ctx.fillStyle = NAVY
  const monoSet = () => { ctx.font = `500 ${ms}px ${MONO}`; ls(ctx, 2) }
  monoSet()
  let mlines = [camp ? `${camp} · ${winTxt}` : winTxt]
  if (ctx.measureText(mlines[0]).width > rw) {
    mlines = [...(camp ? wrap(ctx, camp, rw) : []), winTxt]
    while (ms > 20 && mlines.length > 3) { ms -= 2; monoSet(); mlines = [...wrap(ctx, camp, rw), winTxt] }
    mlines = mlines.slice(-3)
  }
  y += 56
  for (const l of mlines) { ctx.fillText(l, RX, y); y += ms + 12 }
  y += -12 + 22

  // price pill + one-line caption
  const fee = `Pay only ₦${Number(g.fee_ngn || 24500).toLocaleString('en-NG')}`
  ctx.font = `700 38px ${BODY}`; ls(ctx, 0)
  const pw = Math.min(rw, ctx.measureText(fee).width + 88)
  rr(ctx, RX, y, pw, 88, 44); ctx.fillStyle = NAVY; ctx.fill()
  ctx.fillStyle = '#FFFFFF'; ctx.textAlign = 'center'; ctx.fillText(fee, RX + pw / 2, y + 57); ctx.textAlign = 'left'
  y += 88 + 46
  let cs = 25
  const cap = 'FOR DOMAIN + 1 YEAR HOSTING'
  ctx.font = `500 ${cs}px ${MONO}`; ls(ctx, 2)
  while (cs > 16 && ctx.measureText(cap).width > rw) { cs -= 1; ctx.font = `500 ${cs}px ${MONO}`; ls(ctx, 2) }
  ctx.fillStyle = NAVY; ctx.fillText(cap, RX + 6, y)

  // the real website, in a browser frame and a phone frame
  const mockTop = Math.max(y, numBase) + 50
  const avail = barTop - 30 - mockTop
  const s = Math.max(0.75, Math.min(1.0, avail / 400))
  const used = 400 * s
  const top = mockTop + Math.max(0, (avail - used) / 2)
  drawBrowser(ctx, mock.desktop, M, top + 6 * s, s)
  drawPhone(ctx, mock.phone, W - M - (270 * s) / 2 - 10, top, s)

  // bottom strip: QR + call to action + link
  const qb = 210
  ctx.save()
  ctx.shadowColor = 'rgba(15,23,51,0.22)'; ctx.shadowBlur = 30; ctx.shadowOffsetY = 12
  rr(ctx, M, barTop - 40, qb, qb, 28); ctx.fillStyle = '#FFFFFF'; ctx.fill()
  ctx.restore()
  if (qrImg) ctx.drawImage(qrImg, M + 18, barTop - 40 + 18, qb - 36, qb - 36)
  const tx = M + qb + 36, tw = W - M - tx
  ctx.font = `500 22px ${MONO}`; ls(ctx, 3); ctx.fillStyle = SOFT; ctx.fillText('SCAN OR TAP THE LINK', tx, barTop + 56)
  let ts = 56
  ctx.font = `700 ${ts}px ${HEAD}`; ls(ctx, -1)
  while (ts > 36 && ctx.measureText('Claim your free slot').width > tw) { ts -= 2; ctx.font = `700 ${ts}px ${HEAD}` }
  ctx.fillStyle = '#FFFFFF'; ctx.fillText('Claim your free slot', tx, barTop + 56 + 14 + ts * 0.8)
  const link = (g.link_url || '').replace(/^https?:\/\//, '')
  let lsz = 24
  ctx.font = `500 ${lsz}px ${MONO}`; ls(ctx, 0)
  while (lsz > 14 && ctx.measureText(link).width > tw) { lsz -= 1; ctx.font = `500 ${lsz}px ${MONO}` }
  ctx.fillStyle = SOFT; ctx.fillText(link, tx, barTop + 172)
  if (opts.contact) { ctx.font = `500 22px ${MONO}`; ctx.fillText(opts.contact.slice(0, 40), tx, barTop + 206) }
  return { width: W, height: H }
}

export default function GiveawayFlier({ giveaway, onClose, showToast }) {
  const canvasRef = useRef(null)
  const [format, setFormat] = useState('feed')
  const [contact, setContact] = useState('')
  const [qr, setQr] = useState(null)
  const [mock, setMock] = useState({})
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let alive = true, url = null
    ;(async () => {
      await loadFonts()
      const [desktop, phone] = await Promise.all([loadImage(MOCK_SRC.desktop), loadImage(MOCK_SRC.phone)])
      if (alive) setMock({ desktop, phone })
      try {
        const res = await fetch(qrSvgUrl(giveaway.slug))
        if (res.ok) {
          const blob = await res.blob()
          url = URL.createObjectURL(blob)
          const img = new Image()
          await new Promise((ok, no) => { img.onload = ok; img.onerror = no; img.src = url })
          if (alive) setQr(img)
        }
      } catch { /* the flier still works without the QR; the link is printed on it */ }
      if (alive) setReady(true)
    })()
    return () => { alive = false; if (url) URL.revokeObjectURL(url) }
  }, [giveaway.slug])

  const paint = useCallback(() => { if (canvasRef.current && ready) drawFlier(canvasRef.current, giveaway, { format, contact }, qr, mock) }, [giveaway, format, contact, qr, mock, ready])
  useEffect(() => { paint() }, [paint])

  function download() {
    const c = canvasRef.current
    if (!c) return
    c.toBlob((b) => {
      if (!b) return showToast?.('Could not make the image', 'bad')
      const a = document.createElement('a')
      a.href = URL.createObjectURL(b)
      a.download = `${giveaway.slug}-${format === 'story' ? 'stories' : 'feed'}.png`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(a.href), 2000)
    }, 'image/png')
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Giveaway flier" style={{ position: 'fixed', inset: 0, background: 'rgba(10,15,35,0.6)', zIndex: 60, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', overflowY: 'auto', padding: 16 }}>
      <div style={{ background: T.card || '#fff', borderRadius: 12, padding: 16, width: '100%', maxWidth: 520, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong style={{ fontSize: 15, color: T.ink }}>Flier: {giveaway.campaign_name || giveaway.title}</strong>
          <Button size="sm" variant="ghost" icon={X} onClick={onClose} aria-label="Close" />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {[['feed', 'Feed 4:5'], ['story', 'Stories 9:16']].map(([k, l]) => (
            <Button key={k} size="sm" variant={format === k ? 'primary' : 'secondary'} onClick={() => setFormat(k)}>{l}</Button>
          ))}
        </div>
        <label style={{ fontSize: 12.5, color: T.muted }}>Contact line (optional, e.g. WhatsApp number)
          <input style={{ ...INPUT, marginTop: 4 }} maxLength={40} value={contact} onChange={(e) => setContact(e.target.value)} placeholder="WhatsApp 0803 000 0000" /></label>
        <div style={{ background: '#e8ebf5', borderRadius: 8, padding: 8 }}>
          {!ready && <div style={{ padding: 40, textAlign: 'center', fontSize: 13, color: T.muted }}>Preparing…</div>}
          <canvas ref={canvasRef} style={{ width: '100%', height: 'auto', display: ready ? 'block' : 'none', borderRadius: 6 }} />
        </div>
        <Button variant="primary" icon={Download} disabled={!ready} onClick={download}>Download PNG</Button>
      </div>
    </div>
  )
}
