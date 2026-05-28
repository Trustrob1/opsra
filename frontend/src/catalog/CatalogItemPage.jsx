/**
 * frontend/src/catalog/CatalogItemPage.jsx
 * CATALOG-3B: Individual public product page.
 * Hybrid variant selector: clickable size buttons + expandable price table.
 * Non-Shopify products (no variants) fall back to item.price_label — backwards compatible.
 * Option C accordion layout, sticky CTA bar, Shopify HTML section dividers.
 * WARNING: Full rewrite required for any edit (Pattern 51).
 */
import { useState, useRef, useEffect } from 'react'

const C = {
  bg:        '#FAFAF8',
  surface:   '#FFFFFF',
  border:    '#E8E4DC',
  text:      '#1A1714',
  muted:     '#7A7269',
  teal:      '#0B6E74',
  tealLight: '#E8F4F5',
  accent:    '#C8A96E',
}

function normaliseImages(raw) {
  return (raw || []).map(img =>
    typeof img === 'string' ? { url: img, caption: '' } : (img || {})
  )
}

/** Mirror of backend availability logic — must stay in sync with shopify_service.py */
function isVariantAvailable(v) {
  if (!v) return false
  // Non-Shopify variants carry an explicit available boolean — use it directly
  if (typeof v.available === 'boolean') return v.available
  // Shopify variants — derive from inventory fields
  return (
    v.inventory_management === null ||
    v.inventory_management === undefined ||
    v.inventory_policy === 'continue' ||
    parseInt(v.inventory_quantity || 0) > 0
  )
}

/** Format a numeric price using the org price_label_template. */
function formatVariantPrice(price, template, priceOnRequest) {
  if (priceOnRequest) return 'Price on Request'
  if (price === null || price === undefined || price === '') return ''
  const tmpl = template || '₦{price}'
  const formatted = parseFloat(price).toLocaleString('en-NG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
  return tmpl.replace('{price}', formatted)
}

function AccordionSection({ label, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderTop: `1px solid ${C.border}` }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', background: 'none', border: 'none',
          padding: '14px 0',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          cursor: 'pointer', fontFamily: "'Jost', sans-serif",
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', color: C.text }}>
          {label}
        </span>
        <span style={{
          fontSize: 11, fontWeight: 500,
          padding: '3px 10px', borderRadius: 20,
          background: open ? C.teal : C.tealLight,
          color: open ? 'white' : C.teal,
          userSelect: 'none', flexShrink: 0,
          transition: 'background 0.15s, color 0.15s',
        }}>
          {open ? 'Hide ▴' : 'Show ▾'}
        </span>
      </button>
      {open && <div style={{ paddingBottom: 16 }}>{children}</div>}
    </div>
  )
}

function preprocessDescription(html) {
  if (!html) return ''
  let pCount = 0
  return html
    .replace(/<(h[2-5])([^>]*)>/gi, '<p$2 class="ci-section-head">')
    .replace(/<\/h[2-5]>/gi, '</p>')
    .replace(/<p([^>]*)>([\s\S]*?)<\/p>/gi, (match, attrs, content) => {
      pCount++
      if (pCount === 1) return match
      const plain = content.replace(/<[^>]+>/g, '').trim()
      if (plain.length > 0 && plain.length < 90) {
        const already = /ci-section-head/.test(attrs)
        return `<p${attrs}${already ? '' : ' class="ci-section-head"'}>${content}</p>`
      }
      return match
    })
}

export default function CatalogItemPage({ orgName, waNumber, catalogConfig, item, onBack }) {
  const [activeImg, setActiveImg]         = useState(0)
  const [showSticky, setShowSticky]       = useState(false)
  const [selectedVariant, setSelectedVariant] = useState(null)
  const [showPriceTable, setShowPriceTable]   = useState(false)
  const titleRef = useRef(null)

  useEffect(() => {
    const el = titleRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => setShowSticky(!entry.isIntersecting),
      { threshold: 0 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  if (!item) return null

  const images        = normaliseImages(item.catalog_images)
  const itemLabel     = catalogConfig?.catalog_item_label        || 'Product'
  const itemLabelPlur = catalogConfig?.catalog_item_label_plural || 'Products'
  const availLabel    = catalogConfig?.availability_labels?.available   || 'In Stock'
  const unavailLabel  = catalogConfig?.availability_labels?.unavailable || 'Out of Stock'
  const ctaButtons    = catalogConfig?.cta_buttons    || []
  const tagDimensions = catalogConfig?.tag_dimensions || []
  const customFields  = item.custom_fields || {}
  const isAvailable   = item.available !== false
  const galleryLabel  = catalogConfig?.gallery_section_label        || 'Gallery'
  const specsLabel    = catalogConfig?.specifications_section_label || 'Specifications'
  const priceTemplate = catalogConfig?.price_label_template || '₦{price}'
  const priceOnReq    = catalogConfig?.price_on_request || false

  // ── Variant selector data ─────────────────────────────────────────────────
  // Filter out "Default Title" (single-variant Shopify products with no real options)
  const shopifyVariants = (item.variants || []).filter(
    v => v && v.title && v.title.toLowerCase() !== 'default title'
  )
  const hasVariants = shopifyVariants.length > 1

  // Compute price range from all variants for the unselected state
  const variantPrices = shopifyVariants
    .map(v => parseFloat(v.price || 0))
    .filter(p => p > 0)
  const priceMin = variantPrices.length ? Math.min(...variantPrices) : null
  const priceMax = variantPrices.length ? Math.max(...variantPrices) : null
  const showRange = hasVariants && priceMin !== null && priceMax !== null && priceMin !== priceMax

  // Displayed price: selected variant > range > fallback item.price_label
  let displayedPrice
  if (priceOnReq) {
    displayedPrice = 'Price on Request'
  } else if (selectedVariant) {
    displayedPrice = formatVariantPrice(selectedVariant.price, priceTemplate, false)
  } else if (showRange) {
    displayedPrice = `${formatVariantPrice(priceMin, priceTemplate, false)} – ${formatVariantPrice(priceMax, priceTemplate, false)}`
  } else {
    displayedPrice = item.price_label || null
  }

  const priceHint = selectedVariant
    ? selectedVariant.title
    : showRange
      ? 'Select a size to see exact price'
      : null

  // ── WhatsApp CTA links ────────────────────────────────────────────────────
  const waMessage = selectedVariant
    ? `Hi, I'm interested in the ${selectedVariant.title} size ${item.title}`
    : `Hi, I'm interested in the ${item.title}`

  const orderLink = waNumber
    ? `https://wa.me/${waNumber}?text=${encodeURIComponent(waMessage)}`
    : null

  const postQualLinks = waNumber
    ? ctaButtons.map(btn => ({
        ...btn,
        href: `https://wa.me/${waNumber}?text=${encodeURIComponent(btn.id)}`,
      }))
    : []

  const hasGallery = images.length > 1
  const hasSpecs   = Object.keys(customFields).length > 0
  const hasDesc    = !!(item.catalog_description || item.description)

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Jost', sans-serif" }}>
      <style>{`
        .ci-header  { padding: 18px 32px; }
        .ci-content { padding: 32px 32px 80px; }
        .ci-btns    { display: flex; flex-wrap: wrap; gap: 10px; }

        .ci-desc p  { margin: 0 0 6px; font-size: 14px; line-height: 1.75; color: #7A7269; }
        .ci-desc strong, .ci-desc b { color: #1A1714; }
        .ci-desc ul, .ci-desc ol    { padding-left: 20px; margin: 6px 0 10px; }
        .ci-desc li { margin-bottom: 4px; font-size: 14px; line-height: 1.65; color: #7A7269; }
        .ci-desc a  { color: #0B6E74; text-decoration: underline; }
        .ci-desc p.ci-section-head,
        .ci-desc p:not(:first-child):has(> strong:first-child),
        .ci-desc p:not(:first-child):has(> b:first-child) {
          margin-top: 16px; padding-top: 14px;
          border-top: 1px solid #E8E4DC;
          font-weight: 500; color: #1A1714;
        }
        .ci-desc > p:first-child { border-top: none !important; padding-top: 0 !important; margin-top: 0 !important; }

        .ci-size-btn {
          padding: 8px 14px; border-radius: 8px;
          border: 0.5px solid #C8C0B4;
          background: #FFFFFF;
          font-size: 13px; color: #1A1714;
          cursor: pointer; font-family: 'Jost', sans-serif;
          transition: border-color 0.15s, background 0.15s, color 0.15s;
        }
        .ci-size-btn:hover:not(:disabled) { border-color: #0B6E74; background: #E8F4F5; color: #0B6E74; }
        .ci-size-btn.selected { border: 1.5px solid #0B6E74; background: #E8F4F5; color: #0B6E74; font-weight: 500; }
        .ci-size-btn:disabled { opacity: 0.38; cursor: not-allowed; text-decoration: line-through; }

        .ci-sticky {
          position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
          background: #FFFFFF; border-top: 1px solid #E8E4DC;
          padding: 12px 32px;
          display: flex; align-items: center;
          justify-content: space-between; gap: 16px;
          box-shadow: 0 -4px 16px rgba(26,23,20,0.07);
        }

        @media (max-width: 640px) {
          .ci-header  { padding: 12px 16px; }
          .ci-content { padding: 20px 16px 80px; }
          .ci-btns    { gap: 8px; }
          .ci-sticky  { padding: 10px 16px; }
        }
      `}</style>

      {/* ── Header ── */}
      <header className="ci-header" style={{
        borderBottom: `1px solid ${C.border}`, background: C.surface,
        position: 'sticky', top: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <button onClick={onBack} style={{
          background: 'none', border: `1px solid ${C.border}`, borderRadius: 7,
          padding: '6px 14px', fontFamily: "'Jost', sans-serif", fontSize: 13,
          color: C.muted, cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', gap: 6,
        }}>
          ← Browse all {itemLabelPlur}
        </button>
        <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, color: C.muted }}>
          {orgName}
        </span>
      </header>

      <div className="ci-content" style={{ maxWidth: 720, margin: '0 auto' }}>

        {/* ── Main image ── */}
        <div style={{
          width: '100%', aspectRatio: '16/9',
          background: '#F5F3EF', borderRadius: 12, overflow: 'hidden',
          border: `1px solid ${C.border}`, marginBottom: 8,
        }}>
          {images[activeImg]?.url ? (
            <img src={images[activeImg].url} alt={item.title}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          ) : (
            <div style={{
              width: '100%', height: '100%',
              display: 'flex', alignItems: 'center',
              justifyContent: 'center', color: '#C8C0B4', fontSize: 48,
            }}>📦</div>
          )}
        </div>

        {/* ── Thumbnail strip — always visible directly below main image ── */}
        {images.length > 1 && (
          <div style={{
            display: 'flex', gap: 6, overflowX: 'auto',
            padding: '6px 0 10px',
            WebkitOverflowScrolling: 'touch',
            scrollbarWidth: 'none',
          }}>
            {images.map((img, i) => (
              <div
                key={i}
                onClick={() => setActiveImg(i)}
                style={{
                  flexShrink: 0,
                  width: 56, height: 56,
                  borderRadius: 6, overflow: 'hidden',
                  border: `2px solid ${i === activeImg ? C.teal : C.border}`,
                  cursor: 'pointer',
                  transition: 'border-color 0.15s',
                  background: '#F5F3EF',
                }}
              >
                {img.url
                  ? <img src={img.url} alt={img.caption || `Image ${i + 1}`}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  : <div style={{ width: '100%', height: '100%', background: '#F0EDE8' }} />
                }
              </div>
            ))}
          </div>
        )}

        {/* Caption for active image if present */}
        {images[activeImg]?.caption
          ? <p style={{ fontSize: 12, color: C.muted, margin: '0 0 16px', fontStyle: 'italic', lineHeight: 1.5 }}>
              {images[activeImg].caption}
            </p>
          : <div style={{ marginBottom: 16 }} />
        }

        {/* ── Title + availability ── */}
        <div ref={titleRef} style={{ marginBottom: 14 }}>
          <div style={{
            display: 'inline-block',
            background: isAvailable ? '#E8F5E9' : '#FFF3E0',
            color: isAvailable ? '#2E7D32' : '#E65100',
            padding: '3px 10px', borderRadius: 20,
            fontSize: 11, fontWeight: 600, marginBottom: 8,
          }}>
            {isAvailable ? availLabel : unavailLabel}
          </div>
          <h1 style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 28, fontWeight: 700,
            color: C.text, margin: 0, lineHeight: 1.2,
          }}>{item.title}</h1>
        </div>

        {/* ── Price display ── */}
        {displayedPrice && (
          <div style={{ marginBottom: hasVariants ? 4 : 20 }}>
            <div style={{ fontSize: 22, fontWeight: 600, color: C.teal }}>
              {displayedPrice}
            </div>
            {priceHint && (
              <p style={{ fontSize: 12, color: C.muted, margin: '3px 0 0' }}>{priceHint}</p>
            )}
          </div>
        )}

        {/* ── Variant size selector ── */}
        {hasVariants && (
          <div style={{ marginBottom: 20, marginTop: 16 }}>
            <p style={{
              fontSize: 11, fontWeight: 600, letterSpacing: '0.07em',
              textTransform: 'uppercase', color: C.muted, margin: '0 0 10px',
            }}>Select size</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
              {shopifyVariants.map((v, i) => {
                const avail = isVariantAvailable(v)
                const sel   = selectedVariant?.title === v.title
                return (
                  <button
                    key={i}
                    disabled={!avail}
                    onClick={() => setSelectedVariant(sel ? null : v)}
                    className={`ci-size-btn${sel ? ' selected' : ''}`}
                    title={!avail ? 'Out of stock' : ''}
                  >
                    {v.title}
                  </button>
                )
              })}
            </div>

            {/* View all prices toggle */}
            <button
              onClick={() => setShowPriceTable(p => !p)}
              style={{
                background: 'none', border: 'none', padding: 0,
                fontFamily: "'Jost', sans-serif", fontSize: 12,
                color: C.teal, cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 4,
              }}
            >
              <span>{showPriceTable ? '▴ Hide prices' : '▾ View all prices'}</span>
            </button>

            {showPriceTable && (
              <table style={{
                width: '100%', borderCollapse: 'collapse',
                marginTop: 10, fontSize: 13,
              }}>
                <tbody>
                  {shopifyVariants.map((v, i) => {
                    const avail = isVariantAvailable(v)
                    const sel   = selectedVariant?.title === v.title
                    return (
                      <tr key={i} style={{
                        borderBottom: i < shopifyVariants.length - 1
                          ? `1px solid ${C.border}` : 'none',
                        background: sel ? C.tealLight : 'transparent',
                        cursor: avail ? 'pointer' : 'default',
                      }} onClick={() => avail && setSelectedVariant(sel ? null : v)}>
                        <td style={{
                          padding: '8px 6px',
                          color: sel ? C.teal : avail ? C.text : C.muted,
                          textDecoration: avail ? 'none' : 'line-through',
                          borderRadius: sel ? '6px 0 0 6px' : 0,
                        }}>
                          {v.title}
                        </td>
                        <td style={{
                          padding: '8px 6px', textAlign: 'right',
                          fontWeight: 500,
                          color: sel ? C.teal : avail ? C.text : C.muted,
                          borderRadius: sel ? '0 6px 6px 0' : 0,
                        }}>
                          {avail
                            ? formatVariantPrice(v.price, priceTemplate, priceOnReq)
                            : 'Out of stock'
                          }
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* ── Tag spec table — descriptive dimensions only (T1) ── */}
        {(() => {
          const DESCRIPTIVE_KEYS = ['feel', 'firmness', 'health', 'purpose', 'type', 'pillow', 'size']
          const descriptiveDims = tagDimensions.filter(d =>
            DESCRIPTIVE_KEYS.some(k =>
              d.key.toLowerCase().includes(k) || (d.label || '').toLowerCase().includes(k)
            )
          )
          const rows = descriptiveDims
            .map(dim => {
              const val = (item.tags || {})[dim.key]
              if (!val) return null
              const vals = Array.isArray(val) ? val : [val]
              if (!vals.length) return null
              // For size dimensions with many values, show first 2 + count
              const MAX_INLINE = 3
              const display = vals.length > MAX_INLINE
                ? vals.slice(0, MAX_INLINE).join(', ') + ` +${vals.length - MAX_INLINE} more`
                : vals.join(', ')
              return { label: dim.label, display }
            })
            .filter(Boolean)

          if (!rows.length) return null
          return (
            <div style={{
              background: '#F5F3EF', borderRadius: 8,
              padding: '2px 14px', marginBottom: 16,
            }}>
              {rows.map((row, idx) => (
                <div key={row.label} style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'baseline', gap: 12, padding: '8px 0',
                  borderBottom: idx < rows.length - 1 ? `1px solid ${C.border}` : 'none',
                  fontSize: 13,
                }}>
                  <span style={{ color: C.muted, flexShrink: 0 }}>{row.label}</span>
                  <span style={{ color: C.text, fontWeight: 500, textAlign: 'right' }}>
                    {row.display}
                  </span>
                </div>
              ))}
            </div>
          )
        })()}

        {/* ── Description accordion ── */}
        {hasDesc && (
          <AccordionSection label="Description" defaultOpen={false}>
            {item.catalog_description && (
              <div style={{
                fontSize: 14, lineHeight: 1.75, color: C.text,
                marginBottom: item.description ? 12 : 0,
              }}>
                {item.catalog_description}
              </div>
            )}
            {item.description && (
              <div
                className="ci-desc"
                dangerouslySetInnerHTML={{ __html: preprocessDescription(item.description) }}
              />
            )}
          </AccordionSection>
        )}

        {/* Gallery accordion removed — thumbnails now shown directly below main image */}

        {/* ── Specifications accordion ── */}
        {hasSpecs && (
          <AccordionSection label={specsLabel} defaultOpen>
            <div style={{ background: '#F5F3EF', borderRadius: 8, padding: '2px 16px' }}>
              {Object.entries(customFields).map(([k, v], idx, arr) => (
                <div key={k} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                  padding: '9px 0', gap: 12,
                  borderBottom: idx < arr.length - 1 ? `1px solid ${C.border}` : 'none',
                  fontSize: 13,
                }}>
                  <span style={{ color: C.muted, textTransform: 'capitalize', flexShrink: 0 }}>
                    {k.replace(/_/g, ' ')}
                  </span>
                  <span style={{ color: C.text, fontWeight: 500, textAlign: 'right' }}>
                    {String(v)}
                  </span>
                </div>
              ))}
            </div>
          </AccordionSection>
        )}

        {/* ── Inline CTAs ── */}
        <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 24, marginTop: 8 }}>

          {orderLink && (
            <div style={{
              background: C.tealLight, border: `1px solid ${C.teal}33`,
              borderRadius: 10, padding: '18px 20px', marginBottom: 16,
            }}>
              <p style={{
                fontFamily: "'Cormorant Garamond', serif",
                fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 4px',
              }}>
                {selectedVariant
                  ? `Interested in the ${selectedVariant.title}? Chat with us on WhatsApp 💬`
                  : `Interested in this ${itemLabel}? Chat with us on WhatsApp 💬`
                }
              </p>
              <p style={{ fontSize: 12, color: C.muted, margin: '0 0 14px' }}>
                Our team will answer any questions and help you order.
              </p>
              <a href={orderLink} target="_blank" rel="noopener noreferrer" style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                background: '#25D366', color: 'white',
                padding: '10px 20px', borderRadius: 8,
                fontFamily: "'Jost', sans-serif", fontSize: 14, fontWeight: 600,
                textDecoration: 'none',
              }}>
                {selectedVariant ? `Order ${selectedVariant.title} via WhatsApp` : 'Order via WhatsApp'}
              </a>
            </div>
          )}

          {postQualLinks.length > 0 && (
            <div>
              <p style={{ fontSize: 13, color: C.muted, fontStyle: 'italic', margin: '0 0 10px' }}>
                Returning from a recommendation? Complete your request:
              </p>
              <div className="ci-btns">
                {postQualLinks.map(btn => (
                  <a key={btn.id} href={btn.href} target="_blank" rel="noopener noreferrer"
                    style={{
                      display: 'inline-flex', alignItems: 'center',
                      padding: '10px 18px', borderRadius: 8,
                      border: `1.5px solid ${C.teal}`,
                      color: C.teal, fontFamily: "'Jost', sans-serif",
                      fontSize: 13, fontWeight: 600,
                      textDecoration: 'none', whiteSpace: 'nowrap',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = C.tealLight }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    {btn.label}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Back link ── */}
        <div style={{ marginTop: 32, paddingTop: 20, borderTop: `1px solid ${C.border}` }}>
          <button onClick={onBack} style={{
            background: 'none', border: 'none', padding: 0,
            fontFamily: "'Jost', sans-serif", fontSize: 13,
            color: C.muted, cursor: 'pointer',
          }}>
            ← Browse all {itemLabelPlur}
          </button>
        </div>
      </div>

      {/* ── Sticky CTA bar ── */}
      {orderLink && showSticky && (
        <div className="ci-sticky">
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{
              margin: 0, fontSize: 13, fontWeight: 600, color: C.text,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {selectedVariant ? `${item.title} — ${selectedVariant.title}` : item.title}
            </p>
            {displayedPrice && (
              <p style={{ margin: 0, fontSize: 13, color: C.teal, fontWeight: 600 }}>
                {displayedPrice}
              </p>
            )}
          </div>
          <a href={orderLink} target="_blank" rel="noopener noreferrer" style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#25D366', color: 'white',
            padding: '9px 16px', borderRadius: 8,
            fontFamily: "'Jost', sans-serif", fontSize: 13, fontWeight: 600,
            textDecoration: 'none', flexShrink: 0,
          }}>
            {selectedVariant ? `Order ${selectedVariant.title}` : 'Order via WhatsApp'}
          </a>
        </div>
      )}
    </div>
  )
}
