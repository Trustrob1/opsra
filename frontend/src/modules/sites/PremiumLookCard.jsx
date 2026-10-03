/**
 * frontend/src/modules/sites/PremiumLookCard.jsx
 * SITE-PREMIUM P4-2/P4-3a/P4-3b - the customer's colour, font, per-section colour, show/hide and headline size choice for a Premium site (builder portal).
 * Buttons and pickers only. Choosing something previews it at once (nothing is saved); "Apply this look" saves it.
 * The server decides which colours and fonts are allowed for this design, so everything offered here works.
 */
import { useEffect, useState } from 'react'
import { Check, Undo2 } from 'lucide-react'
import { T, INPUT } from './sitesKit'
import { Card, Button, Notice, SectionTitle, Field } from './sitesUi'

const HEX = /^#[0-9a-fA-F]{6}$/

function choiceStyle(selected, disabled) {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 10, minHeight: 44,
    border: `${selected ? 2 : 1}px solid ${selected ? T.teal : T.lineStrong}`, background: '#fff',
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1, fontFamily: 'inherit', fontSize: 14, color: T.ink,
  }
}

export default function PremiumLookCard({ data, busy, previewing, error, onPreview, onApply, onCancel, onGoBack }) {
  const look = data?.look
  const current = look?.current || {}
  const savedSections = JSON.stringify((look?.sections || []).map((r) => [r.name, r.current, r.visible, r.size]))
  const [accent, setAccent] = useState(null)
  const [custom, setCustom] = useState('')
  const [headline, setHeadline] = useState(null)
  const [body, setBody] = useState(null)
  const [secPick, setSecPick] = useState({})            // P4-3a: {section name: colour key} not saved yet
  const [layPick, setLayPick] = useState({})            // P4-3b: {section name: {show?, size?}} not saved yet

  // Show the options in their own fonts: one Google Fonts stylesheet for the fonts on offer.
  useEffect(() => {
    const url = look?.sample_css_url
    if (!url) return undefined
    const el = document.createElement('link')
    el.rel = 'stylesheet'
    el.href = url
    document.head.appendChild(el)
    return () => { try { document.head.removeChild(el) } catch (e) { /* already gone */ } }
  }, [look?.sample_css_url])

  // The server knows a new look was saved (or undone) when `current` changes: clear the pending choice.
  useEffect(() => { setAccent(null); setCustom(''); setHeadline(null); setBody(null); setSecPick({}); setLayPick({}) }, [current.accent, current.headline_font, current.body_font, savedSections])

  if (!look) return null
  const sectionRows = look.sections || []

  const selection = (over = {}) => {
    const a = 'accent' in over ? over.accent : accent
    const h = 'headline' in over ? over.headline : headline
    const b = 'body' in over ? over.body : body
    const sp = 'sections' in over ? over.sections : secPick
    const lp = 'layout' in over ? over.layout : layPick
    const sel = {}
    if (a && a.toUpperCase() !== (current.accent || '').toUpperCase()) sel.accent = a
    if (h && h !== current.headline_font) sel.headline_font = h
    if (b && b !== current.body_font) sel.body_font = b
    const sd = {}
    sectionRows.forEach((row) => { if (sp[row.name] && sp[row.name] !== row.current) sd[row.name] = sp[row.name] })
    if (Object.keys(sd).length) sel.sections = sd
    const ld = {}
    sectionRows.forEach((row) => {
      const l = lp[row.name] || {}
      const d = {}
      if (l.show !== undefined && l.show !== row.visible) d.show = l.show
      if (l.size && l.size !== row.size) d.size = l.size
      if (Object.keys(d).length) ld[row.name] = d
    })
    if (Object.keys(ld).length) sel.section_layout = ld
    return sel
  }
  const pick = (over) => {
    if ('accent' in over) setAccent(over.accent)
    if ('headline' in over) setHeadline(over.headline)
    if ('body' in over) setBody(over.body)
    if ('sections' in over) setSecPick(over.sections)
    if ('layout' in over) setLayPick(over.layout)
    onPreview(selection(over))
  }
  const sel = selection()
  const changed = Object.keys(sel).length > 0
  const cancel = () => { setAccent(null); setCustom(''); setHeadline(null); setBody(null); setSecPick({}); setLayPick({}); onCancel() }
  const fo = look.fonts || {}
  const setLay = (name, change) => pick({ layout: { ...layPick, [name]: { ...(layPick[name] || {}), ...change } } })

  return (
    <Card>
      <SectionTitle title="Your look" />
      <p style={{ margin: '0 0 12px', fontSize: 13, color: T.muted }}>
        Choose a colour or a font. The preview changes straight away, and nothing is saved until you press Apply.
      </p>

      <Field label="Brand colour" hint="Used for buttons, links and highlights.">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {look.swatches.map((s) => {
            const isCurrent = (current.accent || '').toUpperCase() === s.hex.toUpperCase()
            const selected = (accent || '').toUpperCase() === s.hex.toUpperCase()
            return (
              <div key={s.key} style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 190 }}>
                <button type="button" aria-pressed={selected} disabled={!s.ok || busy}
                  title={s.ok ? s.name : s.reason} onClick={() => pick({ accent: s.hex })} style={choiceStyle(selected, !s.ok)}>
                  <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: '50%', background: s.hex, border: '1px solid rgba(0,0,0,.15)' }} />
                  <span>{s.name}{isCurrent ? ' (current)' : ''}</span>
                </button>
                {!s.ok && s.reason && <span style={{ fontSize: 11, lineHeight: 1.3, color: T.muted }}>{s.reason}</span>}
              </div>
            )
          })}
        </div>
      </Field>

      <Field label="Or use your own colour" hint="Type a colour like #1F4FD8. We check that it stays easy to read.">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input style={{ ...INPUT, maxWidth: 140 }} value={custom} maxLength={7} placeholder="#1F4FD8" aria-label="Your own colour"
            onChange={(e) => setCustom(e.target.value)} />
          <Button disabled={!HEX.test(custom) || busy} onClick={() => pick({ accent: custom.toUpperCase() })}>Preview colour</Button>
        </div>
      </Field>

      {(fo.headlines || []).length > 1 && (
        <Field label="Heading font" hint="Other fonts in the same style as your design.">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {fo.headlines.map((name) => {
              const isCurrent = name === current.headline_font
              const selected = name === (headline || current.headline_font)
              return (
                <button key={name} type="button" aria-pressed={selected} disabled={busy}
                  onClick={() => pick({ headline: name })} style={{ ...choiceStyle(selected, false), fontFamily: `'${name}', sans-serif`, fontSize: 18 }}>
                  {name}{isCurrent ? ' (current)' : ''}
                </button>
              )
            })}
          </div>
        </Field>
      )}

      {(fo.bodies || []).length > 1 && (
        <Field label="Body font" hint="For paragraphs and prices.">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {fo.bodies.map((name) => {
              const isCurrent = name === current.body_font
              const selected = name === (body || current.body_font)
              return (
                <button key={name} type="button" aria-pressed={selected} disabled={busy}
                  onClick={() => pick({ body: name })} style={{ ...choiceStyle(selected, false), fontFamily: `'${name}', sans-serif` }}>
                  {name}{isCurrent ? ' (current)' : ''}
                </button>
              )
            })}
          </div>
        </Field>
      )}

      {sectionRows.length > 0 && (
        <Field label="Sections" hint="Give a section its own colour, hide it, or make its heading bigger or smaller. Only colours from your design are offered, so the text always stays easy to read. A hidden section can be shown again at any time.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {sectionRows.map((row) => {
              const chosen = secPick[row.name] || row.current
              const lay = layPick[row.name] || {}
              const visible = lay.show !== undefined ? lay.show : row.visible
              const size = lay.size || row.size
              return (
                <div key={row.name} style={{ opacity: visible ? 1 : 0.6 }}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 6 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: T.ink, marginRight: 4 }}>{row.label}{visible ? '' : ' (hidden)'}</div>
                    {row.can_hide && (
                      <button type="button" aria-pressed={!visible} disabled={busy}
                        onClick={() => setLay(row.name, { show: !visible })} style={choiceStyle(!visible, false)}>
                        {visible ? 'Hide this section' : 'Show this section'}
                      </button>
                    )}
                    {row.can_resize && visible && [['small', 'Smaller heading'], ['normal', 'Normal heading'], ['large', 'Larger heading']].map(([key, label]) => (
                      <button key={key} type="button" aria-pressed={size === key} disabled={busy}
                        onClick={() => setLay(row.name, { size: key })} style={choiceStyle(size === key, false)}>
                        {label}
                      </button>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {row.options.map((o) => {
                      const selected = chosen === o.key
                      return (
                        <button key={o.key} type="button" aria-pressed={selected} disabled={busy}
                          onClick={() => pick({ sections: { ...secPick, [row.name]: o.key } })} style={choiceStyle(selected, false)}>
                          {o.hex && <span aria-hidden="true" style={{ width: 20, height: 20, borderRadius: 4, background: o.hex, border: '1px solid rgba(0,0,0,.2)' }} />}
                          <span>{o.label}{o.key === row.current ? ' (current)' : ''}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </Field>
      )}

      {error && <Notice tone="bad">{error}</Notice>}
      {changed && !error && (
        <Notice tone="info">
          {previewing ? 'Updating the preview...' : 'You are previewing a new look. It is not saved yet.'}
          {data.counts_as_edit ? ' Applying it uses 1 of your edits.' : ''}
        </Notice>
      )}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
        <Button variant="primary" icon={Check} loading={busy && !previewing} disabled={!changed || !!error || busy} onClick={() => onApply(sel)}>Apply this look</Button>
        {changed && <Button disabled={busy} onClick={cancel}>Cancel</Button>}
        {data.can_go_back && !changed && <Button icon={Undo2} disabled={busy} onClick={onGoBack}>Go back to my previous look</Button>}
      </div>
    </Card>
  )
}
