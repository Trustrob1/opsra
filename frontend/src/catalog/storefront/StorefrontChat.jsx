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
import { chatSrc, cleanProductId, viewingMessage } from './storefrontChat'

const FACE = '/chioma/chioma-face-64.webp'
const FACE2 = '/chioma/chioma-face-128.webp'

export default function StorefrontChat({ chatKey, accent, orgName, productId }) {
  const [open, setOpen] = useState(false)
  const [everOpened, setEverOpened] = useState(false)
  const [folded, setFolded] = useState(false)
  const [src, setSrc] = useState('')
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

  const openChat = () => {
    if (!everOpened) {
      setSrc(chatSrc(chatKey, pid))
      lastSent.current = pid
      setEverOpened(true)
    } else if (pid && pid !== lastSent.current) {
      lastSent.current = pid
      const m = viewingMessage(pid)
      try { if (m && frameRef.current && frameRef.current.contentWindow) frameRef.current.contentWindow.postMessage(m, window.location.origin) } catch { /* ignore */ }
    }
    setOpen(true)
  }
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
        .sfc-panel { position: fixed; right: 20px; bottom: calc(92px + env(safe-area-inset-bottom, 0px)); z-index: 1100; width: 380px; height: min(640px, calc(100dvh - 112px)); background: #fff; border-radius: 18px; overflow: hidden; box-shadow: 0 12px 40px rgba(20,34,43,.3); opacity: 0; transform: translateY(14px) scale(.98); pointer-events: none; visibility: hidden; transition: opacity .18s ease, transform .18s ease, visibility 0s .18s }
        .sfc-open .sfc-panel { opacity: 1; transform: none; pointer-events: auto; visibility: visible; transition: opacity .18s ease, transform .18s ease }
        .sfc-panel iframe { width: 100%; height: 100%; border: 0; display: block; background: #fff }
        .sfc-open .sfc-btn { z-index: 1101 }
        @media (max-width: 480px) { .sfc-panel { inset: 0; width: 100%; height: 100dvh; border-radius: 0; transform: translateY(24px) } .sfc-open .sfc-panel { transform: none } .sfc-open .sfc-btn { display: none } }
        @media (prefers-reduced-motion: reduce) { .sfc-btn, .sfc-panel, .sfc-lbl { transition: none } }
      `}</style>
      <div className={`${open ? 'sfc-open' : ''} ${folded ? 'sfc-folded' : ''}`}>
        <div className="sfc-panel" role="dialog" aria-label={label} aria-hidden={!open}>
          {everOpened && <iframe ref={frameRef} src={src} title={label} allow="microphone; clipboard-write" />}
        </div>
        {!open && (
          <button ref={btnRef} type="button" className="sfc-btn" aria-label={label} aria-expanded="false" onClick={openChat}
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
