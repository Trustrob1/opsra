/**
 * frontend/src/catalog/PublicCatalogShell.jsx
 * CATALOG-3B: No-auth wrapper for public catalog pages.
 * Detects org_slug from URL path (/catalog/{org_slug}/...).
 * Fetches catalog data and renders CatalogListPage or CatalogItemPage.
 * NO Zustand auth store dependency. NO login required.
 * WARNING: Full rewrite required for any edit (Pattern 51).
 */
import { useState, useEffect } from 'react'
import { getCatalogList, getCatalogItem } from './catalog.service'
import CatalogListPage from './CatalogListPage'
import CatalogItemPage from './CatalogItemPage'

const C = {
  bg:   '#FAFAF8',
  text: '#1A1714',
  muted:'#7A7269',
  teal: '#0B6E74',
}

// Parse URL: /catalog/{org_slug} or /catalog/{org_slug}/{item_slug}
function _parsePath() {
  const parts = window.location.pathname.split('/').filter(Boolean)
  // parts[0] === 'catalog'
  const orgSlug  = parts[1] || null
  const itemSlug = parts[2] || null
  return { orgSlug, itemSlug }
}

export default function PublicCatalogShell() {
  const { orgSlug, itemSlug: initialItemSlug } = _parsePath()

  const [catalogData, setCatalogData] = useState(null)  // { orgName, waNumber, catalogConfig, items }
  const [currentItem, setCurrentItem] = useState(null)  // full item object when on item page
  const [itemSlug, setItemSlug]       = useState(initialItemSlug)
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)  // null | 'not_found' | 'error'

  // Load list data on mount
  useEffect(() => {
    if (!orgSlug) { setError('not_found'); setLoading(false); return }

    getCatalogList(orgSlug)
      .then(data => {
        setCatalogData({
          orgName:       data.org_name,
          waNumber:      data.wa_number,
          catalogConfig: data.catalog_config,
          items:         data.items || [],
        })
        setLoading(false)
      })
      .catch(err => {
        setError(err.status === 404 ? 'not_found' : 'error')
        setLoading(false)
      })
  }, [orgSlug])

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
    // Update URL without page reload (pushState)
    window.history.pushState({}, '', `/catalog/${orgSlug}/${item.slug}`)
    window.scrollTo(0, 0)
  }

  function handleBack() {
    setItemSlug(null)
    setCurrentItem(null)
    window.history.pushState({}, '', `/catalog/${orgSlug}`)
    window.scrollTo(0, 0)
  }

  // ── Loading ──
  if (loading) {
    return (
      <div style={{
        minHeight: '100vh', background: C.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'Jost', sans-serif",
      }}>
        <div style={{ textAlign: 'center', color: C.muted }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            border: `3px solid #E8E4DC`,
            borderTopColor: C.teal,
            animation: 'spin 0.8s linear infinite',
            margin: '0 auto 16px',
          }} />
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          <p style={{ fontSize: 14 }}>Loading catalog…</p>
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

  // ── Item page ──
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
  return (
    <CatalogListPage
      orgName={catalogData.orgName}
      waNumber={catalogData.waNumber}
      catalogConfig={catalogData.catalogConfig}
      items={catalogData.items}
      onSelectItem={handleSelectItem}
    />
  )
}
