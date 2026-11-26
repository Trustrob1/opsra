/**
 * frontend/src/catalog/PublicCatalogShell.jsx
 * CATALOG-3B: No-auth wrapper for public catalog pages.
 * Detects org_slug from URL path (/catalog/{org_slug}/...).
 * Fetches catalog data and renders CatalogListPage or CatalogItemPage.
 * NO Zustand auth store dependency. NO login required.
 * STORE-2/3: reads `template`, `shop` and `style` from the public API. When the
 * business uses the Storefront look, the list page and item page are the Storefront
 * ones; the size-compare page stays Classic. Classic is unchanged.
 * STORE-4: Storefront shows the cart (web chat shop cart + Paystack checkout) when the business has it on.
 * STORE-5: /shop/{slug} is the short link; it opens the same catalog and the address bar then shows /catalog/{slug}.
 * STOREFRONT-2: no "Loading catalog" screen. index.html starts the request early, a saved copy from the last visit shows at
 * once (then refreshes quietly), and a first visit sees the page outline instead of a spinner.
 * WARNING: Full rewrite required for any edit (Pattern 51).
 */
import { useState, useEffect } from 'react'
import { getCatalogList, getCatalogItem, getCatalogCompare, postCatalogVisit } from './catalog.service'
import { trackVisitOnce } from './catalogVisit'
import CatalogListPage from './CatalogListPage'
import CatalogItemPage from './CatalogItemPage'
import CatalogSizeComparePage from './CatalogSizeComparePage'
import StorefrontItemPage from './storefront/StorefrontItemPage'
import StorefrontListPage from './storefront/StorefrontListPage'
import CartDrawer from './storefront/CartDrawer'
import StorefrontChat from './storefront/StorefrontChat'
import { canShowChat } from './storefront/storefrontChat'
import useStorefrontCart from './storefront/useStorefrontCart'
import { listUrl, resolveAccent } from './storefront/storefrontLogic'
import { cleanSource, canUseCart, decorateLines, catalogPathFromShort } from './storefront/storefrontCart'
import { SLOW_AFTER_MS } from './fetchRetry'
import { shapeCatalog, readCachedCatalog, writeCachedCatalog, takePrefetch } from './catalogBoot'

function _local() {
  try { return window.localStorage } catch { return null }
}

const C = {
  bg:   '#FAFAF8',
  text: '#1A1714',
  muted:'#7A7269',
  teal: '#0B6E74',
}

// Parse URL: /catalog/{org_slug} or /catalog/{org_slug}/{item_slug}
function _parsePath() {
  // STORE-5: /shop/{slug}/... is the short link; show it as /catalog/{slug}/... (keeps ?src= and anything after)
  const asCatalog = catalogPathFromShort(window.location.pathname)
  if (asCatalog) window.history.replaceState({}, '', asCatalog + window.location.search + window.location.hash)
  const parts = window.location.pathname.split('/').filter(Boolean)
  // parts[0] === 'catalog'
  const orgSlug  = parts[1] || null
  const segment  = parts[2] || null
  // /catalog/{org_slug}/compare?size=... is the compare route
  const isCompare = segment === 'compare'
  const itemSlug  = isCompare ? null : segment
  const sizeValue = isCompare
    ? new URLSearchParams(window.location.search).get('size') || null
    : null
  return { orgSlug, itemSlug, isCompare, sizeValue }
}

export default function PublicCatalogShell() {
  const { orgSlug, itemSlug: initialItemSlug, isCompare: initialIsCompare, sizeValue: initialSizeValue } = _parsePath()

  const [saved]                         = useState(() => readCachedCatalog(_local(), orgSlug))   // STOREFRONT-2
  const [catalogData, setCatalogData]   = useState(() => (saved ? shapeCatalog(saved) : null))
  const [currentItem, setCurrentItem]   = useState(null)
  const [itemSlug, setItemSlug]         = useState(initialItemSlug)
  const [compareMode, setCompareMode]   = useState(initialIsCompare)
  const [sizeValue, setSizeValue]       = useState(initialSizeValue)
  const [compareItems, setCompareItems] = useState([])
  const [loading, setLoading]           = useState(() => !saved)
  const [error, setError]               = useState(null)
  const [slow, setSlow]                 = useState(false)     // LOAD-RETRY-1: the first load is taking a while
  const [cartOpen, setCartOpen]         = useState(false)
  const [source]                        = useState(() => cleanSource(window.location.search))

  // STORE-4: the cart only exists for the Storefront look, when the business has the web chat shop on
  const cartShop = catalogData && catalogData.template === 'storefront' && canUseCart(catalogData.shop, catalogData.catalogConfig)
    ? catalogData.shop : null
  const cartApi = useStorefrontCart({ shop: cartShop, source })

  // Load list data on mount
  useEffect(() => {
    if (!orgSlug) { setError('not_found'); setLoading(false); return }

    const slowTimer = saved ? null : setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    // STOREFRONT-2: use the request index.html already started; if that one failed, ask again (with retries)
    const early = takePrefetch(window, orgSlug)
    const request = early ? early.catch(() => getCatalogList(orgSlug)) : getCatalogList(orgSlug)
    request
        .then(data => {
          clearTimeout(slowTimer)
          writeCachedCatalog(_local(), orgSlug, data)
          setCatalogData(shapeCatalog(data))
        setLoading(false)
        // STORE-7: a tagged link that opens a real store is counted once per browser session
        let storage = null
        try { storage = window.sessionStorage } catch { /* blocked */ }
        trackVisitOnce({ orgSlug, tag: source, storage, send: postCatalogVisit })
      })
      .catch(err => {
        clearTimeout(slowTimer)
        // a saved copy is already on screen: keep showing it unless the catalog no longer exists
        if (saved && err.status !== 404) return
        setError(err.status === 404 ? 'not_found' : 'error')
        setLoading(false)
      })
    return () => clearTimeout(slowTimer)
  }, [orgSlug, source, saved])

  // Load individual item when itemSlug is set
  useEffect(() => {
    if (!itemSlug || !orgSlug) {
      setCurrentItem(null)
      return
    }

    getCatalogItem(orgSlug, itemSlug)
      .then(data => {
        setCurrentItem(data.item)
        // Update OG meta title for SEO
        if (data.item?.title && catalogData?.orgName) {
          document.title = `${data.item.title} — ${catalogData.orgName}`
        }
      })
      .catch(() => {
        setCurrentItem(null)
        setItemSlug(null)
      })
  }, [itemSlug, orgSlug])

  // Load compare items when in compare mode
  useEffect(() => {
    if (!compareMode || !sizeValue || !orgSlug) return
    getCatalogCompare(orgSlug, sizeValue)
      .then(data => setCompareItems(data.items || []))
      .catch(() => setCompareItems([]))
  }, [compareMode, sizeValue, orgSlug])

  // Update page title
  useEffect(() => {
    if (catalogData?.orgName) {
      document.title = currentItem
        ? `${currentItem.title} — ${catalogData.orgName}`
        : `${catalogData.orgName} Catalog`
    }
  }, [catalogData, currentItem])

  function handleSelectItem(item) {
    setItemSlug(item.slug)
    setCompareMode(false)
    setSizeValue(null)
    window.history.pushState({}, '', `/catalog/${orgSlug}/${item.slug}`)
    window.scrollTo(0, 0)
  }

  function handleBack() {
    setItemSlug(null)
    setCurrentItem(null)
    setCompareMode(false)
    setSizeValue(null)
    window.history.pushState({}, '', `/catalog/${orgSlug}`)
    window.scrollTo(0, 0)
  }

  // Storefront menu: open the list, optionally on one category (keeps ?src= etc.)
  function handleOpenCategory(category) {
    setItemSlug(null)
    setCurrentItem(null)
    setCompareMode(false)
    setSizeValue(null)
    window.history.pushState({}, '', listUrl(orgSlug, category, window.location.search))
    window.scrollTo(0, 0)
  }

  function handleShowCompare(size) {
    setCompareMode(true)
    setSizeValue(size)
    setItemSlug(null)
    setCurrentItem(null)
    window.history.pushState({}, '', `/catalog/${orgSlug}/compare?size=${encodeURIComponent(size)}`)
    window.scrollTo(0, 0)
  }

  // ── Loading (first visit only): the page outline, no spinner and no "Loading" words ──
  if (loading) {
    const bar = (w, h, extra = {}) => <div className="cat-skel" style={{ width: w, height: h, borderRadius: 8, ...extra }} />
    return (
      <div aria-busy="true" style={{ minHeight: '100vh', background: '#fff', fontFamily: "system-ui, sans-serif" }}>
        <style>{`
          .cat-skel { background: linear-gradient(90deg, #F1EFEB 25%, #F8F7F4 37%, #F1EFEB 63%); background-size: 400% 100%; animation: cat-skel 1.3s ease infinite }
          .cat-skel-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px }
          @media (max-width: 700px) { .cat-skel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px } }
          @keyframes cat-skel { 0% { background-position: 100% 50% } 100% { background-position: 0 50% } }
          @media (prefers-reduced-motion: reduce) { .cat-skel { animation: none } }
        `}</style>
        <div style={{ borderBottom: '1px solid #EEECE8' }}>
          <div style={{ maxWidth: 1200, margin: '0 auto', padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
            {bar(40, 40, { borderRadius: 10 })}{bar(140, 18)}
          </div>
        </div>
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '20px' }}>
          {bar('100%', 'clamp(180px, 32vw, 340px)', { borderRadius: 20 })}
          <div className="cat-skel-grid" style={{ marginTop: 32 }}>
            {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
              <div key={i}>{bar('100%', 0, { aspectRatio: '1 / 1.1', height: 'auto', borderRadius: 16 })}<div style={{ height: 12 }} />{bar('70%', 14)}<div style={{ height: 8 }} />{bar('40%', 14)}</div>
            ))}
          </div>
          {slow && (
            <div role="status" style={{ marginTop: 28, textAlign: 'center', color: C.muted }}>
              <p style={{ fontSize: 14, margin: '0 0 12px' }}>Taking longer than usual. Your connection may be slow.</p>
              <button onClick={() => window.location.reload()} style={{ background: C.teal, color: 'white', border: 'none', borderRadius: 8, padding: '10px 22px', minHeight: 44, fontSize: 14, cursor: 'pointer' }}>Tap to retry</button>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── 404 ──
  if (error === 'not_found') {
    return (
      <div style={{
        minHeight: '100vh', background: C.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'Jost', sans-serif", padding: 32,
      }}>
        <div style={{ textAlign: 'center', maxWidth: 400 }}>
          <p style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 64, margin: '0 0 16px', lineHeight: 1,
          }}>404</p>
          <h2 style={{ fontSize: 20, color: C.text, margin: '0 0 8px' }}>Catalog not found</h2>
          <p style={{ fontSize: 14, color: C.muted }}>
            This catalog link may be invalid or no longer active.
          </p>
        </div>
      </div>
    )
  }

  // ── Error ──
  if (error === 'error') {
    return (
      <div style={{
        minHeight: '100vh', background: C.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'Jost', sans-serif", padding: 32,
      }}>
        <div style={{ textAlign: 'center', maxWidth: 400 }}>
          <p style={{ fontSize: 32, margin: '0 0 12px' }}>⚠️</p>
          <h2 style={{ fontSize: 20, color: C.text, margin: '0 0 8px' }}>Something went wrong</h2>
          <p style={{ fontSize: 14, color: C.muted, margin: '0 0 20px' }}>
            We couldn't load the catalog right now. Please try again.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: C.teal, color: 'white',
              border: 'none', borderRadius: 8,
              padding: '10px 22px', fontSize: 14,
              fontFamily: "'Jost', sans-serif", cursor: 'pointer',
            }}
          >Try again</button>
        </div>
      </div>
    )
  }

  // ── Compare page ──
  if (compareMode && sizeValue) {
    return (
      <CatalogSizeComparePage
        orgName={catalogData.orgName}
        waNumber={catalogData.waNumber}
        catalogConfig={catalogData.catalogConfig}
        items={compareItems}
        sizeValue={sizeValue}
        onBack={handleBack}
        onSelectItem={handleSelectItem}
      />
    )
  }

  const openCart = () => setCartOpen(true)
  // STORE-CHIOMA-1: when Chioma is on for this storefront, its buttons lead to Chioma (same condition as the chat bubble)
  const chiomaChat = catalogData.template === 'storefront' && canShowChat(catalogData.chat) ? catalogData.chat : null
  const headerCart = cartApi.enabled ? { count: cartApi.cart.count, onOpen: openCart } : null
  const withCart = (page) => (
    <>
      {page}
      {catalogData.template === 'storefront' && canShowChat(catalogData.chat) && (
        <StorefrontChat
          chatKey={catalogData.chat.key} accent={resolveAccent(catalogData.style)} orgName={catalogData.orgName} goal={catalogData.chat.goal || ''}
          productId={itemSlug && currentItem ? currentItem.id : null}
          productTitle={itemSlug && currentItem ? currentItem.title : ''}
        />
      )}
      {cartApi.enabled && (
        <CartDrawer
          open={cartOpen} onClose={() => setCartOpen(false)}
          accent={resolveAccent(catalogData.style)} orgName={catalogData.orgName} waNumber={catalogData.waNumber}
          template={catalogData.catalogConfig && catalogData.catalogConfig.price_label_template}
          lines={decorateLines(cartApi.cart, catalogData.items)} total={cartApi.cart.total} count={cartApi.cart.count}
          busy={cartApi.busy} error={cartApi.error} hasContact={cartApi.hasContact}
          onSetQty={cartApi.setQty} onRemove={cartApi.remove} onSubmitContact={cartApi.submitContact}
          onCheckout={cartApi.checkout} onClearError={cartApi.clearError}
          onOpenItem={(l) => { setCartOpen(false); handleSelectItem({ slug: l.slug }) }}
        />
      )}
    </>
  )

  // ── Item page ──
  if (itemSlug && currentItem && catalogData.template === 'storefront') {
    return withCart(
      <StorefrontItemPage
        key={currentItem.slug}
        orgName={catalogData.orgName}
        waNumber={catalogData.waNumber}
        catalogConfig={catalogData.catalogConfig}
        style={catalogData.style}
        shop={catalogData.shop}
        item={currentItem}
        items={catalogData.items}
        onBack={handleBack}
        onSelectItem={handleSelectItem}
        onShowCompare={handleShowCompare}
        onPickCategory={handleOpenCategory}
        cart={cartApi}
        headerCart={headerCart}
        onOpenCart={openCart}
        chiomaChat={chiomaChat}
      />
    )
  }
  if (itemSlug && currentItem) {
    return (
      <CatalogItemPage
        orgName={catalogData.orgName}
        waNumber={catalogData.waNumber}
        catalogConfig={catalogData.catalogConfig}
        item={currentItem}
        onBack={handleBack}
      />
    )
  }

  // ── List page (default) ──
  if (catalogData.template === 'storefront') {
    return withCart(
      <StorefrontListPage
        orgName={catalogData.orgName}
        orgSlug={orgSlug}
        waNumber={catalogData.waNumber}
        catalogConfig={catalogData.catalogConfig}
        style={catalogData.style}
        wizardQuestions={catalogData.wizardQuestions || []}
        items={catalogData.items}
        onSelectItem={handleSelectItem}
        onShowCompare={handleShowCompare}
        headerCart={headerCart}
        cart={cartApi}
        chiomaChat={chiomaChat}
      />
    )
  }
  return (
    <CatalogListPage
      orgName={catalogData.orgName}
      waNumber={catalogData.waNumber}
      catalogConfig={catalogData.catalogConfig}
      wizardQuestions={catalogData.wizardQuestions || []}
      items={catalogData.items}
      onSelectItem={handleSelectItem}
      onShowCompare={handleShowCompare}
    />
  )
}
