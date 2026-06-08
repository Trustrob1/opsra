/**
 * frontend/src/catalog/CatalogSizeComparePage.jsx
 * CATALOG-COMPARE: Size comparison page.
 * Shows all products available in a specific size, with exact variant prices.
 * Accessed via /catalog/{org_slug}/compare?size={size_value}
 * Shareable URL generated from CatalogListPage when a size filter is active.
 * NO auth dependency. Public page.
 * WARNING: Full rewrite required for any edit (Pattern 51).
 */
import { useState } from 'react'

const C = {
  bg:        '#FAFAF8',
  surface:   '#FFFFFF',
  border:    '#E8E4DC',
  text:      '#1A1714',
  muted:     '#7A7269',
  teal:      '#0B6E74',
  tealLight: '#E8F4F5',
  tealDark:  '#085041',
  green:     '#2E7D32',
  greenBg:   '#E8F5E9',
  orange:    '#E65100',
  orangeBg:  '#FFF3E0',
}

function isVariantAvailable(v) {
  if (!v) return false
  if (typeof v.available === 'boolean') return v.available
  return (
    v.inventory_management === null ||
    v.inventory_management === undefined ||
    v.inventory_policy === 'continue' ||
    parseInt(v.inventory_quantity || 0) > 0
  )
}

function formatPrice(price, template) {
  if (price === null || price === undefined || price === '') return ''
  const tmpl = template || '₦{price}'
  const formatted = parseFloat(price).toLocaleString('en-NG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
  return tmpl.replace('{price}', formatted)
}

function getVariantForSize(item, sizeValue) {
  const variants = (item.variants || []).filter(
    v => v && v.title && v.title.toLowerCase() !== 'default title'
  )
  return variants.find(
    v => v.title.trim().toLowerCase() === sizeValue.trim().toLowerCase()
  ) || null
}

function getDescriptiveTags(item, tagDimensions) {
  const DESCRIPTIVE_KEYS = ['feel', 'firmness', 'health', 'purpose']
  const dims = tagDimensions.filter(d =>
    DESCRIPTIVE_KEYS.some(k =>
      d.key.toLowerCase().includes(k) || (d.label || '').toLowerCase().includes(k)
    )
  )
  const result = []
  dims.forEach(dim => {
    const val = (item.tags || {})[dim.key]
    if (!val) return
    const vals = Array.isArray(val) ? val : [val]
    vals.slice(0, 2).forEach(v => result.push(v))
  })
  return result
}

function getWeightTag(item, tagDimensions) {
  const weightDim = tagDimensions.find(d =>
    d.key.toLowerCase().includes('weight')
  )
  if (!weightDim) return null
  const val = (item.tags || {})[weightDim.key]
  if (!val) return null
  const vals = Array.isArray(val) ? val : [val]
  if (!vals.length) return null
  if (vals.length === 1) return vals[0]
  const sorted = [...vals].sort((a, b) => {
    const numA = parseFloat(a) || 0
    const numB = parseFloat(b) || 0
    return numA - numB
  })
  return `${sorted[0]} – ${sorted[sorted.length - 1]}`
}

export default function CatalogSizeComparePage({
  orgName,
  waNumber,
  catalogConfig,
  items = [],
  sizeValue,
  onBack,
  onSelectItem,
}) {
  const [linkCopied, setLinkCopied] = useState(false)

  const priceTemplate  = catalogConfig?.price_label_template || '₦{price}'
  const priceOnReq     = catalogConfig?.price_on_request || false
  const tagDimensions  = catalogConfig?.tag_dimensions || []
  const ctaButtons     = catalogConfig?.cta_buttons || []
  const itemLabelPlur  = catalogConfig?.catalog_item_label_plural || 'Products'
  const itemLabelSing  = catalogConfig?.catalog_item_label || 'product'
  const availLabel     = catalogConfig?.availability_labels?.available || 'In Stock'
  const unavailLabel   = catalogConfig?.availability_labels?.unavailable || 'Out of Stock'

  // Sort: available first, then by price ascending
  const sortedItems = [...items].sort((a, b) => {
    const varA = getVariantForSize(a, sizeValue)
    const varB = getVariantForSize(b, sizeValue)
    const availA = varA ? isVariantAvailable(varA) : false
    const availB = varB ? isVariantAvailable(varB) : false
    if (availA !== availB) return availA ? -1 : 1
    const priceA = parseFloat(varA?.price || a.price || 0)
    const priceB = parseFloat(varB?.price || b.price || 0)
    return priceA - priceB
  })

  const availableCount = sortedItems.filter(item => {
    const v = getVariantForSize(item, sizeValue)
    return v ? isVariantAvailable(v) : false
  }).length

  function copyLink() {
    const url = window.location.href
    navigator.clipboard?.writeText(url).then(() => {
      setLinkCopied(true)
      setTimeout(() => setLinkCopied(false), 2000)
    })
  }

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Jost', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Jost:wght@300;400;500;600&display=swap');
        .cc-card { transition: box-shadow 0.18s, transform 0.18s; }
        .cc-card:hover { box-shadow: 0 6px 24px rgba(0,0,0,0.08); transform: translateY(-2px); }
        .cc-btn-outline { transition: background 0.15s; }
        .cc-btn-outline:hover { background: ${C.tealLight} !important; }
        @media (max-width: 600px) {
          .cc-header { padding: 10px 14px !important; }
          .cc-info-bar { flex-direction: column !important; align-items: flex-start !important; }
          .cc-grid { grid-template-columns: 1fr !important; }
          .cc-card-inner { flex-direction: column !important; }
          .cc-card-img { width: 100% !important; height: 160px !important; }
          .cc-help { flex-direction: column !important; align-items: flex-start !important; }
        }
      `}</style>

      {/* Header */}
      <header className="cc-header" style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`,
        padding: '14px 24px', position: 'sticky', top: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <button
          onClick={onBack}
          style={{
            background: 'none', border: `1px solid ${C.border}`,
            borderRadius: 7, padding: '5px 12px',
            fontFamily: "'Jost', sans-serif", fontSize: 13,
            color: C.muted, cursor: 'pointer', flexShrink: 0,
          }}
        >
          ← All {itemLabelPlur}
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 13, color: C.muted, margin: 0,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>{orgName}</p>
          <p style={{
            fontSize: 15, fontWeight: 600, color: C.text, margin: 0,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>{sizeValue}</p>
        </div>
      </header>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: '20px 20px 48px' }}>

        {/* Info bar */}
        <div className="cc-info-bar" style={{
          background: C.surface, border: `1px solid ${C.border}`,
          borderRadius: 10, padding: '14px 18px', marginBottom: 20,
          display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', gap: 12,
        }}>
          <div>
            <p style={{ fontSize: 14, fontWeight: 600, color: C.text, margin: '0 0 2px' }}>
              {availableCount} {availableCount === 1 ? itemLabelSing : itemLabelPlur.toLowerCase()} available in {sizeValue}
            </p>
            <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              Prices shown are for this size only.
            </p>
          </div>
          <button
            onClick={copyLink}
            style={{
              background: linkCopied ? C.teal : C.surface,
              color: linkCopied ? 'white' : C.teal,
              border: `1px solid ${linkCopied ? C.teal : C.border}`,
              borderRadius: 8, padding: '7px 14px',
              fontFamily: "'Jost', sans-serif", fontSize: 12,
              fontWeight: 600, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              transition: 'background 0.2s, color 0.2s',
              flexShrink: 0,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/>
            </svg>
            {linkCopied ? 'Link copied!' : 'Copy link'}
          </button>
        </div>

        {/* Product grid */}
        {sortedItems.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '64px 0',
            color: C.muted, fontFamily: "'Cormorant Garamond', serif", fontSize: 20,
          }}>
            No {itemLabelPlur.toLowerCase()} found for this size.
            <div style={{ marginTop: 16 }}>
              <button onClick={onBack} style={{
                background: 'none', border: `1px solid ${C.border}`,
                borderRadius: 8, padding: '9px 20px',
                color: C.teal, fontSize: 13, cursor: 'pointer',
                fontFamily: "'Jost', sans-serif",
              }}>Browse all {itemLabelPlur.toLowerCase()}</button>
            </div>
          </div>
        ) : (
          <div className="cc-grid" style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 16,
          }}>
            {sortedItems.map((item, idx) => {
              const variant      = getVariantForSize(item, sizeValue)
              const available    = variant ? isVariantAvailable(variant) : false
              const variantPrice = variant ? parseFloat(variant.price || 0) : null
              const priceDisplay = priceOnReq
                ? 'Price on Request'
                : variantPrice
                  ? formatPrice(variantPrice, priceTemplate)
                  : item.price_label || ''
              const cover       = (item.catalog_images || [])[0] || null
              const descTags    = getDescriptiveTags(item, tagDimensions)
              const weightTag   = getWeightTag(item, tagDimensions)
              const isMostPop   = idx === 0 && available
              const waMessage   = `Hi, I'm interested in the ${sizeValue} size ${item.title}`
              const orderLink   = waNumber
                ? `https://wa.me/${waNumber}?text=${encodeURIComponent(waMessage)}`
                : null
              const postQualLinks = waNumber
                ? ctaButtons.map(btn => ({
                    ...btn,
                    href: `https://wa.me/${waNumber}?text=${encodeURIComponent(btn.id)}`,
                  }))
                : []

              return (
                <div
                  key={item.id}
                  className="cc-card"
                  style={{
                    background: C.surface,
                    border: isMostPop ? `2px solid ${C.teal}` : `1px solid ${C.border}`,
                    borderRadius: 12, overflow: 'hidden',
                    display: 'flex', flexDirection: 'column',
                    opacity: available ? 1 : 0.65,
                  }}
                >
                  {isMostPop && (
                    <div style={{
                      background: C.teal, textAlign: 'center',
                      padding: '4px 0', fontSize: 11, fontWeight: 600,
                      color: 'white', letterSpacing: '0.04em',
                    }}>
                      Most popular
                    </div>
                  )}

                  {/* Image */}
                  <div style={{
                    aspectRatio: '16/9', background: '#F5F3EF',
                    overflow: 'hidden', position: 'relative', flexShrink: 0,
                  }}>
                    {cover ? (
                      <img
                        src={typeof cover === 'string' ? cover : cover.url}
                        alt={item.title}
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      />
                    ) : (
                      <div style={{
                        width: '100%', height: '100%',
                        display: 'flex', alignItems: 'center',
                        justifyContent: 'center', color: '#C8C0B4', fontSize: 36,
                      }}>🛏</div>
                    )}
                    <div style={{
                      position: 'absolute', top: 8, right: 8,
                      background: available ? C.greenBg : C.orangeBg,
                      color: available ? C.green : C.orange,
                      padding: '3px 9px', borderRadius: 20,
                      fontSize: 11, fontWeight: 600,
                    }}>
                      {available ? availLabel : unavailLabel}
                    </div>
                  </div>

                  {/* Content */}
                  <div style={{ padding: '14px 16px', flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>

                    {/* Title + price */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                      <h3
                        onClick={() => onSelectItem && onSelectItem(item)}
                        style={{
                          fontFamily: "'Cormorant Garamond', serif",
                          fontSize: 17, fontWeight: 600,
                          color: C.text, margin: 0, lineHeight: 1.25,
                          cursor: onSelectItem ? 'pointer' : 'default',
                          flex: 1,
                        }}
                      >
                        {item.title}
                      </h3>
                      <div style={{ textAlign: 'right', flexShrink: 0 }}>
                        <p style={{ fontSize: 16, fontWeight: 600, color: C.teal, margin: 0 }}>
                          {priceDisplay}
                        </p>
                        <p style={{ fontSize: 10, color: C.muted, margin: '1px 0 0' }}>
                          {sizeValue}
                        </p>
                      </div>
                    </div>

                    {/* Tags */}
                    {(descTags.length > 0 || weightTag) && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {descTags.map((tag, i) => (
                          <span key={i} style={{
                            fontSize: 11, padding: '3px 8px',
                            background: '#F0EDE8', borderRadius: 10,
                            color: '#5A5248',
                          }}>{tag}</span>
                        ))}
                        {weightTag && (
                          <span style={{
                            fontSize: 11, padding: '3px 8px',
                            background: '#F0EDE8', borderRadius: 10,
                            color: '#5A5248',
                          }}>{weightTag}</span>
                        )}
                      </div>
                    )}

                    {/* Short description */}
                    {item.catalog_description && (
                      <p style={{
                        fontSize: 12, color: C.muted, margin: 0,
                        lineHeight: 1.6, flex: 1,
                        display: '-webkit-box',
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>
                        {item.catalog_description}
                      </p>
                    )}

                    {/* CTAs */}
                    <div style={{
                      borderTop: `1px solid ${C.border}`,
                      paddingTop: 10, marginTop: 4,
                    }}>
                      {available ? (
                        <div style={{ display: 'flex', gap: 8 }}>
                          {onSelectItem && (
                            <button
                              onClick={() => onSelectItem(item)}
                              className="cc-btn-outline"
                              style={{
                                flex: 1, fontSize: 12, fontWeight: 600,
                                color: C.teal, padding: '7px 0',
                                border: `1px solid ${C.teal}`,
                                borderRadius: 8, cursor: 'pointer',
                                background: C.surface,
                                fontFamily: "'Jost', sans-serif",
                              }}
                            >
                              View details
                            </button>
                          )}
                          {orderLink && (
                            <a
                              href={orderLink}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{
                                flex: 1, textAlign: 'center',
                                fontSize: 12, fontWeight: 600,
                                color: 'white', padding: '7px 0',
                                background: '#25D366',
                                borderRadius: 8, textDecoration: 'none',
                                display: 'block',
                              }}
                            >
                              Order on WhatsApp
                            </a>
                          )}
                        </div>
                      ) : (
                        <p style={{
                          fontSize: 12, color: C.muted, margin: 0,
                          textAlign: 'center',
                        }}>
                          {unavailLabel} in this size — {' '}
                          {onSelectItem && (
                            <span
                              onClick={() => onSelectItem(item)}
                              style={{ color: C.teal, cursor: 'pointer', textDecoration: 'underline' }}
                            >
                              view other sizes
                            </span>
                          )}
                        </p>
                      )}

                      {/* Post-qual CTA buttons */}
                      {available && postQualLinks.length > 0 && (
                        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {postQualLinks.map(btn => (
                            <a
                              key={btn.id}
                              href={btn.href}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{
                                fontSize: 11, fontWeight: 600,
                                color: C.teal, padding: '5px 12px',
                                border: `1px solid ${C.teal}`,
                                borderRadius: 8, textDecoration: 'none',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {btn.label}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Help strip */}
        {waNumber && (
          <div className="cc-help" style={{
            marginTop: 24,
            background: C.surface, border: `1px solid ${C.border}`,
            borderRadius: 10, padding: '16px 20px',
            display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', gap: 14,
          }}>
            <div>
              <p style={{
                fontFamily: "'Cormorant Garamond', serif",
                fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 3px',
              }}>Not sure which to pick?</p>
              <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
                Our team can help you decide based on your needs and budget.
              </p>
            </div>
            <a
              href={`https://wa.me/${waNumber}?text=${encodeURIComponent(`I need help choosing a ${sizeValue} mattress`)}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                background: '#25D366', color: 'white',
                padding: '10px 18px', borderRadius: 8,
                fontFamily: "'Jost', sans-serif", fontSize: 13, fontWeight: 600,
                textDecoration: 'none', flexShrink: 0,
              }}
            >
              Chat with us
            </a>
          </div>
        )}

      </div>
    </div>
  )
}
