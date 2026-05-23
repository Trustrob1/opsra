/**
 * frontend/src/modules/admin/CatalogItems.jsx
 * CATALOG-2B: Catalog items table with search, filters, and drawer.
 * Pattern 33: client-side search — no ILIKE.
 * Pattern 51: full rewrite only — never sed.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import CatalogItemDrawer from './CatalogItemDrawer'

const BTN_PRIMARY = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8,
  padding: '9px 18px', fontFamily: ds.fontDm, fontSize: 13.5,
  fontWeight: 600, cursor: 'pointer',
}

const BTN_GHOST = {
  background: 'none', border: '1px solid #D0E8F0', borderRadius: 8,
  padding: '7px 14px', fontFamily: ds.fontDm, fontSize: 13,
  color: '#4a7a8a', cursor: 'pointer',
}

const BADGE = ({ children, color = '#E2EFF4', textColor = '#4a7a8a' }) => (
  <span style={{
    background: color, color: textColor, borderRadius: 12,
    padding: '2px 9px', fontFamily: ds.fontDm, fontSize: 11.5, fontWeight: 600,
    whiteSpace: 'nowrap',
  }}>
    {children}
  </span>
)

function TagSummary({ tags, config }) {
  if (!tags || !config?.tag_dimensions) return <span style={{ color: '#7A9BAD', fontSize: 12 }}>—</span>
  const parts = []
  for (const dim of config.tag_dimensions) {
    const val = tags[dim.key]
    if (!val || (Array.isArray(val) && val.length === 0)) continue
    const label = Array.isArray(val) ? val.join(', ') : val
    parts.push(label)
  }
  if (parts.length === 0) return <span style={{ color: '#7A9BAD', fontSize: 12 }}>—</span>
  const preview = parts.join(' · ')
  return (
    <span style={{ fontFamily: ds.fontDm, fontSize: 12, color: '#4a7a8a' }} title={preview}>
      {preview.length > 40 ? preview.slice(0, 40) + '…' : preview}
    </span>
  )
}

export default function CatalogItems() {
  const [items, setItems]           = useState([])
  const [config, setConfig]         = useState(null)
  const [loading, setLoading]       = useState(true)
  const [search, setSearch]         = useState('')
  const [showHidden, setShowHidden] = useState(false)
  const [showOOS, setShowOOS]       = useState(false)
  const [drawerItem, setDrawerItem] = useState(null)
  const [creating, setCreating]     = useState(false)
  const [error, setError]           = useState('')

  async function loadAll() {
    setLoading(true)
    setError('')
    try {
      const [itemsData, configData] = await Promise.all([
        adminSvc.getCatalogItems(),
        adminSvc.getCatalogConfig(),
      ])
      setItems(itemsData || [])
      setConfig(configData || {})
    } catch {
      setError('Failed to load catalog items.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadAll() }, [])

  // Client-side filtering (Pattern 33)
  const filtered = items.filter(item => {
    if (!showHidden && !item.catalog_visible) return false
    if (!showOOS && !item.available) return false
    if (search && !item.title?.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const isShopify = (config?.external_sync || 'none') === 'shopify'

  function formatPrice(price) {
    if (price == null) return '—'
    const template = config?.price_label_template || '₦{price}'
    return template.replace('{price}', Number(price).toLocaleString())
  }

  function handleSaved(updated) {
    setItems(prev => prev.map(i => i.id === updated?.id ? { ...i, ...updated } : i))
    setDrawerItem(d => d ? { ...d, ...updated } : d)
  }

  async function handleCreateItem() {
    const title = window.prompt('New item title:')
    if (!title?.trim()) return
    setCreating(true)
    try {
      const newItem = await adminSvc.createCatalogItem({ title: title.trim() })
      setItems(prev => [newItem, ...prev])
      setDrawerItem(newItem)
    } catch { setError('Failed to create item.') }
    finally { setCreating(false) }
  }

  if (loading) return (
    <div style={{ padding: 40, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>Loading catalog items…</div>
  )

  return (
    <div>
      {error && (
        <div style={{ background: '#fff2f2', border: '1px solid #e05c5c', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontFamily: ds.fontDm, fontSize: 13.5, color: '#c0392b' }}>
          ⚠️ {error}
        </div>
      )}

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
        <input
          style={{ padding: '9px 14px', borderRadius: 8, border: '1px solid #D0E8F0', fontFamily: ds.fontDm, fontSize: 13.5, color: '#0a1a24', outline: 'none', flex: 1, minWidth: 220 }}
          placeholder={`Search ${config?.catalog_item_label_plural || 'items'}…`}
          value={search} onChange={e => setSearch(e.target.value)}
        />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={showHidden} onChange={e => setShowHidden(e.target.checked)} />
          Show hidden
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={showOOS} onChange={e => setShowOOS(e.target.checked)} />
          Show out of stock
        </label>
        {!isShopify && (
          <button style={{ ...BTN_PRIMARY, opacity: creating ? 0.6 : 1 }} disabled={creating} onClick={handleCreateItem}>
            {creating ? 'Creating…' : `+ Add ${config?.catalog_item_label || 'Item'}`}
          </button>
        )}
        <button style={BTN_GHOST} onClick={loadAll}>↻ Refresh</button>
      </div>

      {/* Count */}
      <p style={{ fontFamily: ds.fontDm, fontSize: 12.5, color: '#7A9BAD', margin: '0 0 14px' }}>
        Showing {filtered.length} of {items.length} {config?.catalog_item_label_plural || 'items'}
        {isShopify && ' · Synced from Shopify'}
      </p>

      {/* Table */}
      {filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 0', color: '#7A9BAD', fontFamily: ds.fontDm, fontSize: 13.5 }}>
          {items.length === 0 ? 'No catalog items yet.' : 'No items match your filters.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #E2EFF4' }}>
                {['Cover', 'Title', 'Tags', 'Price', 'Status', 'Views', 'Actions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '10px 12px', fontFamily: ds.fontDm, fontSize: 12, fontWeight: 700, color: '#4a7a8a', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(item => {
                const coverUrl = (item.catalog_images || [])[0]
                return (
                  <tr key={item.id} style={{ borderBottom: '1px solid #E2EFF4', opacity: item.catalog_visible ? 1 : 0.55 }}>
                    {/* Cover */}
                    <td style={{ padding: '10px 12px', width: 56 }}>
                      {coverUrl ? (
                        <img src={coverUrl} alt="" style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 6, border: '1px solid #E2EFF4' }} />
                      ) : (
                        <div style={{ width: 44, height: 44, borderRadius: 6, background: '#f5fbfd', border: '1px solid #E2EFF4', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>📦</div>
                      )}
                    </td>
                    {/* Title */}
                    <td style={{ padding: '10px 12px', maxWidth: 220 }}>
                      <div style={{ fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, color: '#0a1a24', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.title}
                      </div>
                      {item.slug && (
                        <div style={{ fontFamily: ds.fontDm, fontSize: 11.5, color: '#7A9BAD', marginTop: 2 }}>/{item.slug}</div>
                      )}
                    </td>
                    {/* Tags */}
                    <td style={{ padding: '10px 12px' }}>
                      <TagSummary tags={item.tags} config={config} />
                    </td>
                    {/* Price */}
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap', fontFamily: ds.fontDm, fontSize: 13, color: '#0a1a24' }}>
                      {config?.price_on_request ? 'On Request' : formatPrice(item.price)}
                    </td>
                    {/* Status */}
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <BADGE color={item.available ? '#eafaf2' : '#fff2f2'} textColor={item.available ? '#1a6640' : '#c0392b'}>
                          {item.available
                            ? (config?.availability_labels?.available || 'In Stock')
                            : (config?.availability_labels?.unavailable || 'Out of Stock')}
                        </BADGE>
                        {!item.catalog_visible && (
                          <BADGE color="#fff8e6" textColor="#8a6a00">Hidden</BADGE>
                        )}
                      </div>
                    </td>
                    {/* Views */}
                    <td style={{ padding: '10px 12px', fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', textAlign: 'center' }}>
                      {item.catalog_views ?? 0}
                    </td>
                    {/* Actions */}
                    <td style={{ padding: '10px 12px' }}>
                      <button style={BTN_GHOST} onClick={() => setDrawerItem(item)}>Edit</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Drawer */}
      <CatalogItemDrawer
        item={drawerItem}
        config={config}
        isOpen={!!drawerItem}
        onClose={() => setDrawerItem(null)}
        onSaved={handleSaved}
      />
    </div>
  )
}
