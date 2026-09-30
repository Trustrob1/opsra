/**
 * frontend/src/modules/sites/DesignSuggestModal.jsx
 * SITE-1C-2b — "Suggest another design": a few fresh, valid looks for this site as picture cards.
 * The parent supplies `fetchSuggestions()` (server call) and `onUse(recipe)`; this component only shows them.
 *
 *   fetchSuggestions() -> { suggestions: [{ recipe, summary, fingerprint }], remaining, cap, counts_as_edit }
 *   onUse(recipe)      -> may throw; the parent shows its own message (e.g. the edit-limit offer)
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Shuffle } from 'lucide-react'
import { Button, Modal, Notice, Spinner } from './sitesUi'
import { T } from './sitesKit'
import { curFromRecipe, ensureLookFonts, TEAL } from './lookKit'
import LookPreview from './LookPreview'
import SectionThumb from './SectionThumb'

const CARD_W = 224, PREVIEW_W = 570, PREVIEW_H = 700
const SCALE = (CARD_W - 2) / PREVIEW_W

const codeOf = (e) => e?.response?.data?.detail?.code

export default function DesignSuggestModal({ open, onClose, fetchSuggestions, onUse, errorText }) {
  const [state, setState] = useState({ loading: false, error: null, limited: false, data: null })
  const [using, setUsing] = useState(null)
  const started = useRef(false)

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fetchSuggestions()
      setState({ loading: false, error: null, limited: false, data })
    } catch (e) {
      const limited = codeOf(e) === 'DESIGN_SUGGEST_LIMIT'
      setState((s) => ({ ...s, loading: false, limited, error: limited ? (e.response.data.detail.message) : (errorText ? errorText(e) : 'Could not get design suggestions.') }))
    }
  }, [fetchSuggestions, errorText])

  useEffect(() => { ensureLookFonts() }, [])
  useEffect(() => {
    if (open && !started.current) { started.current = true; load() }
    if (!open) { started.current = false; setState({ loading: false, error: null, limited: false, data: null }) }
  }, [open, load])

  const use = async (recipe, key) => {
    setUsing(key)
    try { await onUse(recipe) } finally { setUsing(null) }
  }

  const { data, loading, error, limited } = state
  const suggestions = data?.suggestions || []
  const outOfRounds = limited || data?.remaining === 0

  return (
    <Modal open={open} onClose={onClose} title="Suggest another design" width={1040}
      footer={<>
        <Button onClick={onClose}>Close</Button>
        <Button variant="secondary" icon={Shuffle} loading={loading} disabled={outOfRounds} onClick={load}>Show me different ones</Button>
      </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ fontSize: 12.5, color: T.soft, lineHeight: 1.5 }}>
          Fresh looks for this site. They keep your sections and your business details, and change the theme, colours, fonts, style and layouts.
          {data?.counts_as_edit && <strong> Using one counts as 1 edit.</strong>}
          {data && data.remaining != null && !outOfRounds && <> You have {data.remaining} free suggestion{data.remaining === 1 ? '' : 's'} left for this preview.</>}
        </div>
        {error && <Notice tone={limited ? 'info' : 'bad'}>{error}</Notice>}
        {loading && !suggestions.length && <div style={{ padding: 30, textAlign: 'center' }}><Spinner /></div>}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, opacity: loading ? 0.5 : 1 }}>
          {suggestions.map((s, i) => {
            const key = s.fingerprint || i
            const v = s.recipe.variants || {}
            return (
              <div key={key} style={{ width: CARD_W, border: '2px solid #d5dbe3', borderRadius: 12, background: '#fff', display: 'flex', flexDirection: 'column' }}>
                <div aria-hidden="true" style={{ height: 260, overflow: 'hidden', pointerEvents: 'none', background: '#f3f5f8', borderRadius: '10px 10px 0 0' }}>
                  <div style={{ width: PREVIEW_W, height: PREVIEW_H, transform: `scale(${SCALE})`, transformOrigin: 'top left' }}><LookPreview cur={curFromRecipe(s.recipe)} /></div>
                </div>
                <div style={{ padding: '10px 12px 12px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
                  <div style={{ display: 'flex', gap: 5 }}>
                    {['hero', 'items', 'about'].filter((k) => v[k]).map((k) => <SectionThumb key={k} section={k} variant={v[k]} width={60} />)}
                  </div>
                  <div style={{ fontSize: 11.5, color: T.soft, lineHeight: 1.4, flex: 1 }}>{s.summary}</div>
                  <Button size="sm" variant="primary" loading={using === key} disabled={!!using} onClick={() => use(s.recipe, key)} style={{ borderColor: TEAL }}>Use this design</Button>
                </div>
              </div>
            )
          })}
        </div>
        {!loading && !error && data && !suggestions.length && <Notice tone="info">No new looks to suggest right now. You can still change the design yourself.</Notice>}
      </div>
    </Modal>
  )
}
