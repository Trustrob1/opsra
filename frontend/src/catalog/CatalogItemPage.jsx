/**
 * frontend/src/catalog/CatalogItemPage.jsx
 * CATALOG-3B: Individual public product page.
 * Option C accordion layout: Description collapsible (defaultOpen), Gallery and
 * Specifications collapsible with configurable labels.
 * Sticky CTA bar: appears on scroll past title via IntersectionObserver.
 * Shopify HTML description: CSS section dividers via :has(> strong/b:first-child).
 * Image captions: backwards compatible — supports string[] and {url,caption}[].
 * Mobile-first: auto-width buttons, responsive padding.
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

/**
 * Normalise catalog_images to {url, caption}[] format.
 * Backwards compatible: plain string URLs → { url, caption: '' }
 */
function normaliseImages(raw) {
  return (raw || []).map(img =>
    typeof img === 'string' ? { url: img, caption: '' } : (img || {})
  )
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
        <span style={{ fontSize: 13, color: C.muted, lineHeight: 1, userSelect: 'none' }}>
          {open ? '▴' : '▾'}
        </span>
      </button>
      {open && <div style={{ paddingBottom: 16 }}>{children}</div>}
    </div>
  )
}

export default function CatalogItemPage({ orgName, waNumber, catalogConfig, item, onBack }) {
  const [activeImg, setActiveImg]   = useState(0)
  const [showSticky, setShowSticky] = useState(false)
  const titleRef = useRef(null)

  // Show sticky bar only once title scrolls out of view
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

  const hasGallery = images.length > 1
  const hasSpecs   = Object.keys(customFields).length > 0
  const hasDesc    = !!(item.catalog_description || item.description)

  // Variant A — cold visitor WhatsApp CTA
  const orderLink = waNumber
    ? `https://wa.me/${waNumber}?text=${encodeURIComponent(`Hi, I'm interested in the ${item.title}`)}`
    : null

  // Variant B — post-qual CTA buttons
  const postQualLinks = waNumber
    ? ctaButtons.map(btn => ({
        ...btn,
        href: `https://wa.me/${waNumber}?text=${encodeURIComponent(btn.id)}`,
      }))
    : []

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Jost', sans-serif" }}>
      <style>{`
        .ci-header  { padding: 18px 32px; }
        .ci-content { padding: 32px 32px 64px; }
        .ci-btns    { display: flex; flex-wrap: wrap; gap: 10px; }

        /* Shopify description HTML styling */
        .ci-desc p  { margin: 0 0 6px; font-size: 14px; line-height: 1.75; color: #7A7269; }
        .ci-desc strong, .ci-desc b { color: #1A1714; }
        .ci-desc ul, .ci-desc ol    { padding-left: 20px; margin: 6px 0 10px; }
        .ci-desc li { margin-bottom: 4px; font-size: 14px; line-height: 1.65; color: #7A7269; }
        .ci-desc a  { color: #0B6E74; text-decoration: underline; }

        /* Section dividers: paragraph starting with bold = new section */
        .ci-desc p:not(:first-child):has(> strong:first-child),
        .ci-desc p:not(:first-child):has(> b:first-child) {
          margin-top: 16px;
          padding-top: 14px;
          border-top: 1px solid #E8E4DC;
        }

        /* Sticky CTA bar */
        .ci-sticky {
          position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
          background: #FFFFFF;
          border-top: 1px solid #E8E4DC;
          padding: 12px 32px;
          display: flex; align-items: center;
          justify-content: space-between; gap: 16px;
          box-shadow: 0 -4px 16px rgba(26,23,20,0.07);
          transition: transform 0.2s ease;
        }
        .ci-sticky-title {
          font-size: 13px; font-weight: 600; color: #1A1714;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          flex: 1; min-width: 0;
        }
        .ci-sticky-price {
          font-size: 13px; font-weight: 600; color: #0B6E74;
          flex-shrink: 0;
        }

        @media (max-width: 640px) {
          .ci-header  { padding: 12px 16px; }
          .ci-content { padding: 20px 16px 80px; }
          .ci-btns    { gap: 8px; }
          .ci-sticky  { padding: 10px 16px; }
          .ci-sticky-title { font-size: 12px; }
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
            <img
              src={images[activeImg].url}
              alt={item.title}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          ) : (
            <div style={{
              width: '100%', height: '100%',
              display: 'flex', alignItems: 'center',
              justifyContent: 'center', color: '#C8C0B4', fontSize: 48,
            }}>📦</div>
          )}
        </div>

        {/* Active image caption */}
        {images[activeImg]?.caption
          ? <p style={{ fontSize: 12, color: C.muted, margin: '0 0 20px', fontStyle: 'italic', lineHeight: 1.5 }}>
              {images[activeImg].caption}
            </p>
          : <div style={{ marginBottom: 20 }} />
        }

        {/* ── Title + Price (observed for sticky bar trigger) ── */}
        <div ref={titleRef} style={{
          display: 'flex', justifyContent: 'space-between',
          alignItems: 'flex-start', gap: 16, flexWrap: 'wrap',
          marginBottom: 14,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
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
          {item.price_label && (
            <div style={{
              fontSize: 22, fontWeight: 600, color: C.teal,
              flexShrink: 0, paddingTop: 30,
            }}>{item.price_label}</div>
          )}
        </div>

        {/* ── Tag badges ── */}
        {tagDimensions.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            {tagDimensions.map(dim => {
              const val = (item.tags || {})[dim.key]
              if (!val) return null
              const vals = Array.isArray(val) ? val : [val]
              return (
                <div key={dim.key} style={{ marginBottom: 8 }}>
                  <span style={{
                    fontSize: 11, fontWeight: 600, letterSpacing: '0.08em',
                    textTransform: 'uppercase', color: C.muted,
                    display: 'block', marginBottom: 4,
                  }}>{dim.label}</span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {vals.map(v => (
                      <span key={v} style={{
                        fontSize: 12, padding: '3px 10px',
                        background: C.tealLight, color: C.teal,
                        borderRadius: 12, fontWeight: 500,
                      }}>{v}</span>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* ── Description accordion (fixed label, collapsible, open by default) ── */}
        {hasDesc && (
          <AccordionSection label="Description" defaultOpen>
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
                dangerouslySetInnerHTML={{ __html: item.description }}
              />
            )}
          </AccordionSection>
        )}

        {/* ── Gallery accordion (configurable label, open by default) ── */}
        {hasGallery && (
          <AccordionSection label={`${galleryLabel} (${images.length})`} defaultOpen>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
              gap: 10,
            }}>
              {images.map((img, i) => (
                <div key={i} onClick={() => setActiveImg(i)} style={{ cursor: 'pointer' }}>
                  <div style={{
                    aspectRatio: '1/1', borderRadius: 8, overflow: 'hidden',
                    border: `2px solid ${i === activeImg ? C.teal : C.border}`,
                    marginBottom: img.caption ? 4 : 0,
                    transition: 'border-color 0.15s',
                  }}>
                    {img.url
                      ? <img src={img.url} alt={img.caption || ''} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      : <div style={{ width: '100%', height: '100%', background: '#F5F3EF' }} />
                    }
                  </div>
                  {img.caption && (
                    <p style={{ fontSize: 11, color: C.muted, margin: 0, lineHeight: 1.4 }}>
                      {img.caption}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </AccordionSection>
        )}

        {/* ── Specifications accordion (configurable label, open by default) ── */}
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

        {/* ── CTAs (inline — always present in page flow) ── */}
        <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 24, marginTop: 8 }}>

          {/* Variant A: Cold visitor */}
          {orderLink && (
            <div style={{
              background: C.tealLight, border: `1px solid ${C.teal}33`,
              borderRadius: 10, padding: '18px 20px', marginBottom: 16,
            }}>
              <p style={{
                fontFamily: "'Cormorant Garamond', serif",
                fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 4px',
              }}>
                Interested in this {itemLabel}? Chat with us on WhatsApp 💬
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
                Order via WhatsApp
              </a>
            </div>
          )}

          {/* Variant B: Post-qual */}
          {postQualLinks.length > 0 && (
            <div>
              <p style={{ fontSize: 13, color: C.muted, fontStyle: 'italic', margin: '0 0 10px' }}>
                Returning from a recommendation? Complete your request:
              </p>
              <div className="ci-btns">
                {postQualLinks.map(btn => (
                  <a
                    key={btn.id}
                    href={btn.href}
                    target="_blank"
                    rel="noopener noreferrer"
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

        {/* ── Back link (bottom) ── */}
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

      {/* ── Sticky CTA bar (appears when title scrolls out of view) ── */}
      {orderLink && showSticky && (
        <div className="ci-sticky">
          <div style={{ flex: 1, minWidth: 0 }}>
            <p className="ci-sticky-title">{item.title}</p>
            {item.price_label && (
              <p className="ci-sticky-price">{item.price_label}</p>
            )}
          </div>
          <a href={orderLink} target="_blank" rel="noopener noreferrer" style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#25D366', color: 'white',
            padding: '9px 16px', borderRadius: 8,
            fontFamily: "'Jost', sans-serif", fontSize: 13, fontWeight: 600,
            textDecoration: 'none', flexShrink: 0,
          }}>
            Order via WhatsApp
          </a>
        </div>
      )}
    </div>
  )
}
