/**
 * frontend/src/modules/ops/CommissionsTab.jsx
 * REPORTS-DEPT-1 Phase 4c — Commissions tab inside Business Activities.
 *
 * Full leaderboard visible to every role that can reach this tab,
 * including sales_agent (client-confirmed: every rep sees everyone's
 * commission).
 *
 * Phase 4c changes:
 *   - Date filtering is now the shared DateRangePresets control
 *     (Today/Yesterday/Last 30 days/Last Month/Last Year/Custom),
 *     defaulting to Today.
 *   - rep_name grouping already worked off the backend's rep_name field —
 *     no change needed here, since list_commission_sales now populates
 *     that field from the raw sheet column directly instead of via an
 *     Opsra-users join. Same field name, more accurate source.
 *   - Variant is now a separate column in the expandable per-rep detail
 *     table, alongside Model.
 *
 * Commission rates are managed HERE, not in Admin Dashboard (client
 * preference) — owner/ops_manager can add/edit/remove rates inline;
 * sales_agent sees the rates read-only.
 *
 * Commission calculation mirrors the reference tool:
 *   commission = (rate matched against the sale's Model text) × units
 * Model is now a clean, controlled value (e.g. "Elite Cool", no variant
 * baked in), so this match is effectively exact now, though substring
 * matching is kept for robustness.
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { Trophy, ChevronDown, ChevronUp } from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  getCommissionSales,
  getCommissionRates,
  createCommissionRate,
  updateCommissionRate,
  deleteCommissionRate,
} from '../../services/growth.service'
import DateRangePresets from './DateRangePresets'

const INP = {
  padding:      '8px 10px',
  border:       '1px solid #D1D5DB',
  borderRadius: 8,
  fontSize:     13,
  outline:      'none',
  background:   'white',
  fontFamily:   'inherit',
}

const BTN_PRIMARY = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8,
  padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
}

function matchRate(rates, text) {
  if (!text) return 0
  const t = text.toLowerCase()
  const sorted = [...rates].sort((a, b) => (b.product_name?.length ?? 0) - (a.product_name?.length ?? 0))
  const hit = sorted.find(r => r.product_name && t.includes(r.product_name.toLowerCase()))
  return hit ? hit.rate_per_unit : 0
}

function commissionFor(rates, sale) {
  const units = sale.units || 1
  return matchRate(rates, sale.model || '') * units
}

function Kpi({ label, value, accent }) {
  return (
    <div style={{ background: 'white', border: '1px solid #E4EEF2', borderRadius: 12, padding: '16px 18px', flex: 1 }}>
      <p style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.6px', margin: '0 0 6px' }}>{label}</p>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 24, color: accent ?? '#0a1a24', margin: 0 }}>{value}</p>
    </div>
  )
}

function RateConfig({ rates, canEdit, onAdd, onUpdate, onDelete }) {
  const [newName, setNewName] = useState('')
  const [newRate, setNewRate] = useState('')

  return (
    <div style={{ background: 'white', border: '1px solid #E4EEF2', borderRadius: 12, padding: 18, marginBottom: 20 }}>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', margin: '0 0 4px' }}>Product commission rates</p>
      <p style={{ fontSize: 12, color: '#7A9BAD', margin: '0 0 12px' }}>
        Matched against the Model on each sale — e.g. a rate named "Elite Cool" matches any variant of Elite Cool.
      </p>
      {rates.length === 0 ? (
        <p style={{ fontSize: 13, color: '#7A9BAD', marginBottom: 12 }}>No rates set yet — commissions will show ₦0 until at least one is added.</p>
      ) : (
        <div style={{ marginBottom: 12 }}>
          {rates.map(r => (
            <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
              {canEdit ? (
                <>
                  <input
                    defaultValue={r.product_name}
                    onBlur={e => e.target.value !== r.product_name && onUpdate(r.id, { product_name: e.target.value })}
                    style={{ ...INP, flex: 1 }}
                  />
                  <input
                    type="number"
                    defaultValue={r.rate_per_unit}
                    onBlur={e => Number(e.target.value) !== r.rate_per_unit && onUpdate(r.id, { rate_per_unit: Number(e.target.value) })}
                    style={{ ...INP, width: 130 }}
                  />
                  <button onClick={() => onDelete(r.id)} style={{ background: 'none', border: 'none', color: '#B0453A', cursor: 'pointer', fontSize: 16 }}>×</button>
                </>
              ) : (
                <>
                  <span style={{ flex: 1, fontSize: 13.5 }}>{r.product_name}</span>
                  <span style={{ fontSize: 13.5, color: '#0a1a24', fontWeight: 500 }}>₦{Number(r.rate_per_unit).toLocaleString()}/unit</span>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {canEdit && (
        <div style={{ display: 'flex', gap: 8 }}>
          <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="e.g. Elite Cool" style={{ ...INP, flex: 1 }} />
          <input type="number" value={newRate} onChange={e => setNewRate(e.target.value)} placeholder="Rate per unit (₦)" style={{ ...INP, width: 160 }} />
          <button
            onClick={() => { if (newName.trim() && newRate) { onAdd(newName.trim(), Number(newRate)); setNewName(''); setNewRate('') } }}
            disabled={!newName.trim() || !newRate}
            style={{ ...BTN_PRIMARY, opacity: (!newName.trim() || !newRate) ? 0.5 : 1 }}
          >
            + Add
          </button>
        </div>
      )}
    </div>
  )
}

export default function CommissionsTab({ user, isActive }) {
  const canEdit = ['owner', 'ops_manager'].includes(user?.roles?.template)

  const [rates, setRates]       = useState([])
  const [sales, setSales]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [expandedRep, setExpandedRep] = useState(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const filters = {}
      if (dateFrom) filters.date_from = dateFrom
      if (dateTo)   filters.date_to   = dateTo
      const [ratesData, salesData] = await Promise.all([
        getCommissionRates(),
        getCommissionSales(filters),
      ])
      setRates(ratesData?.commission_rates ?? [])
      setSales(salesData?.items ?? [])
    } catch {
      setError('Failed to load commission data.')
    } finally {
      setLoading(false)
    }
  }, [dateFrom, dateTo])

  useEffect(() => { load() }, [load])

  // REPORTS-DEPT-1: this tab stays mounted once opened (Pattern 26), so
  // it never refetches after a new import unless the whole page is
  // reloaded. Refetch when this tab becomes visible again.
  useEffect(() => { if (isActive) load() }, [isActive])

  const handleAddRate = async (name, rate) => {
    try {
      const data = await createCommissionRate({ product_name: name, rate_per_unit: rate })
      setRates(data?.commission_rates ?? [])
    } catch {
      setError('Failed to add rate.')
    }
  }
  const handleUpdateRate = async (id, payload) => {
    try {
      const data = await updateCommissionRate(id, payload)
      setRates(data?.commission_rates ?? [])
    } catch {
      setError('Failed to update rate.')
    }
  }
  const handleDeleteRate = async (id) => {
    if (!window.confirm('Remove this rate? Past commission figures already computed elsewhere are not affected.')) return
    try {
      const data = await deleteCommissionRate(id)
      setRates(data?.commission_rates ?? [])
    } catch {
      setError('Failed to remove rate.')
    }
  }

  const leaderboard = useMemo(() => {
    const byRep = {}
    for (const s of sales) {
      const key = s.rep_name || 'Not recorded'
      if (!byRep[key]) byRep[key] = { rep: key, total: 0, reconciled: 0, pending: 0, sales: [] }
      const commission = commissionFor(rates, s)
      byRep[key].total += commission
      if (s.reconciliation_status === 'Reconciled') byRep[key].reconciled += 1
      else byRep[key].pending += 1
      byRep[key].sales.push({ ...s, commission })
    }
    return Object.values(byRep).sort((a, b) => b.total - a.total)
  }, [sales, rates])

  const totalCommission = leaderboard.reduce((sum, r) => sum + r.total, 0)
  const totalReconciled  = sales.filter(s => s.reconciliation_status === 'Reconciled').length
  const totalPending     = sales.length - totalReconciled

  return (
    <div style={{ padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Commissions</h2>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>Visible to every rep — full leaderboard, no filtering by who's viewing.</p>
      </div>

      {error && <p style={{ color: '#DC2626', fontSize: 13, marginBottom: 14 }}>{error}</p>}

      <RateConfig rates={rates} canEdit={canEdit} onAdd={handleAddRate} onUpdate={handleUpdateRate} onDelete={handleDeleteRate} />

      <div style={{ marginBottom: 16 }}>
        <DateRangePresets onChange={({ dateFrom: f, dateTo: t }) => { setDateFrom(f); setDateTo(t) }} />
      </div>

      {loading ? (
        <p style={{ color: '#7A9BAD', fontSize: 14 }}>Loading…</p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            <Kpi label="Total commission" value={`₦${totalCommission.toLocaleString()}`} accent={ds.teal} />
            <Kpi label="Total sales" value={sales.length} />
            <Kpi label="Reconciled" value={totalReconciled} accent="#059669" />
            <Kpi label="Pending" value={totalPending} accent="#92601A" />
          </div>

          {leaderboard.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '64px 32px', color: '#7A9BAD' }}>
              <p style={{ fontSize: 14 }}>No commission-eligible sales yet — import a transaction sales sheet to see the leaderboard.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {leaderboard.map((r, idx) => {
                const isOpen = expandedRep === r.rep
                return (
                  <div key={r.rep} style={{ background: 'white', border: '1px solid #E4EEF2', borderRadius: 12, overflow: 'hidden' }}>
                    <div
                      onClick={() => setExpandedRep(isOpen ? null : r.rep)}
                      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', cursor: 'pointer' }}
                    >
                      <div style={{
                        width: 26, height: 26, borderRadius: '50%',
                        background: idx === 0 ? '#FDF4E3' : '#F0F9FF',
                        color: idx === 0 ? '#92601A' : '#0369A1',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 12, fontWeight: 700, flexShrink: 0,
                      }}>
                        {idx === 0 ? <Trophy size={13} /> : idx + 1}
                      </div>
                      <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: '#0a1a24' }}>{r.rep}</span>
                      <span style={{ fontSize: 12, color: '#059669' }}>{r.reconciled} reconciled</span>
                      <span style={{ fontSize: 12, color: '#92601A' }}>{r.pending} pending</span>
                      <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.teal, minWidth: 110, textAlign: 'right' }}>
                        ₦{r.total.toLocaleString()}
                      </span>
                      {isOpen ? <ChevronUp size={16} color="#9CA3AF" /> : <ChevronDown size={16} color="#9CA3AF" />}
                    </div>
                    {isOpen && (
                      <table style={{ width: '100%', borderCollapse: 'collapse', borderTop: '1px solid #F0F7FA' }}>
                        <thead>
                          <tr style={{ background: '#F8FBFC' }}>
                            {['Date', 'Model', 'Variant', 'Units', 'Commission', 'Status'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '8px 18px', fontSize: 10.5, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase' }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {r.sales.map(s => (
                            <tr key={s.id} style={{ borderTop: '1px solid #F0F7FA' }}>
                              <td style={{ padding: '8px 18px', fontSize: 13 }}>{s.sale_date}</td>
                              <td style={{ padding: '8px 18px', fontSize: 13 }}>{s.model}</td>
                              <td style={{ padding: '8px 18px', fontSize: 13 }}>{s.variant ?? '—'}</td>
                              <td style={{ padding: '8px 18px', fontSize: 13 }}>{s.units}</td>
                              <td style={{ padding: '8px 18px', fontSize: 13, fontWeight: 500 }}>₦{s.commission.toLocaleString()}</td>
                              <td style={{ padding: '8px 18px', fontSize: 12.5, color: s.reconciliation_status === 'Reconciled' ? '#059669' : '#92601A' }}>
                                {s.reconciliation_status}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
