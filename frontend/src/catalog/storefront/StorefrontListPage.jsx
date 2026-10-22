/**
 * frontend/src/catalog/storefront/StorefrontListPage.jsx
 * STORE-3: Storefront look of the public product list (online-shop grid).
 * Search, category buttons, tag filters, "Help me choose" finder and size compare all keep working.
 * Buying is by WhatsApp from the product page; cart and checkout arrive in STORE-4.
 */
import { useMemo, useState } from 'react'
import {
  resolveAccent, readableOn, categoryChips, otherFilterDims, filterItems, cardView, readUrlState, listUrl,
} from './storefrontLogic'
import { INK, MUTED, LINE, FONT, placeholder, useManrope } from './storefrontTheme'
import {
  Icon, WhatsAppIcon, ChromeStyles, Announcement, StorefrontHeader, StorefrontFooter,
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

function Finder({ questions, accent, onAnswer, onClear, done, matchCount, itemWord }) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)
  const onAccent = readableOn(accent)
  const q = questions[step]

  if (done) {
    return (
      <div style={{ marginTop: 20, padding: '18px 22px', borderRadius: 16, background: '#F1F6F5', display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800 }}>
            {matchCount === 1 ? `1 ${itemWord} fits` : `${matchCount} ${itemWord}s fit`} your answers
          </div>
          <div style={{ marginTop: 3, fontSize: 14, color: '#3A3F44' }}>Scroll down to see them.</div>
        </div>
        <button onClick={() => { onClear(); setStep(0); setOpen(false) }} style={{
          height: 46, padding: '0 22px', border: `1.5px solid ${INK}`, borderRadius: 12, background: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer',
        }}>Change answers</button>
      </div>
    )
  }

  return (
    <div style={{ marginTop: 20, padding: '18px 22px', borderRadius: 16, background: '#F1F6F5' }}>
      <div style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800 }}>Not sure which one?</div>
          <div style={{ marginTop: 3, fontSize: 14, color: '#3A3F44' }}>
            Answer {questions.length} quick {questions.length === 1 ? 'question' : 'questions'} and we will show the best fit.
          </div>
        </div>
        <button aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{
          height: 46, padding: '0 22px', border: 0, borderRadius: 12, background: accent, color: onAccent, fontSize: 14, fontWeight: 700, cursor: 'pointer',
        }}>{open ? 'Close' : 'Help me choose'}</button>
      </div>
      {open && q && (
        <div style={{ marginTop: 18, paddingTop: 16, borderTop: `1px solid ${LINE}` }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: MUTED }}>Question {step + 1} of {questions.length}</div>
          <div style={{ marginTop: 6, fontSize: 18, fontWeight: 800 }}>{q.text}</div>
          <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {(q.options || []).map((opt) => (
              <button key={opt.id || opt.tag_value} onClick={() => {
                onAnswer(q.map_to_catalog_tag, opt.tag_value, step + 1 >= questions.length)
                if (step + 1 < questions.length) setStep(step + 1)
                else setOpen(false)
              }} style={{
                minHeight: 44, padding: '0 18px', borderRadius: 22, border: '1px solid #C9C6BF', background: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', color: INK,
              }}>{opt.label}</button>
            ))}
          </div>
          <div style={{ marginTop: 14, display: 'flex', justifyContent: 'space-between' }}>
            <button disabled={step === 0} onClick={() => { onClear(questions[step - 1]?.map_to_catalog_tag); setStep(step - 1) }} style={{
              minHeight: 44, border: 0, background: 'transparent', fontSize: 14, fontWeight: 600, color: step === 0 ? '#B5B8BB' : INK, cursor: step === 0 ? 'default' : 'pointer', padding: 0,
            }}>Back</button>
            <button onClick={() => setOpen(false)} style={{ minHeight: 44, border: 0, background: 'transparent', fontSize: 14, fontWeight: 600, textDecoration: 'underline', cursor: 'pointer', padding: 0 }}>
              Skip and browse all
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function StorefrontListPage({
  orgName, orgSlug, waNumber, catalogConfig, style, wizardQuestions = [], items = [], onSelectItem, onShowCompare, headerCart,
}) {
  useManrope()
  const accent = resolveAccent(style)
  const plural = catalogConfig?.catalog_item_label_plural || 'Products'
  const singular = catalogConfig?.catalog_item_label || 'Product'

  const [filters, setFilters] = useState(() => readUrlState(window.location.search, catalogConfig))
  const [search, setSearch] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [finderDone, setFinderDone] = useState(false)

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
    setFinderDone(false)
    try { window.history.replaceState({}, '', listUrl(orgSlug, null, window.location.search)) } catch { /* address bar only */ }
  }

  const waHelp = waNumber
    ? `https://wa.me/${String(waNumber).replace('+', '')}?text=${encodeURIComponent(`I need help choosing a ${singular.toLowerCase()}`)}`
    : null

  const heading = activeCategory || plural
  const countText = `${shown.length} ${shown.length === 1 ? singular.toLowerCase() : plural.toLowerCase()}`

  return (
    <div className="sf-root" style={{ minHeight: '100vh', background: '#fff', fontFamily: FONT, color: INK }}>
      <ChromeStyles accent={accent} />
      <style>{`
        .sf-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 28px 24px }
        .sf-chips { display: flex; gap: 10px; flex-wrap: wrap; align-items: center }
        @media (max-width: 1000px) { .sf-cards { grid-template-columns: repeat(3, minmax(0, 1fr)) } }
        @media (max-width: 700px) {
          .sf-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px 14px }
          .sf-chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 4px }
          .sf-chips::-webkit-scrollbar { display: none }
        }
      `}</style>

      <Announcement style={style} />
      <StorefrontHeader orgName={orgName} style={style} accent={accent} onHome={clearAll} cart={headerCart}>
        <div className="sf-search-slot">
          <label style={{
            height: 44, border: '1px solid #C9C6BF', borderRadius: 22, display: 'flex', alignItems: 'center', gap: 10, padding: '0 18px', boxSizing: 'border-box', color: MUTED,
          }}>
            <Icon size={18} stroke={MUTED}><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></Icon>
            <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Search {plural.toLowerCase()}</span>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={`Search ${plural.toLowerCase()}`}
              style={{ border: 0, outline: 'none', flexGrow: 1, minWidth: 0, fontSize: 14, background: 'transparent', color: INK }} />
          </label>
        </div>
      </StorefrontHeader>

      <main className="sf-wrap">
        <div style={{ marginTop: 36, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 24, flexWrap: 'wrap' }}>
          <h1 style={{ margin: 0, fontSize: 'clamp(28px, 4.4vw, 40px)', lineHeight: 1.1, fontWeight: 800, letterSpacing: '-0.02em' }}>{heading}</h1>
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

        {wizardQuestions.length > 0 && (
          <Finder
            questions={wizardQuestions}
            accent={accent}
            done={finderDone}
            matchCount={shown.length}
            itemWord={singular.toLowerCase()}
            onAnswer={(key, val, last) => {
              setFilters((p) => ({ ...p, [key]: val }))
              if (last) setFinderDone(true)
            }}
            onClear={(key) => {
              if (key) {
                setFilters((p) => ({ ...p, [key]: '' }))
              } else {
                setFilters((p) => {
                  const next = { ...p }
                  wizardQuestions.forEach((w) => { next[w.map_to_catalog_tag] = '' })
                  return next
                })
                setFinderDone(false)
              }
            }}
          />
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
              return (
                <button key={it.id || it.slug} onClick={() => onSelectItem(it)} style={{
                  display: 'block', textAlign: 'left', border: 0, background: 'transparent', cursor: 'pointer', padding: 0, color: INK,
                }}>
                  <div style={{ position: 'relative', aspectRatio: '1 / 1.1', borderRadius: 16, overflow: 'hidden', background: placeholder(i, 24) }}>
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
              )
            })}
          </div>
        )}

        {anyActive && shown.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <button onClick={clearAll} style={{ minHeight: 44, border: 0, background: 'transparent', fontSize: 14, fontWeight: 600, textDecoration: 'underline', cursor: 'pointer', color: MUTED, padding: 0 }}>Clear all</button>
          </div>
        )}

        {waHelp && (
          <section style={{ marginTop: 72, padding: '32px 36px', borderRadius: 20, background: INK, color: '#fff', display: 'flex', gap: 24, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>Need help choosing?</div>
              <div style={{ marginTop: 6, fontSize: 14, color: '#D5D8DB' }}>Our team can recommend the right {singular.toLowerCase()} for you on WhatsApp.</div>
            </div>
            <a href={waHelp} target="_blank" rel="noopener noreferrer" style={{
              minHeight: 52, padding: '0 26px', borderRadius: 14, background: '#fff', color: INK, display: 'flex', alignItems: 'center', gap: 10, fontSize: 15, fontWeight: 700,
            }}>
              <WhatsAppIcon stroke={INK} />Chat on WhatsApp
            </a>
          </section>
        )}

        <StorefrontFooter orgName={orgName} hasWhatsApp={!!waNumber} />
      </main>
    </div>
  )
}
