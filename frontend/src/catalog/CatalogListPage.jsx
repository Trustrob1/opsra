/**
 * frontend/src/catalog/CatalogListPage.jsx
 * CATALOG-3B: Public product grid with tag filters and help-me-choose strip.
 * No auth. Receives data from PublicCatalogShell via props.
 *
 * CATALOG-UX-1 update:
 *   - Hybrid Option 1+3 layout:
 *       Header: purpose headline + two-track CTAs (WhatsApp recommendation vs browse)
 *       Wizard: step-by-step questions from org's qualification_flow (via wizardQuestions prop)
 *               Only shows if wizardQuestions.length > 0 — falls back to plain filter chips
 *       Cards:  raw tag badges removed, "View details" CTA added
 *       Help strip: updated copy, stays at bottom
 *   - wizardQuestions prop: array of { text, map_to_catalog_tag, options[] }
 *     Derived from org's qualification_flow.questions where map_to_catalog_tag is set.
 *     If empty: plain filter chips shown instead (backwards compatible).
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
  bg:        '#FAFAF8',
  surface:   '#FFFFFF',
  border:    '#E8E4DC',
  text:      '#1A1714',
  muted:     '#7A7269',
  teal:      '#0B6E74',
  tealLight: '#E8F4F5',
  accent:    '#C8A96E',
  danger:    '#B85C4A',
}

export default function CatalogListPage({
  orgName,
  waNumber,
  catalogConfig,
  wizardQuestions = [],
  items,
  onSelectItem,
}) {
  injectFonts()

  const [activeFilters, setActiveFilters] = useState({})
  const [search, setSearch]               = useState('')
  const [wizardStep, setWizardStep]       = useState(0)
  const [wizardDone, setWizardDone]       = useState(false)
  const [wizardSkipped, setWizardSkipped] = useState(false)
  const [showBrowse, setShowBrowse]       = useState(false)

  const tagDimensions  = (catalogConfig?.tag_dimensions || []).filter(d => d.filterable)
  const itemLabel      = catalogConfig?.catalog_item_label_plural || 'Products'
  const itemLabelSing  = catalogConfig?.catalog_item_label || 'product'
  const availLabel     = catalogConfig?.availability_labels?.available   || 'In Stock'
  const unavailLabel   = catalogConfig?.availability_labels?.unavailable || 'Out of Stock'

  const useWizard = wizardQuestions.length > 0
  const showGrid  = !useWizard || wizardDone || wizardSkipped || showBrowse

  const filtered = useMemo(() => {
    let result = items || []
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(i =>
        (i.title || '').toLowerCase().includes(q) ||
        (i.description || '').toLowerCase().includes(q)
      )
    }
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
    setActiveFilters(prev => ({ ...prev, [key]: prev[key] === val ? '' : val }))
  }

  function clearFilters() {
    setActiveFilters({})
    setSearch('')
    setWizardStep(0)
    setWizardDone(false)
    setWizardSkipped(false)
    setShowBrowse(false)
  }

  function handleWizardAnswer(tagKey, tagValue) {
    setActiveFilters(prev => ({ ...prev, [tagKey]: tagValue }))
    const nextStep = wizardStep + 1
    if (nextStep >= wizardQuestions.length) {
      setWizardDone(true)
    } else {
      setWizardStep(nextStep)
    }
  }

  function handleWizardBack() {
    if (wizardStep === 0) return
    const prevStep = wizardStep - 1
    const prevTagKey = wizardQuestions[prevStep].map_to_catalog_tag
    setActiveFilters(prev => ({ ...prev, [prevTagKey]: '' }))
    setWizardStep(prevStep)
    setWizardDone(false)
  }

  const hasFilters = search.trim() || Object.values(activeFilters).some(Boolean)
  const activeFilterCount = Object.values(activeFilters).filter(Boolean).length

  const waHelpLink = waNumber
    ? `https://wa.me/${waNumber.replace('+', '')}?text=${encodeURIComponent('I need help choosing')}`
    : null

  const waRecommendLink = waNumber
    ? `https://wa.me/${waNumber.replace('+', '')}?text=${encodeURIComponent("I'd like a personal recommendation")}`
    : null

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Jost', sans-serif" }}>

      {/* Header */}
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
            fontSize: 30, fontWeight: 700,
            color: C.text, margin: '0 0 8px', lineHeight: 1.15,
          }}>
            {useWizard && !showGrid
              ? `Find your perfect ${itemLabelSing}`
              : itemLabel}
          </h1>

          {useWizard && !showGrid && (
            <p style={{ fontSize: 14, color: C.muted, margin: '0 0 16px', lineHeight: 1.5 }}>
              Answer a few quick questions and we will match you with the right {itemLabelSing.toLowerCase()} — or browse everything below.
            </p>
          )}

          {useWizard && !showGrid && waRecommendLink && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <a
                href={waRecommendLink}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  background: '#25D366', color: 'white',
                  padding: '10px 20px', borderRadius: 8,
                  fontFamily: "'Jost', sans-serif", fontSize: 13, fontWeight: 600,
                  textDecoration: 'none', whiteSpace: 'nowrap',
                }}
              >
                Get a personal recommendation
              </a>
              <button
                onClick={() => setShowBrowse(true)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                  background: C.surface, color: C.teal,
                  border: `1.5px solid ${C.teal}`,
                  padding: '10px 20px', borderRadius: 8,
                  fontFamily: "'Jost', sans-serif", fontSize: 13, fontWeight: 600,
                  cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >
                Browse all {itemLabel.toLowerCase()}
              </button>
            </div>
          )}
        </div>
      </header>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 32px' }}>

        {/* Wizard */}
        {useWizard && !showGrid && (
          <div style={{ padding: '28px 0' }}>
            <div style={{
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: 12, padding: '24px 28px',
            }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 12,
              }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: C.text }}>
                  Help me find the right one
                </span>
                <span style={{ fontSize: 12, color: C.muted }}>
                  Step {wizardStep + 1} of {wizardQuestions.length}
                </span>
              </div>
              <div style={{ height: 3, background: C.border, borderRadius: 2, marginBottom: 20 }}>
                <div style={{
                  height: 3,
                  width: `${(wizardStep / wizardQuestions.length) * 100}%`,
                  background: C.teal, borderRadius: 2,
                  transition: 'width 0.3s ease',
                }} />
              </div>

              <p style={{
                fontFamily: "'Cormorant Garamond', serif",
                fontSize: 20, fontWeight: 600,
                color: C.text, margin: '0 0 16px', lineHeight: 1.3,
              }}>
                {wizardQuestions[wizardStep].text}
              </p>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
                {wizardQuestions[wizardStep].options.map(opt => {
                  const isSelected = activeFilters[wizardQuestions[wizardStep].map_to_catalog_tag] === opt.tag_value
                  return (
                    <button
                      key={opt.id}
                      onClick={() => handleWizardAnswer(
                        wizardQuestions[wizardStep].map_to_catalog_tag,
                        opt.tag_value
                      )}
                      style={{
                        padding: '9px 20px', borderRadius: 24,
                        border: `1.5px solid ${isSelected ? C.teal : C.border}`,
                        background: isSelected ? C.teal : C.surface,
                        color: isSelected ? 'white' : C.text,
                        fontFamily: "'Jost', sans-serif", fontSize: 14,
                        cursor: 'pointer', fontWeight: isSelected ? 600 : 400,
                        transition: 'all 0.15s',
                      }}
                    >
                      {opt.label}
                    </button>
                  )
                })}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button
                  onClick={handleWizardBack}
                  disabled={wizardStep === 0}
                  style={{
                    background: 'none', border: 'none',
                    fontSize: 13, color: wizardStep === 0 ? C.border : C.muted,
                    cursor: wizardStep === 0 ? 'default' : 'pointer',
                    fontFamily: "'Jost', sans-serif", padding: 0,
                  }}
                >
                  Back
                </button>
                <button
                  onClick={() => setWizardSkipped(true)}
                  style={{
                    background: 'none', border: 'none',
                    fontSize: 12, color: C.muted,
                    cursor: 'pointer',
                    fontFamily: "'Jost', sans-serif", padding: 0,
                  }}
                >
                  Skip and show all {itemLabel.toLowerCase()}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Grid section */}
        {showGrid && (
          <div style={{ padding: '24px 0 0' }}>

            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={`Search ${itemLabel.toLowerCase()}...`}
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '12px 16px',
                border: `1.5px solid ${C.border}`,
                borderRadius: 8, background: C.surface,
                fontFamily: "'Jost', sans-serif", fontSize: 14,
                color: C.text, outline: 'none', marginBottom: 16,
              }}
            />

            {/* Plain filter chips — only when no wizard configured */}
            {!useWizard && tagDimensions.length > 0 && (
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

            {/* Results bar */}
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', padding: '12px 0',
              borderTop: `1px solid ${C.border}`, marginBottom: 24,
            }}>
              <span style={{ fontSize: 13, color: C.muted }}>
                {wizardDone && activeFilterCount > 0
                  ? `${filtered.length} ${filtered.length === 1 ? itemLabelSing : itemLabel.toLowerCase()} matched your answers`
                  : `${filtered.length} ${filtered.length === 1 ? itemLabelSing : itemLabel.toLowerCase()}`
                }
              </span>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                {wizardDone && (
                  <button
                    onClick={() => { setWizardStep(0); setWizardDone(false); setActiveFilters({}) }}
                    style={{
                      background: 'none', border: 'none',
                      color: C.teal, fontSize: 13, cursor: 'pointer',
                      fontFamily: "'Jost', sans-serif", fontWeight: 500,
                    }}
                  >Edit answers</button>
                )}
                {hasFilters && (
                  <button onClick={clearFilters} style={{
                    background: 'none', border: 'none',
                    color: C.muted, fontSize: 13, cursor: 'pointer',
                    fontFamily: "'Jost', sans-serif",
                  }}>Clear all</button>
                )}
              </div>
            </div>

            {/* Product grid */}
            {filtered.length === 0 ? (
              <div style={{
                textAlign: 'center', padding: '64px 0',
                color: C.muted, fontFamily: "'Cormorant Garamond', serif", fontSize: 20,
              }}>
                No {itemLabel.toLowerCase()} match your answers.
                <div style={{ marginTop: 16 }}>
                  <button onClick={clearFilters} style={{
                    background: 'none', border: `1px solid ${C.border}`,
                    borderRadius: 8, padding: '9px 20px',
                    color: C.teal, fontSize: 13, cursor: 'pointer',
                    fontFamily: "'Jost', sans-serif",
                  }}>Show all {itemLabel.toLowerCase()}</button>
                </div>
              </div>
            ) : (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: 24, paddingBottom: 48,
              }}>
                {filtered.map(item => (
                  <ProductCard
                    key={item.id}
                    item={item}
                    catalogConfig={catalogConfig}
                    availLabel={availLabel}
                    unavailLabel={unavailLabel}
                    itemLabelSing={itemLabelSing}
                    onClick={() => onSelectItem(item)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Help me choose strip */}
        {showGrid && waHelpLink && (
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
              }}>Not sure which {itemLabelSing.toLowerCase()} fits you?</p>
              <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
                Chat with us and get a recommendation tailored to your needs.
              </p>
            </div>
            <a
              href={waHelpLink}
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
              Chat with us
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

function ProductCard({ item, catalogConfig, availLabel, unavailLabel, itemLabelSing, onClick }) {
  const cover = (item.catalog_images || [])[0] || null
  const priceLabel = item.price_label || ''
  const isAvailable = item.available !== false

  const tagDimensions = (catalogConfig?.tag_dimensions || []).filter(d => d.filterable)
  const cardTags = tagDimensions.filter(d =>
    ['feel', 'firmness', 'health', 'purpose', 'type', 'pillow'].some(k =>
      d.key.toLowerCase().includes(k) || (d.label || '').toLowerCase().includes(k)
    )
  )

  return (
    <div
      onClick={onClick}
      style={{
        background: '#FFFFFF',
        border: '1px solid #E8E4DC',
        borderRadius: 12, overflow: 'hidden',
        cursor: 'pointer',
        transition: 'box-shadow 0.2s, transform 0.2s',
        display: 'flex', flexDirection: 'column',
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
      <div style={{
        aspectRatio: '4/3', background: '#F5F3EF',
        overflow: 'hidden', position: 'relative',
      }}>
        {cover ? (
          <img src={cover} alt={item.title}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <div style={{
            width: '100%', height: '100%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#C8C0B4', fontSize: 32,
          }}>No image</div>
        )}
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

      <div style={{ padding: '16px 18px', flex: 1, display: 'flex', flexDirection: 'column' }}>
        <h3 style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: 18, fontWeight: 600,
          color: '#1A1714', margin: '0 0 6px', lineHeight: 1.2,
        }}>{item.title}</h3>

        {priceLabel && (
          <p style={{
            fontFamily: "'Jost', sans-serif",
            fontSize: 15, fontWeight: 600,
            color: '#0B6E74', margin: '0 0 10px',
          }}>{priceLabel}</p>
        )}

        {cardTags.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 12 }}>
            {cardTags.map(dim => {
              const val = (item.tags || {})[dim.key]
              if (!val) return null
              const vals = Array.isArray(val) ? val : [val]
              return vals.slice(0, 2).map(v => (
                <span key={`${dim.key}-${v}`} style={{
                  fontSize: 11, padding: '3px 9px',
                  background: '#F0EDE8', borderRadius: 10,
                  color: '#5A5248',
                  fontFamily: "'Jost', sans-serif",
                }}>{v}</span>
              ))
            })}
          </div>
        )}

        <div style={{ flex: 1 }} />
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 6, paddingTop: 12,
          borderTop: '1px solid #E8E4DC',
          color: '#0B6E74', fontSize: 13, fontWeight: 600,
          fontFamily: "'Jost', sans-serif",
        }}>
          View details
        </div>
      </div>
    </div>
  )
}
