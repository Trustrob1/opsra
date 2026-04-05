/**
 * RenewalModule.jsx — Module 04 container: Renewal & Subscriptions
 *
 * Structure:
 *   ┌─ Header bar (title + Bulk Upload button)
 *   ├─ SubscriptionList  (mounted, hidden with display:none when detail open — Pattern 26)
 *   └─ SubscriptionDetail (conditionally rendered when a subscription is selected)
 *
 * Pattern 26: mount-and-hide keeps the list state (filters, page, scroll)
 * alive while the user is viewing a detail, so Back returns to the exact
 * same position without a re-fetch.
 *
 * Pattern 30: listTick is incremented after bulk upload completes and passed
 * as externalTick to SubscriptionList, which calls refresh() in response.
 *
 * Props:
 *   user  {object} — authenticated user from Zustand auth store
 *
 * SECURITY:
 *   F1 — JWT Zustand only (no localStorage) — enforced in renewal.service.js
 *   F2 — org_id never in any payload — enforced in renewal.service.js
 *   F3 — No react-router-dom — navigation via useState
 */
import { useState, useCallback } from 'react'
import { ds } from '../../utils/ds'
import SubscriptionList   from './SubscriptionList'
import SubscriptionDetail from './SubscriptionDetail'
import BulkUploadModal    from './BulkUploadModal'
import {
  fetchAllForExport,
  generateRenewalExportCSV,
  downloadCSV,
} from '../../services/renewal.service'

// ─────────────────────────────────────────────────────────────────────────────

export default function RenewalModule({ user }) {
  const [selectedId, setSelectedId]         = useState(null)
  const [showBulkUpload, setShowBulkUpload] = useState(false)
  const [listTick, setListTick]             = useState(0)
  const [exporting, setExporting]           = useState(false)
  const [exportError, setExportError]       = useState(null)

  /** Trigger a list refresh without changing filters or page. */
  const refreshList = useCallback(() => setListTick(t => t + 1), [])

  /** Bulk upload complete — close modal and refresh list. */
  const handleBulkComplete = useCallback(() => {
    setShowBulkUpload(false)
    refreshList()
  }, [refreshList])

  /** After a mutation in SubscriptionDetail that should reset navigation. */
  const handleUpdated = useCallback(() => {
    setSelectedId(null)
    refreshList()
  }, [refreshList])

  /**
   * Export Renewals CSV
   * Fetches all non-cancelled subscriptions and downloads a pre-filled CSV.
   * Staff adds payment_channel, payment_date, reference from bank statement,
   * then re-uploads via Bulk Upload.
   */
  const handleExport = useCallback(async () => {
    setExporting(true)
    setExportError(null)
    try {
      const subscriptions = await fetchAllForExport()
      if (subscriptions.length === 0) {
        setExportError('No subscriptions to export.')
        return
      }
      const csv      = generateRenewalExportCSV(subscriptions)
      const today    = new Date().toISOString().slice(0, 10)
      const filename = `renewals-${today}.csv`
      downloadCSV(csv, filename)
    } catch {
      setExportError('Export failed. Please try again.')
    } finally {
      setExporting(false)
    }
  }, [])

  return (
    <div style={{ padding: 28, fontFamily: ds.fontDm, minHeight: 'calc(100vh - 60px)' }}>

      {/* ── Module header ───────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', marginBottom: 24,
      }}>
        <div>
          <h1 style={{
            fontFamily: ds.fontSyne, fontWeight: 700,
            fontSize: 24, color: ds.dark, margin: 0,
          }}>
            🔄 Renewal &amp; Subscriptions
          </h1>
          <p style={{ fontSize: 13, color: ds.gray, margin: '4px 0 0' }}>
            Manage subscription renewals, confirm payments, and track billing status
          </p>
        </div>

        {/* Action buttons — only shown on list view */}
        {!selectedId && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
            <div style={{ display: 'flex', gap: 10 }}>

              {/* Export Renewals CSV */}
              <button
                onClick={handleExport}
                disabled={exporting}
                style={{
                  background:   'white',
                  color:        ds.teal,
                  border:       `1.5px solid ${ds.teal}`,
                  borderRadius: 10,
                  padding:      '11px 20px',
                  fontSize:     13,
                  fontWeight:   600,
                  fontFamily:   ds.fontSyne,
                  cursor:       exporting ? 'not-allowed' : 'pointer',
                  display:      'flex',
                  alignItems:   'center',
                  gap:          8,
                  opacity:      exporting ? 0.7 : 1,
                  transition:   'opacity 0.2s',
                }}
              >
                {exporting ? '⏳ Exporting…' : '⬇ Export Renewals CSV'}
              </button>

              {/* Bulk Upload CSV */}
              <button
                onClick={() => setShowBulkUpload(true)}
                style={{
                  background:   ds.teal,
                  color:        'white',
                  border:       'none',
                  borderRadius: 10,
                  padding:      '11px 20px',
                  fontSize:     13,
                  fontWeight:   600,
                  fontFamily:   ds.fontSyne,
                  cursor:       'pointer',
                  display:      'flex',
                  alignItems:   'center',
                  gap:          8,
                  boxShadow:    '0 2px 10px rgba(0,140,160,0.25)',
                  transition:   'opacity 0.2s',
                }}
                onMouseEnter={e => e.currentTarget.style.opacity = '0.88'}
                onMouseLeave={e => e.currentTarget.style.opacity = '1'}
              >
                ⬆ Bulk Upload CSV
              </button>
            </div>

            {/* Export error */}
            {exportError && (
              <p style={{ fontSize: 12, color: '#B91C1C', margin: 0 }}>
                ⚠ {exportError}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── List (Pattern 26: mount-and-hide) ─────────────────────────────── */}
      <div style={{ display: selectedId ? 'none' : 'block' }}>
        <SubscriptionList
          user={user}
          onSelect={setSelectedId}
          externalTick={listTick}
        />
      </div>

      {/* ── Detail (conditionally rendered — new instance per selection) ──── */}
      {selectedId && (
        <SubscriptionDetail
          subscriptionId={selectedId}
          user={user}
          onBack={() => setSelectedId(null)}
          onUpdated={handleUpdated}
        />
      )}

      {/* ── Bulk Upload Modal ─────────────────────────────────────────────── */}
      {showBulkUpload && (
        <BulkUploadModal
          onClose={() => setShowBulkUpload(false)}
          onComplete={handleBulkComplete}
        />
      )}
    </div>
  )
}
