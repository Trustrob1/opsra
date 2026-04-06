/**
 * frontend/src/modules/notifications/NotificationsDrawer.jsx
 * Notifications slide-in drawer — Phase 9
 *
 * Props:
 *   onClose          — called when backdrop or ✕ is clicked
 *   onUnreadChange   — called with new unread count after any read action
 *                      so the topbar bell badge stays in sync
 *
 * Behaviour:
 *   - Fetches notifications on mount
 *   - Clicking a notification marks it read (if unread) and calls onUnreadChange
 *   - "Mark all read" button marks all and refreshes
 *   - Paginated with Load More button
 *   - Plain text only — no innerHTML (F4 safe)
 */
import { useState, useEffect, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as notifSvc from '../../services/notifications.service'

// Notification type → icon mapping
const TYPE_ICON = {
  churn_alert:        '🔴',
  lead_aging:         '⏰',
  sla_breach:         '🚨',
  nps_response:       '⭐',
  subscription_expiring: '🔔',
  digest:             '📊',
  task:               '✅',
  anomaly:            '⚠️',
}

function _icon(type) {
  return TYPE_ICON[type] ?? '🔔'
}

function _timeAgo(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1)  return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)  return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export default function NotificationsDrawer({ onClose, onUnreadChange }) {
  const [items, setItems]         = useState([])
  const [unread, setUnread]       = useState(0)
  const [page, setPage]           = useState(1)
  const [hasMore, setHasMore]     = useState(false)
  const [loading, setLoading]     = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError]         = useState(null)
  const [markingAll, setMarkingAll] = useState(false)

  const PAGE_SIZE = 20

  const fetchPage = useCallback(async (pg, append = false) => {
    try {
      const data = await notifSvc.listNotifications(pg, PAGE_SIZE)
      setItems(prev => append ? [...prev, ...(data.items ?? [])] : (data.items ?? []))
      setHasMore(data.has_more ?? false)
      setUnread(data.unread_count ?? 0)
      onUnreadChange?.(data.unread_count ?? 0)
    } catch {
      setError('Failed to load notifications.')
    }
  }, [onUnreadChange])

  useEffect(() => {
    fetchPage(1).finally(() => setLoading(false))
  }, [fetchPage])

  const handleLoadMore = async () => {
    const next = page + 1
    setPage(next)
    setLoadingMore(true)
    await fetchPage(next, true)
    setLoadingMore(false)
  }

  const handleMarkRead = async (notif) => {
    if (notif.is_read) return
    try {
      await notifSvc.markRead(notif.id)
      setItems(prev => prev.map(n => n.id === notif.id ? { ...n, is_read: true } : n))
      const newUnread = Math.max(0, unread - 1)
      setUnread(newUnread)
      onUnreadChange?.(newUnread)
    } catch { /* silent — non-critical */ }
  }

  const handleMarkAll = async () => {
    setMarkingAll(true)
    try {
      await notifSvc.markAllRead()
      setItems(prev => prev.map(n => ({ ...n, is_read: true })))
      setUnread(0)
      onUnreadChange?.(0)
    } catch { /* silent */ } finally {
      setMarkingAll(false)
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.35)',
          zIndex: 1100,
        }}
      />

      {/* Drawer */}
      <div style={{
        position:   'fixed',
        top:        0,
        right:      0,
        bottom:     0,
        width:      400,
        background: 'white',
        zIndex:     1101,
        display:    'flex',
        flexDirection: 'column',
        boxShadow:  '-8px 0 40px rgba(0,0,0,0.18)',
      }}>
        {/* Header */}
        <div style={{
          display:       'flex',
          alignItems:    'center',
          justifyContent:'space-between',
          padding:       '18px 20px',
          borderBottom:  '1px solid #E4EEF2',
          background:    '#F5F9FA',
          flexShrink:    0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18 }}>🔔</span>
            <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: '#0a1a24' }}>
              Notifications
            </span>
            {unread > 0 && (
              <span style={{
                background: ds.teal, color: 'white',
                borderRadius: 20, padding: '2px 8px',
                fontSize: 11, fontWeight: 700,
              }}>
                {unread}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {unread > 0 && (
              <button
                onClick={handleMarkAll}
                disabled={markingAll}
                style={{
                  background: 'none', border: '1px solid #CBD5E1',
                  borderRadius: 6, padding: '5px 10px',
                  fontSize: 12, color: '#4a7a8a', cursor: 'pointer',
                  fontFamily: ds.fontDm,
                }}
              >
                {markingAll ? 'Marking…' : 'Mark all read'}
              </button>
            )}
            <button
              onClick={onClose}
              style={{
                background: 'none', border: 'none',
                fontSize: 22, cursor: 'pointer',
                color: '#7A9BAD', lineHeight: 1, padding: '0 4px',
              }}
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading && (
            <div style={{ padding: 32, textAlign: 'center', color: '#7A9BAD', fontSize: 14 }}>
              Loading…
            </div>
          )}
          {error && (
            <div style={{ padding: 32, textAlign: 'center', color: '#DC2626', fontSize: 14 }}>
              {error}
            </div>
          )}
          {!loading && !error && items.length === 0 && (
            <div style={{ padding: '48px 24px', textAlign: 'center' }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>🎉</div>
              <p style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 15, color: '#0a1a24', margin: '0 0 6px' }}>
                All caught up
              </p>
              <p style={{ fontSize: 13, color: '#7A9BAD', margin: 0 }}>
                No notifications yet.
              </p>
            </div>
          )}
          {!loading && items.map(notif => (
            <div
              key={notif.id}
              onClick={() => handleMarkRead(notif)}
              style={{
                display:    'flex',
                gap:        14,
                padding:    '14px 20px',
                borderBottom: '1px solid #F0F7FA',
                cursor:     notif.is_read ? 'default' : 'pointer',
                background: notif.is_read ? 'white' : '#F0FAFA',
                transition: 'background 0.15s',
              }}
            >
              {/* Icon */}
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                background: notif.is_read ? '#F1F5F9' : '#E0F5F7',
                display: 'flex', alignItems: 'center',
                justifyContent: 'center', fontSize: 16, flexShrink: 0,
              }}>
                {_icon(notif.type)}
              </div>

              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 13.5, fontWeight: notif.is_read ? 400 : 600,
                  color: '#0a1a24', marginBottom: 3,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {notif.title}
                </div>
                {notif.body && (
                  <div style={{
                    fontSize: 12.5, color: '#7A9BAD', lineHeight: 1.4,
                    display: '-webkit-box', WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical', overflow: 'hidden',
                  }}>
                    {notif.body}
                  </div>
                )}
                <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 4 }}>
                  {_timeAgo(notif.created_at)}
                </div>
              </div>

              {/* Unread dot */}
              {!notif.is_read && (
                <div style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: ds.teal, flexShrink: 0, marginTop: 6,
                }} />
              )}
            </div>
          ))}

          {/* Load more */}
          {hasMore && !loading && (
            <div style={{ padding: '16px 20px', textAlign: 'center' }}>
              <button
                onClick={handleLoadMore}
                disabled={loadingMore}
                style={{
                  background: 'white', border: '1px solid #CBD5E1',
                  borderRadius: 8, padding: '8px 20px',
                  fontSize: 13, color: '#4a7a8a', cursor: loadingMore ? 'not-allowed' : 'pointer',
                  fontFamily: ds.fontDm,
                }}
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
