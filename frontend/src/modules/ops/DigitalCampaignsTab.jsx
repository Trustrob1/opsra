/**
 * frontend/src/modules/ops/DigitalCampaignsTab.jsx
 * REPORTS-DEPT-1 Phase 4d — Digital Campaigns tab inside Business Activities.
 *
 * Data model: one entry = one campaign, one WEEK (manually typed in by
 * the Digital Marketer from their ads platform — no file upload, no API
 * integration). Monthly view is a pure client-side rollup of whichever
 * weeks fall inside the selected calendar month — nothing is stored at
 * "monthly" granularity, so there's no double-counting risk.
 *
 * ROAS is calculated automatically by cross-referencing REAL revenue
 * from Sales Record (direct_sales) for the same date range — returned
 * by the backend's /digital-campaigns/summary route alongside the raw
 * campaign entries. Matches the source reference doc's own approach:
 * ROAS is only ever a single blended, org-wide figure (total spend vs.
 * total revenue) — never per-campaign, since individual sales aren't
 * attributable to individual campaigns in this data model.
 *
 * CTR is stored per-entry exactly as copied from the ads platform
 * (e.g. Meta Ads Manager), not as raw clicks. Blended CTR across
 * multiple weeks/campaigns is therefore an ESTIMATE — clicks are
 * back-derived as (ctr_pct / 100) * impressions per row, summed, then
 * re-divided by total impressions. Labelled "(est.)" everywhere it's
 * shown so it's never mistaken for an exact platform-reported figure.
 *
 * Owner/ops_manager only, matching Sales Record and Data Sources.
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Pencil, Trash2, Download, ChevronLeft, ChevronRight, Loader2, AlertTriangle } from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  upsertCampaignEntry,
  updateCampaignEntry,
  deleteCampaignEntry,
  getCampaignEntries,
  getCampaignSummary,
  downloadDigitalCampaignsReport,
} from '../../services/digital_campaigns.service'

const CARD = {
  background: 'white', border: '1px solid #E4EEF2', borderRadius: 12,
  padding: '16px 18px',
}

const INP = {
  padding: '8px 10px', border: '1px solid #D1D5DB', borderRadius: 8,
  fontSize: 13, outline: 'none', background: 'white', fontFamily: 'inherit',
}

const BTN_PRIMARY = {
  background: ds.teal, color: 'white', border: 'none', borderRadius: 8,
  padding: '9px 18px', fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
  fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 6,
}

const BTN_OUTLINE = {
  background: 'white', color: ds.teal, border: `1px solid ${ds.teal}`,
  borderRadius: 8, padding: '9px 18px', fontSize: 13.5, fontWeight: 600,
  cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 6,
}

function isoDate(d) {
  return d.toISOString().slice(0, 10)
}

function fmtNaira(v) {
  return `₦${Math.round(v || 0).toLocaleString()}`
}

const EMPTY_FORM = {
  id: null,
  campaign_name: '',
  week_start: '',
  daily_budget: '',
  spend: '',
  conversations: '',
  ctr_pct: '',
  impressions: '',
  notes: '',
}

// ─── Entry form (add / edit one campaign's week) ───────────────────────────

function EntryForm({ initial, onSaved, onCancel }) {
  const [form, setForm]     = useState(initial ?? EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState(null)

  const upd = (field, value) => setForm(f => ({ ...f, [field]: value }))

  const handleSave = async () => {
    setError(null)
    if (!form.campaign_name.trim()) { setError('Campaign name is required.'); return }
    if (!form.week_start) { setError('Pick any date within the week this entry covers.'); return }
    setSaving(true)
    try {
      const payload = {
        campaign_name: form.campaign_name.trim(),
        week_start:    form.week_start,
        daily_budget:  Number(form.daily_budget) || 0,
        spend:         Number(form.spend) || 0,
        conversations: Number(form.conversations) || 0,
        ctr_pct:       Number(form.ctr_pct) || 0,
        impressions:   Number(form.impressions) || 0,
        notes:         form.notes?.trim() || null,
      }
      if (form.id) {
        await updateCampaignEntry(form.id, payload)
      } else {
        await upsertCampaignEntry(payload)
      }
      onSaved()
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to save this entry. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ ...CARD, marginBottom: 20 }}>
      <p style={{ fontSize: 13, fontWeight: 700, color: '#0a1a24', margin: '0 0 12px' }}>
        {form.id ? 'Edit weekly entry' : 'Log this week\u2019s numbers'}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Campaign name</label>
          <input style={{ ...INP, width: '100%' }} value={form.campaign_name} onChange={e => upd('campaign_name', e.target.value)} placeholder="e.g. Direct Sales 23/06" />
        </div>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Any date in the week</label>
          <input type="date" style={{ ...INP, width: '100%' }} value={form.week_start} onChange={e => upd('week_start', e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Daily budget (₦)</label>
          <input type="number" min="0" style={{ ...INP, width: '100%' }} value={form.daily_budget} onChange={e => upd('daily_budget', e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Spend this week (₦)</label>
          <input type="number" min="0" style={{ ...INP, width: '100%' }} value={form.spend} onChange={e => upd('spend', e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Conversations</label>
          <input type="number" min="0" style={{ ...INP, width: '100%' }} value={form.conversations} onChange={e => upd('conversations', e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>CTR (%)</label>
          <input type="number" min="0" step="0.01" style={{ ...INP, width: '100%' }} value={form.ctr_pct} onChange={e => upd('ctr_pct', e.target.value)} placeholder="e.g. 1.91" />
        </div>
        <div>
          <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Impressions</label>
          <input type="number" min="0" style={{ ...INP, width: '100%' }} value={form.impressions} onChange={e => upd('impressions', e.target.value)} />
        </div>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 11.5, color: '#7A9BAD', display: 'block', marginBottom: 4 }}>Notes (optional)</label>
        <input style={{ ...INP, width: '100%' }} value={form.notes} onChange={e => upd('notes', e.target.value)} placeholder="Anything worth remembering about this week" />
      </div>
      {error && <p style={{ color: '#DC2626', fontSize: 13, margin: '0 0 12px', display: 'flex', alignItems: 'center', gap: 6 }}><AlertTriangle size={14} /> {error}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={handleSave} disabled={saving} style={{ ...BTN_PRIMARY, opacity: saving ? 0.6 : 1 }}>
          {saving ? <Loader2 size={15} style={{ animation: 'spin 0.8s linear infinite' }} /> : null}
          {saving ? 'Saving…' : form.id ? 'Save changes' : 'Add entry'}
        </button>
        <button onClick={onCancel} style={BTN_OUTLINE}>Cancel</button>
      </div>
    </div>
  )
}

// ─── Month navigator ────────────────────────────────────────────────────────

function MonthNav({ monthDate, onChange }) {
  const label = monthDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
  const go = (delta) => {
    const next = new Date(Date.UTC(monthDate.getUTCFullYear(), monthDate.getUTCMonth() + delta, 1))
    onChange(next)
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <button onClick={() => go(-1)} style={{ ...BTN_OUTLINE, padding: '6px 10px' }}><ChevronLeft size={15} /></button>
      <span style={{ fontSize: 14, fontWeight: 600, color: '#0a1a24', minWidth: 140, textAlign: 'center' }}>{label}</span>
      <button onClick={() => go(1)} style={{ ...BTN_OUTLINE, padding: '6px 10px' }}><ChevronRight size={15} /></button>
    </div>
  )
}

// ─── KPI card ────────────────────────────────────────────────────────────────

function Kpi({ label, value }) {
  return (
    <div style={{ ...CARD, flex: 1 }}>
      <p style={{ fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.6px', margin: '0 0 6px' }}>{label}</p>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: '#0a1a24', margin: 0 }}>{value}</p>
    </div>
  )
}

export default function DigitalCampaignsTab({ isActive }) {
  const [monthDate, setMonthDate] = useState(() => new Date())
  const [summaryItems, setSummaryItems] = useState([])
  const [revenue, setRevenue]     = useState(0)
  const [entries, setEntries]     = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [showForm, setShowForm]   = useState(false)
  const [editingEntry, setEditingEntry] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const monthRange = useMemo(() => {
    const y = monthDate.getUTCFullYear(), m = monthDate.getUTCMonth()
    const from = new Date(Date.UTC(y, m, 1))
    const to   = new Date(Date.UTC(y, m + 1, 0))
    return { from: isoDate(from), to: isoDate(to) }
  }, [monthDate])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [summaryData, entriesData] = await Promise.all([
        getCampaignSummary(monthRange.from, monthRange.to),
        getCampaignEntries(monthRange.from, monthRange.to),
      ])
      setSummaryItems(summaryData?.items ?? [])
      setRevenue(summaryData?.revenue ?? 0)
      setEntries(entriesData?.items ?? [])
    } catch {
      setError('Failed to load Digital Campaigns data.')
    } finally {
      setLoading(false)
    }
  }, [monthRange])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  // Per-campaign aggregation (mirrors the backend PDF's own logic exactly).
  const byCampaign = useMemo(() => {
    const map = {}
    for (const e of summaryItems) {
      const name = e.campaign_name || 'Unnamed campaign'
      const c = map[name] || { daily_budget: 0, spend: 0, conversations: 0, impressions: 0, estClicks: 0 }
      c.daily_budget = Math.max(c.daily_budget, Number(e.daily_budget) || 0)
      c.spend += Number(e.spend) || 0
      c.conversations += Number(e.conversations) || 0
      const impressions = Number(e.impressions) || 0
      const ctr = Number(e.ctr_pct) || 0
      c.impressions += impressions
      c.estClicks += (impressions * ctr) / 100
      map[name] = c
    }
    return Object.entries(map)
      .map(([name, c]) => ({
        name,
        ...c,
        costPerConv: c.conversations > 0 ? c.spend / c.conversations : null,
        ctrPct: c.impressions > 0 ? (c.estClicks / c.impressions) * 100 : 0,
      }))
      .sort((a, b) => b.spend - a.spend)
  }, [summaryItems])

  const totals = useMemo(() => {
    const spend         = byCampaign.reduce((s, c) => s + c.spend, 0)
    const conversations = byCampaign.reduce((s, c) => s + c.conversations, 0)
    const impressions   = byCampaign.reduce((s, c) => s + c.impressions, 0)
    const estClicks     = byCampaign.reduce((s, c) => s + c.estClicks, 0)
    const ctrPct        = impressions > 0 ? (estClicks / impressions) * 100 : 0
    const costPerConv   = conversations > 0 ? spend / conversations : 0
    const roas          = spend > 0 ? revenue / spend : 0
    return { spend, conversations, impressions, ctrPct, costPerConv, roas }
  }, [byCampaign, revenue])

  const insights = useMemo(() => {
    const ranked = byCampaign.filter(c => c.costPerConv != null)
    const lines = []
    if (ranked.length > 0) {
      const best = ranked.reduce((a, b) => (a.costPerConv < b.costPerConv ? a : b))
      const worst = ranked.reduce((a, b) => (a.costPerConv > b.costPerConv ? a : b))
      lines.push(`Lowest cost per conversation: ${best.name} at ${fmtNaira(best.costPerConv)} — a strong candidate for more budget.`)
      if (worst.name !== best.name) {
        lines.push(`Highest cost per conversation: ${worst.name} at ${fmtNaira(worst.costPerConv)} — worth reviewing or pausing.`)
      }
    }
    if (totals.spend > 0) {
      lines.push(revenue > 0
        ? `Blended return on ad spend: ${totals.roas.toFixed(1)}x — ₦${totals.roas.toFixed(1)} in revenue for every ₦1 spent (revenue from Sales Record, same month).`
        : 'No Sales Record revenue found for this month, so ROAS could not be calculated.')
    }
    return lines
  }, [byCampaign, totals, revenue])

  const handleEdit = (entry) => {
    setEditingEntry({
      id: entry.id,
      campaign_name: entry.campaign_name,
      week_start: entry.week_start,
      daily_budget: entry.daily_budget,
      spend: entry.spend,
      conversations: entry.conversations,
      ctr_pct: entry.ctr_pct,
      impressions: entry.impressions,
      notes: entry.notes || '',
    })
    setShowForm(true)
  }

  const handleDelete = async (entry) => {
    if (!window.confirm(`Delete "${entry.campaign_name}" for week of ${entry.week_start}? This cannot be undone.`)) return
    try {
      await deleteCampaignEntry(entry.id)
      load()
    } catch {
      setError('Failed to delete this entry.')
    }
  }

  const handleDownload = async () => {
    setDownloading(true); setError(null)
    try {
      const blob = await downloadDigitalCampaignsReport({ date_from: monthRange.from, date_to: monthRange.to })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `Digital_Campaigns_Report_${monthRange.from}_to_${monthRange.to}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      const msg = e?.response?.status === 429
        ? 'You can download up to 10 reports per hour.'
        : (e?.response?.data?.detail?.message ?? 'Download failed. Please try again.')
      setError(msg)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div style={{ padding: 28 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: 0 }}>Digital Campaigns</h2>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: '4px 0 0' }}>Monthly view — logged weekly, rolled up automatically.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <MonthNav monthDate={monthDate} onChange={setMonthDate} />
          <button onClick={handleDownload} disabled={downloading} style={{ ...BTN_OUTLINE, opacity: downloading ? 0.6 : 1 }}>
            <Download size={15} /> {downloading ? 'Generating…' : 'Download PDF'}
          </button>
          <button onClick={() => { setEditingEntry(null); setShowForm(true) }} style={BTN_PRIMARY}>
            <Plus size={15} /> Log week
          </button>
        </div>
      </div>

      {error && <p style={{ color: '#DC2626', fontSize: 13, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}><AlertTriangle size={14} /> {error}</p>}

      {showForm && (
        <EntryForm
          initial={editingEntry}
          onSaved={() => { setShowForm(false); setEditingEntry(null); load() }}
          onCancel={() => { setShowForm(false); setEditingEntry(null) }}
        />
      )}

      {loading ? (
        <p style={{ color: '#7A9BAD', fontSize: 14 }}>Loading…</p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <Kpi label="Total Spend" value={fmtNaira(totals.spend)} />
            <Kpi label="Conversations" value={totals.conversations.toLocaleString()} />
            <Kpi label="Cost/Conv (blended)" value={fmtNaira(totals.costPerConv)} />
            <Kpi label="CTR (blended, est.)" value={`${totals.ctrPct.toFixed(2)}%`} />
            <Kpi label="ROAS" value={`${totals.roas.toFixed(1)}x`} />
          </div>

          <div style={{ ...CARD, marginBottom: 20 }}>
            <p style={{ fontSize: 13, fontWeight: 700, color: '#0a1a24', margin: '0 0 12px' }}>Per-Campaign Breakdown</p>
            {byCampaign.length === 0 ? (
              <p style={{ fontSize: 13, color: '#9CA3AF', margin: 0 }}>No campaigns logged for this month yet.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                  <thead>
                    <tr style={{ background: '#F8FBFC' }}>
                      {['Campaign', 'Daily Budget', 'Spent', 'Conversations', 'Cost/Conv', 'CTR (est.)', 'Impressions'].map((h, i) => (
                        <th key={h} style={{ textAlign: i === 0 ? 'left' : 'right', padding: '8px 10px', fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.4px' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {byCampaign.map(c => (
                      <tr key={c.name} style={{ borderTop: '1px solid #F0F7FA' }}>
                        <td style={{ padding: '8px 10px', color: '#0a1a24', fontWeight: 500 }}>{c.name}</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{fmtNaira(c.daily_budget)}</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{fmtNaira(c.spend)}</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{c.conversations.toLocaleString()}</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{c.costPerConv != null ? fmtNaira(c.costPerConv) : '—'}</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{c.ctrPct.toFixed(2)}%</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{c.impressions.toLocaleString()}</td>
                      </tr>
                    ))}
                    <tr style={{ borderTop: '2px solid #E4EEF2', fontWeight: 700 }}>
                      <td style={{ padding: '8px 10px', color: '#0a1a24' }}>Total</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>—</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{fmtNaira(totals.spend)}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{totals.conversations.toLocaleString()}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{fmtNaira(totals.costPerConv)}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{totals.ctrPct.toFixed(2)}%</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#0a1a24' }}>{totals.impressions.toLocaleString()}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {insights.length > 0 && (
            <div style={{ ...CARD, marginBottom: 20 }}>
              <p style={{ fontSize: 13, fontWeight: 700, color: '#0a1a24', margin: '0 0 10px' }}>Insights</p>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {insights.map((line, i) => (
                  <li key={i} style={{ fontSize: 12.5, color: '#4a7a8a', marginBottom: 6 }}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <div style={CARD}>
            <p style={{ fontSize: 13, fontWeight: 700, color: '#0a1a24', margin: '0 0 12px' }}>Weekly Entries This Month</p>
            {entries.length === 0 ? (
              <p style={{ fontSize: 13, color: '#9CA3AF', margin: 0 }}>No weekly entries logged for this month yet.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                  <thead>
                    <tr style={{ background: '#F8FBFC' }}>
                      {['Week of', 'Campaign', 'Spend', 'Conversations', 'CTR', 'Impressions', ''].map(h => (
                        <th key={h} style={{ textAlign: 'left', padding: '8px 10px', fontSize: 11, fontWeight: 700, color: '#7A9BAD', textTransform: 'uppercase', letterSpacing: '0.4px' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((e, i) => (
                      <tr key={e.id} style={{ borderTop: i > 0 ? '1px solid #F0F7FA' : 'none' }}>
                        <td style={{ padding: '8px 10px', color: '#0a1a24' }}>{e.week_start}</td>
                        <td style={{ padding: '8px 10px', color: '#0a1a24' }}>{e.campaign_name}</td>
                        <td style={{ padding: '8px 10px', color: '#0a1a24' }}>{fmtNaira(e.spend)}</td>
                        <td style={{ padding: '8px 10px', color: '#0a1a24' }}>{e.conversations}</td>
                        <td style={{ padding: '8px 10px', color: '#0a1a24' }}>{Number(e.ctr_pct).toFixed(2)}%</td>
                        <td style={{ padding: '8px 10px', color: '#0a1a24' }}>{Number(e.impressions).toLocaleString()}</td>
                        <td style={{ padding: '8px 10px', display: 'flex', gap: 6 }}>
                          <button onClick={() => handleEdit(e)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, display: 'flex' }} aria-label="Edit">
                            <Pencil size={14} color={ds.teal} />
                          </button>
                          <button onClick={() => handleDelete(e)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, display: 'flex' }} aria-label="Delete">
                            <Trash2 size={14} color="#DC2626" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
