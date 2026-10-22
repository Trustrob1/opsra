/**
 * frontend/src/catalog/storefront/StorefrontChrome.jsx
 * STORE-2/3: pieces shared by every Storefront page: font, colours, announcement bar, header, footer.
 */
import { readableOn, initials } from './storefrontLogic'
import { INK, MUTED, LINE } from './storefrontTheme'

export function Icon({ children, size = 22, stroke = INK, width = 1.8 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke}
      strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}

export function WhatsAppIcon({ stroke = '#fff' }) {
  return (
    <Icon size={20} stroke={stroke} width={1.9}>
      <path d="M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 20.5l1.7-5A8.5 8.5 0 1 1 21 11.5z" />
    </Icon>
  )
}

/** Layout and focus rules used by all Storefront pages. */
export function ChromeStyles({ accent }) {
  return (
    <style>{`
      .sf-root a { color: inherit; text-decoration: none }
      .sf-root button, .sf-root input { font-family: inherit }
      .sf-root :focus-visible { outline: 3px solid ${accent}; outline-offset: 2px }
      .sf-wrap { max-width: 1200px; margin: 0 auto; padding: 0 40px; box-sizing: border-box }
      .sf-head { display: flex; align-items: center; gap: 24px; min-height: 72px }
      .sf-nav { flex-grow: 1; display: flex; gap: 8px; font-size: 14px; font-weight: 600; overflow-x: auto; scrollbar-width: none }
      .sf-nav::-webkit-scrollbar { display: none }
      .sf-search-slot { flex-grow: 1; max-width: 460px }
      @media (max-width: 900px) {
        .sf-wrap { padding: 0 16px }
        .sf-head { flex-wrap: wrap; gap: 8px 12px; padding: 8px 0 }
        .sf-nav { order: 3; flex-basis: 100%; padding-bottom: 4px }
        .sf-search-slot { order: 3; flex-basis: 100%; max-width: none }
      }
    `}</style>
  )
}

export function Announcement({ style }) {
  if (!style?.announcement) return null
  return (
    <div style={{ background: INK, color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', padding: '11px 24px' }}>
      {style.announcement}
    </div>
  )
}

/**
 * Header: brand on the left (goes to the full list), whatever the page needs after it (search or menu) in `children`.
 */
export function StorefrontHeader({ orgName, style, accent, onHome, cart, children }) {
  const onAccent = readableOn(accent)
  return (
    <header style={{ borderBottom: `1px solid ${LINE}`, background: '#fff' }}>
      <div className="sf-wrap sf-head">
        <button onClick={onHome} aria-label={`${orgName}, all products`} style={{
          display: 'flex', alignItems: 'center', gap: 10, border: 0, background: 'transparent', cursor: 'pointer', padding: 0, minHeight: 44, color: INK,
        }}>
          {style?.logo_url ? (
            <img src={style.logo_url} alt="" style={{ height: 36, width: 'auto', borderRadius: 8 }} />
          ) : (
            <span style={{
              width: 36, height: 36, borderRadius: 10, background: accent, color: onAccent,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 15,
            }}>{initials(orgName)}</span>
          )}
          <span style={{ fontWeight: 800, fontSize: 20, letterSpacing: '-0.01em' }}>{orgName}</span>
        </button>
        {children}
        {cart && (
          <button onClick={cart.onOpen} aria-label={`Open cart, ${cart.count} ${cart.count === 1 ? 'item' : 'items'}`} style={{
            marginLeft: 'auto', position: 'relative', width: 44, height: 44, border: 0, background: 'transparent', cursor: 'pointer', flexShrink: 0,
          }}>
            <Icon size={24} width={1.8}><path d="M6 8h12l-1 12H7L6 8z" /><path d="M9 8V6.5a3 3 0 0 1 6 0V8" /></Icon>
            {cart.count > 0 && (
              <span style={{
                position: 'absolute', top: 2, right: 0, minWidth: 20, height: 20, padding: '0 5px', borderRadius: 10, boxSizing: 'border-box',
                background: accent, color: onAccent, fontSize: 11, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>{cart.count}</span>
            )}
          </button>
        )}
      </div>
    </header>
  )
}

export function StorefrontFooter({ orgName, hasWhatsApp }) {
  return (
    <footer style={{ marginTop: 88, borderTop: `1px solid ${LINE}`, padding: '28px 0 36px', textAlign: 'center', fontSize: 13, color: MUTED }}>
      {orgName}{hasWhatsApp ? '. Message us on WhatsApp any time.' : ''}
    </footer>
  )
}
