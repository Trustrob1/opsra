/**
 * frontend/src/catalog/storefront/StorefrontItemPage.jsx
 * STORE-2: Storefront look of the public product page (online-shop style).
 * Same data and routes as Classic. Buying is by WhatsApp for now; the cart and
 * Paystack checkout arrive in STORE-4 (props.shop carries the web chat key then).
 * Rule: a was-price and "% off" show only when compare-at is higher than the price.
 */
import { useMemo, useState } from 'react'
import { sanitizeHtml } from '../../utils/sanitize'
import {
  resolveAccent, readableOn, realVariants, isVariantAvailable, priceView,
  whatsappOrderLink, relatedItems, trustPoints, categoryChips, tagValues, categoryNames,
} from './storefrontLogic'
import { INK, MUTED, LINE, FONT, placeholder, useManrope } from './storefrontTheme'
import { Icon, WhatsAppIcon, ChromeStyles, Announcement, StorefrontHeader, StorefrontFooter } from './StorefrontChrome'

function normaliseImages(raw) {
  return (raw || [])
    .map((img) => (typeof img === 'string' ? { url: img, caption: '' } : img || {}))
    .filter((img) => img.url)
}

export default function StorefrontItemPage({
  orgName, waNumber, catalogConfig, style, item, items = [], onBack, onSelectItem, onShowCompare, onPickCategory,
}) {
  useManrope()
  const accent = resolveAccent(style)
  const onAccent = readableOn(accent)

  const variants = useMemo(() => realVariants(item), [item])
  const hasVariants = variants.length > 1

  const [photo, setPhoto] = useState(0)
  const [tab, setTab] = useState('details')
  // Honour ?variant= deep links. The shell re-mounts this page per product (key), so no reset effect is needed.
  const [selected, setSelected] = useState(() => {
    const wanted = new URLSearchParams(window.location.search).get('variant')
    if (!wanted) return null
    return realVariants(item).find((v) => String(v.id || '') === wanted || String(v.shopify_id || '') === wanted) || null
  })

  if (!item) return null

  const images = normaliseImages(item.catalog_images)
  const pluralLabel = catalogConfig?.catalog_item_label_plural || 'Products'
  const availLabel = catalogConfig?.availability_labels?.available || 'In stock'
  const unavailLabel = catalogConfig?.availability_labels?.unavailable || 'Out of stock'
  const inStock = item.available !== false
  const view = priceView(item, selected, catalogConfig)
  const points = trustPoints(style)
  const related = relatedItems(items, item, 4)
  const crumbCategory = style?.show_categories === false ? '' : tagValues(item, 'category').find((c) => categoryNames(catalogConfig).includes(c)) || ''
  const menu = categoryChips(items, catalogConfig, style).slice(0, 5)
  const navBtn = { border: 0, background: 'transparent', cursor: 'pointer', fontSize: 14, fontWeight: 600, minHeight: 44, padding: '0 12px', whiteSpace: 'nowrap', color: INK }

  const description = sanitizeHtml(item.description)
  const intro = item.catalog_description || ''
  const customFields = Object.entries(item.custom_fields || {}).filter(([, v]) => v !== '' && v != null)
  const tagDims = catalogConfig?.tag_dimensions || []
  const tagRows = tagDims
    .map((d) => {
      const raw = (item.tags || {})[d.key]
      const vals = Array.isArray(raw) ? raw : raw ? [raw] : []
      return vals.length ? { label: d.label || d.key, text: vals.join(', ') } : null
    })
    .filter(Boolean)
  const hasDetails = !!(intro || description)
  const hasSpecs = customFields.length > 0 || tagRows.length > 0
  const tabs = [
    hasDetails && { id: 'details', label: 'Details' },
    hasSpecs && { id: 'specs', label: catalogConfig?.specifications_section_label || 'Specifications' },
  ].filter(Boolean)
  const activeTab = tabs.find((t) => t.id === tab) ? tab : tabs[0]?.id

  const needsSize = hasVariants && !selected
  const orderHref = whatsappOrderLink(waNumber, item, selected)
  const canOrder = inStock && !needsSize && !!orderHref

  let buttonLabel = 'Order on WhatsApp'
  if (!inStock) buttonLabel = unavailLabel
  else if (needsSize) buttonLabel = 'Pick a size to order'
  else if (!orderHref) buttonLabel = 'Ordering is not set up yet'

  const mainImg = images[photo]

  return (
    <div className="sf-root" style={{ minHeight: '100vh', background: '#fff', fontFamily: FONT, color: INK }}>
      <ChromeStyles accent={accent} />
      <style>{`
        .sf-top { display: flex; gap: 56px; flex-wrap: wrap; align-items: flex-start }
        .sf-gallery { display: flex; gap: 16px; flex: 1 1 520px; min-width: 0 }
        .sf-thumbs { display: flex; flex-direction: column; gap: 12px; width: 88px; flex-shrink: 0 }
        .sf-info { flex: 1 1 420px; min-width: 0 }
        .sf-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px }
        .sf-desc p { margin: 0 0 10px; font-size: 15px; line-height: 1.7; color: #3A3F44 }
        .sf-desc ul, .sf-desc ol { padding-left: 20px; margin: 6px 0 12px }
        .sf-desc li { margin-bottom: 6px; font-size: 15px; line-height: 1.65; color: #3A3F44 }
        .sf-desc a { color: ${accent}; text-decoration: underline }
        @media (max-width: 900px) {
          .sf-top { gap: 28px }
          .sf-gallery { flex-direction: column-reverse; flex-basis: 100% }
          .sf-thumbs { flex-direction: row; width: auto; overflow-x: auto }
          .sf-info { flex-basis: 100% }
          .sf-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px }
        }
      `}</style>

      <Announcement style={style} />
      <StorefrontHeader orgName={orgName} style={style} accent={accent} onHome={() => onBack()}>
        <nav className="sf-nav" aria-label="Shop menu">
          <button onClick={() => onBack()} style={navBtn}>All {pluralLabel.toLowerCase()}</button>
          {menu.map((c) => (
            <button key={c.name} onClick={() => (onPickCategory ? onPickCategory(c.name) : onBack())} style={navBtn}>{c.name}</button>
          ))}
        </nav>
      </StorefrontHeader>

      <main className="sf-wrap">
        <nav aria-label="Breadcrumb" style={{ padding: '22px 0 20px', fontSize: 13, color: MUTED, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={onBack} style={{ border: 0, background: 'transparent', cursor: 'pointer', fontSize: 13, color: MUTED, padding: 0, minHeight: 32 }}>
            All {pluralLabel.toLowerCase()}
          </button>
          {crumbCategory && (
            <>
              <span aria-hidden="true">/</span>
              <button onClick={() => (onPickCategory ? onPickCategory(crumbCategory) : onBack())} style={{ border: 0, background: 'transparent', cursor: 'pointer', fontSize: 13, color: MUTED, padding: 0, minHeight: 32 }}>
                {crumbCategory}
              </button>
            </>
          )}
          <span aria-hidden="true">/</span>
          <span aria-current="page" style={{ color: INK, fontWeight: 600 }}>{item.title}</span>
        </nav>

        <div className="sf-top">
          <div className="sf-gallery">
            {images.length > 1 && (
              <div className="sf-thumbs">
                {images.map((img, i) => (
                  <button key={i} aria-label={`Show photo ${i + 1}`} aria-pressed={i === photo}
                    onClick={() => setPhoto(i)} style={{
                      width: 88, height: 88, flexShrink: 0, padding: 0, borderRadius: 12, cursor: 'pointer', overflow: 'hidden',
                      background: placeholder(i, 16),
                      border: i === photo ? `2px solid ${accent}` : `1px solid ${LINE}`,
                    }}>
                    <img src={img.url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                  </button>
                ))}
              </div>
            )}
            <div style={{
              flexGrow: 1, minWidth: 0, borderRadius: 20, overflow: 'hidden', aspectRatio: '1 / 1.08',
              background: placeholder(photo, 36), position: 'relative',
            }}>
              {mainImg ? (
                <img src={mainImg.url} alt={mainImg.caption || item.title}
                  style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
              ) : (
                <span style={{ position: 'absolute', left: 18, bottom: 18, padding: '6px 12px', borderRadius: 999, background: 'rgba(255,255,255,0.92)', fontSize: 12, fontWeight: 600, color: MUTED }}>
                  No photo yet
                </span>
              )}
            </div>
          </div>

          <div className="sf-info">
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700,
              background: inStock ? '#E8F3EE' : '#FBEDE4', color: inStock ? '#1B6B49' : '#9A4A12',
            }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: inStock ? '#1B6B49' : '#9A4A12' }} />
              {inStock ? availLabel : unavailLabel}
            </div>

            <h1 style={{ margin: '14px 0 0', fontSize: 'clamp(28px, 4vw, 38px)', lineHeight: 1.12, fontWeight: 800, letterSpacing: '-0.02em' }}>
              {item.title}
            </h1>

            {view.priceText && (
              <div style={{ marginTop: 18, display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 'clamp(26px, 3.4vw, 32px)', fontWeight: 800, letterSpacing: '-0.01em' }}>{view.priceText}</span>
                {view.wasText && (
                  <>
                    <span style={{ fontSize: 18, color: MUTED, textDecoration: 'line-through' }}>
                      <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Was </span>
                      {view.wasText}
                    </span>
                    <span style={{ padding: '5px 10px', borderRadius: 6, background: INK, color: '#fff', fontSize: 12, fontWeight: 800 }}>
                      {view.pct}% OFF
                    </span>
                  </>
                )}
              </div>
            )}
            {view.rangeNote && <p style={{ margin: '6px 0 0', fontSize: 13, color: MUTED }}>{view.rangeNote}</p>}

            {intro && (
              <p style={{ margin: '18px 0 0', fontSize: 15, lineHeight: 1.6, color: '#3A3F44', maxWidth: 480 }}>{intro}</p>
            )}

            {hasVariants && (
              <>
                <div style={{ height: 1, background: LINE, margin: '26px 0 22px' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
                  <div style={{ fontSize: 14 }}>
                    <span style={{ fontWeight: 700 }}>Size:</span>{' '}
                    <span style={{ color: '#3A3F44' }}>{selected ? selected.title : 'Select one'}</span>
                  </div>
                  {selected && onShowCompare && (
                    <button onClick={() => onShowCompare(selected.title)} style={{
                      border: 0, background: 'transparent', cursor: 'pointer', fontSize: 13, fontWeight: 600,
                      color: accent, textDecoration: 'underline', minHeight: 44,
                    }}>Compare by size</button>
                  )}
                </div>
                <div role="group" aria-label="Size" style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8 }}>
                  {variants.map((v, i) => {
                    const ok = isVariantAvailable(v)
                    const on = selected && selected.title === v.title
                    const vp = priceView(item, v, catalogConfig)
                    return (
                      <button key={i} disabled={!ok} aria-pressed={!!on}
                        aria-label={ok ? v.title : `${v.title}, out of stock`}
                        onClick={() => setSelected(on ? null : v)}
                        style={{
                          minWidth: 108, minHeight: 56, padding: '10px 14px', borderRadius: 12, textAlign: 'left', fontSize: 13, fontWeight: 700,
                          cursor: ok ? 'pointer' : 'not-allowed',
                          background: ok ? '#fff' : '#F6F5F2', color: ok ? INK : '#8A8F94',
                          border: !ok ? '1px dashed #C9C6BF' : on ? `2px solid ${accent}` : '1px solid #C9C6BF',
                        }}>
                        <span style={{ display: 'block', textDecoration: ok ? 'none' : 'line-through' }}>{v.title}</span>
                        <span style={{ display: 'block', marginTop: 2, fontSize: 12, fontWeight: 600, color: ok ? '#3A3F44' : '#8A8F94' }}>
                          {ok ? vp.priceText : 'Out of stock'}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </>
            )}

            <div style={{ marginTop: 26 }}>
              {canOrder ? (
                <a href={orderHref} target="_blank" rel="noopener noreferrer" style={{
                  height: 56, borderRadius: 14, background: accent, color: onAccent, fontSize: 16, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
                }}>
                  <WhatsAppIcon stroke={onAccent} />{buttonLabel}
                </a>
              ) : (
                <button disabled aria-disabled="true" style={{
                  width: '100%', height: 56, borderRadius: 14, border: 0, background: '#E6E4DF', color: '#5C6166',
                  fontSize: 16, fontWeight: 700, cursor: 'not-allowed',
                }}>{buttonLabel}</button>
              )}
            </div>

            {points.length > 0 && (
              <ul style={{ listStyle: 'none', padding: 0, margin: '26px 0 0', display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                {points.map((p) => (
                  <li key={p} style={{ display: 'flex', gap: 10, alignItems: 'center', flex: '1 1 130px', fontSize: 13, fontWeight: 700, lineHeight: 1.4 }}>
                    <Icon size={22} stroke={accent} width={2}><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>{p}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {tabs.length > 0 && (
          <section style={{ marginTop: 72, maxWidth: 720 }}>
            <div role="tablist" style={{ display: 'flex', gap: 8, borderBottom: `1px solid ${LINE}` }}>
              {tabs.map((t) => {
                const on = t.id === activeTab
                return (
                  <button key={t.id} role="tab" aria-selected={on} onClick={() => setTab(t.id)} style={{
                    padding: '14px 18px 13px', border: 0, background: 'transparent', cursor: 'pointer', fontSize: 15, minHeight: 48,
                    borderBottom: `3px solid ${on ? accent : 'transparent'}`, fontWeight: on ? 800 : 600, color: on ? INK : MUTED,
                  }}>{t.label}</button>
                )
              })}
            </div>
            <div role="tabpanel" style={{ marginTop: 24 }}>
              {activeTab === 'details' && (
                <>
                  {intro && <p style={{ margin: '0 0 12px', fontSize: 15, lineHeight: 1.7, color: '#3A3F44' }}>{intro}</p>}
                  {description && <div className="sf-desc" dangerouslySetInnerHTML={{ __html: description }} />}
                </>
              )}
              {activeTab === 'specs' && (
                <div style={{ borderTop: `1px solid ${LINE}` }}>
                  {[...tagRows, ...customFields.map(([k, v]) => ({ label: k, text: String(v) }))].map((r) => (
                    <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '14px 0', borderBottom: `1px solid ${LINE}`, fontSize: 14 }}>
                      <span style={{ color: MUTED }}>{r.label}</span>
                      <span style={{ fontWeight: 600, textAlign: 'right' }}>{r.text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {related.length > 0 && (
          <section style={{ marginTop: 80 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
              <h2 style={{ margin: 0, fontSize: 26, fontWeight: 800, letterSpacing: '-0.01em' }}>You may also like</h2>
              <button onClick={onBack} style={{ border: 0, background: 'transparent', cursor: 'pointer', fontSize: 14, fontWeight: 700, minHeight: 44 }}>View all</button>
            </div>
            <div className="sf-grid" style={{ marginTop: 22 }}>
              {related.map((r, i) => {
                const img = normaliseImages(r.catalog_images)[0]
                const rp = priceView(r, null, catalogConfig)
                return (
                  <button key={r.slug || i} onClick={() => onSelectItem && onSelectItem(r)} style={{
                    display: 'block', textAlign: 'left', border: 0, background: 'transparent', cursor: 'pointer', padding: 0, color: INK,
                  }}>
                    <div style={{ aspectRatio: '1 / 1.1', borderRadius: 16, overflow: 'hidden', background: placeholder(i, 24) }}>
                      {img && <img src={img.url} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
                    </div>
                    <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                      <span style={{ fontSize: 15, fontWeight: 700 }}>{r.title}</span>
                      <span style={{ fontSize: 15, fontWeight: 800, whiteSpace: 'nowrap' }}>{rp.priceText}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>
        )}

        <StorefrontFooter orgName={orgName} hasWhatsApp={!!waNumber} />
      </main>
    </div>
  )
}
