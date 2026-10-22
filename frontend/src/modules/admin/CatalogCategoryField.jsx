/**
 * frontend/src/modules/admin/CatalogCategoryField.jsx
 * STORE-6: the "Categories" field in the product drawer. Chosen categories are chips with an x;
 * the rest are outlined chips with a +. A new category can be added on the spot.
 */
import { useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { catalogErrorText } from './catalogErrors'
import { chosenCategories, withCategory, withoutCategory, remainingCategories, CATEGORY_NAME_MAX } from './catalogStorefrontLogic'

const CHIP = { display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 36, padding: '0 12px', borderRadius: 18, fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, cursor: 'pointer' }

export default function CatalogCategoryField({ names, tags, onChange, onManage }) {
  const [known, setKnown] = useState(names || [])
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const chosen = chosenCategories(tags)
  const rest = remainingCategories(known, chosen)

  async function add() {
    const v = newName.trim()
    if (!v) return
    setBusy(true); setError('')
    try {
      const r = await adminSvc.addCatalogCategory(v)
      const list = (r?.categories || []).map((c) => c.name)
      if (list.length) setKnown(list)
      const created = r?.added || v
      onChange(withCategory(chosen, created))
      setNewName('')
    } catch (e) {
      setError(catalogErrorText(e, 'Could not add the category. Please try again.'))
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {chosen.map((n) => (
          <button key={n} type="button" aria-label={`Remove ${n}`} onClick={() => onChange(withoutCategory(chosen, n))}
            style={{ ...CHIP, background: ds.teal, color: 'white', border: `1px solid ${ds.teal}` }}>{n} <span aria-hidden="true">×</span></button>
        ))}
        {rest.map((n) => (
          <button key={n} type="button" aria-label={`Add ${n}`} onClick={() => onChange(withCategory(chosen, n))}
            style={{ ...CHIP, background: 'white', color: '#0a1a24', border: '1px solid #D0E8F0' }}>{n} <span aria-hidden="true">+</span></button>
        ))}
        {chosen.length === 0 && rest.length === 0 && (
          <span style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD' }}>No categories yet. Add the first one below.</span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <input aria-label="Add new category" value={newName} maxLength={CATEGORY_NAME_MAX + 20} placeholder="Add new category"
          onChange={(e) => { setNewName(e.target.value); setError('') }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
          style={{ flex: 1, minHeight: 44, padding: '0 12px', borderRadius: 8, border: '1px solid #D0E8F0', fontFamily: ds.fontDm, fontSize: 13.5, boxSizing: 'border-box' }} />
        <button type="button" onClick={add} disabled={busy || !newName.trim()}
          style={{ minHeight: 44, padding: '0 16px', borderRadius: 8, border: '1px solid #D0E8F0', background: 'white', fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer' }}>
          {busy ? 'Adding…' : 'Add'}
        </button>
      </div>
      {error && <p role="alert" style={{ fontFamily: ds.fontDm, fontSize: 12.5, color: '#c0392b', margin: '6px 0 0' }}>{error}</p>}
      {onManage && (
        <button type="button" onClick={onManage}
          style={{ marginTop: 8, background: 'none', border: 'none', padding: 0, minHeight: 32, color: ds.teal, fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600, cursor: 'pointer' }}>
          Manage categories
        </button>
      )}
    </div>
  )
}
