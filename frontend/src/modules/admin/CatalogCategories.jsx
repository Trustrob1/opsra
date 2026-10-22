/**
 * frontend/src/modules/admin/CatalogCategories.jsx
 * STORE-6: "Categories" screen - add, rename, reorder and delete product categories and
 * choose which products belong to each. One Save button applies everything.
 * Categories become the Storefront menu, the filter buttons and the breadcrumb.
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import { catalogErrorText } from './catalogErrors'
import {
  CATEGORY_MAX, CATEGORY_NAME_MAX, draftFromSnapshot, addDraftCategory, renameDraftCategory,
  removeDraftCategory, moveDraftCategory, entriesFromDraft, assignmentsFromItems, draftAssignments,
  toggleAssignment, assignmentCalls, categoriesChanged,
} from './catalogStorefrontLogic'

const CARD = { background: 'white', borderRadius: 12, border: '1px solid #E2EFF4', padding: 20 }
const INPUT = {
  width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid #D0E8F0', fontFamily: ds.fontDm,
  fontSize: 13.5, color: '#0a1a24', background: 'white', boxSizing: 'border-box', outline: 'none', minHeight: 44,
}
const BTN = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8, padding: '0 20px', minHeight: 44,
  fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
}
const BTN_GHOST = {
  background: 'white', border: '1px solid #D0E8F0', borderRadius: 8, padding: '0 14px', minHeight: 44,
  fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#0a1a24', cursor: 'pointer',
}
const SQUARE = { ...BTN_GHOST, width: 44, padding: 0 }

export default function CatalogCategories({ onSaved }) {
  const [loaded, setLoaded] = useState(false)
  const [snap, setSnap] = useState(null)
  const [items, setItems] = useState([])
  const [saved, setSaved] = useState({})
  const [draft, setDraft] = useState([])
  const [assign, setAssign] = useState({})
  const [showInMenu, setShowInMenu] = useState(true)
  const [selected, setSelected] = useState(null)
  const [newName, setNewName] = useState('')
  const [renameTo, setRenameTo] = useState('')
  const [search, setSearch] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')

  function apply(s, its) {
    const d = draftFromSnapshot(s)
    const sv = assignmentsFromItems(its, d.map((c) => c.name))
    setSnap(s); setItems(its); setSaved(sv); setDraft(d)
    setAssign(draftAssignments(d, sv))
    setShowInMenu(s?.show_in_menu !== false)
    setSelected((cur) => (cur && d.some((c) => c.id === cur) ? cur : d[0]?.id ?? null))
  }

  useEffect(() => {
    Promise.all([adminSvc.getCatalogCategories(), adminSvc.getCatalogItems()])
      .then(([s, its]) => { apply(s, its || []); setLoaded(true) })
      .catch((e) => { setError(catalogErrorText(e, 'Could not load your categories. Please refresh.')); setLoaded(true) })
  }, [])

  const current = draft.find((c) => c.id === selected) || null
  useEffect(() => { setRenameTo(current ? current.name : ''); setConfirmDelete(false) }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps

  const changed = loaded && snap && categoriesChanged(draft, assign, saved, snap, showInMenu)
  const countOf = (id) => (assign[id] || []).length
  const visibleItems = items.filter((i) => !search.trim() || (i.title || '').toLowerCase().includes(search.trim().toLowerCase()))

  function add() {
    const r = addDraftCategory(draft, newName)
    if (r.error) { setError(r.error); return }
    setDraft(r.draft); setAssign((a) => ({ ...a, [r.id]: [] })); setSelected(r.id); setNewName(''); setError('')
  }
  function rename() {
    if (!current) return
    const r = renameDraftCategory(draft, current.id, renameTo)
    if (r.error) { setError(r.error); return }
    setDraft(r.draft); setError('')
  }
  function remove() {
    if (!current) return
    const next = removeDraftCategory(draft, current.id)
    setDraft(next); setSelected(next[0]?.id ?? null); setConfirmDelete(false); setError('')
  }

  async function save() {
    setSaving(true); setError('')
    try {
      const afterSave = await adminSvc.saveCatalogCategories(entriesFromDraft(draft), showInMenu)
      for (const call of assignmentCalls(draft, assign, saved)) {
        await adminSvc.setCatalogCategoryItems(call.name, call.item_ids)
      }
      const fresh = await adminSvc.getCatalogItems()
      apply(afterSave && afterSave.categories ? afterSave : await adminSvc.getCatalogCategories(), fresh || [])
      if (onSaved) onSaved()
      setToast('Categories saved.')
      setTimeout(() => setToast(''), 3000)
    } catch (e) {
      setError(catalogErrorText(e, 'Could not save. Please try again.'))
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) return <div style={{ padding: 32, fontFamily: ds.fontDm, color: '#7A9BAD' }}>Loading…</div>

  return (
    <div style={{ padding: '4px 0 40px' }}>
      <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', margin: '0 0 16px', maxWidth: 640 }}>
        Categories become the menu at the top of your Storefront, the filter buttons on the grid, and the path on each product.
        Removing a category never deletes products.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20, alignItems: 'start' }}>
        <div style={CARD}>
          <div style={{ display: 'flex', gap: 10 }}>
            <input aria-label="New category name" style={INPUT} value={newName} maxLength={CATEGORY_NAME_MAX + 20}
              placeholder="New category, e.g. Beds" onChange={(e) => { setNewName(e.target.value); setError('') }}
              onKeyDown={(e) => { if (e.key === 'Enter') add() }} />
            <button type="button" style={BTN} onClick={add} disabled={draft.length >= CATEGORY_MAX}>Add</button>
          </div>
          <div style={{ marginTop: 4, fontFamily: ds.fontDm, fontSize: 12, color: '#7A9BAD' }}>{draft.length} of {CATEGORY_MAX} categories</div>

          {draft.length === 0 ? (
            <p style={{ fontFamily: ds.fontDm, fontSize: 13.5, color: '#4a7a8a', margin: '18px 0 0' }}>
              No categories yet. Add your first one above, then choose its products.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', margin: '14px 0 0', padding: 0, display: 'grid', gap: 8 }}>
              {draft.map((c, i) => (
                <li key={c.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <button type="button" onClick={() => setSelected(c.id)} aria-pressed={c.id === selected}
                    style={{
                      flex: 1, minHeight: 44, textAlign: 'left', padding: '0 12px', borderRadius: 8, cursor: 'pointer',
                      fontFamily: ds.fontDm, fontSize: 14, fontWeight: 600, color: '#0a1a24',
                      background: c.id === selected ? '#E8F5F7' : 'white',
                      border: c.id === selected ? `2px solid ${ds.teal}` : '1px solid #D0E8F0',
                    }}>
                    {c.name} <span style={{ fontWeight: 400, color: '#7A9BAD' }}>({countOf(c.id)})</span>
                  </button>
                  <button type="button" style={SQUARE} aria-label={`Move ${c.name} up`} disabled={i === 0}
                    onClick={() => setDraft((d) => moveDraftCategory(d, c.id, -1))}>↑</button>
                  <button type="button" style={SQUARE} aria-label={`Move ${c.name} down`} disabled={i === draft.length - 1}
                    onClick={() => setDraft((d) => moveDraftCategory(d, c.id, 1))}>↓</button>
                </li>
              ))}
            </ul>
          )}

          <label style={{ marginTop: 18, display: 'flex', gap: 10, alignItems: 'center', fontFamily: ds.fontDm, fontSize: 13.5, color: '#0a1a24', minHeight: 44, cursor: 'pointer' }}>
            <input type="checkbox" checked={showInMenu} onChange={(e) => setShowInMenu(e.target.checked)} style={{ width: 20, height: 20 }} />
            Show categories in the store menu
          </label>
        </div>

        <div style={CARD}>
          {!current ? (
            <p style={{ fontFamily: ds.fontDm, fontSize: 13.5, color: '#4a7a8a', margin: 0 }}>Pick a category to choose its products.</p>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <input aria-label="Category name" style={{ ...INPUT, flex: '1 1 160px', width: 'auto' }} value={renameTo}
                  onChange={(e) => { setRenameTo(e.target.value); setError('') }}
                  onKeyDown={(e) => { if (e.key === 'Enter') rename() }} />
                <button type="button" style={BTN_GHOST} onClick={rename} disabled={renameTo.trim() === current.name}>Rename</button>
                {confirmDelete ? (
                  <button type="button" style={{ ...BTN_GHOST, color: '#c0392b', borderColor: '#c0392b' }} onClick={remove}>
                    Delete {current.name}? Products stay
                  </button>
                ) : (
                  <button type="button" style={{ ...BTN_GHOST, color: '#c0392b' }} onClick={() => setConfirmDelete(true)}>Delete</button>
                )}
              </div>

              <div style={{ margin: '16px 0 8px', fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600, color: '#4a7a8a' }}>
                Products in {current.name} ({countOf(current.id)})
              </div>
              <input aria-label="Search products" style={INPUT} value={search} placeholder="Search products" onChange={(e) => setSearch(e.target.value)} />
              <div style={{ marginTop: 10, maxHeight: 360, overflowY: 'auto', display: 'grid', gap: 2 }}>
                {items.length === 0 && (
                  <p style={{ fontFamily: ds.fontDm, fontSize: 13.5, color: '#4a7a8a' }}>You have no products yet. Add some in the Items tab.</p>
                )}
                {visibleItems.map((it) => {
                  const id = String(it.id)
                  const on = (assign[current.id] || []).includes(id)
                  return (
                    <label key={id} style={{ display: 'flex', gap: 10, alignItems: 'center', minHeight: 44, padding: '0 6px', cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 13.5, color: '#0a1a24' }}>
                      <input type="checkbox" checked={on} style={{ width: 20, height: 20 }}
                        onChange={() => setAssign((a) => toggleAssignment(a, current.id, id))} />
                      <span style={{ flex: 1 }}>{it.title}</span>
                      {it.catalog_visible === false && <span style={{ fontSize: 11.5, color: '#7A9BAD' }}>Hidden</span>}
                    </label>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </div>

      {error && <p role="alert" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#c0392b', margin: '16px 0 0' }}>{error}</p>}
      <div style={{ marginTop: 18, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" style={{ ...BTN, opacity: saving || !changed ? 0.6 : 1 }} disabled={saving || !changed} onClick={save}>
          {saving ? 'Saving…' : 'Save categories'}
        </button>
        {toast && <span role="status" style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#1B6B49', fontWeight: 600 }}>{toast}</span>}
      </div>
    </div>
  )
}
