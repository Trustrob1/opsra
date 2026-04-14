/**
 * LeadsPipeline — Kanban board + paginated List view
 *
 * Phase 9B:
 *   - affiliate_partner users see a read-only board
 *   - isAffiliate derived from authStore.getRoleTemplate()
 *
 * M01-7a additions:
 *   - "Demo Queue" button in header — admin/owner/ops_manager only
 *   - Attention badge system — multi-signal per Kanban card
 *
 * M01-9b additions:
 *   - View toggle: ⊞ Kanban | ☰ List (pill switcher in header)
 *   - List view: paginated table (pageSize=20, server-side filters)
 *     Score / Source / Stage filter dropdowns
 *     Search filters client-side on current page (no search param in API spec)
 *   - Pattern 26: Kanban and List panels both stay mounted after first
 *     activation, toggled with display:none. List is lazy-mounted on first
 *     activation to avoid a fetch on initial Kanban load.
 *   - Kanban view: unchanged — useLeads({}, 200), client-side useMemo filtering
 *
 * 7 columns: new → contacted → demo_done → proposal_sent
 *   → converted (terminal) | lost | not_ready
 */
import { useState, useCallback, useMemo, useEffect } from 'react'
import { useLeads }       from '../../hooks/useLeads'
import {
  moveStage, convertLead, getLeadAttentionSummary, listLeads,
} from '../../services/leads.service'
import { ds, STAGES, SCORE_STYLE, SOURCE_SHORT } from '../../utils/ds'
import useAuthStore       from '../../store/authStore'
import LeadCreateModal    from './LeadCreateModal'
import LeadImportModal    from './LeadImportModal'
import MarkLostModal      from './MarkLostModal'
import NurtureQueue       from './NurtureQueue'
import Pagination         from '../../shared/Pagination'

const LIST_PAGE_SIZE = 20

// ── Source label map ──────────────────────────────────────────────────────────

const SOURCE_LABELS = {
  facebook_ad:       'Facebook Ad',
  instagram_ad:      'Instagram Ad',
  landing_page:      'Landing Page',
  whatsapp_inbound:  'WhatsApp',
  manual_phone:      'Manual (Phone)',
  manual_referral:   'Manual (Referral)',
  import:            'Import',
}

// ── Stage badge ───────────────────────────────────────────────────────────────

function StageBadge({ stageKey }) {
  const stage = STAGES.find(s => s.key === stageKey)
  if (!stage) return <span style={{ fontSize: 11, color: ds.gray }}>—</span>
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: stage.dot, flexShrink: 0 }} />
      <span style={{ fontSize: 11, fontWeight: 600, color: ds.dark }}>{stage.label}</span>
    </span>
  )
}

// ── Score badge ───────────────────────────────────────────────────────────────

function ScoreBadge({ score }) {
  const s = SCORE_STYLE[score] ?? SCORE_STYLE.unscored
  return (
    <span style={{
      background: s.bg, color: s.color,
      padding: '2px 8px', borderRadius: 20,
      fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne,
    }}>
      {s.label}
    </span>
  )
}

// ── List view ─────────────────────────────────────────────────────────────────

/**
 * LeadListView — paginated table, lazy-mounted by parent.
 * Server-side: score, source, stage filters.
 * Client-side: text search on current page (no search param in API spec).
 */
function LeadListView({ filterScore, filterSource, filterSearch, onOpenLead }) {
  const [filterStage, setFilterStage] = useState('')
  const [page,        setPage]        = useState(1)
  const [rawLeads,    setRawLeads]    = useState([])
  const [total,       setTotal]       = useState(0)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)

  // Reset page when server-side filters change
  useEffect(() => { setPage(1) }, [filterScore, filterSource, filterStage])

  // Server fetch
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const params = { page, page_size: LIST_PAGE_SIZE }
    if (filterScore)  params.score  = filterScore
    if (filterSource) params.source = filterSource
    if (filterStage)  params.stage  = filterStage

    listLeads(params)
      .then(res => {
        if (cancelled) return
        if (res.success) {
          setRawLeads(res.data.items ?? [])
          setTotal(res.data.total ?? 0)
        } else {
          setError(res.error ?? 'Failed to load leads')
        }
      })
      .catch(err => {
        if (cancelled) return
        setError(
          err?.response?.data?.error ??
          err?.response?.data?.message ??
          'Failed to load leads',
        )
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [filterScore, filterSource, filterStage, page])

  // Client-side text search on current page
  const leads = useMemo(() => {
    if (!filterSearch) return rawLeads
    const q = filterSearch.toLowerCase()
    return rawLeads.filter(l =>
      [l.full_name, l.business_name, l.email, l.phone]
        .filter(Boolean).some(v => v.toLowerCase().includes(q))
    )
  }, [rawLeads, filterSearch])

  const thStyle = {
    padding: '10px 14px', textAlign: 'left',
    fontSize: 10, fontWeight: 700, color: '#5b8a9a',
    textTransform: 'uppercase', letterSpacing: '0.7px',
    whiteSpace: 'nowrap', background: '#f5fbfc',
    borderBottom: `1px solid ${ds.border}`,
  }
  const tdStyle = {
    padding: '11px 14px', borderBottom: `1px solid ${ds.border}`,
    fontSize: 13, color: ds.dark, verticalAlign: 'middle',
  }

  return (
    <div>
      {/* Stage filter row — list-view only */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <select value={filterStage} onChange={e => setFilterStage(e.target.value)} style={filterSelect}>
          <option value="">All Stages</option>
          {STAGES.map(s => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        {filterStage && (
          <button
            onClick={() => setFilterStage('')}
            style={{ fontSize: 12, color: ds.gray, background: 'none', border: 'none', cursor: 'pointer' }}
          >
            ✕ Clear stage
          </button>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: ds.gray }}>
          {loading ? 'Loading…' : `${total} lead${total !== 1 ? 's' : ''} total`}
        </span>
      </div>

      {/* Error */}
      {error && (
        <div style={{ background: '#FFE8E8', border: `1px solid #FFCCCC`, borderRadius: ds.radius.md, padding: '10px 14px', fontSize: 13, color: ds.red, marginBottom: 14 }}>
          ⚠ {error}
        </div>
      )}

      {/* Table */}
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: 12, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={thStyle}>Stage</th>
              <th style={thStyle}>Name</th>
              <th style={thStyle}>Score</th>
              <th style={thStyle}>Source</th>
              <th style={thStyle}>Phone</th>
              <th style={thStyle}>Assigned To</th>
              <th style={thStyle}>Created</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} style={{ ...tdStyle, textAlign: 'center', color: ds.gray, padding: 40 }}>
                  <span style={{ color: ds.teal }}>Loading leads…</span>
                </td>
              </tr>
            ) : leads.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ ...tdStyle, textAlign: 'center', color: ds.gray, padding: 40 }}>
                  No leads match the current filters.
                </td>
              </tr>
            ) : leads.map(lead => (
              <tr
                key={lead.id}
                onClick={() => onOpenLead(lead.id)}
                style={{ cursor: 'pointer', transition: 'background 0.12s' }}
                onMouseEnter={e => { e.currentTarget.style.background = '#f5fbfc' }}
                onMouseLeave={e => { e.currentTarget.style.background = '' }}
              >
                <td style={tdStyle}><StageBadge stageKey={lead.stage} /></td>
                <td style={tdStyle}>
                  <div style={{ fontWeight: 600 }}>{lead.full_name}</div>
                  {lead.business_name && (
                    <div style={{ fontSize: 11, color: ds.gray, marginTop: 2 }}>{lead.business_name}</div>
                  )}
                </td>
                <td style={tdStyle}><ScoreBadge score={lead.score} /></td>
                <td style={{ ...tdStyle, fontSize: 12, color: ds.gray }}>
                  {SOURCE_LABELS[lead.source] ?? lead.source ?? '—'}
                </td>
                <td style={{ ...tdStyle, fontSize: 12 }}>{lead.phone ?? '—'}</td>
                <td style={{ ...tdStyle, fontSize: 12, color: ds.gray }}>
                  {lead.assigned_user?.full_name ?? '—'}
                </td>
                <td style={{ ...tdStyle, fontSize: 12, color: ds.gray, whiteSpace: 'nowrap' }}>
                  {lead.created_at
                    ? new Date(lead.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination inside the table card */}
        {!loading && (
          <div style={{ padding: '0 14px' }}>
            <Pagination
              page={page}
              total={total}
              pageSize={LIST_PAGE_SIZE}
              onGoToPage={setPage}
            />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function LeadsPipeline({ onOpenLead, onOpenDemoQueue }) {
  const { leads, loading, error, refresh, total } = useLeads({}, 200)

  // M01-7a: attention summary
  const [attentionMap, setAttentionMap] = useState({})
  useEffect(() => {
    getLeadAttentionSummary()
      .then(res => { if (res.success) setAttentionMap(res.data ?? {}) })
      .catch(() => {})
  }, [leads])

  // Phase 9B: role checks
  const roleTemplate = useAuthStore.getState().getRoleTemplate()
  const isAffiliate  = roleTemplate === 'affiliate_partner'
  const isManager    = ['owner', 'admin', 'ops_manager'].includes(roleTemplate)

  // Drag state
  const [draggedId, setDraggedId]   = useState(null)
  const [dragTarget, setDragTarget] = useState(null)
  const [movingId,  setMovingId]    = useState(null)
  const [moveError, setMoveError]   = useState(null)

  // Modal state
  const [showCreate,   setShowCreate]   = useState(false)
  const [showImport,   setShowImport]   = useState(false)
  const [markLostCtx,  setMarkLostCtx]  = useState(null)

  // Shared filters (Kanban = client-side, List = server-side)
  const [filterScore,  setFilterScore]  = useState('')
  const [filterSource, setFilterSource] = useState('')
  const [filterSearch, setFilterSearch] = useState('')

  // M01-9b: view toggle + lazy list mount
  const [viewMode,       setViewMode]       = useState('kanban')
  const [listMounted,    setListMounted]    = useState(false)
  const [nurtureMounted, setNurtureMounted] = useState(false)

  const handleViewToggle = useCallback((mode) => {
    setViewMode(mode)
    if (mode === 'list')    setListMounted(true)
    if (mode === 'nurture') setNurtureMounted(true)
  }, [])

  // Kanban client-side filter (unchanged)
  const filtered = useMemo(() => {
    const q = filterSearch.toLowerCase()
    return leads.filter((l) => {
      if (filterScore  && l.score  !== filterScore)  return false
      if (filterSource && l.source !== filterSource) return false
      if (q && ![l.full_name, l.business_name, l.email, l.phone]
                .filter(Boolean).some(v => v.toLowerCase().includes(q))) return false
      return true
    })
  }, [leads, filterScore, filterSource, filterSearch])

  const byStage = useMemo(() => {
    const map = {}
    STAGES.forEach(s => { map[s.key] = [] })
    filtered.forEach(lead => { if (map[lead.stage]) map[lead.stage].push(lead) })
    return map
  }, [filtered])

  // Pending demo count for Demo Queue badge
  const pendingDemosTotal = useMemo(() =>
    Object.values(attentionMap).reduce((sum, a) => sum + (a.pending_demos || 0), 0),
  [attentionMap])

  // ── Drag handlers (unchanged) ──────────────────────────────────────────────

  const onDragStart = useCallback((e, leadId) => {
    if (isAffiliate) return
    setDraggedId(leadId)
    setMoveError(null)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', leadId)
  }, [isAffiliate])

  const onDragOver = useCallback((e, stageKey) => {
    if (isAffiliate) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragTarget(stageKey)
  }, [isAffiliate])

  const onDragLeave = useCallback(() => setDragTarget(null), [])

  const onDrop = useCallback(async (e, targetStage) => {
    e.preventDefault()
    setDragTarget(null)
    if (isAffiliate) return
    const id = e.dataTransfer.getData('text/plain') || draggedId
    setDraggedId(null)
    if (!id || movingId) return
    const lead = leads.find(l => l.id === id)
    if (!lead || lead.stage === targetStage) return

    if (targetStage === 'converted') {
      if (!window.confirm(`Convert ${lead.full_name} to a customer?`)) return
      setMovingId(id)
      try {
        const res = await convertLead(id)
        if (!res.success) setMoveError(res.error ?? 'Conversion failed')
        else refresh()
      } catch (err) {
        setMoveError(err?.response?.data?.error ?? 'Conversion failed')
      } finally { setMovingId(null) }
      return
    }

    if (targetStage === 'lost' || targetStage === 'not_ready') {
      setMarkLostCtx({ id, defaultReason: targetStage === 'not_ready' ? 'not_ready' : '' })
      return
    }

    setMovingId(id)
    try {
      const res = await moveStage(id, targetStage)
      if (!res.success) setMoveError(res.error ?? 'Stage move failed')
      else refresh()
    } catch (err) {
      setMoveError(err?.response?.data?.error ?? 'Stage move failed')
    } finally { setMovingId(null) }
  }, [draggedId, movingId, leads, refresh, isAffiliate])

  const onDragEnd = useCallback(() => { setDraggedId(null); setDragTarget(null) }, [])

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 28, minHeight: 'calc(100vh - 60px)' }}>

      {/* ── Page header ──────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20, flexWrap: 'wrap' }}>
        <div style={{
          width: 44, height: 44, background: ds.teal, borderRadius: 11, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 15, color: 'white',
        }}>01</div>
        <div>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: 0 }}>
            Lead Command Center
          </h1>
          <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
            {loading ? 'Loading…' : `${total} leads · ${filtered.length} shown`}
          </p>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>

          {/* View toggle — M01-9b */}
          <div style={{
            display: 'flex',
            border: `1.5px solid ${ds.teal}`,
            borderRadius: ds.radius.md,
            overflow: 'hidden',
            flexShrink: 0,
          }}>
            <button
              onClick={() => handleViewToggle('kanban')}
              style={{
                padding: '7px 14px', border: 'none', cursor: 'pointer',
                fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne,
                background: viewMode === 'kanban' ? ds.teal : 'white',
                color:      viewMode === 'kanban' ? 'white' : ds.teal,
                transition: 'all 0.15s',
              }}
            >
              ⊞ Kanban
            </button>
            <button
              onClick={() => handleViewToggle('list')}
              style={{
                padding: '7px 14px', border: 'none', cursor: 'pointer',
                fontSize: 12.5, fontWeight: 600, fontFamily: ds.fontSyne,
                background: viewMode === 'list' ? ds.teal : 'white',
                color:      viewMode === 'list' ? 'white' : ds.teal,
                borderLeft: `1.5px solid ${ds.teal}`,
                transition: 'all 0.15s',
              }}
            >
              ☰ List
            </button>
          </div>

          {/* Demo Queue — admin/manager only (unchanged) */}
          {isManager && onOpenDemoQueue && (
            <button
              onClick={onOpenDemoQueue}
              style={{ ...secondaryBtn, position: 'relative', paddingRight: pendingDemosTotal > 0 ? 28 : undefined }}
            >
              📅 Demo Queue
              {pendingDemosTotal > 0 && (
                <span style={{
                  position: 'absolute', top: -7, right: -7,
                  background: '#E53E3E', color: 'white',
                  borderRadius: '50%', width: 18, height: 18,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne,
                }}>
                  {pendingDemosTotal > 9 ? '9+' : pendingDemosTotal}
                </span>
              )}
            </button>
          )}

          {/* Nurture Queue — managers only, GAP-6 */}
          {isManager && (
            <button
              onClick={() => handleViewToggle(viewMode === 'nurture' ? 'kanban' : 'nurture')}
              style={{
                ...secondaryBtn,
                background: viewMode === 'nurture' ? ds.teal : 'white',
                color:      viewMode === 'nurture' ? 'white' : ds.teal,
              }}
            >
              🌱 Nurture Queue
            </button>
          )}

          {/* Action buttons — hidden for affiliate_partner (unchanged) */}
          {!isAffiliate && (
            <>
              <button onClick={() => setShowImport(true)} style={secondaryBtn}>
                ⬆ Import CSV
              </button>
              <button onClick={() => setShowCreate(true)} style={primaryBtn}>
                + New Lead
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Shared filter bar — hidden in nurture queue view ────── */}
      {viewMode !== 'nurture' && (
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search name, business, email…"
          value={filterSearch}
          onChange={e => setFilterSearch(e.target.value)}
          style={{
            border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
            padding: '8px 14px', fontSize: 13, color: ds.dark,
            fontFamily: ds.fontDm, background: 'white', outline: 'none',
            width: 240,
          }}
        />
        <select value={filterScore} onChange={e => setFilterScore(e.target.value)} style={filterSelect}>
          <option value="">All Scores</option>
          <option value="hot">🔥 Hot</option>
          <option value="warm">☀️ Warm</option>
          <option value="cold">❄️ Cold</option>
          <option value="unscored">— Unscored</option>
        </select>
        <select value={filterSource} onChange={e => setFilterSource(e.target.value)} style={filterSelect}>
          <option value="">All Sources</option>
          <option value="facebook_ad">Facebook Ad</option>
          <option value="instagram_ad">Instagram Ad</option>
          <option value="landing_page">Landing Page</option>
          <option value="whatsapp_inbound">WhatsApp Inbound</option>
          <option value="manual_phone">Manual (Phone)</option>
          <option value="manual_referral">Manual (Referral)</option>
          <option value="import">Import</option>
        </select>
        {(filterSearch || filterScore || filterSource) && (
          <button
            onClick={() => { setFilterSearch(''); setFilterScore(''); setFilterSource('') }}
            style={{ fontSize: 12, color: ds.gray, background: 'none', border: 'none', cursor: 'pointer', padding: '0 4px' }}
          >
            ✕ Clear filters
          </button>
        )}
      </div>
      )}{/* end nurture filter hide */}

      {/* ── Error feedback (unchanged) ────────────────────────────── */}
      {error && (
        <div style={{ background: '#FFE8E8', border: `1px solid #FFCCCC`, borderRadius: ds.radius.md, padding: '10px 14px', fontSize: 13, color: ds.red, marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}
      {moveError && (
        <div style={{ background: '#FFF9E0', border: `1px solid #FFE066`, borderRadius: ds.radius.md, padding: '10px 14px', fontSize: 13, color: '#8B6800', marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
          <span>⚠ {moveError}</span>
          <button onClick={() => setMoveError(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: ds.gray }}>✕</button>
        </div>
      )}

      {/* ── Kanban — Pattern 26: hidden (not unmounted) in list mode ── */}
      <div style={{ display: viewMode === 'kanban' ? 'flex' : 'none', gap: 12, overflowX: 'auto', paddingBottom: 16 }}>
        {STAGES.map(stage => {
          const cards        = byStage[stage.key] ?? []
          const isDropTarget = !isAffiliate && dragTarget === stage.key && draggedId
          return (
            <div
              key={stage.key}
              onDragOver={e => onDragOver(e, stage.key)}
              onDragLeave={onDragLeave}
              onDrop={e => onDrop(e, stage.key)}
              style={{
                minWidth:    220,
                maxWidth:    220,
                flexShrink:  0,
                background:  isDropTarget ? ds.mint : ds.light,
                border:      `2px dashed ${isDropTarget ? ds.teal : 'transparent'}`,
                borderRadius: ds.radius.lg,
                padding:     14,
                transition:  'all 0.15s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: stage.dot, flexShrink: 0 }} />
                <span style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.8px', color: ds.gray, flex: 1 }}>
                  {stage.label}
                </span>
                <span style={{ background: ds.teal, color: 'white', width: 18, height: 18, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, flexShrink: 0 }}>
                  {cards.length}
                </span>
              </div>

              {loading && cards.length === 0 && <LoadingCard />}
              {cards.map(lead => (
                <KanbanCard
                  key={lead.id}
                  lead={lead}
                  onOpen={() => onOpenLead(lead.id)}
                  onDragStart={e => onDragStart(e, lead.id)}
                  onDragEnd={onDragEnd}
                  isMoving={movingId === lead.id}
                  canDrag={!isAffiliate}
                  attention={attentionMap[lead.id] ?? null}
                />
              ))}

              {!loading && cards.length === 0 && (
                <div style={{ border: `1px dashed ${ds.border}`, borderRadius: ds.radius.md, padding: '20px 10px', textAlign: 'center', fontSize: 12, color: ds.border }}>
                  {isAffiliate ? 'No leads' : 'Drop here'}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── List view — lazy-mounted, Pattern 26 hidden when not active ── */}
      {listMounted && (
        <div style={{ display: viewMode === 'list' ? 'block' : 'none' }}>
          <LeadListView
            filterScore={filterScore}
            filterSource={filterSource}
            filterSearch={filterSearch}
            onOpenLead={onOpenLead}
          />
        </div>
      )}

      {/* ── Nurture Queue — lazy-mounted, Pattern 26, managers only ── */}
      {nurtureMounted && (
        <div style={{ display: viewMode === 'nurture' ? 'block' : 'none' }}>
          <NurtureQueue onOpenLead={onOpenLead} />
        </div>
      )}

      {/* ── Modals (unchanged) ───────────────────────────────────── */}
      {showCreate && (
        <LeadCreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refresh() }}
        />
      )}
      {showImport && (
        <LeadImportModal
          onClose={() => setShowImport(false)}
          onImported={() => { setShowImport(false); refresh() }}
        />
      )}
      {markLostCtx && (
        <MarkLostModal
          leadId={markLostCtx.id}
          leadName={leads.find(l => l.id === markLostCtx.id)?.full_name}
          defaultReason={markLostCtx.defaultReason}
          onClose={() => setMarkLostCtx(null)}
          onMarked={() => { setMarkLostCtx(null); refresh() }}
        />
      )}
    </div>
  )
}

// ── Kanban card (unchanged) ───────────────────────────────────────────────────

function KanbanCard({ lead, onOpen, onDragStart, onDragEnd, isMoving, canDrag, attention }) {
  const scoreStyle = SCORE_STYLE[lead.score] ?? SCORE_STYLE.unscored

  const badges = []
  if (attention) {
    if ((attention.unread_messages ?? 0) > 0) {
      badges.push({
        key: 'msg',
        label: `💬 ${attention.unread_messages}`,
        bg: '#E53E3E', color: 'white',
        title: `${attention.unread_messages} unread message${attention.unread_messages > 1 ? 's' : ''}`,
      })
    }
    if ((attention.pending_demos ?? 0) > 0) {
      badges.push({
        key: 'demo',
        label: '📅',
        bg: '#D97706', color: 'white',
        title: 'Demo awaiting confirmation',
      })
    }
    if ((attention.open_tickets ?? 0) > 0) {
      badges.push({
        key: 'ticket',
        label: `🎫 ${attention.open_tickets}`,
        bg: '#ED8936', color: 'white',
        title: `${attention.open_tickets} open ticket${attention.open_tickets > 1 ? 's' : ''}`,
      })
    }
  }

  return (
    <div
      draggable={canDrag}
      onDragStart={canDrag ? onDragStart : undefined}
      onDragEnd={canDrag ? onDragEnd : undefined}
      onClick={onOpen}
      style={{
        background:   'white',
        border:       `1px solid ${badges.length > 0 ? '#FED7AA' : ds.border}`,
        borderRadius: ds.radius.md,
        padding:      12,
        marginBottom: 9,
        cursor:       isMoving ? 'wait' : (canDrag ? 'grab' : 'pointer'),
        opacity:      isMoving ? 0.4 : 1,
        boxShadow:    ds.cardShadow,
        transition:   'all 0.15s',
        userSelect:   'none',
      }}
      onMouseEnter={e => { e.currentTarget.style.boxShadow = ds.hoverShadow; e.currentTarget.style.borderColor = ds.teal }}
      onMouseLeave={e => {
        e.currentTarget.style.boxShadow = ds.cardShadow
        e.currentTarget.style.borderColor = badges.length > 0 ? '#FED7AA' : ds.border
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 4, marginBottom: badges.length > 0 ? 5 : 3 }}>
        <p style={{ fontWeight: 600, fontSize: 12.5, color: ds.dark, margin: 0, lineHeight: 1.4, flex: 1 }}>
          {lead.full_name}
        </p>
        {badges.length > 0 && (
          <div style={{ display: 'flex', gap: 3, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {badges.map(b => (
              <span
                key={b.key}
                title={b.title}
                style={{
                  background: b.bg, color: b.color,
                  borderRadius: 20, padding: '1px 6px',
                  fontSize: 10, fontWeight: 700, flexShrink: 0,
                  lineHeight: '16px', cursor: 'default',
                }}
              >
                {b.label}
              </span>
            ))}
          </div>
        )}
      </div>

      {lead.business_name && (
        <p style={{ color: ds.gray, fontSize: 11.5, margin: '0 0 7px' }}>
          {lead.business_name}
        </p>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
        <span style={{ background: scoreStyle.bg, color: scoreStyle.color, padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne }}>
          {scoreStyle.label}
        </span>
        {lead.source && (
          <span style={{ background: ds.mint, color: ds.tealDark, padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 600 }}>
            {SOURCE_SHORT[lead.source] ?? lead.source}
          </span>
        )}
      </div>
    </div>
  )
}

function LoadingCard() {
  return (
    <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: ds.radius.md, padding: 12, marginBottom: 9 }}>
      <div style={{ height: 12, background: ds.border, borderRadius: 4, width: '70%', marginBottom: 6 }} />
      <div style={{ height: 10, background: ds.border, borderRadius: 4, width: '45%' }} />
    </div>
  )
}

// ── Button + filter styles ────────────────────────────────────────────────────

const primaryBtn = {
  display: 'inline-flex', alignItems: 'center', gap: 8,
  padding: '10px 20px', borderRadius: ds.radius.md, border: 'none',
  background: ds.teal, color: 'white', fontSize: 13.5, fontWeight: 600,
  fontFamily: ds.fontSyne, cursor: 'pointer', transition: 'all 0.15s',
}
const secondaryBtn = {
  ...primaryBtn,
  background: 'white', color: ds.teal, border: `1.5px solid ${ds.teal}`,
}
const filterSelect = {
  border: `1.5px solid ${ds.border}`, borderRadius: ds.radius.md,
  padding: '8px 12px', fontSize: 13, color: ds.dark,
  fontFamily: ds.fontDm, background: 'white', outline: 'none', cursor: 'pointer',
}
