/**
 * frontend/src/modules/sites/DesignStyleFields.jsx
 * SITE-1C-1 — the font-pairing and design-token pickers (corners, spacing, buttons, headings,
 * photos, section divider), shared by the staff site editor and the builder editor.
 *
 * Every field defaults to "Theme default" (null), which leaves the site exactly as it was.
 * When a preset is given, its allowed_fonts / token_options narrow the choices; the server
 * enforces the same rules on save (site_renderer.validate_recipe).
 */
import { useEffect } from 'react'
import { Field } from './sitesUi'
import { INPUT, FONT_PAIRINGS, FONT_GROUP_LABELS, TOKENS, THEME_TOKEN_EXCLUSIONS } from './sitesKit'

const DEFAULT_LABEL = 'Theme default'

function tokenOptionsFor(token, theme, preset) {
  const excluded = THEME_TOKEN_EXCLUSIONS[theme]?.[token.key] || []
  const narrowed = preset?.token_options?.[token.key] || []
  return token.options.filter((o) => !excluded.includes(o.value) && (!narrowed.length || narrowed.includes(o.value)))
}

function fontOptionsFor(preset, current) {
  const allowed = preset?.allowed_fonts || []
  return FONT_PAIRINGS.filter((f) => !allowed.length || allowed.includes(f.value) || f.value === current)
}

export default function DesignStyleFields({ recipe, setRecipe, canEdit = true, preset = null }) {
  const tokens = recipe.tokens || {}

  // A token the chosen theme does not support is cleared, so a save is never rejected for it.
  useEffect(() => {
    const excluded = THEME_TOKEN_EXCLUSIONS[recipe.theme] || {}
    const bad = Object.keys(excluded).filter((k) => excluded[k].includes(recipe.tokens?.[k]))
    if (bad.length) {
      setRecipe((r) => ({ ...r, tokens: { ...(r.tokens || {}), ...Object.fromEntries(bad.map((k) => [k, null])) } }))
    }
  }, [recipe.theme, recipe.tokens, setRecipe])

  const fonts = fontOptionsFor(preset, recipe.fonts)
  const setToken = (key, value) => setRecipe((r) => ({ ...r, tokens: { ...(r.tokens || {}), [key]: value || null } }))

  return (
    <>
      <Field label="Fonts" hint="The headings and body text. Theme default keeps the theme's own pair.">
        <select style={INPUT} disabled={!canEdit} value={recipe.fonts || ''}
          onChange={(e) => setRecipe((r) => ({ ...r, fonts: e.target.value || null }))}>
          <option value="">{DEFAULT_LABEL}</option>
          {Object.keys(FONT_GROUP_LABELS).map((g) => {
            const list = fonts.filter((f) => f.group === g)
            return list.length ? (
              <optgroup key={g} label={FONT_GROUP_LABELS[g]}>
                {list.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </optgroup>
            ) : null
          })}
        </select>
      </Field>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
        {TOKENS.map((t) => (
          <Field key={t.key} label={t.label}>
            <select style={INPUT} disabled={!canEdit} value={tokens[t.key] || ''} onChange={(e) => setToken(t.key, e.target.value)}>
              <option value="">{DEFAULT_LABEL}</option>
              {tokenOptionsFor(t, recipe.theme, preset).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
        ))}
      </div>
    </>
  )
}
