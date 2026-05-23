/**
 * frontend/src/catalog/CatalogItemPage.jsx
 * CATALOG-3B: Individual public product page.
 * Image gallery, description, tag badges, custom fields, dual CTA variants.
 * WARNING: Full rewrite required for any edit (Pattern 51).
 */
import { useState } from 'react'

const C = {
  bg:       '#FAFAF8',
  surface:  '#FFFFFF',
  border:   '#E8E4DC',
  text:     '#1A1714',
  muted:    '#7A7269',
  teal:     '#0B6E74',
  tealLight:'#E8F4F5',
  accent:   '#C8A96E',
}

export default function CatalogItemPage({ orgName, waNumber, catalogConfig, item, onBack }) {
  const [activeImg, setActiveImg] = useState(0)

  if (!item) return null

  const images        = item.catalog_images || []
  const itemLabel     = catalogConfig?.catalog_item_label        || 'Product'
  const itemLabelPlur = catalogConfig?.catalog_item_label_plural || 'Products'
  const availLabel    = catalogConfig?.availability_labels?.available    || 'In Stock'
  const unavailLabel  = catalogConfig?.availability_labels?.unavailable  || 'Out of Stock'
  const ctaButtons    = catalogConfig?.cta_buttons || []
  const tagDimensions = catalogConfig?.tag_dimensions || []
  const customFields  = item.custom_fields || {}
  const isAvailable   = item.available !== false

  // Variant A — cold visitor WhatsApp CTA
  const orderLink = waNumber
    ? `https://wa.me/${waNumber}?text=${encodeURIComponent(`Hi, I'm interested in the ${item.title}`)}`
    : null

  // Variant B — post-qual CTA buttons (button_id sent as pre-filled text)
  const postQualLinks = waNumber
    ? ctaButtons.map(btn => ({
        ...btn,
        href: `https://wa.me/${waNumber}?text=${encodeURIComponent(btn.id)}`,
      }))
    : []

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Jost', sans-serif" }}>

      {/* ── Header ── */}
      <header style={{
        borderBottom: `1px solid ${C.border}`,
        background: C.surface,
        padding: '20px 32px',
        position: 'sticky', top: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <button
          onClick={onBack}
          style={{
            background: 'none', border: `1px solid ${C.border}`,
            borderRadius: 7, padding: '6px 14px',
            fontFamily: "'Jost', sans-serif", fontSize: 13,
            color: C.muted, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
          }}
        >← Browse all {itemLabelPlur}</button>
        <span style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: 15, color: C.muted,
        }}>{orgName}</span>
      </header>

      <div style={{ maxWidth: 960, margin: '0 auto', padding: '40px 32px 64px' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
          gap: 48,
        }}>

          {/* ── Left: Image Gallery ── */}
          <div>
            {/* Main image */}
            <div style={{
              aspectRatio: '1/1',
              background: '#F5F3EF',
              borderRadius: 12,
              overflow: 'hidden',
              marginBottom: 12,
              border: `1px solid ${C.border}`,
            }}>
              {images[activeImg] ? (
                <img
                  src={images[activeImg]}
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

            {/* Thumbnails */}
            {images.length > 1 && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {images.map((img, i) => (
                  <div
                    key={i}
                    onClick={() => setActiveImg(i)}
                    style={{
                      width: 64, height: 64,
                      borderRadius: 8, overflow: 'hidden',
                      border: `2px solid ${i === activeImg ? C.teal : C.border}`,
                      cursor: 'pointer', flexShrink: 0,
                    }}
                  >
                    <img src={img} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Right: Details ── */}
          <div>
            {/* Availability */}
            <div style={{
              display: 'inline-block',
              background: isAvailable ? '#E8F5E9' : '#FFF3E0',
              color: isAvailable ? '#2E7D32' : '#E65100',
              padding: '4px 12px', borderRadius: 20,
              fontSize: 12, fontWeight: 600, marginBottom: 12,
            }}>
              {isAvailable ? availLabel : unavailLabel}
            </div>

            {/* Title */}
            <h1 style={{
              fontFamily: "'Cormorant Garamond', serif",
              fontSize: 32, fontWeight: 700,
              color: C.text, margin: '0 0 10px', lineHeight: 1.15,
            }}>{item.title}</h1>

            {/* Price */}
            {item.price_label && (
              <p style={{
                fontFamily: "'Jost', sans-serif",
                fontSize: 22, fontWeight: 600,
                color: C.teal, margin: '0 0 20px',
              }}>{item.price_label}</p>
            )}

            {/* Tag badges */}
            {tagDimensions.length > 0 && (
              <div style={{ marginBottom: 20 }}>
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

            {/* Description */}
            {item.description && (
              <div style={{ marginBottom: 24 }}>
                <div
                  style={{
                    fontSize: 14, lineHeight: 1.7,
                    color: C.muted,
                    maxHeight: 200, overflowY: 'auto',
                  }}
                  dangerouslySetInnerHTML={{ __html: item.description }}
                />
              </div>
            )}

            {/* Custom fields */}
            {Object.keys(customFields).length > 0 && (
              <div style={{
                background: '#F5F3EF', borderRadius: 8,
                padding: '14px 16px', marginBottom: 24,
              }}>
                {Object.entries(customFields).map(([k, v]) => (
                  <div key={k} style={{
                    display: 'flex', justifyContent: 'space-between',
                    padding: '5px 0',
                    borderBottom: `1px solid ${C.border}`,
                    fontSize: 13,
                  }}>
                    <span style={{ color: C.muted, textTransform: 'capitalize' }}>
                      {k.replace(/_/g, ' ')}
                    </span>
                    <span style={{ color: C.text, fontWeight: 500 }}>{String(v)}</span>
                  </div>
                ))}
              </div>
            )}

            {/* ── Variant A: Cold visitor CTA ── */}
            {orderLink && (
              <div style={{
                background: C.tealLight,
                border: `1px solid ${C.teal}33`,
                borderRadius: 10,
                padding: '20px 20px',
                marginBottom: 16,
              }}>
                <p style={{
                  fontFamily: "'Cormorant Garamond', serif",
                  fontSize: 17, fontWeight: 600,
                  color: C.text, margin: '0 0 4px',
                }}>
                  Interested in this {itemLabel}? Chat with us on WhatsApp 💬
                </p>
                <p style={{ fontSize: 12, color: C.muted, margin: '0 0 14px' }}>
                  Our team will answer any questions and help you order.
                </p>
                <a
                  href={orderLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    background: '#25D366', color: 'white',
                    padding: '12px 22px', borderRadius: 8,
                    fontFamily: "'Jost', sans-serif", fontSize: 14, fontWeight: 600,
                    textDecoration: 'none',
                  }}
                >
                  Order via WhatsApp
                </a>
              </div>
            )}

            {/* ── Variant B: Post-qual CTA buttons ── */}
            {postQualLinks.length > 0 && (
              <div style={{
                borderTop: `1px solid ${C.border}`,
                paddingTop: 16,
              }}>
                <p style={{
                  fontSize: 13, color: C.muted,
                  fontStyle: 'italic', margin: '0 0 10px',
                }}>
                  Returning from a recommendation? Complete your request:
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {postQualLinks.map(btn => (
                    <a
                      key={btn.id}
                      href={btn.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'block', textAlign: 'center',
                        padding: '12px 20px', borderRadius: 8,
                        border: `1.5px solid ${C.teal}`,
                        color: C.teal, fontFamily: "'Jost', sans-serif",
                        fontSize: 14, fontWeight: 600,
                        textDecoration: 'none',
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
        </div>
      </div>
    </div>
  )
}
