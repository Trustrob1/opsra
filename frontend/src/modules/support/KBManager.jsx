/**
 * frontend/src/modules/support/KBManager.jsx
 * Knowledge base article list, create, edit, and unpublish (soft-delete).
 * Unpublish restricted to owner / ops_manager roles per DRD §4.2.
 *
 * WH-1: Added action_type toggle + action_label field to ArticleForm.
 *   action_type  — 'informational' (default) | 'action_required'
 *   action_label — free text, only shown when action_required is selected
 *                  e.g. "Process refund in billing system"
 * Also added AI Behaviour column to article table.
 */

import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import {
  listKBArticles, createKBArticle, updateKBArticle, unpublishKBArticle,
} from '../../services/support.service'
import { getTicketCategories } from '../../services/admin.service'

const DEFAULT_CATEGORIES = [
  { key: 'product_overview', label: 'Product Overview', enabled: true },
  { key: 'pricing',          label: 'Pricing',          enabled: true },
  { key: 'faq',              label: 'FAQ',               enabled: true },
  { key: 'troubleshooting',  label: 'Troubleshooting',  enabled: true },
  { key: 'hardware',         label: 'Hardware',         enabled: true },
  { key: 'contact',          label: 'Contact',          enabled: true },
]

// ---------------------------------------------------------------------------
// Article form modal — create and edit share this
// ---------------------------------------------------------------------------
function ArticleForm({ initial, onSave, onClose, saving, error, categories }) {
  const isEdit = !!initial
  const [form, setForm] = useState(
    isEdit
      ? {
          ...initial,
          tags:         (initial.tags || []).join(', '),
          action_type:  initial.action_type  || 'informational',
          action_label: initial.action_label || '',
        }
      : {
          category:     'faq',
          title:        '',
          content:      '',
          tags:         '',
          is_published: true,
          action_type:  'informational',
          action_label: '',
        }
  )
  function set(f, v) { setForm(p => ({ ...p, [f]: v })) }

  function handleSave() {
    const payload = {
      category:     form.category,
      title:        form.title.trim(),
      content:      form.content.trim(),
      tags:         form.tags ? form.tags.split(',').map(t => t.trim()).filter(Boolean) : [],
      is_published: form.is_published,
      action_type:  form.action_type,
      action_label: form.action_type === 'action_required' ? form.action_label.trim() : '',
    }
    onSave(payload)
  }

  const lb = {
    fontSize: '11px', fontWeight: 600, color: ds.gray,
    textTransform: 'uppercase', letterSpacing: '0.6px',
    marginBottom: '5px', display: 'block',
  }
  const inp = {
    width: '100%', border: `1.5px solid ${ds.border}`, borderRadius: '9px',
    padding: '10px 13px', fontSize: '13px', color: ds.dark,
    fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box', background: 'white',
  }
  const overlay = {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000, padding: '16px',
  }
  const modal = {
    background: 'white', borderRadius: '16px', width: '100%', maxWidth: '620px',
    maxHeight: '90vh', display: 'flex', flexDirection: 'column',
    boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
  }

  const isActionRequired = form.action_type === 'action_required'
  const saveDisabled = saving || !form.title.trim() || !form.content.trim() || (isActionRequired && !form.action_label.trim())

  return (
    <div style={overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={modal}>
        {/* Header */}
        <div style={{ padding: '22px 26px 18px', borderBottom: `1px solid ${ds.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '17px', color: ds.dark }}>
            {isEdit ? 'Edit Article' : 'New KB Article'}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer', color: ds.gray, lineHeight: 1 }}>x</button>
        </div>

        {/* Body */}
        <div style={{ padding: '22px 26px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {error && (
            <div style={{ background: '#FFF0F0', border: '1px solid #FFD0D0', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#C0392B' }}>
              {error}
            </div>
          )}

          {/* Category + Published */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            <div>
              <label style={lb}>Category</label>
              <select style={inp} value={form.category} onChange={e => set('category', e.target.value)}>
                {(categories || DEFAULT_CATEGORIES).filter(c => c.enabled !== false).map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: '2px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: ds.dark, fontWeight: 500 }}>
                <input type="checkbox" checked={form.is_published} onChange={e => set('is_published', e.target.checked)} />
                Published
              </label>
            </div>
          </div>

          {/* Title */}
          <div>
            <label style={lb}>Title <span style={{ color: '#C0392B' }}>*</span></label>
            <input style={inp} placeholder="Article title..." value={form.title} onChange={e => set('title', e.target.value)} />
          </div>

          {/* Content */}
          <div>
            <label style={lb}>Content <span style={{ color: '#C0392B' }}>*</span></label>
            <textarea
              style={{ ...inp, minHeight: '200px', resize: 'vertical' }}
              placeholder="Write the full article content..."
              value={form.content}
              onChange={e => set('content', e.target.value)}
            />
          </div>

          {/* Tags */}
          <div>
            <label style={lb}>Tags (comma-separated)</label>
            <input style={inp} placeholder="e.g. password, login, reset" value={form.tags} onChange={e => set('tags', e.target.value)} />
          </div>

          {/* WH-1: AI Response Behaviour */}
          <div style={{ border: `1.5px solid ${isActionRequired ? ds.teal : ds.border}`, borderRadius: '10px', padding: '14px 16px', background: isActionRequired ? ds.mint : '#FAFAFA', transition: 'border-color 0.15s, background 0.15s' }}>
            <label style={{ ...lb, marginBottom: '10px' }}>AI Response Behaviour</label>

            <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', cursor: 'pointer', marginBottom: '10px' }}>
              <input
                type="radio"
                name="action_type"
                value="informational"
                checked={form.action_type === 'informational'}
                onChange={() => set('action_type', 'informational')}
                style={{ marginTop: '2px', accentColor: ds.teal }}
              />
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: ds.dark }}>Informational</div>
                <div style={{ fontSize: '12px', color: ds.gray, marginTop: '2px' }}>
                  AI sends the answer directly to the customer. No rep action needed.
                </div>
              </div>
            </label>

            <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', cursor: 'pointer' }}>
              <input
                type="radio"
                name="action_type"
                value="action_required"
                checked={form.action_type === 'action_required'}
                onChange={() => set('action_type', 'action_required')}
                style={{ marginTop: '2px', accentColor: ds.teal }}
              />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '13px', fontWeight: 600, color: ds.dark }}>Action Required</div>
                <div style={{ fontSize: '12px', color: ds.gray, marginTop: '2px' }}>
                  AI sends the answer to the customer, then creates a task for the rep to take a follow-up action.
                </div>

                {isActionRequired && (
                  <div style={{ marginTop: '10px' }}>
                    <label style={{ fontSize: '12px', fontWeight: 600, color: ds.gray, display: 'block', marginBottom: '5px' }}>
                      What action should the rep take? <span style={{ color: '#C0392B' }}>*</span>
                    </label>
                    <input
                      style={{ ...inp, fontSize: '12.5px' }}
                      placeholder="e.g. Process refund in billing system"
                      value={form.action_label}
                      onChange={e => set('action_label', e.target.value)}
                      maxLength={255}
                    />
                    <div style={{ fontSize: '11px', color: ds.gray, marginTop: '4px' }}>
                      This appears as the task title for the rep. Be specific.
                    </div>
                  </div>
                )}
              </div>
            </label>
          </div>

          {isEdit && (
            <div style={{ fontSize: '12px', color: ds.gray, background: ds.mint, padding: '8px 12px', borderRadius: '8px' }}>
              Editing title or content will auto-increment the article version.
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 26px', borderTop: `1px solid ${ds.border}`, display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{ padding: '9px 18px', borderRadius: '8px', border: `1px solid ${ds.border}`, background: 'white', fontSize: '13px', fontWeight: 600, cursor: 'pointer', color: ds.gray }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saveDisabled}
            style={{ padding: '9px 20px', borderRadius: '8px', border: 'none', background: ds.teal, color: 'white', fontSize: '13px', fontWeight: 600, cursor: saveDisabled ? 'not-allowed' : 'pointer', opacity: saveDisabled ? 0.65 : 1 }}
          >
            {saving ? 'Saving...' : 'Save Article'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function KBManager({ user, externalTick = 0 }) {
  const [articles, setArticles]   = useState([])
  const [total, setTotal]         = useState(0)
  const [loading, setLoading]     = useState(false)
  const [listError, setListError] = useState(null)
  const [catFilter, setCatFilter] = useState('')
  const [editing, setEditing]     = useState(null)
  const [saving, setSaving]       = useState(false)
  const [formError, setFormError] = useState(null)
  const [actionErr, setActionErr] = useState(null)
  const [tick, setTick]           = useState(0)
  const refresh = useCallback(() => setTick(t => t + 1), [])

  // CONFIG-1: org-configured categories
  const [categories, setCategories] = useState(DEFAULT_CATEGORIES)
  useEffect(() => {
    getTicketCategories()
      .then(data => {
        const cats = data?.categories
        if (Array.isArray(cats) && cats.length > 0) setCategories(cats)
      })
      .catch(() => {})
  }, [])

  const isAdmin = ['owner', 'ops_manager'].includes(user?.roles?.template)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setListError(null)
    listKBArticles({ category: catFilter || undefined, page_size: 50 })
      .then(data => {
        if (cancelled) return
        setArticles(data?.items || [])
        setTotal(data?.total || 0)
      })
      .catch(e => { if (!cancelled) setListError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [catFilter, tick, externalTick])

  async function handleSave(payload) {
    setSaving(true)
    setFormError(null)
    try {
      if (editing === 'new') {
        await createKBArticle(payload)
      } else {
        await updateKBArticle(editing.id, payload)
      }
      setEditing(null)
      refresh()
    } catch (e) {
      setFormError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleUnpublish(articleId) {
    if (!window.confirm('Unpublish this article? It will no longer be visible.')) return
    setActionErr(null)
    try {
      await unpublishKBArticle(articleId)
      refresh()
    } catch (e) {
      setActionErr(e.message)
    }
  }

  const sel = {
    border: `1.5px solid ${ds.border}`, borderRadius: '8px', padding: '8px 12px',
    fontSize: '12.5px', color: ds.dark, background: 'white', cursor: 'pointer', outline: 'none',
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '18px', flexWrap: 'wrap' }}>
        <select style={sel} value={catFilter} onChange={e => setCatFilter(e.target.value)}>
          <option value="">All Categories</option>
          {categories.filter(c => c.enabled !== false).map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <span style={{ fontSize: '12px', color: ds.gray }}>{total} article{total !== 1 ? 's' : ''}</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => { setFormError(null); setEditing('new') }}
          style={{ padding: '9px 18px', borderRadius: '8px', border: 'none', background: ds.teal, color: 'white', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
        >
          + New Article
        </button>
      </div>

      {actionErr && (
        <div style={{ background: '#FFF0F0', border: '1px solid #FFD0D0', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#C0392B', marginBottom: '14px' }}>
          {actionErr}
        </div>
      )}
      {listError && <div style={{ color: '#C0392B', marginBottom: '12px', fontSize: '13px' }}>{listError}</div>}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px', color: ds.gray, fontSize: '13px' }}>Loading articles...</div>
      ) : articles.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px', color: ds.gray, fontSize: '13px' }}>
          No articles found. {catFilter ? 'Try a different category or ' : ''}Create your first KB article.
        </div>
      ) : (
        <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: '14px', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: ds.mint }}>
                {['Title', 'Category', 'Tags', 'AI Behaviour', 'Version', 'Uses', 'Status', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '11px 14px', textAlign: 'left', fontSize: '11px', fontWeight: 600, color: ds.tealDark, textTransform: 'uppercase', letterSpacing: '0.6px', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {articles.map(a => (
                <tr key={a.id} style={{ borderBottom: `1px solid ${ds.border}` }}>
                  <td style={{ padding: '11px 14px', color: ds.dark, fontWeight: 600, maxWidth: '200px' }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</div>
                  </td>
                  <td style={{ padding: '11px 14px', color: ds.gray, whiteSpace: 'nowrap', textTransform: 'capitalize' }}>
                    {a.category?.replace(/_/g, ' ')}
                  </td>
                  <td style={{ padding: '11px 14px', maxWidth: '140px' }}>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      {(a.tags || []).slice(0, 3).map(tag => (
                        <span key={tag} style={{ background: ds.mint, color: ds.tealDark, fontSize: '10px', fontWeight: 600, padding: '2px 7px', borderRadius: '10px' }}>{tag}</span>
                      ))}
                      {(a.tags || []).length > 3 && <span style={{ fontSize: '10px', color: ds.gray }}>+{a.tags.length - 3}</span>}
                    </div>
                  </td>
                  <td style={{ padding: '11px 14px', whiteSpace: 'nowrap' }}>
                    {a.action_type === 'action_required' ? (
                      <div>
                        <span style={{ background: '#FFF3E0', color: '#E65100', padding: '3px 9px', borderRadius: '20px', fontSize: '11px', fontWeight: 600 }}>
                          Action required
                        </span>
                        {a.action_label && (
                          <div style={{ fontSize: '11px', color: ds.gray, marginTop: '3px', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={a.action_label}>
                            {a.action_label}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span style={{ background: '#E8F8EE', color: '#1B6B3A', padding: '3px 9px', borderRadius: '20px', fontSize: '11px', fontWeight: 600 }}>
                        Informational
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '11px 14px', color: ds.gray, textAlign: 'center', whiteSpace: 'nowrap' }}>v{a.version}</td>
                  <td style={{ padding: '11px 14px', color: ds.gray, textAlign: 'center' }}>{a.usage_count || 0}</td>
                  <td style={{ padding: '11px 14px' }}>
                    <span style={{ background: a.is_published ? '#E8F8EE' : '#F0F0F0', color: a.is_published ? ds.green : '#888', padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 600 }}>
                      {a.is_published ? 'Published' : 'Unpublished'}
                    </span>
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        onClick={() => { setFormError(null); setEditing(a) }}
                        style={{ padding: '5px 12px', borderRadius: '6px', border: `1px solid ${ds.border}`, background: 'white', fontSize: '12px', fontWeight: 600, cursor: 'pointer', color: ds.dark }}
                      >
                        Edit
                      </button>
                      {isAdmin && a.is_published && (
                        <button
                          onClick={() => handleUnpublish(a.id)}
                          style={{ padding: '5px 12px', borderRadius: '6px', border: '1px solid #FFD0D0', background: '#FFF0F0', fontSize: '12px', fontWeight: 600, cursor: 'pointer', color: '#C0392B' }}
                        >
                          Unpublish
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <ArticleForm
          initial={editing === 'new' ? null : editing}
          onSave={handleSave}
          onClose={() => { setEditing(null); setFormError(null) }}
          saving={saving}
          error={formError}
          categories={categories}
        />
      )}
    </div>
  )
}
