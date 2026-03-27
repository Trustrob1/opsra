/**
 * LeadsPipeline — Kanban board
 *
 * 7 columns (one per stage): new → contacted → demo_done → proposal_sent
 *   → converted (terminal) | lost | not_ready
 *
 * Drag mechanics (HTML5 native — no library):
 *   - Dragging to converted  → confirm + POST /convert
 *   - Dragging to lost       → open MarkLostModal
 *   - Dragging to not_ready  → open MarkLostModal with defaultReason='not_ready'
 *   - Dragging to any other  → POST /move-stage
 *
 * Stage transition rules come from the backend state machine — invalid
 * transitions are rejected by the server with a 422.  The UI does not
 * try to mirror the full state machine locally; it surfaces server errors.
 */
import { useState, useCallback, useMemo } from 'react'
import { useLeads }       from '../../hooks/useLeads'
import { moveStage, convertLead } from '../../services/leads.service'
import { ds, STAGES, SCORE_STYLE, SOURCE_SHORT } from '../../utils/ds'
import LeadCreateModal  from './LeadCreateModal'
import LeadImportModal  from './LeadImportModal'
import MarkLostModal    from './MarkLostModal'

const SCORE_FILTERS  = ['', 'hot', 'warm', 'cold', 'unscored']
const SOURCE_FILTERS = [
  '', 'facebook_ad', 'instagram_ad', 'landing_page',
  'whatsapp_inbound', 'manual_phone', 'manual_referral', 'import',
]

export default function LeadsPipeline({ onOpenLead }) {
  const { leads, loading, error, refresh, total } = useLeads({}, 200)

  const [draggedId, setDraggedId]     = useState(null)
  const [dragTarget, setDragTarget]   = useState(null) // stage key being hovered
  const [movingId, setMovingId]       = useState(null)
  const [moveError, setMoveError]     = useState(null)

  const [showCreate, setShowCreate]   = useState(false)
  const [showImport, setShowImport]   = useState(false)
  const [markLostCtx, setMarkLostCtx] = useState(null) // { id, defaultReason }

  const [filterScore, setFilterScore]   = useState('')
  const [filterSource, setFilterSource] = useState('')
  const [filterSearch, setFilterSearch] = useState('')

  // ── Filtering ───────────────────────────────────────────────────────────────
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

  // Group by stage
  const byStage = useMemo(() => {
    const map = {}
    STAGES.forEach(s => { map[s.key] = [] })
    filtered.forEach(lead => { if (map[lead.stage]) map[lead.stage].push(lead) })
    return map
  }, [filtered])

  // ── Drag handlers ───────────────────────────────────────────────────────────
  const onDragStart = useCallback((e, leadId) => {
    setDraggedId(leadId)
    setMoveError(null)
    e.dataTransfer.effectAllowed = 'move'
    // Store id in dataTransfer for robustness
    e.dataTransfer.setData('text/plain', leadId)
  }, [])

  const onDragOver = useCallback((e, stageKey) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragTarget(stageKey)
  }, [])

  const onDragLeave = useCallback(() => setDragTarget(null), [])

  const onDrop = useCallback(async (e, targetStage) => {
    e.preventDefault()
    setDragTarget(null)
    const id = e.dataTransfer.getData('text/plain') || draggedId
    setDraggedId(null)
    if (!id || movingId) return
    const lead = leads.find(l => l.id === id)
    if (!lead || lead.stage === targetStage) return

    // ── Path: convert ─────────────────────────────────────────────
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

    // ── Path: mark lost / not_ready ────────────────────────────────
    if (targetStage === 'lost' || targetStage === 'not_ready') {
      setMarkLostCtx({
        id,
        defaultReason: targetStage === 'not_ready' ? 'not_ready' : '',
      })
      return
    }

    // ── Path: move stage ───────────────────────────────────────────
    setMovingId(id)
    try {
      const res = await moveStage(id, targetStage)
      if (!res.success) setMoveError(res.error ?? 'Stage move failed')
      else refresh()
    } catch (err) {
      setMoveError(err?.response?.data?.error ?? 'Stage move failed')
    } finally { setMovingId(null) }
  }, [draggedId, movingId, leads, refresh])

  const onDragEnd = useCallback(() => { setDraggedId(null); setDragTarget(null) }, [])

  // ── Render ──────────────────────────────────────────────────────────────────
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
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button onClick={() => setShowImport(true)} style={secondaryBtn}>
            ⬆ Import CSV
          </button>
          <button onClick={() => setShowCreate(true)} style={primaryBtn}>
            + New Lead
          </button>
        </div>
      </div>

      {/* ── Filters bar ──────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Search */}
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
        {/* Score filter */}
        <select
          value={filterScore}
          onChange={e => setFilterScore(e.target.value)}
          style={filterSelect}
        >
          <option value="">All Scores</option>
          <option value="hot">🔥 Hot</option>
          <option value="warm">☀️ Warm</option>
          <option value="cold">❄️ Cold</option>
          <option value="unscored">— Unscored</option>
        </select>
        {/* Source filter */}
        <select
          value={filterSource}
          onChange={e => setFilterSource(e.target.value)}
          style={filterSelect}
        >
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

      {/* ── Error feedback ────────────────────────────────────────── */}
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

      {/* ── Kanban columns ────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 16 }}>
        {STAGES.map(stage => {
          const cards       = byStage[stage.key] ?? []
          const isDropTarget = dragTarget === stage.key && draggedId
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
              {/* Column header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: stage.dot, flexShrink: 0,
                }} />
                <span style={{
                  fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 11,
                  textTransform: 'uppercase', letterSpacing: '0.8px', color: ds.gray,
                  flex: 1,
                }}>
                  {stage.label}
                </span>
                <span style={{
                  background: ds.teal, color: 'white',
                  width: 18, height: 18, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 10, fontWeight: 700, flexShrink: 0,
                }}>
                  {cards.length}
                </span>
              </div>

              {/* Cards */}
              {loading && cards.length === 0 && <LoadingCard />}
              {cards.map(lead => (
                <KanbanCard
                  key={lead.id}
                  lead={lead}
                  onOpen={() => onOpenLead(lead.id)}
                  onDragStart={e => onDragStart(e, lead.id)}
                  onDragEnd={onDragEnd}
                  isMoving={movingId === lead.id}
                />
              ))}

              {/* Empty state */}
              {!loading && cards.length === 0 && (
                <div style={{
                  border:       `1px dashed ${ds.border}`,
                  borderRadius: ds.radius.md,
                  padding:      '20px 10px',
                  textAlign:    'center',
                  fontSize:     12,
                  color:        ds.border,
                }}>
                  Drop here
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── Modals ───────────────────────────────────────────────── */}
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

// ─── Kanban card ──────────────────────────────────────────────────────────────

function KanbanCard({ lead, onOpen, onDragStart, onDragEnd, isMoving }) {
  const scoreStyle = SCORE_STYLE[lead.score] ?? SCORE_STYLE.unscored
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      style={{
        background:   'white',
        border:       `1px solid ${ds.border}`,
        borderRadius: ds.radius.md,
        padding:      12,
        marginBottom: 9,
        cursor:       isMoving ? 'wait' : 'grab',
        opacity:      isMoving ? 0.4 : 1,
        boxShadow:    ds.cardShadow,
        transition:   'all 0.15s',
        userSelect:   'none',
      }}
      onMouseEnter={e => { e.currentTarget.style.boxShadow = ds.hoverShadow; e.currentTarget.style.borderColor = ds.teal }}
      onMouseLeave={e => { e.currentTarget.style.boxShadow = ds.cardShadow;  e.currentTarget.style.borderColor = ds.border }}
    >
      <p style={{ fontWeight: 600, fontSize: 12.5, color: ds.dark, margin: '0 0 3px', lineHeight: 1.4 }}>
        {lead.full_name}
      </p>
      {lead.business_name && (
        <p style={{ color: ds.gray, fontSize: 11.5, margin: '0 0 7px' }}>
          {lead.business_name}
        </p>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
        <span style={{
          background: scoreStyle.bg, color: scoreStyle.color,
          padding: '2px 8px', borderRadius: 20,
          fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne,
        }}>
          {scoreStyle.label}
        </span>
        {lead.source && (
          <span style={{
            background: ds.mint, color: ds.tealDark,
            padding: '2px 7px', borderRadius: 10,
            fontSize: 10, fontWeight: 600,
          }}>
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

// ─── Styles ───────────────────────────────────────────────────────────────────

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
