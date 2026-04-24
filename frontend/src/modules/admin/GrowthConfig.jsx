/**
 * frontend/src/modules/admin/GrowthConfig.jsx
 * Growth Config — GPM-1D
 *
 * Three stacked cards (all visible on scroll — not tabs):
 *   1. Growth Teams   — POST/PATCH/DELETE /api/v1/growth/teams
 *   2. Campaign Spend — POST/DELETE        /api/v1/growth/spend
 *   3. Direct Sales   — POST/PATCH/DELETE  /api/v1/growth/direct-sales
 *
 * Pattern 26: panels always mounted, display:none when hidden.
 * Pattern 50: all API calls via growth.service.js (axios + _h()).
 * Pattern 51: full rewrite only.
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as growthSvc from '../../services/growth.service'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRESET_COLORS = [
  { name: 'teal',   hex: '#00BFA5' },
  { name: 'blue',   hex: '#2979FF' },
  { name: 'purple', hex: '#7C4DFF' },
  { name: 'orange', hex: '#FF6D00' },
  { name: 'red',    hex: '#FF1744' },
  { name: 'green',  hex: '#00C853' },
  { name: 'yellow', hex: '#FFD600' },
  { name: 'grey',   hex: '#607D8B' },
]

const CARD_STYLE = {
  background: 'white',
  borderRadius: 12,
  border: '1px solid #E2EFF4',
  marginBottom: 24,
  overflow: 'hidden',
}

const CARD_HEADER = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '18px 24px',
  borderBottom: '1px solid #E2EFF4',
  background: '#F7FBFC',
}

const CARD_TITLE = {
  fontFamily: ds.fontSyne,
  fontWeight: 700,
  fontSize: 15,
  color: '#0a1a24',
  margin: 0,
}

const BTN_TEAL = {
  background: ds.teal,
  color: 'white',
  border: 'none',
  borderRadius: 7,
  padding: '8px 16px',
  fontFamily: ds.fontDm,
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
}

const BTN_GHOST = {
  background: 'none',
  border: '1px solid #cde3ea',
  borderRadius: 7,
  padding: '7px 14px',
  fontFamily: ds.fontDm,
  fontSize: 13,
  color: '#4a7a8a',
  cursor: 'pointer',
}

const TH = {
  padding: '10px 16px',
  fontFamily: ds.fontDm,
  fontSize: 12,
  fontWeight: 600,
  color: '#7A9BAD',
  textAlign: 'left',
  borderBottom: '1px solid #E2EFF4',
  whiteSpace: 'nowrap',
}

const TD = {
  padding: '12px 16px',
  fontFamily: ds.fontDm,
  fontSize: 13.5,
  color: '#1a3a4a',
  borderBottom: '1px solid #F0F8FA',
  verticalAlign: 'middle',
}

function EmptyState({ message }) {
  return (
    <div style={{ padding: '40px 24px', textAlign: 'center', color: '#7A9BAD', fontSize: 13.5 }}>
      {message}
    </div>
  )
}

function Modal({ title, onClose, children }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,20,30,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: 'white', borderRadius: 14, width: '100%', maxWidth: 460,
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)', overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '18px 24px', borderBottom: '1px solid #E2EFF4',
          background: '#F7FBFC',
        }}>
          <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24' }}>
            {title}
          </span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: '#7A9BAD', lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: 24 }}>
          {children}
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontFamily: ds.fontDm, fontSize: 12, fontWeight: 600, color: '#5a8a9f', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </label>
      {children}
    </div>
  )
}

const INPUT = {
  width: '100%', boxSizing: 'border-box',
  border: '1.5px solid #cde3ea', borderRadius: 8,
  padding: '9px 12px', fontFamily: ds.fontDm, fontSize: 14,
  color: '#1a3a4a', outline: 'none',
}

// ---------------------------------------------------------------------------
// Section 1: Growth Teams
// ---------------------------------------------------------------------------

function GrowthTeams({ teams, loading, onRefresh }) {
  const [showAdd, setShowAdd]       = useState(false)
  const [editId, setEditId]         = useState(null)
  const [editName, setEditName]     = useState('')
  const [editColor, setEditColor]   = useState(PRESET_COLORS[0].hex)
  const [newName, setNewName]       = useState('')
  const [newColor, setNewColor]     = useState(PRESET_COLORS[0].hex)
  const [confirmDelete, setConfirmDelete] = useState(null) // { team, leadCount }
  const [saving, setSaving]         = useState(false)
  const [error, setError]           = useState('')

  const handleAdd = async () => {
    if (!newName.trim()) { setError('Team name is required'); return }
    if (newName.length > 50) { setError('Max 50 characters'); return }
    setSaving(true); setError('')
    try {
      await growthSvc.createGrowthTeam({ name: newName.trim(), color: newColor, is_active: true })
      setShowAdd(false); setNewName(''); setNewColor(PRESET_COLORS[0].hex)
      onRefresh()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Failed to create team')
    } finally { setSaving(false) }
  }

  const handleEdit = async (teamId) => {
    if (!editName.trim()) return
    setSaving(true)
    try {
      await growthSvc.updateGrowthTeam(teamId, { name: editName.trim(), color: editColor })
      setEditId(null)
      onRefresh()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Failed to update')
    } finally { setSaving(false) }
  }

  const handleToggleActive = async (team) => {
    try {
      await growthSvc.updateGrowthTeam(team.id, { is_active: !team.is_active })
      onRefresh()
    } catch (e) {
      setError('Failed to update status')
    }
  }

  const handleDeleteConfirm = async () => {
    if (!confirmDelete) return
    setSaving(true)
    try {
      await growthSvc.deleteGrowthTeam(confirmDelete.team.id)
      setConfirmDelete(null)
      onRefresh()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Failed to delete')
    } finally { setSaving(false) }
  }

  // Before delete, check if the team has leads attributed (from team performance data)
  const handleDeleteClick = async (team) => {
    setConfirmDelete({ team, leadCount: null })
  }

  return (
    <div style={CARD_STYLE}>
      <div style={CARD_HEADER}>
        <h3 style={CARD_TITLE}>Growth Teams</h3>
        <button style={BTN_TEAL} onClick={() => { setShowAdd(true); setError('') }}>+ Add Team</button>
      </div>

      {loading ? (
        <div style={{ padding: 24, color: '#7A9BAD', fontSize: 13 }}>Loading…</div>
      ) : teams.length === 0 ? (
        <EmptyState message='No teams configured yet. Add your first team to start tracking attribution across campaigns.' />
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH}>Colour</th>
              <th style={TH}>Team Name</th>
              <th style={TH}>Status</th>
              <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {teams.map(team => (
              <tr key={team.id}>
                <td style={TD}>
                  <div style={{ width: 20, height: 20, borderRadius: '50%', background: team.color || '#607D8B', border: '2px solid #E2EFF4' }} />
                </td>
                <td style={TD}>
                  {editId === team.id ? (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <input
                        value={editName}
                        onChange={e => setEditName(e.target.value)}
                        maxLength={50}
                        style={{ ...INPUT, width: 180, padding: '6px 10px', fontSize: 13 }}
                        autoFocus
                      />
                      <div style={{ display: 'flex', gap: 4 }}>
                        {PRESET_COLORS.map(c => (
                          <div
                            key={c.hex}
                            onClick={() => setEditColor(c.hex)}
                            style={{
                              width: 18, height: 18, borderRadius: '50%', background: c.hex,
                              cursor: 'pointer',
                              outline: editColor === c.hex ? `3px solid ${c.hex}` : 'none',
                              outlineOffset: 2,
                            }}
                          />
                        ))}
                      </div>
                      <button style={{ ...BTN_TEAL, padding: '5px 12px', fontSize: 12 }} onClick={() => handleEdit(team.id)} disabled={saving}>Save</button>
                      <button style={{ ...BTN_GHOST, padding: '5px 10px', fontSize: 12 }} onClick={() => setEditId(null)}>Cancel</button>
                    </div>
                  ) : (
                    <span
                      style={{ cursor: 'pointer', borderBottom: '1px dashed #cde3ea' }}
                      onClick={() => { setEditId(team.id); setEditName(team.name); setEditColor(team.color || PRESET_COLORS[0].hex) }}
                      title='Click to edit'
                    >
                      {team.name}
                    </span>
                  )}
                </td>
                <td style={TD}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                    <div
                      onClick={() => handleToggleActive(team)}
                      style={{
                        width: 36, height: 20, borderRadius: 10,
                        background: team.is_active ? ds.teal : '#cde3ea',
                        position: 'relative', transition: 'background 0.2s', cursor: 'pointer',
                      }}
                    >
                      <div style={{
                        position: 'absolute', top: 3, left: team.is_active ? 19 : 3,
                        width: 14, height: 14, borderRadius: '50%', background: 'white',
                        transition: 'left 0.2s',
                      }} />
                    </div>
                    <span style={{ fontSize: 12, color: team.is_active ? ds.teal : '#7A9BAD' }}>
                      {team.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </label>
                </td>
                <td style={{ ...TD, textAlign: 'right' }}>
                  <button
                    onClick={() => handleDeleteClick(team)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#e57373', fontSize: 15, padding: '2px 6px' }}
                    title='Delete team'
                  >
                    🗑
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && <div style={{ padding: '8px 24px', color: '#e57373', fontSize: 13 }}>{error}</div>}

      {/* Add Team Modal */}
      {showAdd && (
        <Modal title='Add Growth Team' onClose={() => { setShowAdd(false); setError('') }}>
          <Field label='Team Name'>
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder='e.g. Team A, Content Crew'
              maxLength={50}
              style={INPUT}
              autoFocus
            />
            <div style={{ fontSize: 11, color: '#7A9BAD', marginTop: 4 }}>{newName.length}/50</div>
          </Field>
          <Field label='Colour'>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {PRESET_COLORS.map(c => (
                <div
                  key={c.hex}
                  onClick={() => setNewColor(c.hex)}
                  title={c.name}
                  style={{
                    width: 28, height: 28, borderRadius: '50%', background: c.hex,
                    cursor: 'pointer',
                    outline: newColor === c.hex ? `3px solid ${c.hex}` : 'none',
                    outlineOffset: 2,
                  }}
                />
              ))}
            </div>
          </Field>
          {error && <div style={{ marginBottom: 12, color: '#e57373', fontSize: 13 }}>{error}</div>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button style={BTN_GHOST} onClick={() => { setShowAdd(false); setError('') }}>Cancel</button>
            <button style={BTN_TEAL} onClick={handleAdd} disabled={saving}>
              {saving ? 'Saving…' : 'Save Team'}
            </button>
          </div>
        </Modal>
      )}

      {/* Delete Confirm Modal */}
      {confirmDelete && (
        <Modal title='Delete Team?' onClose={() => setConfirmDelete(null)}>
          <p style={{ fontFamily: ds.fontDm, fontSize: 14, color: '#1a3a4a', marginBottom: 16 }}>
            Are you sure you want to delete <strong>{confirmDelete.team.name}</strong>?
          </p>
          <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', marginBottom: 20 }}>
            Deleting will not remove attribution — historical data is preserved.
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button style={BTN_GHOST} onClick={() => setConfirmDelete(null)}>Cancel</button>
            <button
              style={{ ...BTN_TEAL, background: '#e57373' }}
              onClick={handleDeleteConfirm}
              disabled={saving}
            >
              {saving ? 'Deleting…' : 'Yes, Delete'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 2: Campaign Spend
// ---------------------------------------------------------------------------

function CampaignSpend({ teams, onRefresh }) {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  const [form, setForm] = useState({
    spendType: 'team',
    teamId: '',
    channelName: '',
    periodStart: '',
    periodEnd: '',
    amount: '',
    notes: '',
  })

  const activeTeams = teams.filter(t => t.is_active)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await growthSvc.getSpendEntries()
      setEntries(data || [])
    } catch (e) {
      setError('Failed to load spend entries')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const resolveTeamName = (entry) => {
    if (entry.spend_type === 'team') {
      const t = teams.find(t => t.name?.toLowerCase() === (entry.team_name || '').toLowerCase())
      return t ? t.name : entry.team_name || '—'
    }
    return entry.channel_name || '—'
  }

  const handleAdd = async () => {
    if (!form.periodStart || !form.periodEnd || !form.amount) {
      setError('Period and amount are required'); return
    }
    if (form.spendType === 'team' && !form.teamId) {
      setError('Select a team'); return
    }
    if (form.spendType === 'channel' && !form.channelName.trim()) {
      setError('Enter a channel name'); return
    }

    const selectedTeam = teams.find(t => t.id === form.teamId)
    const payload = {
      spend_type:   form.spendType,
      period_start: form.periodStart,
      period_end:   form.periodEnd,
      amount:       parseFloat(form.amount),
      notes:        form.notes || null,
      ...(form.spendType === 'team'
        ? { team_name: selectedTeam?.name }
        : { channel_name: form.channelName.trim() }
      ),
    }

    setSaving(true); setError('')
    try {
      await growthSvc.createSpendEntry(payload)
      setShowAdd(false)
      setForm({ spendType: 'team', teamId: '', channelName: '', periodStart: '', periodEnd: '', amount: '', notes: '' })
      load()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Failed to log spend')
    } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this spend entry?')) return
    try {
      await growthSvc.deleteSpendEntry(id)
      load()
    } catch (e) {
      setError('Failed to delete')
    }
  }

  return (
    <div style={CARD_STYLE}>
      <div style={CARD_HEADER}>
        <h3 style={CARD_TITLE}>Campaign Spend</h3>
        <button style={BTN_TEAL} onClick={() => { setShowAdd(true); setError('') }}>+ Log Spend</button>
      </div>

      {loading ? (
        <div style={{ padding: 24, color: '#7A9BAD', fontSize: 13 }}>Loading…</div>
      ) : entries.length === 0 ? (
        <EmptyState message='No spend logged yet. Log campaign spend to calculate CAC and cost per lead.' />
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH}>Period</th>
              <th style={TH}>Type</th>
              <th style={TH}>Team / Channel</th>
              <th style={TH}>Amount</th>
              <th style={TH}>Notes</th>
              <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.id}>
                <td style={TD}>{e.period_start} → {e.period_end}</td>
                <td style={TD}><span style={{ textTransform: 'capitalize', fontSize: 12, background: '#E8F5F9', color: '#1a6a8a', borderRadius: 4, padding: '2px 8px' }}>{e.spend_type}</span></td>
                <td style={TD}>{resolveTeamName(e)}</td>
                <td style={TD}><strong>{Number(e.amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong></td>
                <td style={{ ...TD, color: '#7A9BAD', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.notes || '—'}</td>
                <td style={{ ...TD, textAlign: 'right' }}>
                  <button onClick={() => handleDelete(e.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#e57373', fontSize: 15, padding: '2px 6px' }}>🗑</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && <div style={{ padding: '8px 24px', color: '#e57373', fontSize: 13 }}>{error}</div>}

      {showAdd && (
        <Modal title='Log Campaign Spend' onClose={() => { setShowAdd(false); setError('') }}>
          <Field label='Spend Type'>
            <div style={{ display: 'flex', gap: 16 }}>
              {['team', 'channel'].map(type => (
                <label key={type} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 14 }}>
                  <input type='radio' checked={form.spendType === type} onChange={() => setForm(f => ({ ...f, spendType: type }))} />
                  {type === 'team' ? 'By Team' : 'By Channel'}
                </label>
              ))}
            </div>
          </Field>

          {form.spendType === 'team' ? (
            <Field label='Team'>
              <select
                value={form.teamId}
                onChange={e => setForm(f => ({ ...f, teamId: e.target.value }))}
                style={{ ...INPUT }}
              >
                <option value=''>Select team…</option>
                {activeTeams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
          ) : (
            <Field label='Channel Name'>
              <input
                value={form.channelName}
                onChange={e => setForm(f => ({ ...f, channelName: e.target.value }))}
                placeholder='e.g. facebook, google, instagram'
                style={INPUT}
              />
            </Field>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label='Period Start'>
              <input type='date' value={form.periodStart} onChange={e => setForm(f => ({ ...f, periodStart: e.target.value }))} style={INPUT} />
            </Field>
            <Field label='Period End'>
              <input type='date' value={form.periodEnd} onChange={e => setForm(f => ({ ...f, periodEnd: e.target.value }))} style={INPUT} />
            </Field>
          </div>

          <Field label='Amount'>
            <input
              type='number'
              min='0'
              step='0.01'
              value={form.amount}
              onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
              placeholder='0.00'
              style={INPUT}
            />
          </Field>

          <Field label='Notes (optional)'>
            <input
              value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              placeholder='Brief description…'
              style={INPUT}
            />
          </Field>

          {error && <div style={{ marginBottom: 12, color: '#e57373', fontSize: 13 }}>{error}</div>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button style={BTN_GHOST} onClick={() => { setShowAdd(false); setError('') }}>Cancel</button>
            <button style={BTN_TEAL} onClick={handleAdd} disabled={saving}>
              {saving ? 'Saving…' : 'Log Spend'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 3: Direct Sales
// ---------------------------------------------------------------------------

function DirectSales({ teams }) {
  const [sales, setSales]     = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [page, setPage]       = useState(1)
  const [total, setTotal]     = useState(0)
  const PAGE_SIZE = 20

  const [form, setForm] = useState({
    customerName: '',
    amount: '',
    saleDate: '',
    channel: '',
    utmSource: '',
    sourceTeam: '',
    notes: '',
  })

  const activeTeams = teams.filter(t => t.is_active)

  const load = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const data = await growthSvc.getDirectSales(p, PAGE_SIZE)
      setSales(data?.items || data || [])
      setTotal(data?.total || (data?.length ?? 0))
    } catch (e) {
      setError('Failed to load direct sales')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load(page) }, [load, page])

  const handleAdd = async () => {
    if (!form.customerName.trim() || !form.amount || !form.saleDate) {
      setError('Customer name, amount, and sale date are required'); return
    }
    setSaving(true); setError('')
    try {
      await growthSvc.createDirectSale({
        customer_name: form.customerName.trim(),
        amount:        parseFloat(form.amount),
        sale_date:     form.saleDate,
        channel:       form.channel || null,
        utm_source:    form.utmSource || null,
        source_team:   form.sourceTeam || null,
        notes:         form.notes || null,
      })
      setShowAdd(false)
      setForm({ customerName: '', amount: '', saleDate: '', channel: '', utmSource: '', sourceTeam: '', notes: '' })
      load(1); setPage(1)
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Failed to log sale')
    } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this direct sale?')) return
    try {
      await growthSvc.deleteDirectSale(id)
      load(page)
    } catch (e) {
      setError('Failed to delete')
    }
  }

  return (
    <div style={CARD_STYLE}>
      <div style={CARD_HEADER}>
        <h3 style={CARD_TITLE}>Direct Sales</h3>
        <button style={BTN_TEAL} onClick={() => { setShowAdd(true); setError('') }}>+ Log Sale</button>
      </div>

      {loading ? (
        <div style={{ padding: 24, color: '#7A9BAD', fontSize: 13 }}>Loading…</div>
      ) : sales.length === 0 ? (
        <EmptyState message='No direct sales logged. Record sales not going through the lead pipeline here.' />
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={TH}>Date</th>
              <th style={TH}>Customer</th>
              <th style={TH}>Amount</th>
              <th style={TH}>Channel</th>
              <th style={TH}>Team</th>
              <th style={TH}>Notes</th>
              <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sales.map(s => (
              <tr key={s.id}>
                <td style={TD}>{s.sale_date || '—'}</td>
                <td style={TD}>{s.customer_name || s.customer_id || '—'}</td>
                <td style={TD}><strong>{Number(s.amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong></td>
                <td style={{ ...TD, color: '#5a8a9f' }}>{s.channel || s.utm_source || '—'}</td>
                <td style={{ ...TD, color: '#5a8a9f' }}>{s.source_team || '—'}</td>
                <td style={{ ...TD, color: '#7A9BAD', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.notes || '—'}</td>
                <td style={{ ...TD, textAlign: 'right' }}>
                  <button onClick={() => handleDelete(s.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#e57373', fontSize: 15, padding: '2px 6px' }}>🗑</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {total > PAGE_SIZE && (
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', padding: '12px 24px', borderTop: '1px solid #E2EFF4' }}>
          <button style={BTN_GHOST} disabled={page === 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
          <span style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#7A9BAD', alignSelf: 'center' }}>Page {page}</span>
          <button style={BTN_GHOST} disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next →</button>
        </div>
      )}

      {error && <div style={{ padding: '8px 24px', color: '#e57373', fontSize: 13 }}>{error}</div>}

      {showAdd && (
        <Modal title='Log Direct Sale' onClose={() => { setShowAdd(false); setError('') }}>
          <Field label='Customer Name'>
            <input value={form.customerName} onChange={e => setForm(f => ({ ...f, customerName: e.target.value }))} placeholder='Customer or company name' style={INPUT} autoFocus />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label='Amount'>
              <input type='number' min='0' step='0.01' value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} placeholder='0.00' style={INPUT} />
            </Field>
            <Field label='Sale Date'>
              <input type='date' value={form.saleDate} onChange={e => setForm(f => ({ ...f, saleDate: e.target.value }))} style={INPUT} />
            </Field>
          </div>
          <Field label='Channel (optional)'>
            <input value={form.channel} onChange={e => setForm(f => ({ ...f, channel: e.target.value }))} placeholder='e.g. facebook, referral, walk-in' style={INPUT} />
          </Field>
          <Field label='UTM Source (optional)'>
            <input value={form.utmSource} onChange={e => setForm(f => ({ ...f, utmSource: e.target.value }))} placeholder='e.g. facebook' style={INPUT} />
          </Field>
          <Field label='Source Team (optional)'>
            <select value={form.sourceTeam} onChange={e => setForm(f => ({ ...f, sourceTeam: e.target.value }))} style={INPUT}>
              <option value=''>None</option>
              {activeTeams.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
            </select>
          </Field>
          <Field label='Notes (optional)'>
            <input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder='Brief notes…' style={INPUT} />
          </Field>
          {error && <div style={{ marginBottom: 12, color: '#e57373', fontSize: 13 }}>{error}</div>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button style={BTN_GHOST} onClick={() => { setShowAdd(false); setError('') }}>Cancel</button>
            <button style={BTN_TEAL} onClick={handleAdd} disabled={saving}>{saving ? 'Saving…' : 'Log Sale'}</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export default function GrowthConfig() {
  const [teams, setTeams]     = useState([])
  const [loadingTeams, setLoadingTeams] = useState(true)

  const loadTeams = useCallback(async () => {
    setLoadingTeams(true)
    try {
      const data = await growthSvc.getGrowthTeams()
      setTeams(data || [])
    } catch (e) {
      console.error('GrowthConfig: failed to load teams', e)
    } finally { setLoadingTeams(false) }
  }, [])

  useEffect(() => { loadTeams() }, [loadTeams])

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 4px' }}>
          Growth Config
        </h2>
        <p style={{ fontFamily: ds.fontDm, fontSize: 13.5, color: '#5a8a9f', margin: 0 }}>
          Configure teams, log campaign spend, and record direct sales to power the Growth Dashboard.
        </p>
      </div>

      <GrowthTeams teams={teams} loading={loadingTeams} onRefresh={loadTeams} />
      <CampaignSpend teams={teams} onRefresh={loadTeams} />
      <DirectSales teams={teams} />
    </div>
  )
}
