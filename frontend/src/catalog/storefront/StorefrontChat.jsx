/**
 * frontend/src/catalog/storefront/StorefrontChat.jsx
 * WEBCHAT-CATALOG-1 (CATCHAT-1 + CATCHAT-2): the floating "Chat with Chioma" button on the Storefront and the slide-up panel it
 * opens. The panel is the same chat page every other surface uses (/c/{key}), shown in a frame on this same site, so the buyer
 * never leaves the catalog. On a product page the product id goes to the chat so it opens with that product; when the visitor
 * moves to another product while the chat is open, the chat is told. Phone: the panel fills the screen. Escape closes it.
 * Nothing here is trusted for a price or a product: the chat page and server check everything.
 */
import { useEffect, useRef, useState } from 'react'
import { readableOn } from './storefrontLogic'
import { chatSrc, cleanProductId, cleanVariantId, viewingMessage, buyMessage, greetingText, greetedKey, CHIOMA_EVENT } from './storefrontChat'

const FACE = '/chioma/chioma-face-64.webp'
const FACE2 = '/chioma/chioma-face-128.webp'

export default function StorefrontChat({ chatKey, accent, orgName, productId, productTitle }) {
  const [open, setOpen] = useState(false)
  const [everOpened, setEverOpened] = useState(false)
  const [folded, setFolded] = useState(false)
  const [src, setSrc] = useState('')
  const [cardFor, setCardFor] = useState('')   // the greeted-key the card is showing for; it hides on its own when the product changes
  const frameRef = useRef(null)
  const btnRef = useRef(null)
  const lastSent = useRef('')
  const pid = cleanProductId(productId)
  const fg = readableOn(accent)
  const label = `Chat with Chioma. Virtual assistant for ${orgName || 'this shop'}`

  // The label shows first, then folds into the photo (stays if the visitor prefers reduced motion).
  useEffect(() => {
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) return undefined
    const t = setTimeout(() => setFolded(true), 4000)
    return () => clearTimeout(t)
  }, [])

  // WEBCHAT-CATALOG-1c: one short greeting card as the label folds, naming the product on a product page.
  // Once per tab per product; closes when dismissed or the chat opens; skipped for reduced-motion visitors' label timing only.
  useEffect(() => {
    if (open) return undefined
    const k = greetedKey(chatKey, pid)
    let seen = false
    try { seen = !!sessionStorage.getItem(k) } catch { /* storage can be blocked */ }
    if (seen) return undefined
    const t = setTimeout(() => {
      setCardFor(k)
      try { sessionStorage.setItem(k, '1') } catch { /* ignore */ }
    }, 4000)
    return () => clearTimeout(t)
  }, [chatKey, pid, open])
  const cardText = cardFor && cardFor === greetedKey(chatKey, pid) ? greetingText(orgName, productTitle) : ''

  const post = (m) => {
    try { if (m && frameRef.current && frameRef.current.contentWindow) frameRef.current.contentWindow.postMessage(m, window.location.origin) } catch { /* ignore */ }
  }
  // opts.product: show the chat on this product (a card on the list page); opts.buy: also put it in the cart and open the cart.
  const openChat = (opts) => {
    const want = (opts && cleanProductId(opts.product)) || pid
    const buy = opts && opts.buy && cleanProductId(opts.buy.product) ? { product: cleanProductId(opts.buy.product), variant: cleanVariantId(opts.buy.variant) } : null
    setCardFor('')
    if (!everOpened) {
      setSrc(chatSrc(chatKey, want, buy))
      lastSent.current = want
      setEverOpened(true)
    } else {
      if (want && want !== lastSent.current) { lastSent.current = want; post(viewingMessage(want)) }
      if (buy) post(buyMessage(buy.product, buy.variant))
    }
    setOpen(true)
  }
  const openRef = useRef(openChat)
  useEffect(() => { openRef.current = openChat })
  useEffect(() => {
    const on = (e) => {
      const d = (e && e.detail) || {}
      if (d.action === 'buy') openRef.current({ product: d.product, buy: { product: d.product, variant: d.variant } })
      else openRef.current({ product: d.product })
    }
    window.addEventListener(CHIOMA_EVENT, on)
    return () => window.removeEventListener(CHIOMA_EVENT, on)
  }, [])
  const closeChat = () => { setOpen(false); try { if (btnRef.current) btnRef.current.focus() } catch { /* ignore */ } }

  // Moving to another product while the chat is open: tell the chat.
  useEffect(() => {
    if (!open || !pid || pid === lastSent.current) return
    lastSent.current = pid
    const m = viewingMessage(pid)
    try { if (m && frameRef.current && frameRef.current.contentWindow) frameRef.current.contentWindow.postMessage(m, window.location.origin) } catch { /* ignore */ }
  }, [open, pid])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && open) closeChat() }
    const onMsg = (e) => {
      if (e.origin !== window.location.origin || !e.data || e.data.source !== 'opsra-chat') return
      if (e.data.type === 'close') closeChat()
    }
    document.addEventListener('keydown', onKey)
    window.addEventListener('message', onMsg)
    return () => { document.removeEventListener('keydown', onKey); window.removeEventListener('message', onMsg) }
  }, [open])

  useEffect(() => {
    if (open && everOpened) { const t = setTimeout(() => { try { frameRef.current && frameRef.current.focus() } catch { /* ignore */ } }, 200); return () => clearTimeout(t) }
    return undefined
  }, [open, everOpened])

  return (
    <>
      <style>{`
        .sfc-btn { position: fixed; right: 20px; bottom: calc(20px + env(safe-area-inset-bottom, 0px)); z-index: 900; height: 60px; min-width: 60px; padding: 0 8px; border: 0; border-radius: 999px; display: flex; align-items: center; cursor: pointer; font-family: inherit; box-shadow: 0 6px 20px rgba(20,34,43,.28); transition: transform .15s ease }
        .sfc-btn:hover { transform: scale(1.04) }
        .sfc-btn:focus-visible { outline: 3px solid #fff; box-shadow: 0 0 0 5px ${accent} }
        .sfc-av { display: block; width: 44px; height: 44px; flex: none; border-radius: 50%; border: 2px solid #fff; overflow: hidden; background: #E7EDF2 }
        .sfc-av img { width: 100%; height: 100%; object-fit: cover; display: block }
        .sfc-lbl { display: block; max-width: 190px; overflow: hidden; white-space: nowrap; font-size: 15px; font-weight: 600; margin: 0 12px 0 10px; opacity: 1; transition: max-width .3s ease, margin .3s ease, opacity .2s ease }
        .sfc-folded .sfc-lbl { max-width: 0; margin: 0; opacity: 0 }
        .sfc-card { position: fixed; right: 20px; bottom: calc(92px + env(safe-area-inset-bottom, 0px)); z-index: 900; max-width: 260px; background: #fff; color: #14222b; border: 0; text-align: left; font: inherit; font-size: 14px; line-height: 1.35; border-radius: 14px; padding: 12px 34px 12px 14px; box-shadow: 0 8px 28px rgba(20,34,43,.22); cursor: pointer; animation: sfc-rise .25s ease }
        .sfc-cx { position: absolute; top: 4px; right: 4px; width: 28px; height: 28px; border: 0; background: transparent; color: #5b6b76; font-size: 18px; line-height: 1; cursor: pointer; border-radius: 50% }
        @keyframes sfc-rise { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: none } }
        .sfc-panel { position: fixed; right: 20px; bottom: calc(92px + env(safe-area-inset-bottom, 0px)); z-index: 1100; width: 380px; height: min(640px, calc(100dvh - 112px)); background: #fff; border-radius: 18px; overflow: hidden; box-shadow: 0 12px 40px rgba(20,34,43,.3); opacity: 0; transform: translateY(14px) scale(.98); pointer-events: none; visibility: hidden; transition: opacity .18s ease, transform .18s ease, visibility 0s .18s }
        .sfc-open .sfc-panel { opacity: 1; transform: none; pointer-events: auto; visibility: visible; transition: opacity .18s ease, transform .18s ease }
        .sfc-panel iframe { width: 100%; height: 100%; border: 0; display: block; background: #fff }
        .sfc-open .sfc-btn { z-index: 1101 }
        @media (max-width: 480px) { .sfc-panel { inset: 0; width: 100%; height: 100dvh; border-radius: 0; transform: translateY(24px) } .sfc-open .sfc-panel { transform: none } .sfc-open .sfc-btn { display: none } }
        @media (max-width: 480px) { .sfc-card { left: 16px; right: 16px; max-width: none } }
        @media (prefers-reduced-motion: reduce) { .sfc-btn, .sfc-panel, .sfc-lbl { transition: none } .sfc-card { animation: none } }
      `}</style>
      <div className={`${open ? 'sfc-open' : ''} ${folded ? 'sfc-folded' : ''}`}>
        <div className="sfc-panel" role="dialog" aria-label={label} aria-hidden={!open}>
          {everOpened && <iframe ref={frameRef} src={src} title={label} allow="microphone; clipboard-write" />}
        </div>
        {!open && cardText && (
          <div className="sfc-card" role="button" tabIndex={0} onClick={() => openChat()}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openChat() } }}>
            <span>{cardText}</span>
            <button type="button" className="sfc-cx" aria-label="Dismiss" onClick={(e) => { e.stopPropagation(); setCardFor('') }}>×</button>
          </div>
        )}
        {!open && (
          <button ref={btnRef} type="button" className="sfc-btn" aria-label={label} aria-expanded="false" onClick={() => openChat()}
            style={{ background: accent, color: fg }}>
            <span className="sfc-av" aria-hidden="true"><img src={FACE} srcSet={`${FACE} 1x, ${FACE2} 2x`} alt="" width="44" height="44" /></span>
            <span className="sfc-lbl">Chat with Chioma</span>
          </button>
        )}
        {open && (
          <button type="button" className="sfc-btn" aria-label="Close chat" aria-expanded="true" onClick={closeChat}
            style={{ background: accent, color: fg, width: 60, justifyContent: 'center' }}>
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        )}
      </div>
    </>
  )
}
