/**
 * frontend/src/modules/sites/PremiumLookCard.jsx
 * SITE-PREMIUM P4-2 - the customer's colour and font choice for a Premium site (builder portal).
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
  const [accent, setAccent] = useState(null)
  const [custom, setCustom] = useState('')
  const [headline, setHeadline] = useState(null)
  const [body, setBody] = useState(null)

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
  useEffect(() => { setAccent(null); setCustom(''); setHeadline(null); setBody(null) }, [current.accent, current.headline_font, current.body_font])

  if (!look) return null

  const selection = (over = {}) => {
    const a = 'accent' in over ? over.accent : accent
    const h = 'headline' in over ? over.headline : headline
    const b = 'body' in over ? over.body : body
    const sel = {}
    if (a && a.toUpperCase() !== (current.accent || '').toUpperCase()) sel.accent = a
    if (h && h !== current.headline_font) sel.headline_font = h
    if (b && b !== current.body_font) sel.body_font = b
    return sel
  }
  const pick = (over) => {
    if ('accent' in over) setAccent(over.accent)
    if ('headline' in over) setHeadline(over.headline)
    if ('body' in over) setBody(over.body)
    onPreview(selection(over))
  }
  const sel = selection()
  const changed = Object.keys(sel).length > 0
  const cancel = () => { setAccent(null); setCustom(''); setHeadline(null); setBody(null); onCancel() }
  const fo = look.fonts || {}

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
              <button key={s.key} type="button" aria-pressed={selected} disabled={!s.ok || busy}
                title={s.ok ? s.name : s.reason} onClick={() => pick({ accent: s.hex })} style={choiceStyle(selected, !s.ok)}>
                <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: '50%', background: s.hex, border: '1px solid rgba(0,0,0,.15)' }} />
                <span>{s.name}{isCurrent ? ' (current)' : ''}</span>
              </button>
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
