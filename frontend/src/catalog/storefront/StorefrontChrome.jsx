/**
 * frontend/src/catalog/storefront/StorefrontChrome.jsx
 * STORE-2/3: pieces shared by every Storefront page: font, colours, announcement bar, header, footer.
 * STOREFRONT-2: sticky header with the uploaded logo, and a fuller footer (logo, trust points, WhatsApp).
 * STOREFRONT-3: a real menu (inline on computers, a menu button on phones), search as an icon, a top bar with the
 * trust points, trust cards with pictures, and a footer with Shop and Help columns.
 */
import { useState } from 'react'
import { readableOn, initials, trustPoints, trustIcon, tint } from './storefrontLogic'
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
      .sf-headbar { position: sticky; top: 0; z-index: 20; background: rgba(255,255,255,0.94); backdrop-filter: saturate(180%) blur(10px); -webkit-backdrop-filter: saturate(180%) blur(10px) }
      .sf-logo-img { height: 44px; width: auto; max-width: 180px; object-fit: contain; display: block }
      .sf-foot-grid { display: flex; gap: 32px; justify-content: space-between; flex-wrap: wrap; align-items: flex-start }
      .sf-menu { flex-grow: 1; display: flex; justify-content: center; gap: 4px; overflow-x: auto; scrollbar-width: none }
      .sf-menu::-webkit-scrollbar { display: none }
      .sf-icon-btn.sf-menu-btn { display: none }
      .sf-menu-link { border: 0; background: transparent; cursor: pointer; font-size: 14px; font-weight: 700; min-height: 44px; padding: 0 12px; white-space: nowrap; color: ${INK}; border-radius: 10px }
      .sf-menu-link:hover { background: #F4F2EE }
      .sf-icon-btn { width: 44px; height: 44px; border: 0; background: transparent; cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 12px; position: relative }
      .sf-icon-btn:hover { background: #F4F2EE }
      .sf-topbar-item + .sf-topbar-item::before { content: '·'; margin: 0 14px; opacity: .7 }
      .sf-trust-cards { display: grid; grid-template-columns: repeat(var(--n, 3), minmax(0, 1fr)); gap: 16px }
      .sf-foot-cols { display: grid; grid-template-columns: 1.4fr repeat(3, minmax(0, 1fr)); gap: 32px }
      @media (max-width: 900px) {
        .sf-menu { display: none }
        .sf-icon-btn.sf-menu-btn { display: flex }
        .sf-topbar-item + .sf-topbar-item { display: none }
        .sf-trust-cards { grid-template-columns: 1fr; gap: 10px }
        .sf-foot-cols { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px 20px }
        .sf-foot-cols > :first-child { grid-column: 1 / -1 }
        .sf-wrap { padding: 0 16px }
        .sf-head { flex-wrap: wrap; gap: 4px 6px; padding: 6px 0 }
        .sf-nav { order: 3; flex-basis: 100%; padding-bottom: 4px }
        .sf-search-slot { order: 3; flex-basis: 100%; max-width: none }
        .sf-logo-img { height: 36px; max-width: 140px }
        .sf-has-logo .sf-brand-name { display: none }
      }
    `}</style>
  )
}

/** The thin bar on top: the owner's announcement, else their trust points (STOREFRONT-3), else nothing. */
export function Announcement({ style, accent }) {
  const points = trustPoints(style)
  if (!style?.announcement && !points.length) return null
  const bg = style?.announcement ? INK : (accent || INK)
  return (
    <div style={{ background: bg, color: readableOn(bg), fontSize: 13, fontWeight: 600, textAlign: 'center', padding: '10px 16px' }}>
      {style?.announcement || points.map((t) => <span key={t} className="sf-topbar-item">{t}</span>)}
    </div>
  )
}

const TRUST_PATHS = {
  shield: ['M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3z', 'M9 12l2 2 4-4'],
  truck: ['M3 7h11v9H3z', 'M14 10h4l3 3v3h-7', 'M7 18.5a1.5 1.5 0 1 0 0 .01', 'M17 18.5a1.5 1.5 0 1 0 0 .01'],
  chat: ['M21 12a8 8 0 0 1-12 7l-5 1 1-4a8 8 0 1 1 16-4z'],
  pin: ['M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11z', 'M12 11.5a1.5 1.5 0 1 0 0-.01'],
  return: ['M4 12a8 8 0 1 0 2.5-5.8', 'M4 4v4h4'],
  badge: ['M12 3l2.5 2 3.2-.3.8 3.1 2.7 1.8-1.3 2.9 1.3 2.9-2.7 1.8-.8 3.1-3.2-.3L12 21l-2.5-2-3.2.3-.8-3.1-2.7-1.8 1.3-2.9-1.3-2.9 2.7-1.8.8-3.1 3.2.3z', 'M9 12l2 2 4-4'],
  check: ['M5 12.5l4.5 4.5L19 7.5'],
}

export function TrustIcon({ text, size = 20, stroke = INK }) {
  return <Icon size={size} stroke={stroke} width={1.9}>{TRUST_PATHS[trustIcon(text)].map((d) => <path key={d} d={d} />)}</Icon>
}

/** STOREFRONT-3: the owner's trust points as cards, each with a picture that fits its words. */
export function TrustCards({ style, accent }) {
  const points = trustPoints(style)
  if (!points.length) return null
  return (
    <ul className="sf-trust-cards" aria-label="Why shop with us" style={{ '--n': points.length, listStyle: 'none', margin: 0, padding: 0 }}>
      {points.map((t) => (
        <li key={t} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '16px 18px', borderRadius: 16, background: tint(accent, 0.06), border: `1px solid ${tint(accent, 0.14)}` }}>
          <span style={{ width: 44, height: 44, borderRadius: 12, background: '#fff', boxShadow: '0 1px 3px rgba(20,24,27,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <TrustIcon text={t} stroke={accent} />
          </span>
          <span style={{ fontSize: 15, fontWeight: 800, lineHeight: 1.3 }}>{t}</span>
        </li>
      ))}
    </ul>
  )
}

/**
 * Header: menu button (phones), brand (goes to the full list), the menu (computers), optional search icon, cart.
 * `links` is [{ id, label, onClick, active }]. `children` is shown under the header row (the open search box).
 */
export function StorefrontHeader({ orgName, style, accent, onHome, cart, links = [], onSearch, searchOpen, children }) {
  const onAccent = readableOn(accent)
  const [menuOpen, setMenuOpen] = useState(false)
  const pick = (l) => { setMenuOpen(false); l.onClick() }
  return (
    <header className={`sf-headbar${style?.logo_url ? ' sf-has-logo' : ''}`} style={{ borderBottom: `1px solid ${LINE}` }}>
      <div className="sf-wrap sf-head">
        {links.length > 0 && (
          <button type="button" className="sf-icon-btn sf-menu-btn" aria-label={menuOpen ? 'Close menu' : 'Open menu'} aria-expanded={menuOpen} aria-controls="sf-menu-panel"
            onClick={() => setMenuOpen((o) => !o)} style={{ marginLeft: -8 }}>
            <Icon size={22} width={2}>{menuOpen ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h10" />}</Icon>
          </button>
        )}
        <button onClick={onHome} aria-label={`${orgName}, all products`} style={{
          display: 'flex', alignItems: 'center', gap: 10, border: 0, background: 'transparent', cursor: 'pointer', padding: 0, minHeight: 44, color: INK, flexShrink: 0,
        }}>
          {style?.logo_url ? (
            <img className="sf-logo-img" src={style.logo_url} alt="" />
          ) : (
            <span style={{
              width: 36, height: 36, borderRadius: 10, background: accent, color: onAccent,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 15,
            }}>{initials(orgName)}</span>
          )}
          {!(style?.logo_url && style.show_name_with_logo === false) && (   /* STOREFRONT-3: the owner can hide the name beside a logo */
            <span className="sf-brand-name" style={{ fontWeight: 800, fontSize: 20, letterSpacing: '-0.01em' }}>{orgName}</span>
          )}
        </button>
        {links.length > 0 ? (
          <nav className="sf-menu" aria-label="Shop menu">
            {links.map((l) => (
              <button key={l.id} type="button" className="sf-menu-link" aria-current={l.active ? 'page' : undefined} onClick={l.onClick}
                style={l.active ? { color: accent } : undefined}>{l.label}</button>
            ))}
          </nav>
        ) : <span style={{ flexGrow: 1 }} />}
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 2 }}>
          {onSearch && (
            <button type="button" className="sf-icon-btn" aria-label={searchOpen ? 'Close search' : 'Search'} aria-expanded={!!searchOpen} onClick={onSearch}>
              <Icon size={21} width={2}><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></Icon>
            </button>
          )}
          {cart && (
            <button type="button" className="sf-icon-btn" onClick={cart.onOpen} aria-label={`Open cart, ${cart.count} ${cart.count === 1 ? 'item' : 'items'}`}>
              <Icon size={23} width={1.9}><path d="M6 8h12l-1 12H7L6 8z" /><path d="M9 8V6.5a3 3 0 0 1 6 0V8" /></Icon>
              {cart.count > 0 && (
                <span style={{
                  position: 'absolute', top: 2, right: 0, minWidth: 20, height: 20, padding: '0 5px', borderRadius: 10, boxSizing: 'border-box',
                  background: accent, color: onAccent, fontSize: 11, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>{cart.count}</span>
              )}
            </button>
          )}
        </span>
      </div>
      {menuOpen && links.length > 0 && (
        <nav id="sf-menu-panel" aria-label="Shop menu" className="sf-wrap" style={{ paddingBottom: 12, display: 'grid' }}>
          {links.map((l) => (
            <button key={l.id} type="button" onClick={() => pick(l)} aria-current={l.active ? 'page' : undefined} style={{
              minHeight: 50, border: 0, borderTop: `1px solid ${LINE}`, background: 'transparent', textAlign: 'left', fontSize: 16, fontWeight: 700,
              color: l.active ? accent : INK, cursor: 'pointer', padding: '0 4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>{l.label}<span aria-hidden="true" style={{ color: MUTED }}>&rsaquo;</span></button>
          ))}
        </nav>
      )}
      {children && <div className="sf-wrap" style={{ paddingBottom: 12 }}>{children}</div>}
    </header>
  )
}

/**
 * Footer: brand and WhatsApp, a Shop column (the menu), a Help column, and the trust points.
 * `links` is the same list the header uses; `help` is [{ id, label, onClick }].
 */
export function StorefrontFooter({ orgName, hasWhatsApp, style, waLink, links = [], help = [] }) {
  const points = trustPoints(style)
  const year = new Date().getFullYear()
  const head = { fontSize: 13, fontWeight: 800, color: INK, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }
  const linkBtn = { border: 0, background: 'transparent', padding: 0, minHeight: 32, cursor: 'pointer', fontSize: 14, color: MUTED, textAlign: 'left', fontWeight: 600 }
  return (
    <footer style={{ marginTop: 88, borderTop: `1px solid ${LINE}`, padding: '44px 0 32px', fontSize: 14, color: MUTED }}>
      <div className="sf-foot-cols">
        <div style={{ maxWidth: 360 }}>
          {style?.logo_url
            ? <img src={style.logo_url} alt={orgName} style={{ height: 40, width: 'auto', maxWidth: 180, objectFit: 'contain', display: 'block' }} />
            : <div style={{ fontWeight: 800, fontSize: 18, color: INK }}>{orgName}</div>}
          {hasWhatsApp && (
            <p style={{ margin: '12px 0 0', lineHeight: 1.5 }}>
              Questions? {waLink
                ? <a href={waLink} target="_blank" rel="noopener noreferrer" style={{ color: INK, fontWeight: 700, textDecoration: 'underline' }}>Message us on WhatsApp</a>
                : 'Message us on WhatsApp'} any time.
            </p>
          )}
        </div>
        {links.length > 0 && (
          <nav aria-label="Shop">
            <div style={head}>Shop</div>
            <div style={{ display: 'grid' }}>{links.map((l) => <button key={l.id} type="button" onClick={l.onClick} style={linkBtn}>{l.label}</button>)}</div>
          </nav>
        )}
        {help.length > 0 && (
          <nav aria-label="Help">
            <div style={head}>Help</div>
            <div style={{ display: 'grid' }}>{help.map((l) => <button key={l.id} type="button" onClick={l.onClick} style={linkBtn}>{l.label}</button>)}</div>
          </nav>
        )}
        {points.length > 0 && (
          <div>
            <div style={head}>Why us</div>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 10 }}>
              {points.map((t) => (
                <li key={t} style={{ display: 'flex', gap: 8, alignItems: 'center', color: INK, fontWeight: 600 }}>
                  <TrustIcon text={t} size={18} />{t}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div style={{ marginTop: 28, paddingTop: 18, borderTop: `1px solid ${LINE}`, fontSize: 12.5 }}>&copy; {year} {orgName}</div>
    </footer>
  )
}
