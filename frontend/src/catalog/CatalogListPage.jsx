/**
 * frontend/src/catalog/CatalogListPage.jsx
 * CATALOG-3B: Public product grid with tag filters and help-me-choose strip.
 * No auth. Receives data from PublicCatalogShell via props.
 * WARNING: Full rewrite required for any edit (Pattern 51).
 */
import { useState, useMemo } from 'react'

const FONTS = `
  @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Jost:wght@300;400;500;600&display=swap');
`

function injectFonts() {
  if (document.getElementById('catalog-fonts')) return
  const style = document.createElement('style')
  style.id = 'catalog-fonts'
  style.textContent = FONTS
  document.head.appendChild(style)
}

const C = {
  bg:       '#FAFAF8',
  surface:  '#FFFFFF',
  border:   '#E8E4DC',
  text:     '#1A1714',
  muted:    '#7A7269',
  teal:     '#0B6E74',
  tealLight:'#E8F4F5',
  accent:   '#C8A96E',
  danger:   '#B85C4A',
}

export default function CatalogListPage({ orgName, waNumber, catalogConfig, items, onSelectItem }) {
  injectFonts()

  const [activeFilters, setActiveFilters] = useState({})
  const [search, setSearch] = useState('')

  const tagDimensions = (catalogConfig?.tag_dimensions || []).filter(d => d.filterable)
  const itemLabel     = catalogConfig?.catalog_item_label_plural || 'Products'
  const availLabel    = catalogConfig?.availability_labels?.available    || 'In Stock'
  const unavailLabel  = catalogConfig?.availability_labels?.unavailable  || 'Out of Stock'

  // Client-side filter (Pattern 33)
  const filtered = useMemo(() => {
    let result = items || []

    // Text search
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(i =>
        (i.title || '').toLowerCase().includes(q) ||
        (i.description || '').toLowerCase().includes(q)
      )
    }

    // Tag filters
    Object.entries(activeFilters).forEach(([key, val]) => {
      if (!val) return
      result = result.filter(item => {
        const tagVal = (item.tags || {})[key]
        if (tagVal === undefined || tagVal === null) return false
        if (Array.isArray(tagVal)) return tagVal.includes(val)
        return String(tagVal).toLowerCase() === val.toLowerCase()
      })
    })

    return result
  }, [items, search, activeFilters])

  function toggleFilter(key, val) {
    setActiveFilters(prev => ({
      ...prev,
      [key]: prev[key] === val ? '' : val,
    }))
  }

  function clearFilters() {
    setActiveFilters({})
    setSearch('')
  }

  const hasFilters = search.trim() || Object.values(activeFilters).some(Boolean)

  const waLink = waNumber
    ? `https://wa.me/${waNumber}?text=${encodeURIComponent('I need help choosing')}`
    : null

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Jost', sans-serif" }}>

      {/* ── Header ── */}
      <header style={{
        borderBottom: `1px solid ${C.border}`,
        background: C.surface,
        padding: '28px 32px 24px',
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <p style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 13, letterSpacing: '0.18em',
            textTransform: 'uppercase', color: C.muted,
            margin: '0 0 4px',
          }}>{orgName}</p>
          <h1 style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 32, fontWeight: 700,
            color: C.text, margin: 0, lineHeight: 1.1,
          }}>{itemLabel}</h1>
        </div>
      </header>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 32px' }}>

        {/* ── Search + Filters ── */}
        <div style={{ padding: '24px 0 0' }}>

          {/* Search */}
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={`Search ${itemLabel.toLowerCase()}…`}
            style={{
              width: '100%', boxSizing: 'border-box',
              padding: '12px 16px',
              border: `1.5px solid ${C.border}`,
              borderRadius: 8, background: C.surface,
              fontFamily: "'Jost', sans-serif", fontSize: 14,
              color: C.text, outline: 'none',
              marginBottom: 16,
            }}
          />

          {/* Tag filter chips */}
          {tagDimensions.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              {tagDimensions.map(dim => (
                <div key={dim.key} style={{ marginBottom: 10 }}>
                  <span style={{
                    fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
                    textTransform: 'uppercase', color: C.muted,
                    display: 'block', marginBottom: 6,
                  }}>{dim.label}</span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {(dim.options || []).map(opt => {
                      const active = activeFilters[dim.key] === opt
                      return (
                        <button
                          key={opt}
                          onClick={() => toggleFilter(dim.key, opt)}
                          style={{
                            padding: '5px 14px', borderRadius: 20,
                            border: `1.5px solid ${active ? C.teal : C.border}`,
                            background: active ? C.teal : C.surface,
                            color: active ? 'white' : C.text,
                            fontFamily: "'Jost', sans-serif", fontSize: 13,
                            cursor: 'pointer', fontWeight: active ? 600 : 400,
                            transition: 'all 0.15s',
                          }}
                        >{opt}</button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Results count + clear */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'center', padding: '12px 0',
            borderTop: `1px solid ${C.border}`,
            marginBottom: 24,
          }}>
            <span style={{ fontSize: 13, color: C.muted }}>
              {filtered.length} {filtered.length === 1
                ? (catalogConfig?.catalog_item_label || 'product')
                : itemLabel.toLowerCase()}
            </span>
            {hasFilters && (
              <button onClick={clearFilters} style={{
                background: 'none', border: 'none',
                color: C.teal, fontSize: 13, cursor: 'pointer',
                fontFamily: "'Jost', sans-serif", fontWeight: 500,
              }}>Clear filters</button>
            )}
          </div>
        </div>

        {/* ── Product Grid ── */}
        {filtered.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '64px 0',
            color: C.muted, fontFamily: "'Cormorant Garamond', serif",
            fontSize: 20,
          }}>
            No {itemLabel.toLowerCase()} match your filters.
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 24,
            paddingBottom: 48,
          }}>
            {filtered.map(item => (
              <ProductCard
                key={item.id}
                item={item}
                catalogConfig={catalogConfig}
                availLabel={availLabel}
                unavailLabel={unavailLabel}
                onClick={() => onSelectItem(item)}
              />
            ))}
          </div>
        )}

        {/* ── Help me choose strip ── */}
        {waLink && (
          <div style={{
            margin: '0 0 48px',
            padding: '28px 32px',
            background: C.tealLight,
            border: `1px solid ${C.teal}22`,
            borderRadius: 12,
            display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', flexWrap: 'wrap', gap: 16,
          }}>
            <div>
              <p style={{
                fontFamily: "'Cormorant Garamond', serif",
                fontSize: 20, fontWeight: 600,
                color: C.text, margin: '0 0 4px',
              }}>Not sure which is right for you?</p>
              <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
                Chat with us and we'll help you find the perfect match.
              </p>
            </div>
            <a
              href={waLink}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                background: '#25D366', color: 'white',
                padding: '12px 22px', borderRadius: 8,
                fontFamily: "'Jost', sans-serif", fontSize: 14, fontWeight: 600,
                textDecoration: 'none', whiteSpace: 'nowrap',
              }}
            >
              💬 Help me choose
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

function ProductCard({ item, catalogConfig, availLabel, unavailLabel, onClick }) {
  const cover = (item.catalog_images || [])[0] || null
  const priceLabel = item.price_label || ''
  const isAvailable = item.available !== false

  const tagDimensions = (catalogConfig?.tag_dimensions || []).filter(d => d.filterable)

  return (
    <div
      onClick={onClick}
      style={{
        background: '#FFFFFF',
        border: `1px solid #E8E4DC`,
        borderRadius: 12,
        overflow: 'hidden',
        cursor: 'pointer',
        transition: 'box-shadow 0.2s, transform 0.2s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.boxShadow = '0 8px 32px rgba(0,0,0,0.10)'
        e.currentTarget.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      {/* Image */}
      <div style={{
        aspectRatio: '4/3',
        background: '#F5F3EF',
        overflow: 'hidden',
        position: 'relative',
      }}>
        {cover ? (
          <img
            src={cover}
            alt={item.title}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <div style={{
            width: '100%', height: '100%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#C8C0B4', fontSize: 32,
          }}>📦</div>
        )}
        {/* Availability chip */}
        <div style={{
          position: 'absolute', top: 10, right: 10,
          background: isAvailable ? '#E8F5E9' : '#FFF3E0',
          color: isAvailable ? '#2E7D32' : '#E65100',
          padding: '3px 10px', borderRadius: 20,
          fontSize: 11, fontWeight: 600,
          fontFamily: "'Jost', sans-serif",
        }}>
          {isAvailable ? availLabel : unavailLabel}
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: '16px 18px' }}>
        <h3 style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: 18, fontWeight: 600,
          color: '#1A1714', margin: '0 0 6px',
          lineHeight: 1.2,
        }}>{item.title}</h3>

        {priceLabel && (
          <p style={{
            fontFamily: "'Jost', sans-serif",
            fontSize: 15, fontWeight: 600,
            color: '#0B6E74', margin: '0 0 10px',
          }}>{priceLabel}</p>
        )}

        {/* Tag badges for filterable dimensions */}
        {tagDimensions.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {tagDimensions.map(dim => {
              const val = (item.tags || {})[dim.key]
              if (!val) return null
              const vals = Array.isArray(val) ? val : [val]
              return vals.slice(0, 2).map(v => (
                <span key={`${dim.key}-${v}`} style={{
                  fontSize: 11, padding: '2px 8px',
                  background: '#F0EDE8', borderRadius: 10,
                  color: '#7A7269', fontFamily: "'Jost', sans-serif",
                }}>{v}</span>
              ))
            })}
          </div>
        )}
      </div>
    </div>
  )
}
