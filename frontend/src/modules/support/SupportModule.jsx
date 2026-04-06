/**
 * frontend/src/modules/support/SupportModule.jsx
 * Module 03 — Support top-level container.
 *
 * Tabs (mount-and-hide pattern — Pattern 26):
 *   Tickets     — TicketList + TicketDetail (inline detail view)
 *   Knowledge Base — KBManager
 *   Interaction Logs — InteractionLogPanel
 *
 * Sub-navigation handled with local useState — no react-router (Pattern 13).
 * Ticket detail replaces TicketList within the Tickets tab using selectedTicketId state.
 */

import { useState } from 'react'
import { ds } from '../../utils/ds'
import useAuthStore from '../../store/authStore'
import TicketList         from './TicketList'
import TicketDetail       from './TicketDetail'
import KBManager          from './KBManager'
import InteractionLogPanel from './InteractionLogPanel'
import { useCallback } from 'react'

const TABS = [
  { id: 'tickets',     label: '🎫 Tickets' },
  { id: 'kb',          label: '📚 Knowledge Base' },
  { id: 'interactions',label: '📞 Interaction Logs' },
]

export default function SupportModule({ user }) {
  // Phase 9B: affiliate_partner cannot access Knowledge Base
  const isAffiliate  = useAuthStore.getState().getRoleTemplate() === 'affiliate_partner'
  const visibleTabs  = isAffiliate ? TABS.filter(t => t.id !== 'kb') : TABS
  const [tab, setTab]                       = useState('tickets')
  const [selectedTicketId, setSelectedTicketId] = useState(null)
  const [kbTick, setKbTick] = useState(0)
  const refreshKB = useCallback(() => setKbTick(t => t + 1), [])

  function handleSelectTicket(ticketId) {
    setSelectedTicketId(ticketId)
  }

  function handleBackToList() {
    setSelectedTicketId(null)
  }

  function handleTicketUpdated() {
    // No-op for now — detail re-fetches internally.
    // List will refresh next time tab is re-focused via tick counter.
  }

  return (
    <div style={{ padding: '28px 32px', maxWidth: '1200px', margin: '0 auto' }}>

      {/* Module header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '26px' }}>
        <div style={{
          width: '44px', height: '44px', borderRadius: '11px',
          background: '#E07B3A',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'Syne, sans-serif', fontWeight: 800, fontSize: '15px', color: 'white', flexShrink: 0,
        }}>
          03
        </div>
        <div>
          <div style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '22px', color: ds.dark }}>Support</div>
          <div style={{ fontSize: '13px', color: ds.gray, marginTop: '2px' }}>Ticket management, knowledge base, and interaction logging</div>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: '4px', borderBottom: `2px solid ${ds.border}`, marginBottom: '26px' }}>
        {visibleTabs.map(t => (
          <button
            key={t.id}
            onClick={() => { setTab(t.id); if (t.id !== 'tickets') setSelectedTicketId(null) }}
            style={{
              padding: '10px 20px',
              border: 'none',
              background: 'none',
              fontSize: '13.5px',
              fontWeight: tab === t.id ? 700 : 500,
              color: tab === t.id ? ds.teal : ds.gray,
              cursor: 'pointer',
              borderBottom: tab === t.id ? `3px solid ${ds.teal}` : '3px solid transparent',
              marginBottom: '-2px',
              fontFamily: 'Syne, sans-serif',
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab panels — mount-and-hide (Pattern 26) */}

      {/* Tickets tab */}
      <div style={{ display: tab === 'tickets' ? 'block' : 'none' }}>
        {selectedTicketId ? (
          <TicketDetail
            ticketId={selectedTicketId}
            onBack={handleBackToList}
            onUpdated={handleTicketUpdated}
            onKBArticlePublished={refreshKB}
          />
        ) : (
          <TicketList onSelectTicket={handleSelectTicket} />
        )}
      </div>

      {/* KB tab */}
      <div style={{ display: tab === 'kb' ? 'block' : 'none' }}>
        <KBManager user={user} externalTick={kbTick} />
      </div>

      {/* Interaction logs tab */}
      <div style={{ display: tab === 'interactions' ? 'block' : 'none' }}>
        <InteractionLogPanel />
      </div>

    </div>
  )
}
