/**
 * frontend/src/catalog/storefront/StorefrontListPage.jsx
 * STORE-3: Storefront look of the public product list (online-shop grid).
 * Search, category buttons, tag filters and size compare all keep working.
 * STOREFRONT-2: banner (owner's words/photo, else product photos), trust strip, "Shop by category" tiles and lifted cards.
 * The "Help me choose" question finder was removed: Chioma (or WhatsApp) does that job.
 * Buying is by WhatsApp from the product page; cart and checkout arrive in STORE-4.
 * STOREFRONT-3: a real menu, search behind an icon, trust cards with pictures, "Shop by need" buttons, and a second
 * button on every card (Ask Chioma, or a WhatsApp question when Chioma is off).
 */
import { useMemo, useRef, useState } from 'react'
import {
  resolveAccent, readableOn, categoryChips, otherFilterDims, filterItems, cardView, readUrlState, listUrl, quickAddState,
  tint, heroView, categoryTiles, trustPoints, needDim, menuLinks, whatsappAskLink,
} from './storefrontLogic'
import { cartVariantId } from './storefrontCart'
import { askChioma } from './storefrontChat'
import { INK, MUTED, LINE, FONT, placeholder, useManrope } from './storefrontTheme'
import {
  Icon, WhatsAppIcon, ChromeStyles, Announcement, StorefrontHeader, StorefrontFooter, TrustCards,
} from './StorefrontChrome'

function Chip({ on, onClick, children }) {
  return (
    <button aria-pressed={on} onClick={onClick} style={{
      height: 44, padding: '0 18px', borderRadius: 22, cursor: 'pointer', fontSize: 14, whiteSpace: 'nowrap', flexShrink: 0,
      border: on ? `1.5px solid ${INK}` : '1px solid #C9C6BF', background: on ? INK : '#fff', color: on ? '#fff' : INK,
      fontWeight: on ? 700 : 600,
    }}>{children}</button>
  )
}

export default function StorefrontListPage({
  orgName, orgSlug, waNumber, catalogConfig, style, items = [], onSelectItem, onShowCompare, headerCart, cart, chiomaChat,
}) {
  useManrope()
  const accent = resolveAccent(style)
  const onAccent = readableOn(accent)
  // STORE-8: a small add button under each product. "added" shows for two seconds; a failure is shown on its own card.
  const cartOn = !!(cart && cart.enabled)
  // STORE-CHIOMA-1: with Chioma on, each card offers Buy now (or Choose size) and Ask Chioma; WhatsApp is not shown.
  const chioma = !!(chiomaChat && chiomaChat.key)
  const chiomaShop = chioma && !!chiomaChat.shop && !catalogConfig?.price_on_request
  const [addState, setAddState] = useState({ id: null, phase: '' })
  const timer = useRef(null)
  async function quickAdd(it) {
    if (cart.busy) return
    setAddState({ id: it.id, phase: 'adding' })
    const ok = await cart.add({ item: it, variantId: cartVariantId(it, null), qty: 1 })
    clearTimeout(timer.current)
    if (ok) {
      setAddState({ id: it.id, phase: 'added' })
      timer.current = setTimeout(() => setAddState({ id: null, phase: '' }), 2000)
    } else {
      setAddState({ id: it.id, phase: 'failed' })
    }
  }
  const plural = catalogConfig?.catalog_item_label_plural || 'Products'
  const singular = catalogConfig?.catalog_item_label || 'Product'

  const [filters, setFilters] = useState(() => readUrlState(window.location.search, catalogConfig))
  const [search, setSearch] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)

  const chips = useMemo(() => categoryChips(items, catalogConfig, style), [items, catalogConfig, style])
  const dims = useMemo(() => otherFilterDims(catalogConfig), [catalogConfig])
  const shown = useMemo(() => filterItems(items, { search, filters }), [items, search, filters])

  const activeCategory = filters.category || ''
  const otherActive = Object.entries(filters).filter(([k, v]) => k !== 'category' && v)
  const anyActive = !!search.trim() || !!activeCategory || otherActive.length > 0

  function setFilter(key, val) {
    setFilters((prev) => {
      const next = { ...prev, [key]: prev[key] === val ? '' : val }
      if (key === 'category') {
        try { window.history.replaceState({}, '', listUrl(orgSlug, next.category || null, window.location.search)) } catch { /* address bar only */ }
      }
      return next
    })
  }

  function clearCategory() {
    setFilters((prev) => ({ ...prev, category: '' }))
    try { window.history.replaceState({}, '', listUrl(orgSlug, null, window.location.search)) } catch { /* address bar only */ }
  }

  function clearAll() {
    setFilters({})
    setSearch('')
    try { window.history.replaceState({}, '', listUrl(orgSlug, null, window.location.search)) } catch { /* address bar only */ }
  }

  function pickCategory(name) {
    setFilters({ category: name })
    setSearch('')
    try { window.history.replaceState({}, '', listUrl(orgSlug, name, window.location.search)) } catch { /* address bar only */ }
    scrollToProducts()
  }

  function scrollTo(id) {
    setTimeout(() => {
      const el = document.getElementById(id)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
  }

  const waHelp = waNumber
    ? `https://wa.me/${String(waNumber).replace('+', '')}?text=${encodeURIComponent(`I need help choosing a ${singular.toLowerCase()}`)}`
    : null

  const heading = activeCategory || plural
  const countText = `${shown.length} ${shown.length === 1 ? singular.toLowerCase() : plural.toLowerCase()}`
  const hero = useMemo(() => heroView(style, { orgName, plural, items }), [style, orgName, plural, items])
  const tiles = useMemo(() => categoryTiles(items, chips), [items, chips])
  const points = trustPoints(style)
  const home = !anyActive
  const waPlain = waNumber ? `https://wa.me/${String(waNumber).replace('+', '')}` : null
  function scrollToProducts() { scrollTo('sf-products') }
  const need = useMemo(() => needDim(items, catalogConfig), [items, catalogConfig])
  const links = menuLinks({ plural, chips, need, chioma, whatsapp: !!waPlain }).map((l) => ({
    ...l,
    active: l.kind === 'all' ? !anyActive : l.kind === 'category' ? activeCategory === l.value : false,
    onClick: () => {
      if (l.kind === 'all') { clearAll(); window.scrollTo({ top: 0, behavior: 'smooth' }) }
      else if (l.kind === 'category') pickCategory(l.value)
      else if (l.kind === 'need') { clearAll(); scrollTo('sf-need') }
      else if (l.kind === 'chioma') askChioma({ action: 'open' })
      else if (l.kind === 'whatsapp') window.open(waPlain, '_blank', 'noopener')
    },
  }))
  const help = [
    ...(chioma ? [{ id: 'chioma', label: 'Ask Chioma', onClick: () => askChioma({ action: 'open' }) }] : []),
    ...(waPlain ? [{ id: 'wa', label: 'Chat on WhatsApp', onClick: () => window.open(waPlain, '_blank', 'noopener') }] : []),
  ]

  return (
    <div className="sf-root" style={{ minHeight: '100vh', background: '#fff', fontFamily: FONT, color: INK }}>
      <ChromeStyles accent={accent} />
      <style>{`
        .sf-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 28px 24px }
        .sf-chips { display: flex; gap: 10px; flex-wrap: wrap; align-items: center }
        .sf-hero { display: grid; grid-template-columns: 1.05fr 1fr; gap: 32px; align-items: center; border-radius: 28px; padding: 48px; overflow: hidden }
        .sf-hero-art { position: relative; aspect-ratio: 5 / 4; border-radius: 20px; overflow: hidden }
        .sf-collage { display: grid; grid-template-columns: 1.4fr 1fr; grid-template-rows: 1fr 1fr; gap: 12px; height: 100% }
        .sf-collage > :first-child { grid-row: 1 / 3 }
        .sf-trust { display: flex; gap: 12px 28px; flex-wrap: wrap; justify-content: center }
        .sf-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px }
        .sf-tile { position: relative; aspect-ratio: 4 / 3; border-radius: 18px; overflow: hidden; border: 0; padding: 0; cursor: pointer; text-align: left; color: #fff }
        .sf-tile img, .sf-card-img img { transition: transform .35s ease }
        .sf-tile:hover img, .sf-card:hover .sf-card-img img { transform: scale(1.04) }
        .sf-card { transition: transform .2s ease }
        .sf-card:hover { transform: translateY(-2px) }
        @media (prefers-reduced-motion: reduce) { .sf-tile img, .sf-card-img img, .sf-card { transition: none } .sf-tile:hover img, .sf-card:hover .sf-card-img img, .sf-card:hover { transform: none } }
        @media (max-width: 860px) {
          .sf-hero { grid-template-columns: 1fr; padding: 28px 22px; gap: 22px; border-radius: 22px }
          .sf-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px }
        }
        @media (max-width: 1000px) { .sf-cards { grid-template-columns: repeat(3, minmax(0, 1fr)) } }
        @media (max-width: 700px) {
          .sf-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px 14px }
          .sf-chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 4px }
          .sf-chips::-webkit-scrollbar { display: none }
        }
      `}</style>

      <Announcement style={style} accent={accent} />
      <StorefrontHeader orgName={orgName} style={style} accent={accent} onHome={clearAll} cart={headerCart}
        links={links} searchOpen={searchOpen || !!search} onSearch={() => { if (searchOpen && search) setSearch(''); setSearchOpen((o) => !(o || search)) }}>
        {(searchOpen || !!search) && (
          <label style={{
            height: 48, border: '1px solid #C9C6BF', borderRadius: 24, display: 'flex', alignItems: 'center', gap: 10, padding: '0 18px', boxSizing: 'border-box', color: MUTED, maxWidth: 640, margin: '0 auto',
          }}>
            <Icon size={18} stroke={MUTED}><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></Icon>
            <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Search {plural.toLowerCase()}</span>
            <input type="search" autoFocus value={search} onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') scrollToProducts(); if (e.key === 'Escape') { setSearch(''); setSearchOpen(false) } }}
              placeholder={`Search ${plural.toLowerCase()}`}
              style={{ border: 0, outline: 'none', flexGrow: 1, minWidth: 0, fontSize: 16, background: 'transparent', color: INK }} />
          </label>
        )}
      </StorefrontHeader>

      <main className="sf-wrap">
        {home && (
          <section className="sf-hero" aria-label={hero.title} style={{ marginTop: 24, background: `linear-gradient(135deg, ${tint(accent, 0.12)} 0%, ${tint(accent, 0.04)} 100%)` }}>
            <div>
              {style?.hero_title && (   /* the default headline already names the shop */
                <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: accent, marginBottom: 12 }}>{orgName}</div>
              )}
              <h1 style={{ margin: 0, fontSize: 'clamp(32px, 5vw, 54px)', lineHeight: 1.05, fontWeight: 800, letterSpacing: '-0.025em' }}>{hero.title}</h1>
              <p style={{ margin: '16px 0 0', fontSize: 'clamp(15px, 1.6vw, 18px)', lineHeight: 1.55, color: '#3A3F44', maxWidth: 480 }}>{hero.text}</p>
              <div style={{ marginTop: 28, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <button type="button" onClick={scrollToProducts} style={{
                  minHeight: 52, padding: '0 28px', borderRadius: 14, border: 0, background: accent, color: onAccent, fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit',
                }}>Shop {plural.toLowerCase()}</button>
                {chioma && (
                  <button type="button" onClick={() => askChioma({ action: 'open' })} style={{
                    minHeight: 52, padding: '0 24px', borderRadius: 14, border: `1.5px solid ${INK}`, background: 'rgba(255,255,255,0.7)', color: INK, fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit',
                  }}>Ask Chioma</button>
                )}
              </div>
            </div>
            {(hero.image || hero.collage.length > 0) && (
              <div className="sf-hero-art" aria-hidden="true">
                {hero.image ? (
                  <img src={hero.image} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                ) : hero.collage.length >= 3 ? (
                  <div className="sf-collage">
                    {hero.collage.map((u, i) => (
                      <div key={u + i} style={{ borderRadius: 16, overflow: 'hidden', background: placeholder(i, 24) }}>
                        <img src={u} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <img src={hero.collage[0]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                )}
              </div>
            )}
          </section>
        )}

        {home && points.length > 0 && (
          <div style={{ marginTop: 20 }}><TrustCards style={style} accent={accent} /></div>
        )}

        {home && tiles.length >= 2 && (
          <section aria-labelledby="sf-cats" style={{ marginTop: 56 }}>
            <h2 id="sf-cats" style={{ margin: 0, fontSize: 'clamp(22px, 3vw, 28px)', fontWeight: 800, letterSpacing: '-0.02em' }}>Shop by category</h2>
            <div className="sf-tiles" style={{ marginTop: 20 }}>
              {tiles.map((t, i) => (
                <button key={t.name} type="button" className="sf-tile" onClick={() => { setFilter('category', t.name); scrollToProducts() }}
                  aria-label={`${t.name}, ${t.count} ${t.count === 1 ? singular.toLowerCase() : plural.toLowerCase()}`}
                  style={{ background: t.cover ? INK : placeholder(i, 24) }}>
                  {t.cover && <img src={t.cover} alt="" loading="lazy" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
                  <span style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(0,0,0,0) 40%, rgba(0,0,0,0.62) 100%)' }} />
                  <span style={{ position: 'absolute', left: 16, right: 16, bottom: 14 }}>
                    <span style={{ display: 'block', fontSize: 17, fontWeight: 800, color: t.cover ? '#fff' : INK }}>{t.name}</span>
                    <span style={{ display: 'block', marginTop: 2, fontSize: 13, fontWeight: 600, color: t.cover ? 'rgba(255,255,255,0.85)' : MUTED }}>{t.count} {t.count === 1 ? singular.toLowerCase() : plural.toLowerCase()}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        )}

        {home && need && (
          <section id="sf-need" aria-labelledby="sf-need-h" style={{ marginTop: 56, scrollMarginTop: 96 }}>
            <h2 id="sf-need-h" style={{ margin: 0, fontSize: 'clamp(22px, 3vw, 28px)', fontWeight: 800, letterSpacing: '-0.02em' }}>Shop by need</h2>
            <div className="sf-chips" style={{ marginTop: 18 }}>
              {need.options.map((o) => (
                <button key={o} type="button" onClick={() => { setFilters({ [need.key]: o }); scrollToProducts() }} style={{
                  minHeight: 48, padding: '0 20px', borderRadius: 24, border: `1.5px solid ${tint(accent, 0.3)}`, background: tint(accent, 0.06), color: INK,
                  fontSize: 15, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
                }}>{o}</button>
              ))}
            </div>
          </section>
        )}

        <div id="sf-products" style={{ marginTop: home ? 56 : 36, scrollMarginTop: 96, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 24, flexWrap: 'wrap' }}>
          {home
            ? <h2 style={{ margin: 0, fontSize: 'clamp(22px, 3vw, 28px)', fontWeight: 800, letterSpacing: '-0.02em' }}>All {plural.toLowerCase()}</h2>
            : <h1 style={{ margin: 0, fontSize: 'clamp(28px, 4.4vw, 40px)', lineHeight: 1.1, fontWeight: 800, letterSpacing: '-0.02em' }}>{heading}</h1>}
          <div aria-live="polite" style={{ fontSize: 14, color: MUTED }}>{countText}</div>
        </div>

        {(chips.length > 0 || dims.length > 0) && (
          <div className="sf-chips" role="group" aria-label="Browse by category" style={{ marginTop: 24 }}>
            {chips.length > 0 && (
              <>
                <Chip on={!activeCategory} onClick={clearCategory}>All</Chip>
                {chips.map((c) => (
                  <Chip key={c.name} on={activeCategory === c.name} onClick={() => setFilter('category', c.name)}>{c.name}</Chip>
                ))}
              </>
            )}
            {dims.length > 0 && (
              <button aria-expanded={showFilters} onClick={() => setShowFilters((s) => !s)} style={{
                height: 44, padding: '0 18px', borderRadius: 22, border: '1px solid #C9C6BF', background: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0, marginLeft: chips.length ? 'auto' : 0,
              }}>
                Filters{otherActive.length ? ` (${otherActive.length})` : ''}
              </button>
            )}
          </div>
        )}

        {showFilters && dims.length > 0 && (
          <div style={{ marginTop: 16, padding: 20, border: `1px solid ${LINE}`, borderRadius: 16, display: 'flex', flexDirection: 'column', gap: 18 }}>
            {dims.map((d) => (
              <div key={d.key} role="group" aria-label={d.label}>
                <div style={{ fontSize: 13, fontWeight: 800 }}>{d.label}</div>
                <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {d.options.map((opt) => {
                    const on = filters[d.key] === opt
                    return (
                      <button key={opt} aria-pressed={on} onClick={() => setFilter(d.key, opt)} style={{
                        minHeight: 40, padding: '0 14px', borderRadius: 20, fontSize: 13, cursor: 'pointer',
                        border: on ? `2px solid ${accent}` : '1px solid #C9C6BF', background: '#fff', color: INK, fontWeight: on ? 700 : 600,
                      }}>{opt}</button>
                    )
                  })}
                </div>
              </div>
            ))}
            {filters.sizes && onShowCompare && (
              <button onClick={() => onShowCompare(filters.sizes)} style={{
                alignSelf: 'flex-start', minHeight: 44, padding: '0 18px', borderRadius: 12, border: `1.5px solid ${INK}`, background: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer',
              }}>Compare every {filters.sizes}</button>
            )}
          </div>
        )}

        {shown.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '72px 0' }}>
            <div style={{ fontSize: 20, fontWeight: 800 }}>No {plural.toLowerCase()} match.</div>
            <p style={{ margin: '8px 0 0', fontSize: 14, color: MUTED }}>Try another word, or look at everything we have.</p>
            <button onClick={clearAll} style={{
              marginTop: 18, minHeight: 48, padding: '0 22px', border: `1.5px solid ${INK}`, borderRadius: 12, background: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer',
            }}>Show all {plural.toLowerCase()}</button>
          </div>
        ) : (
          <div className="sf-cards" style={{ marginTop: 32 }}>
            {shown.map((it, i) => {
              const v = cardView(it, catalogConfig)
              const soldLabel = catalogConfig?.availability_labels?.unavailable || 'Out of stock'
              const quick = chioma ? null : quickAddState(it, { cartOn, config: catalogConfig })
              const cq = chiomaShop ? quickAddState(it, { cartOn: true, config: catalogConfig }) : null
              const mine = addState.id === it.id ? addState.phase : ''
              return (
                <div key={it.id || it.slug} className="sf-card">
                <button onClick={() => onSelectItem(it)} style={{
                  display: 'block', textAlign: 'left', border: 0, background: 'transparent', cursor: 'pointer', padding: 0, color: INK, width: '100%',
                }}>
                  <div className="sf-card-img" style={{ position: 'relative', aspectRatio: '1 / 1.1', borderRadius: 18, overflow: 'hidden', background: placeholder(i, 24), boxShadow: '0 1px 2px rgba(20,24,27,0.06)' }}>
                    {v.cover && <img src={v.cover} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
                    {v.pct && !v.soldOut && (
                      <span style={{ position: 'absolute', left: 12, top: 12, padding: '5px 9px', borderRadius: 6, background: INK, color: '#fff', fontSize: 11, fontWeight: 800 }}>{v.pct}% OFF</span>
                    )}
                    {v.soldOut && (
                      <span style={{ position: 'absolute', left: 12, top: 12, padding: '5px 9px', borderRadius: 6, background: '#fff', color: MUTED, fontSize: 11, fontWeight: 700, border: '1px solid #C9C6BF' }}>{soldLabel}</span>
                    )}
                  </div>
                  <div style={{ marginTop: 12, fontSize: 15, fontWeight: 700 }}>{v.title}</div>
                  {v.note && <div style={{ marginTop: 3, fontSize: 13, color: MUTED }}>{v.note}</div>}
                  {v.priceText && (
                    <div style={{ marginTop: 6, display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 16, fontWeight: 800 }}>{v.priceText}</span>
                      {v.wasText && <span style={{ fontSize: 13, color: MUTED, textDecoration: 'line-through' }}>{v.wasText}</span>}
                    </div>
                  )}
                </button>
                {chioma && (
                  <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
                    {cq && (
                      <button type="button" aria-label={cq === 'add' ? `Buy ${v.title} now` : `Choose a size for ${v.title}`}
                        onClick={() => (cq === 'add' ? askChioma({ action: 'buy', product: it.id, variant: cartVariantId(it, null) }) : onSelectItem(it))}
                        style={{ width: '100%', minHeight: 44, borderRadius: 12, fontSize: 14, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit',
                          ...(cq === 'add' ? { border: 0, background: accent, color: onAccent } : { border: `1.5px solid ${LINE}`, background: '#fff', color: INK }) }}>
                        {cq === 'add' ? 'Buy now' : 'Choose size'}
                      </button>
                    )}
                    <button type="button" aria-label={`Ask Chioma about ${v.title}`} onClick={() => askChioma({ action: 'open', product: it.id })}
                      style={{ width: '100%', minHeight: 44, borderRadius: 12, border: `1.5px solid ${tint(accent, 0.25)}`, background: '#fff', color: INK, fontSize: 14, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                      <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: 11, background: tint(accent, 0.14), color: accent, fontSize: 11, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>C</span>
                      Ask Chioma
                    </button>
                  </div>
                )}
                {quick && (
                  <button type="button" disabled={mine === 'adding'}
                    aria-label={quick === 'add' ? `Add ${v.title} to cart` : `Choose a size for ${v.title}`}
                    onClick={() => (quick === 'add' ? quickAdd(it) : onSelectItem(it))}
                    style={{
                      marginTop: 10, width: '100%', minHeight: 44, borderRadius: 12, fontSize: 14, fontWeight: 700,
                      cursor: mine === 'adding' ? 'default' : 'pointer', fontFamily: 'inherit',
                      ...(quick === 'add'
                        ? { border: `1.5px solid ${accent}`, background: mine === 'added' ? accent : '#fff', color: mine === 'added' ? onAccent : accent }
                        : { border: `1.5px solid ${LINE}`, background: '#fff', color: INK }),
                    }}>
                    {quick === 'choose' ? 'Choose size' : mine === 'adding' ? 'Adding…' : mine === 'added' ? 'Added \u2713' : 'Add to cart'}
                  </button>
                )}
                {!chioma && waNumber && (
                  <a href={whatsappAskLink(waNumber, v.title)} target="_blank" rel="noopener noreferrer" aria-label={`Ask about ${v.title} on WhatsApp`} style={{
                    marginTop: 8, width: '100%', minHeight: 44, borderRadius: 12, border: `1.5px solid ${LINE}`, background: '#fff', color: INK, fontSize: 14, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, boxSizing: 'border-box',
                  }}><WhatsAppIcon stroke={INK} />Ask on WhatsApp</a>
                )}
                {mine === 'failed' && cart && cart.error && <p role="alert" style={{ margin: '6px 0 0', fontSize: 12, color: '#B3261E' }}>{cart.error}</p>}
                </div>
              )
            })}
          </div>
        )}

        {anyActive && shown.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <button onClick={clearAll} style={{ minHeight: 44, border: 0, background: 'transparent', fontSize: 14, fontWeight: 600, textDecoration: 'underline', cursor: 'pointer', color: MUTED, padding: 0 }}>Clear all</button>
          </div>
        )}

        {(waHelp || chioma) && (
          <section style={{ marginTop: 72, padding: '32px 36px', borderRadius: 20, background: INK, color: '#fff', display: 'flex', gap: 24, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>Need help choosing?</div>
              <div style={{ marginTop: 6, fontSize: 14, color: '#D5D8DB' }}>{chioma ? `Chioma can recommend the right ${singular.toLowerCase()} for you, day or night.` : `Our team can recommend the right ${singular.toLowerCase()} for you on WhatsApp.`}</div>
            </div>
            {chioma ? (
              <button type="button" onClick={() => askChioma({ action: 'open' })} style={{
                minHeight: 52, padding: '0 26px', borderRadius: 14, border: 0, background: '#fff', color: INK, fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit',
              }}>Speak to Chioma</button>
            ) : (
            <a href={waHelp} target="_blank" rel="noopener noreferrer" style={{
              minHeight: 52, padding: '0 26px', borderRadius: 14, background: '#fff', color: INK, display: 'flex', alignItems: 'center', gap: 10, fontSize: 15, fontWeight: 700,
            }}>
              <WhatsAppIcon stroke={INK} />Chat on WhatsApp
            </a>
            )}
          </section>
        )}

        <StorefrontFooter orgName={orgName} hasWhatsApp={!!waNumber} style={style} waLink={waPlain} links={links} help={help} />
      </main>
    </div>
  )
}
